"""系統 #2 - 賣 PUT(Wheel Strategy)

第一道閘門:必須在 SELL_PUT_WHITELIST。
權重從 SELL_PUT_WEIGHTS 讀;Layer F 由呼叫方加總後傳入(來自 insider_signals)。
失敗冷啟動回 score=0,不拋例外。
"""

from loguru import logger

from src.config.thresholds import (
    SELL_PUT_WEIGHTS, SELL_PUT_VETO, IVR_THRESHOLDS,
)
from src.config.universe import SELL_PUT_WHITELIST, is_etf_symbol
from src.data.earnings_calendar import is_earnings_within_days
from src.data.iv_rank import calc_iv_rank, get_atm_iv
from src.data.price_data import fetch_history, get_52w_high_low
from src.data.vix_structure import fetch_vix_term_structure
from src.indicators.basic import get_rsi_latest, get_bbands_position
from src.indicators.pattern import find_support_resistance
from src.signals.base_scorer import build_scorer_result, clip
from src.signals.veto_checker import check_all_hard_rules


def score(symbol: str, layer0_mod: int = 0, layer_f_mod: int = 0,
          context: dict | None = None) -> dict:
    """單一標的賣 PUT 評分。"""
    try:
        # ---- 第一道閘門:白名單 ----
        if symbol not in SELL_PUT_WHITELIST:
            return build_scorer_result(
                symbol, "sell_put", raw_score=0,
                veto_triggered=True, veto_reasons=["not_in_sell_put_whitelist"],
            )

        df = fetch_history(symbol, period="6mo", interval="1d")
        if df is None or df.empty:
            return build_scorer_result(
                symbol, "sell_put", raw_score=0,
                veto_triggered=True, veto_reasons=["no_price_data"],
            )

        # ---- Scorer 內部 veto ----
        veto_reasons: list[str] = []

        try:
            if is_earnings_within_days(symbol, SELL_PUT_VETO["earnings_within_days"]):
                veto_reasons.append("scorer_veto_earnings_within_7_days")
        except Exception as e:
            logger.warning(f"sell_put earnings check failed: {e}")

        try:
            vix_data = fetch_vix_term_structure() or {}
            vix = vix_data.get("vix")
            if vix is not None and vix > SELL_PUT_VETO["vix_extreme"]:
                veto_reasons.append(f"scorer_veto_vix_{int(vix)}_above_{SELL_PUT_VETO['vix_extreme']}")
        except Exception as e:
            logger.warning(f"sell_put vix check failed: {e}")
            vix = None

        ivr_data = calc_iv_rank(symbol) or {}
        ivr = ivr_data.get("ivr")
        # v4.1:IVR 閾值分流(個股 70 / ETF 30)
        ivr_threshold = (
            IVR_THRESHOLDS["min_for_short_premium_etf"]
            if is_etf_symbol(symbol)
            else IVR_THRESHOLDS["min_for_short_premium_stock"]
        )
        if ivr is not None and ivr < ivr_threshold:
            veto_reasons.append(f"scorer_veto_ivr_{int(ivr)}_below_{int(ivr_threshold)}")

        # ---- 通用學習鎖 ----
        hard_fails = check_all_hard_rules(
            "sell_put", symbol, ivr=ivr, context=context,
        )
        veto_reasons.extend([reason for ok, reason in hard_fails if not ok])

        if veto_reasons:
            return build_scorer_result(
                symbol, "sell_put", raw_score=0,
                veto_triggered=True, veto_reasons=veto_reasons,
                indicators={"ivr": ivr},
            )

        # ---- 正向評分 ----
        weights = SELL_PUT_WEIGHTS
        components: dict = {}

        # 權利金面(35分)
        iv_score = 0.0
        if ivr is not None:
            iv_score = (ivr / 100) * 20
        atm_iv = get_atm_iv(symbol) or 0
        iv_score += min(15, atm_iv * 50)
        components["premium"] = min(weights["premium"], iv_score)

        # 進場品質(45分)
        rsi = get_rsi_latest(df, 14) or 50
        high_data = get_52w_high_low(symbol) or {}
        bb_pos = get_bbands_position(df) or {}
        sr = find_support_resistance(df) or {}

        entry_score = 0.0
        if rsi < 30:
            entry_score += 18
        elif rsi < 40:
            entry_score += 10

        pct_from_high = high_data.get("pct_from_high") or 0
        if pct_from_high < -0.20:
            entry_score += 12
        elif pct_from_high < -0.10:
            entry_score += 6

        if bb_pos.get("touch_lower"):
            entry_score += 8
        if sr.get("near_support"):
            entry_score += 7

        components["entry_quality"] = min(weights["entry_quality"], entry_score)

        # 形態確認(20分)
        pattern_score = 0.0
        if rsi < 35 and bb_pos.get("touch_lower"):
            pattern_score += 12
        components["pattern"] = min(weights["pattern"], pattern_score)

        raw_score = sum(components.values())

        layer0_capped = clip(layer0_mod, -weights["max_layer0"], weights["max_layer0"])
        layer_f_capped = clip(layer_f_mod, 0, weights["max_layerf"])

        return build_scorer_result(
            symbol, "sell_put",
            raw_score=raw_score,
            layer0_modifier=int(layer0_capped),
            layer_f_modifier=int(layer_f_capped),
            components=components,
            indicators={
                "rsi": rsi, "ivr": ivr, "atm_iv": atm_iv,
                "pct_from_52w_high": pct_from_high,
                "near_support": sr.get("near_support"),
                "vix": vix,
            },
        )
    except Exception as e:
        logger.warning(f"score_sell_put({symbol}) failed: {e}")
        return build_scorer_result(
            symbol, "sell_put", raw_score=0,
            veto_triggered=True, veto_reasons=[f"exception:{type(e).__name__}"],
        )
