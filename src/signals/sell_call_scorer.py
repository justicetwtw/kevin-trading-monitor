"""系統 #1 - 賣 CALL 評分(Covered/Diagonal/Naked-against-2x-ETF)

權重從 SELL_CALL_WEIGHTS 讀。Layer 0 modifier 由呼叫方傳入(來自 aggregate_layer0)。
失敗冷啟動回 score=0,不拋例外。
"""

from loguru import logger

from src.config.thresholds import (
    SELL_CALL_WEIGHTS, SELL_CALL_VETO, IVR_THRESHOLDS, IVR_2X_ETF_THRESHOLD,
)
from src.config.universe import ETF_LEVERAGED_SINGLE_STOCK
from src.data.earnings_calendar import is_earnings_within_days
from src.data.iv_rank import calc_iv_rank, get_atm_iv
from src.data.price_data import fetch_history, get_52w_high_low
from src.indicators.basic import (
    get_rsi_latest, get_bbands_position, get_ma_position,
    get_adx_latest, get_consecutive_up_days,
)
from src.indicators.volume import detect_volume_surge, detect_volume_price_divergence
from src.indicators.pattern import detect_resistance_rejection
from src.layers.analyst_dashboard import get_analyst_modifier
from src.signals.base_scorer import build_scorer_result, clip
from src.signals.veto_checker import check_all_hard_rules


def score(symbol: str, layer0_mod: int = 0, context: dict | None = None) -> dict:
    """單一標的賣 CALL 評分。回傳 12 欄 dict。"""
    try:
        df = fetch_history(symbol, period="6mo", interval="1d")
        if df is None or df.empty:
            return build_scorer_result(
                symbol, "sell_call", raw_score=0,
                veto_triggered=True, veto_reasons=["no_price_data"],
            )

        is_2x_etf = symbol in ETF_LEVERAGED_SINGLE_STOCK
        ivr_threshold = IVR_2X_ETF_THRESHOLD if is_2x_etf else IVR_THRESHOLDS["min_for_short_premium"]

        # ---- Scorer 內部 veto(訊號專屬,與通用學習鎖分開)----
        veto_reasons: list[str] = []

        try:
            if is_earnings_within_days(symbol, SELL_CALL_VETO["earnings_within_days"]):
                veto_reasons.append("scorer_veto_earnings_within_7_days")
        except Exception as e:
            logger.warning(f"sell_call earnings check failed: {e}")

        high_data = get_52w_high_low(symbol) or {}
        pct_from_high = high_data.get("pct_from_high")
        if (pct_from_high is not None
                and pct_from_high > -(1 - SELL_CALL_VETO["near_52w_high_pct"])
                and detect_volume_surge(df, SELL_CALL_VETO["volume_surge_multiplier"])):
            veto_reasons.append("scorer_veto_near_52w_high_with_volume_surge")

        adx = get_adx_latest(df, 14)
        if adx is not None and adx > SELL_CALL_VETO["adx_strong_trend"]:
            veto_reasons.append(f"scorer_veto_adx_{int(adx)}_above_25")

        try:
            analyst = get_analyst_modifier(symbol) or {}
            if analyst.get("sell_call_veto"):
                veto_reasons.append("scorer_veto_analyst_upgrades_2plus")
        except Exception as e:
            logger.warning(f"sell_call analyst veto check failed: {e}")

        ivr_data = calc_iv_rank(symbol) or {}
        ivr = ivr_data.get("ivr")
        if ivr is not None and ivr < ivr_threshold:
            veto_reasons.append(f"scorer_veto_ivr_{int(ivr)}_below_{int(ivr_threshold)}")

        # ---- 通用學習鎖 ----
        hard_fails = check_all_hard_rules(
            "sell_call", symbol, ivr=ivr, context=context,
        )
        veto_reasons.extend([reason for ok, reason in hard_fails if not ok])

        if veto_reasons:
            return build_scorer_result(
                symbol, "sell_call", raw_score=0,
                layer0_modifier=0, layer_f_modifier=0,
                veto_triggered=True, veto_reasons=veto_reasons,
                indicators={"ivr": ivr, "adx": adx, "pct_from_52w_high": pct_from_high},
            )

        # ---- 正向評分 ----
        weights = SELL_CALL_WEIGHTS
        components: dict = {}

        # 權利金面(40分)
        iv_score = 0.0
        if ivr is not None:
            iv_score = (ivr / 100) * 25
        atm_iv = get_atm_iv(symbol) or 0
        iv_score += min(15, atm_iv * 50)
        components["premium"] = min(weights["premium"], iv_score)

        # 價格面(40分)
        rsi = get_rsi_latest(df, 14) or 50
        bb_pos = get_bbands_position(df) or {}
        ma_pos = get_ma_position(df) or {}
        consecutive = get_consecutive_up_days(df)

        price_score = 0.0
        if rsi > 70:
            price_score += 15
        elif rsi > 60:
            price_score += 8
        if ma_pos.get("pct_from_sma_20", 0) > 0.05:
            price_score += 10
        if consecutive >= 4:
            price_score += 8
        if bb_pos.get("touch_upper"):
            price_score += 7
        components["price"] = min(weights["price"], price_score)

        # 形態確認(20分)
        pattern_score = 0.0
        if detect_resistance_rejection(df):
            pattern_score += 12
        div = detect_volume_price_divergence(df) or {}
        if div.get("type") == "bearish":
            pattern_score += 8
        components["pattern"] = min(weights["pattern"], pattern_score)

        raw_score = sum(components.values())
        layer0_capped = clip(layer0_mod, -weights["max_layer0"], weights["max_layer0"])

        return build_scorer_result(
            symbol, "sell_call",
            raw_score=raw_score,
            layer0_modifier=int(layer0_capped),
            layer_f_modifier=0,
            components=components,
            indicators={
                "rsi": rsi, "ivr": ivr, "atm_iv": atm_iv, "adx": adx,
                "pct_from_52w_high": pct_from_high,
                "consecutive_up": consecutive,
                "bb_pos_pct": bb_pos.get("pct"),
            },
        )
    except Exception as e:
        logger.warning(f"score_sell_call({symbol}) failed: {e}")
        return build_scorer_result(
            symbol, "sell_call", raw_score=0,
            veto_triggered=True, veto_reasons=[f"exception:{type(e).__name__}"],
        )
