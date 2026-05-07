"""系統 #3 - LEAPS 進場評分

排除單股 2x ETF(學習鎖 L3)。
權重從 LEAPS_ENTRY_WEIGHTS 讀;Layer F 由呼叫方加總後傳入。
DTE 從 LEAPS_SPEC["default_scan_dte"](365 = 12 個月,v4.1)讀,不 hardcode。
失敗冷啟動回 score=0,不拋例外。
"""

import json

from loguru import logger

from src.config.thresholds import (
    LEAPS_ENTRY_WEIGHTS, LEAPS_ENTRY_VETO, IVR_THRESHOLDS, LEAPS_SPEC,
)
from src.config.universe import ETF_LEVERAGED_SINGLE_STOCK
from src.data.earnings_calendar import is_earnings_within_days
from src.data.fundamentals import fetch_fundamentals, detect_consecutive_eps_miss
from src.data.iv_rank import calc_iv_rank
from src.data.price_data import fetch_history, get_52w_high_low
from src.data.vix_structure import is_vix_consecutive_above
from src.indicators.basic import get_rsi_latest, get_bbands_position, get_ma_position
from src.signals.base_scorer import build_scorer_result, clip
from src.signals.veto_checker import check_all_hard_rules
from src.storage.state_manager import DATA_STORE_DIR


# v4.1:get_value_thesis 已抽至 src/data/value_thesis.py(共用模組,避循環依賴)
# 為向下相容,本 module 仍 re-export get_value_thesis(被 exit_rules 等多處 import)
from src.data.value_thesis import get_value_thesis  # noqa: F401, E402


def score(symbol: str, layer0_mod: int = 0, layer_f_mod: int = 0,
          layer0_veto: bool = False, dte_days: int | None = None,
          context: dict | None = None) -> dict:
    """單一標的 LEAPS 進場評分。"""
    try:
        # 學習鎖 L3:單股 2x ETF 直接擋(也由 veto_checker 擋,這裡早退)
        # v4.1 註:LEAPS 對 underlying 個股開,不對 2x ETF 開,維持向下相容
        if symbol in ETF_LEVERAGED_SINGLE_STOCK:
            return build_scorer_result(
                symbol, "leaps_entry", raw_score=0,
                veto_triggered=True,
                veto_reasons=[f"single_stock_2x_etf_{symbol}_no_leaps"],
            )

        df = fetch_history(symbol, period="6mo", interval="1d")
        if df is None or df.empty:
            return build_scorer_result(
                symbol, "leaps_entry", raw_score=0,
                veto_triggered=True, veto_reasons=["no_price_data"],
            )

        effective_dte = dte_days if dte_days is not None else LEAPS_SPEC["default_scan_dte"]

        # ---- Scorer 內部 veto ----
        veto_reasons: list[str] = []

        try:
            if is_earnings_within_days(symbol, LEAPS_ENTRY_VETO["earnings_within_days"]):
                veto_reasons.append("scorer_veto_earnings_within_7_days")
        except Exception as e:
            logger.warning(f"leaps earnings check failed: {e}")

        try:
            if is_vix_consecutive_above(30, LEAPS_ENTRY_VETO["vix_extreme_consecutive_days"]):
                veto_reasons.append("scorer_veto_vix_consecutive_above_30")
        except Exception as e:
            logger.warning(f"leaps vix check failed: {e}")

        try:
            if detect_consecutive_eps_miss(symbol, 2):
                veto_reasons.append("scorer_veto_consecutive_2q_eps_miss")
        except Exception as e:
            logger.warning(f"leaps eps check failed: {e}")

        if layer0_veto:
            veto_reasons.append("scorer_veto_layer0_vix3m_inverted")

        thesis = get_value_thesis(symbol)
        if thesis in ("review", "exit"):
            veto_reasons.append(f"scorer_veto_value_thesis_{thesis}")

        # ---- 通用學習鎖 ----
        hard_fails = check_all_hard_rules(
            "leaps_entry", symbol, dte_days=effective_dte, context=context,
        )
        veto_reasons.extend([reason for ok, reason in hard_fails if not ok])

        if veto_reasons:
            return build_scorer_result(
                symbol, "leaps_entry", raw_score=0,
                veto_triggered=True, veto_reasons=veto_reasons,
                extra={"value_thesis": thesis, "dte_days": effective_dte},
            )

        # ---- 正向評分 ----
        weights = LEAPS_ENTRY_WEIGHTS
        components: dict = {}

        rsi = get_rsi_latest(df, 14) or 50
        high_data = get_52w_high_low(symbol) or {}
        bb_pos = get_bbands_position(df) or {}
        ma_pos = get_ma_position(df) or {}

        # 進場品質(60分)
        entry_score = 0.0
        if rsi < 30:
            entry_score += 22
        elif rsi < 40:
            entry_score += 12
        if bb_pos.get("touch_lower"):
            entry_score += 12
        pct_from_50ma = ma_pos.get("pct_from_sma_50", 0)
        if pct_from_50ma < -0.05:
            entry_score += 12
        pct_from_high = high_data.get("pct_from_high") or 0
        if pct_from_high < -0.25:
            entry_score += 14
        elif pct_from_high < -0.15:
            entry_score += 7
        components["entry_quality"] = min(weights["entry_quality"], entry_score)

        # 估值面(20分)
        try:
            fund = fetch_fundamentals(symbol) or {}
        except Exception as e:
            logger.warning(f"leaps fundamentals fetch failed: {e}")
            fund = {}
        val_score = 0.0
        pe_fwd = fund.get("pe_forward")
        if pe_fwd is not None and 0 < pe_fwd < 20:
            val_score += 8
        fcf_y = fund.get("fcf_yield")
        if fcf_y is not None and fcf_y > 0.04:
            val_score += 7
        peg = fund.get("peg")
        if peg is not None and 0 < peg < 1.5:
            val_score += 5
        components["valuation"] = min(weights["valuation"], val_score)

        # 波動面(20分)
        ivr_data = calc_iv_rank(symbol) or {}
        ivr = ivr_data.get("ivr")
        vol_score = 0.0
        if ivr is not None:
            if 30 <= ivr <= 70:
                vol_score = 20
            elif ivr > 70:
                vol_score = 12
            else:  # ivr < 30
                vol_score = 8
        components["volatility"] = min(weights["volatility"], vol_score)

        raw_score = sum(components.values())

        layer0_capped = clip(layer0_mod, -30, 20)  # v4 LAYER0_MODIFIER_MIN/MAX
        layer_f_capped = clip(layer_f_mod, 0, weights["max_layerf"])

        return build_scorer_result(
            symbol, "leaps_entry",
            raw_score=raw_score,
            layer0_modifier=int(layer0_capped),
            layer_f_modifier=int(layer_f_capped),
            components=components,
            indicators={
                "rsi": rsi, "ivr": ivr,
                "pct_from_52w_high": pct_from_high,
                "pct_from_50ma": pct_from_50ma,
                "pe_forward": pe_fwd, "fcf_yield": fcf_y, "peg": peg,
            },
            extra={"value_thesis": thesis, "dte_days": effective_dte},
        )
    except Exception as e:
        logger.warning(f"score_leaps_entry({symbol}) failed: {e}")
        return build_scorer_result(
            symbol, "leaps_entry", raw_score=0,
            veto_triggered=True, veto_reasons=[f"exception:{type(e).__name__}"],
        )
