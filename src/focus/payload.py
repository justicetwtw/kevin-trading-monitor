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


def _as_of_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def build_focus_card(
    symbol: str,
    trend: dict[str, Any],
    thesis_state: str,
    *,
    options_capability: dict[str, Any] | None = None,
    options_pressure: dict[str, Any] | None = None,
    valuation_status: str | None = None,
    source: str = "yfinance_delayed_public_market_data",
    as_of: str | None = None,
    reference_date: date | None = None,
    benchmark_freshness: dict[str, Any] | None = None,
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
    states = evaluate_symbol(
        trend,
        thesis_state,
        options_pressure=options_pressure,
        has_leverage=has_leverage,
        data_blocked=data_blocked,
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
