"""Thesis / timing / exposure state machine(docs/focus_trading_engine_v1.md §3, §6)。

三件事永久分離:
  - company_thesis_state:公司論點(由基本面/估值決定,不由價格決定)。
  - timing_state:價格/趨勢節奏(由 20/50/200DMA、RS、breakout、options 決定)。
  - exposure_posture:綜合上面兩者後的曝險姿態(該持有/避險/等確認/加碼/降槓桿/重新承保)。

最重要的紅線(§3.3 / §3.4 / 驗收 #2):
  收盤低於「下降中的 50DMA」時,RSI/BB 超賣不得提高 long eligibility——
  這種型態要標成 falling-knife / trend_damaged,而不是抄底加分。

本模組只吃已算好的 trend features(src/focus/trend.py)與 thesis / options 輸入,
不打網路、不看未來、不產生訂單。缺資料一律 fail closed 成 insufficient_data。
"""

from __future__ import annotations

from typing import Any

# ---- 允許的狀態(schema 穩定,測試據此檢查) ----

COMPANY_THESIS_STATES = (
    "strengthening",
    "intact",
    "watch",
    "impaired",
    "broken",
)

TIMING_STATES = (
    "trend_healthy",
    "pullback_test",
    "bottom_watch",
    "reclaim_confirmed",
    "breakout_confirmed",
    "overheated",
    "trend_damaged",
    "insufficient_data",
)

EXPOSURE_POSTURES = (
    "core_hold",
    "hold_hedged",
    "wait_for_proof",
    "tactical_add_ready",
    "press_trend",
    "reduce_leverage",
    "re_underwrite",
)

_INTACT_OR_BETTER = {"strengthening", "intact"}
#: RSI 判定超賣的門檻(僅描述位置,不獨立生成訊號)。
RSI_OVERSOLD = 30.0
RSI_OVERHEATED = 78.0
#: 距 20DMA 多少比例視為「過度延伸」(overheated 候選)。
EXTENSION_FROM_SMA20 = 0.12


def _slope_declining(slope: float | None) -> bool:
    """slope 明確為負才算下降;None(資料不足)不當成下降,回 False。"""
    return slope is not None and slope < 0


def _slope_not_declining(slope: float | None) -> bool:
    """明確 >= 0 才算「未下降」;None 不足以證明,回 False(fail closed)。"""
    return slope is not None and slope >= 0


def classify_timing(
    trend: dict[str, Any],
    options_pressure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """由 trend features 推導 timing_state。

    回傳 {state, reasons, long_entry_eligible, flags}。
    long_entry_eligible=False 代表現在不是新增 tactical/leveraged 多頭的時機。
    """
    reasons: list[str] = []
    flags: list[str] = []
    options_pressure = options_pressure or {}

    if not trend or trend.get("status") != "ok":
        return {
            "state": "insufficient_data",
            "reasons": ["trend_features_unavailable"],
            "long_entry_eligible": False,
            "flags": ["insufficient_data"],
        }

    close = trend.get("close")
    sma = trend.get("sma", {})
    slope = trend.get("sma_slope", {})
    above = trend.get("above_sma", {})
    rsi = trend.get("rsi")
    bb = trend.get("bollinger", {})
    donchian = trend.get("donchian", {})

    sma20 = sma.get(20)
    sma50 = sma.get(50)
    slope50 = slope.get(50)
    slope20 = slope.get(20)
    above50 = above.get(50)
    above200 = above.get(200)

    # 缺 50DMA 就無法做核心 timing 判定 → fail closed。
    if close is None or sma50 is None or above50 is None:
        return {
            "state": "insufficient_data",
            "reasons": ["missing_50dma_context"],
            "long_entry_eligible": False,
            "flags": ["insufficient_data"],
        }

    below_50 = not above50
    declining_50 = _slope_declining(slope50)
    rsi_oversold = rsi is not None and rsi <= RSI_OVERSOLD
    touch_lower = bool(bb.get("touch_lower"))
    donch20 = donchian.get(20, {})
    donch55 = donchian.get(55, {})
    breakout_up = donch20.get("status") == "breakout_up" or donch55.get("status") == "breakout_up"
    breakout_down = donch20.get("status") == "breakout_down" or donch55.get("status") == "breakout_down"

    options_worsening = bool(options_pressure.get("downside_pressure_worsening"))

    # -- 決策順序:先處理下降趨勢(避免 falling knife 被當抄底) --

    if below_50 and declining_50:
        # 收盤在下降 50DMA 之下:RSI/BB 超賣是「沿下軌的 falling knife」,
        # 明確標記,long_entry_eligible 一律 False(§3.4)。
        if rsi_oversold or touch_lower:
            flags.append("falling_knife_oversold_not_a_buy")
        if breakout_down or (above200 is False):
            reasons.append("sustained_below_declining_50dma")
            return {
                "state": "trend_damaged",
                "reasons": reasons or ["below_declining_50dma"],
                "long_entry_eligible": False,
                "flags": flags,
            }
        reasons.append("below_declining_50dma")
        return {
            "state": "trend_damaged",
            "reasons": reasons,
            "long_entry_eligible": False,
            "flags": flags,
        }

    if below_50 and not declining_50:
        # 低於 50DMA 但 50DMA 尚未明確下彎:等重新站回的 bottom_watch,
        # 仍不主動加碼(long_entry_eligible=False)。
        if rsi_oversold or touch_lower:
            flags.append("oversold_position_label_only")
        reasons.append("below_50dma_awaiting_reclaim")
        if options_worsening:
            flags.append("options_downside_pressure_elevated")
        return {
            "state": "bottom_watch",
            "reasons": reasons,
            "long_entry_eligible": False,
            "flags": flags,
        }

    # -- 收盤在 50DMA 之上 --

    extended = (
        sma20 is not None
        and close is not None
        and sma20 != 0
        and (close / sma20 - 1.0) >= EXTENSION_FROM_SMA20
    )
    rsi_hot = rsi is not None and rsi >= RSI_OVERHEATED
    if extended or rsi_hot:
        reasons.append("extended_from_trend")
        if rsi_hot:
            flags.append("rsi_overheated")
        if bb.get("touch_upper"):
            flags.append("upper_band_extended")
        return {
            "state": "overheated",
            "reasons": reasons,
            # 過熱時不新增追高多頭。
            "long_entry_eligible": False,
            "flags": flags,
        }

    if breakout_up:
        vol_pct = trend.get("volume_percentile")
        volume_ok = vol_pct is None or vol_pct >= 0.5
        reasons.append("donchian_breakout_up")
        if not volume_ok:
            flags.append("breakout_low_volume")
        return {
            "state": "breakout_confirmed",
            "reasons": reasons,
            "long_entry_eligible": bool(volume_ok),
            "flags": flags,
        }

    # 站上 50DMA、50DMA 未下降:若剛從下方站回視為 reclaim,否則 healthy。
    rising_50 = _slope_not_declining(slope50)
    rising_20 = _slope_not_declining(slope20)
    if rising_50 and rising_20:
        reasons.append("above_rising_50dma")
        return {
            "state": "trend_healthy",
            "reasons": reasons,
            "long_entry_eligible": True,
            "flags": flags,
        }

    # 站上 50DMA 但短期節奏未完全轉正 → pullback_test(健康回檔),
    # 允許在趨勢方向的加碼但需 proof。
    reasons.append("above_50dma_pullback")
    if bb.get("touch_lower"):
        flags.append("healthy_pullback_lower_band")
    return {
        "state": "pullback_test",
        "reasons": reasons,
        "long_entry_eligible": bool(rising_50),
        "flags": flags,
    }


def derive_exposure_posture(
    thesis_state: str,
    timing: dict[str, Any],
    has_leverage: bool = False,
) -> dict[str, Any]:
    """由 thesis_state + timing_state 推導 exposure_posture(§3.1, §6)。

    核心原則:
      - thesis intact 時不因單日跌破 50DMA 全部退出核心(§3.3)。
      - thesis impaired/broken → re_underwrite,曝險評級暫停。
      - 下降趨勢中不放大槓桿;有槓桿又 trend_damaged → reduce_leverage。
    """
    thesis_state = thesis_state if thesis_state in COMPANY_THESIS_STATES else "watch"
    timing_state = timing.get("state", "insufficient_data")
    long_eligible = bool(timing.get("long_entry_eligible"))
    reasons: list[str] = []

    # thesis 破壞優先:重新承保,不談加碼。
    if thesis_state in {"impaired", "broken"}:
        reasons.append("thesis_impaired_or_broken")
        return {
            "posture": "re_underwrite",
            "reasons": reasons,
            "add_allowed": False,
        }

    if timing_state == "insufficient_data":
        reasons.append("timing_insufficient_data")
        return {
            "posture": "wait_for_proof",
            "reasons": reasons,
            "add_allowed": False,
        }

    if timing_state == "trend_damaged":
        reasons.append("trend_damaged")
        if has_leverage:
            return {
                "posture": "reduce_leverage",
                "reasons": reasons + ["leverage_in_downtrend"],
                "add_allowed": False,
            }
        # thesis 仍 intact:保留核心但加對沖,不加碼。
        return {
            "posture": "hold_hedged",
            "reasons": reasons,
            "add_allowed": False,
        }

    if timing_state == "overheated":
        reasons.append("overheated_entry_risk")
        return {
            "posture": "hold_hedged" if has_leverage else "core_hold",
            "reasons": reasons,
            "add_allowed": False,
        }

    if timing_state == "bottom_watch":
        reasons.append("below_50dma_awaiting_reclaim")
        return {
            "posture": "wait_for_proof",
            "reasons": reasons,
            "add_allowed": False,
        }

    if timing_state == "breakout_confirmed":
        if long_eligible and thesis_state in _INTACT_OR_BETTER:
            reasons.append("breakout_with_intact_thesis")
            return {
                "posture": "press_trend",
                "reasons": reasons,
                "add_allowed": True,
            }
        reasons.append("breakout_needs_thesis_or_volume")
        return {
            "posture": "wait_for_proof",
            "reasons": reasons,
            "add_allowed": False,
        }

    if timing_state in {"trend_healthy", "reclaim_confirmed", "pullback_test"}:
        if long_eligible and thesis_state in _INTACT_OR_BETTER:
            reasons.append("healthy_trend_intact_thesis")
            return {
                "posture": "tactical_add_ready",
                "reasons": reasons,
                "add_allowed": True,
            }
        reasons.append("healthy_trend_but_add_gate_incomplete")
        return {
            "posture": "core_hold",
            "reasons": reasons,
            "add_allowed": False,
        }

    reasons.append("default_conservative")
    return {"posture": "core_hold", "reasons": reasons, "add_allowed": False}


def evaluate_symbol(
    trend: dict[str, Any],
    thesis_state: str,
    options_pressure: dict[str, Any] | None = None,
    has_leverage: bool = False,
) -> dict[str, Any]:
    """把 trend + thesis + options 綜合成一張 focus card 的狀態組合。

    三個狀態各自獨立輸出,便於 dashboard 與測試分別檢查。
    """
    timing = classify_timing(trend, options_pressure)
    exposure = derive_exposure_posture(thesis_state, timing, has_leverage=has_leverage)
    return {
        "company_thesis_state": (
            thesis_state if thesis_state in COMPANY_THESIS_STATES else "watch"
        ),
        "timing_state": timing["state"],
        "exposure_posture": exposure["posture"],
        "long_entry_eligible": timing["long_entry_eligible"],
        "add_allowed": exposure["add_allowed"],
        "timing_reasons": timing["reasons"],
        "timing_flags": timing["flags"],
        "exposure_reasons": exposure["reasons"],
        "not_a_trade_signal": True,
    }
