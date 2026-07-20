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


def _rs_reading(trend: dict[str, Any]) -> dict[str, Any]:
    """從 trend 讀出 benchmark RS 狀態(add gate 依此判斷,不再只看均線)。

    available:RS20 vs QQQ 是否算得出(benchmark 在且長度足夠)。
    leadership:RS20 vs QQQ 為正(期間內跑贏大盤)。
    improving:RS20 >= RS63(近月相對強度不弱於中期),兩者都可得才判定。
    """
    rs_qqq = trend.get("rs_vs_qqq", {}) if isinstance(trend, dict) else {}
    r20 = rs_qqq.get(20) if isinstance(rs_qqq, dict) else None
    r63 = rs_qqq.get(63) if isinstance(rs_qqq, dict) else None
    v20 = r20.get("value") if isinstance(r20, dict) and r20.get("status") == "ok" else None
    v63 = r63.get("value") if isinstance(r63, dict) and r63.get("status") == "ok" else None
    available = v20 is not None
    leadership = available and v20 > 0
    improving = v20 is not None and v63 is not None and v20 >= v63
    return {
        "available": available,
        "leadership": leadership,
        "improving": improving,
        "rs20": v20,
        "rs63": v63,
    }


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
    options_confirmed = bool(options_pressure.get("downside_pressure_confirmed_ok"))
    rs = _rs_reading(trend)

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
        # 缺 volume 不得視為確認(finding P1):None → 不 eligible 且標 blocker。
        volume_confirmed = vol_pct is not None and vol_pct >= 0.5
        reasons.append("donchian_breakout_up")
        if vol_pct is None:
            flags.append("breakout_volume_unconfirmed")
        elif not volume_confirmed:
            flags.append("breakout_low_volume")
        if not rs["leadership"]:
            flags.append("breakout_rs_not_leading")
        if options_worsening:
            flags.append("breakout_options_pressure_worsening")
        # 突破要成為 add-ready,需 volume 確認 + RS 領先 + options 下檔壓力未惡化。
        eligible = volume_confirmed and rs["leadership"] and not options_worsening
        return {
            "state": "breakout_confirmed",
            "reasons": reasons,
            "long_entry_eligible": bool(eligible),
            "flags": flags,
        }

    rising_50 = _slope_not_declining(slope50)
    rising_20 = _slope_not_declining(slope20)

    # -- reclaim_confirmed(§6):剛站回 50DMA + 50DMA 未惡化 + RS 改善 +
    #    options 下檔壓力未惡化。可達且可測試(依 trend["reclaim"])。 --
    reclaim = trend.get("reclaim", {}) if isinstance(trend, dict) else {}
    if (
        reclaim.get("reclaimed")
        and rising_50
        and rs["improving"]
        and not options_worsening
    ):
        reasons.append("reclaimed_50dma_with_rs_improving")
        if not rs["leadership"]:
            flags.append("reclaim_rs_positive_but_not_leading")
        # add-ready 需 RS 領先;RS 僅改善但未領先時確認 state 但不放行加碼。
        eligible = rs["leadership"] and (options_confirmed or not options_worsening)
        return {
            "state": "reclaim_confirmed",
            "reasons": reasons,
            "long_entry_eligible": bool(eligible),
            "flags": flags,
        }

    # 站上上升 50DMA/20DMA → trend_healthy;但 add-ready 需 RS 可得且領先、options 未惡化。
    if rising_50 and rising_20:
        reasons.append("above_rising_50dma")
        if not rs["available"]:
            flags.append("rs_unavailable_add_gate_closed")
        elif not rs["leadership"]:
            flags.append("rs_not_leading_add_gate_closed")
        if options_worsening:
            flags.append("options_pressure_worsening")
        return {
            "state": "trend_healthy",
            "reasons": reasons,
            "long_entry_eligible": bool(rs["leadership"] and not options_worsening),
            "flags": flags,
        }

    # 站上 50DMA 但短期節奏未完全轉正 → pullback_test(健康回檔);
    # add-ready 需 50DMA 未下降 + RS 領先 + options 未惡化。
    reasons.append("above_50dma_pullback")
    if bb.get("touch_lower"):
        flags.append("healthy_pullback_lower_band")
    if not rs["leadership"]:
        flags.append("pullback_rs_not_leading")
    if options_worsening:
        flags.append("options_pressure_worsening")
    return {
        "state": "pullback_test",
        "reasons": reasons,
        "long_entry_eligible": bool(rising_50 and rs["leadership"] and not options_worsening),
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
    data_blocked: bool = False,
    add_block_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """把 trend + thesis + options 綜合成一張 focus card 的狀態組合。

    三個狀態各自獨立輸出,便於 dashboard 與測試分別檢查。
    data_blocked=True 或 add_block_reasons 非空(stale/partial 資料、缺 valuation 核准、
    required options 確認 unavailable/worsening)時強制關閉 add-ready 與 long eligibility,
    並把 add-ready 姿態降級為 wait_for_proof(fail closed:缺 proof 不等於可加碼)。
    timing_state 仍照常顯示。
    """
    timing = classify_timing(trend, options_pressure)
    exposure = derive_exposure_posture(thesis_state, timing, has_leverage=has_leverage)

    block_reasons = list(add_block_reasons or [])
    if data_blocked and "data_blocked_stale_or_partial" not in block_reasons:
        block_reasons.append("data_blocked_stale_or_partial")

    long_eligible = bool(timing["long_entry_eligible"])
    add_allowed = bool(exposure["add_allowed"])
    posture = exposure["posture"]
    exposure_reasons = list(exposure["reasons"])
    if block_reasons:
        long_eligible = False
        if add_allowed:
            add_allowed = False
            posture = "wait_for_proof"
        exposure_reasons.extend(block_reasons)

    return {
        "company_thesis_state": (
            thesis_state if thesis_state in COMPANY_THESIS_STATES else "watch"
        ),
        "timing_state": timing["state"],
        "exposure_posture": posture,
        "long_entry_eligible": long_eligible,
        "add_allowed": add_allowed,
        "timing_reasons": timing["reasons"],
        "timing_flags": timing["flags"],
        "exposure_reasons": exposure_reasons,
        "not_a_trade_signal": True,
    }
