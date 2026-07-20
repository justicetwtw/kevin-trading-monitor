"""Focus Trading Engine payload assembly(docs/focus_trading_engine_v1.md §8)。

把 trend / state machine / options capability / exposure 組成 holdings-first 的
focus payload,供 Mission Control 以 shadow / display-only 呈現。

紅線:
  - 這是 display-only:不覆蓋既有 alerts,不產生訂單,not_a_trade_signal=True。
  - 每張 focus card 都帶 source/as_of/readiness blockers;缺資料可見,不以單一分數掩蓋。
  - public payload 只用 public_exposure_summary 的 aggregate,不含私有識別資訊。
  - feature flag 關閉時回傳 disabled envelope,呼叫方據此不顯示 focus 區塊。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from src.focus.config import focus_engine_enabled, focus_engine_mode
from src.focus.state_machine import evaluate_symbol
from src.focus.universe import map_instrument

SCHEMA_VERSION = 1
#: 價格 as-of 超過這個日曆天數(含長假)即視為 stale,card fail closed。
MAX_CARD_AGE_DAYS = 5
#: 估值 scenario 的新鮮度窗口(季報節奏 → 較寬鬆,但仍必須有 as_of;core 核准集合與
#: scenario 數學一律重用 Decision Engine 的 validator,不在此另立標準)。
MAX_VALUATION_AGE_DAYS = 45


def _as_of_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def valuation_approved(
    evidence: dict[str, Any] | None,
    reference_date: date | None = None,
    *,
    symbol: str | None = None,
    current_price: float | None = None,
    market_as_of: str | None = None,
) -> dict[str, Any]:
    """判斷估值是否達 decision-grade 核准(finding P1 修正 round 5)。

    紅線:單一 ``valuation_status`` 字串或任意 truthy object **不足以**解鎖 add。
    這裡**重用既有 Decision Engine 的 scenario/readiness validator**(不另建較弱的第二條
    核准路徑):

      - `validate_scenario`:current_price / as_of / source / cases(機率 (0,1] 且合計 100%、
        價格為正)全部有效才過;否則回具體 error。
      - `_scenario_market_anchor_errors`:scenario 的 current_price 必須貼齊該證券的即時
        收盤(drift ≤ 5%)且 as_of 與 market as_of 差距 ≤ 3 天。
      - approval_status ∈ Decision Engine 核准集合、有 approval actor、標的/thesis identity 一致。
      - scenario as_of 在 valuation 新鮮度窗口內。

    任一缺失/過期/不一致 → 不核准(fail closed)。
    """
    from src.decision.decision_grade import APPROVED_VALUES as _DECISION_APPROVED
    from src.decision.opportunity_ranker import (
        _scenario_market_anchor_errors,
        validate_scenario,
    )
    from src.focus.freshness import freshness as _freshness

    if not isinstance(evidence, dict):
        return {"approved": False, "reasons": ["valuation_evidence_missing"], "scenario": None}

    reasons: list[str] = []

    # 核准狀態 + 核准人(actor)。重用 Decision Engine 的核准集合,不另立標準。
    if str(evidence.get("approval_status") or "") not in _DECISION_APPROVED:
        reasons.append("valuation_not_approved")
    if not evidence.get("approved_by"):
        reasons.append("valuation_approval_actor_missing")

    # 標的 / thesis identity 一致(避免拿別的證券的估值解鎖本張卡)。
    ev_symbol = str(evidence.get("symbol") or "").upper()
    if not ev_symbol:
        reasons.append("valuation_symbol_missing")
    elif symbol is not None and ev_symbol != str(symbol).upper():
        reasons.append("valuation_symbol_mismatch")
    if not evidence.get("thesis_id"):
        reasons.append("valuation_thesis_identity_missing")

    # Scenario 數學:直接重用 Decision Engine 的 validate_scenario(單一 source of truth)。
    scenario, scen_errors = validate_scenario(evidence.get("scenario"))
    reasons.extend(scen_errors)

    # current-price anchor + as_of gap vs 該證券即時收盤(重用 Decision Engine anchor 檢查)。
    if scenario is not None and (current_price is not None or market_as_of is not None):
        reasons.extend(
            _scenario_market_anchor_errors(
                scenario, {"current_price": current_price, "as_of": market_as_of}
            )
        )

    # Scenario as_of 的 valuation 新鮮度(季報節奏窗口)。
    scen_as_of = scenario["as_of"] if scenario is not None else (evidence.get("scenario") or {}).get("as_of")
    fresh = _freshness(scen_as_of, reference_date, MAX_VALUATION_AGE_DAYS)
    if fresh["status"] in ("missing", "stale"):
        reasons.append("valuation_evidence_stale_or_missing_as_of")

    return {
        "approved": not reasons,
        "reasons": sorted(set(reasons)),
        "scenario": scenario,
        "freshness": fresh,
    }


def build_focus_card(
    symbol: str,
    trend: dict[str, Any],
    thesis_state: str,
    *,
    options_capability: dict[str, Any] | None = None,
    options_pressure: dict[str, Any] | None = None,
    valuation_status: str | None = None,
    valuation_evidence: dict[str, Any] | None = None,
    source: str = "yfinance_delayed_public_market_data",
    as_of: str | None = None,
    reference_date: date | None = None,
    benchmark_freshness: dict[str, Any] | None = None,
    market_exposure_cap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """組出單一 focus card(§8 每張卡最低欄位)。"""
    from src.focus.freshness import freshness as _freshness

    mapping = map_instrument(symbol)
    has_leverage = mapping["kind"] == "leveraged_single"

    sma = trend.get("sma", {}) if isinstance(trend, dict) else {}
    slope = trend.get("sma_slope", {}) if isinstance(trend, dict) else {}
    rs_qqq = trend.get("rs_vs_qqq", {}) if isinstance(trend, dict) else {}
    rs_smh = trend.get("rs_vs_smh", {}) if isinstance(trend, dict) else {}
    bb = trend.get("bollinger", {}) if isinstance(trend, dict) else {}
    donchian = trend.get("donchian", {}) if isinstance(trend, dict) else {}

    card_as_of = as_of or (trend.get("as_of") if isinstance(trend, dict) else None)
    security_freshness = _freshness(card_as_of, reference_date, MAX_CARD_AGE_DAYS)

    blockers: list[str] = []
    if not isinstance(trend, dict) or trend.get("status") != "ok":
        blockers.append("price_trend_unavailable")
    if rs_qqq.get(20, {}).get("status") not in (None, "ok"):
        blockers.append("rs_benchmark_incomplete")
    if valuation_status in (None, "not_connected", "unconfigured"):
        blockers.append("valuation_not_connected")
    if options_capability is None:
        blockers.append("options_capability_unknown")
    # security as-of / staleness fail-closed。
    if isinstance(trend, dict) and trend.get("status") == "ok":
        if security_freshness["status"] == "missing":
            blockers.append("as_of_missing")
        elif security_freshness["status"] == "stale":
            blockers.append("price_stale")
    # benchmark freshness:benchmark stale/missing → RS 不可信,擋 add(§ freshness gate)。
    if benchmark_freshness is not None and benchmark_freshness.get("status") in ("stale", "missing"):
        blockers.append("rs_benchmark_stale")

    # 任一 stale/missing/incomplete blocker 存在時,強制關閉 add-ready 與 long eligibility
    # (fail closed:資料不可信不得升 add-ready)。
    _blocking = {
        "price_trend_unavailable", "rs_benchmark_incomplete", "rs_benchmark_stale",
        "as_of_missing", "price_stale",
    }
    data_blocked = bool(_blocking & set(blockers))

    # Fundamentals/options proof gate(finding P1):missing valuation approval 或
    # required options 確認 unavailable/worsening 都不得放行 add —— missing ≠ 可加碼。
    add_block_reasons: list[str] = []
    # 估值必須達 decision-grade:重用 Decision Engine 的 scenario/anchor validator
    # (source/as_of/機率/價格排序/current-price anchor/identity);單一字串或任意 truthy
    # object 不解鎖 add(finding P1 round 5)。current_price/as_of 取自本張卡的證券收盤。
    val_gate = valuation_approved(
        valuation_evidence,
        reference_date,
        symbol=mapping["underlying"] or symbol,
        current_price=trend.get("close") if isinstance(trend, dict) else None,
        market_as_of=card_as_of,
    )
    if not val_gate["approved"]:
        add_block_reasons.append("valuation_not_approved")
        if "valuation_not_approved" not in blockers:
            blockers.append("valuation_not_approved")
    opt_status = (options_pressure or {}).get("status")
    if options_pressure is None or opt_status == "unavailable":
        add_block_reasons.append("options_confirmation_unavailable")
        if "options_confirmation_unavailable" not in blockers:
            blockers.append("options_confirmation_unavailable")
    elif opt_status == "worsening":
        add_block_reasons.append("options_pressure_worsening")

    # Market regime exposure cap(§ Layer B)。stress / 未知 regime → 封頂(擋 add);
    # elevated(0<mult<1)不擋 add,但把曝險上限倍數往下收。
    # 注意(finding round 5,honest label):這只是 regime 的「曝險上限倍數」,不是完整的
    # live position proposal —— 尚未併入 ATR sizing、當前曝險與 core/tactical 分層。
    regime_exposure_cap_multiplier: float | None = None
    if market_exposure_cap is not None:
        mult = market_exposure_cap.get("max_exposure_multiplier")
        if market_exposure_cap.get("blocks_new_exposure"):
            add_block_reasons.append("market_regime_caps_exposure")
            if "market_regime_caps_exposure" not in blockers:
                blockers.append("market_regime_caps_exposure")
            regime_exposure_cap_multiplier = 0.0
        elif isinstance(mult, (int, float)) and not isinstance(mult, bool):
            # non-zero cap:上限倍數套到 gross 曝險(leveraged 工具再按槓桿收斂)。
            lev = mapping["leverage"] or 1.0
            regime_exposure_cap_multiplier = round(min(mult, mult / lev) if has_leverage else mult, 4)

    states = evaluate_symbol(
        trend,
        thesis_state,
        options_pressure=options_pressure,
        has_leverage=has_leverage,
        data_blocked=data_blocked,
        add_block_reasons=add_block_reasons,
    )

    def _rs(block: dict[str, Any], window: int) -> Any:
        item = block.get(window) if isinstance(block, dict) else None
        return item.get("value") if isinstance(item, dict) else None

    return {
        "symbol": mapping["underlying"] or symbol,
        "instrument": symbol,
        "theme": mapping["theme"],
        "leverage": mapping["leverage"],
        "company_thesis_state": states["company_thesis_state"],
        "timing_state": states["timing_state"],
        "exposure_posture": states["exposure_posture"],
        "long_entry_eligible": states["long_entry_eligible"],
        "add_allowed": states["add_allowed"],
        "close": trend.get("close") if isinstance(trend, dict) else None,
        "sma20": sma.get(20),
        "sma50": sma.get(50),
        "sma200": sma.get(200),
        "sma50_slope": slope.get(50),
        "rs20_vs_qqq": _rs(rs_qqq, 20),
        "rs63_vs_qqq": _rs(rs_qqq, 63),
        "rs20_vs_smh": _rs(rs_smh, 20),
        "rsi": trend.get("rsi") if isinstance(trend, dict) else None,
        "bb_pct_b": bb.get("pct_b"),
        "donchian20": donchian.get(20, {}).get("status"),
        "donchian55": donchian.get(55, {}).get("status"),
        "valuation_status": valuation_status or "not_connected",
        "valuation_decision_grade": bool(val_gate["approved"]),
        "regime_exposure_cap_multiplier": regime_exposure_cap_multiplier,
        "market_regime": (market_exposure_cap or {}).get("regime"),
        "options_capability_status": (
            options_capability.get("status") if options_capability else "unknown"
        ),
        "timing_flags": states["timing_flags"],
        "timing_reasons": states["timing_reasons"],
        "exposure_reasons": states["exposure_reasons"],
        "readiness_blockers": blockers,
        "source": source,
        "as_of": card_as_of,
        "security_freshness": security_freshness,
        "benchmark_freshness": benchmark_freshness,
        "not_a_trade_signal": True,
    }


def build_focus_payload(
    cards: list[dict[str, Any]] | None = None,
    rotation_panel: dict[str, Any] | None = None,
    exposure_summary: dict[str, Any] | None = None,
    volatility_state: dict[str, Any] | None = None,
    health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """組出完整 focus payload envelope。flag OFF 時回 disabled envelope。"""
    generated_at = datetime.now(timezone.utc).isoformat()
    if not focus_engine_enabled():
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "enabled": False,
            "mode": focus_engine_mode(),
            "reason": "FOCUS_ENGINE_ENABLED != 1; shadow engine not displayed",
            "data": None,
        }

    cards = cards or []
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "enabled": True,
        "mode": focus_engine_mode(),
        "rollout_note": (
            "Shadow/display-only. Does not override existing Decision Engine "
            "alerts and never places an order."
        ),
        "health": health
        or {"workflow_status": "unknown", "error_codes": [], "degraded": False},
        "data": {
            "market_regime": volatility_state,
            "portfolio_exceptions": exposure_summary,
            "theme_rotation": rotation_panel,
            "focus_securities": cards,
            "counts": {
                "focus_card_count": len(cards),
                "cards_with_blockers": sum(
                    1 for card in cards if card.get("readiness_blockers")
                ),
            },
            "disclaimer": (
                "Static public focus universe (not private holdings). Decision "
                "support only. Timing state controls exposure pacing, not the "
                "thesis, and never becomes an automatic trade instruction."
            ),
        },
    }
