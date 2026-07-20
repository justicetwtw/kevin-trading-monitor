"""Focus Trading Engine shadow runner(docs/focus_trading_engine_v1.md §13 rollout)。

Shadow / display-only:
  - 只有 FOCUS_ENGINE_ENABLED=1 才實際計算;否則寫 disabled envelope 後結束。
  - 抓 delayed 公開價格 → 算 trend / RS / rotation / timing / exposure。
  - 私有部位曝險只在 process memory 聚合,寫入 public state 前一律 redact 成 aggregate。
  - 寫出的 focus_engine_state.json 保證不含 symbol / strike / contract / cost / account value。
  - 不送 P0/P1 trade-style alert(尚未通過回測與 Kevin 核准);不覆蓋既有 alerts。

輸出:data_store/focus_engine_state.json(public-safe)。
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from src.focus.config import focus_engine_enabled, focus_engine_mode
from src.focus.exposure import build_private_exposure, public_exposure_summary
from src.focus.payload import build_focus_card, build_focus_payload
from src.focus.providers import (
    PublicVolatilityIndexProvider,
    YFinanceFocusOptionsProvider,
)
from src.focus.rotation import build_rotation_panel
from src.focus.trend import compute_trend_frame
from src.focus.universe import (
    BENCHMARK_BROAD,
    BENCHMARK_SEMI,
    THEME_CONSTITUENTS,
    map_instrument,
    static_focus_symbols,
)

OUTPUT_FILE = "focus_engine_state.json"

# Public-safe keys allowed in the persisted state. Anything outside this set on
# a focus card is a privacy regression and must not be written.
_ALLOWED_CARD_KEYS = frozenset(
    {
        "symbol", "instrument", "theme", "leverage",
        "company_thesis_state", "timing_state", "exposure_posture",
        "long_entry_eligible", "add_allowed",
        "close", "sma20", "sma50", "sma200", "sma50_slope",
        "rs20_vs_qqq", "rs63_vs_qqq", "rs20_vs_smh",
        "rsi", "bb_pct_b", "donchian20", "donchian55",
        "valuation_status", "options_capability_status",
        "timing_flags", "timing_reasons", "exposure_reasons",
        "readiness_blockers", "source", "as_of", "not_a_trade_signal",
    }
)


def _theme_member_symbols() -> list[str]:
    seen: list[str] = []
    for names in THEME_CONSTITUENTS.values():
        for sym in names:
            if sym not in seen:
                seen.append(sym)
    return seen


def _load_frames(symbols: list[str], fetch) -> tuple[dict[str, Any], list[str]]:
    frames: dict[str, Any] = {}
    unavailable: list[str] = []
    for sym in symbols:
        try:
            frame = fetch(sym, period="1y", interval="1d")
        except Exception as exc:
            logger.warning(f"focus shadow: price fetch failed for {sym}: {type(exc).__name__}")
            frame = None
        if frame is None or getattr(frame, "empty", True):
            unavailable.append(sym)
        frames[sym] = frame
    return frames, unavailable


def build_shadow_state(
    holdings: list[str] | None = None,
    positions: dict[str, Any] | None = None,
    positions_status: str = "unknown",
    fetch=None,
    reference_date=None,
) -> dict[str, Any]:
    """Build the public-safe focus engine state (dependency-injectable for tests).

    P0 privacy: public focus cards come ONLY from ``static_focus_symbols()``.
    ``holdings`` never adds a public symbol — it may only influence private
    ordering/aggregate exposure (which is redacted to bands/counts before output).
    """
    if fetch is None:
        from src.data.price_data import fetch_history as fetch
    if reference_date is None:
        reference_date = datetime.now(timezone.utc).date()

    # Public card universe is static and public — independent of private holdings.
    card_symbols = static_focus_symbols()

    benchmark_syms = [BENCHMARK_BROAD, BENCHMARK_SEMI]
    member_syms = _theme_member_symbols()
    all_syms = sorted(set(card_symbols) | set(member_syms) | set(benchmark_syms))
    frames, unavailable = _load_frames(all_syms, fetch)
    benchmark_frames = {name: frames.get(name) for name in benchmark_syms}
    benchmark_missing = [s for s in benchmark_syms if s in unavailable]

    def _theme_basket_close(theme: str | None):
        if not theme:
            return None
        from src.focus.rotation import _basket_close

        return _basket_close(frames, THEME_CONSTITUENTS.get(theme, []))

    options_provider = YFinanceFocusOptionsProvider()
    cards: list[dict[str, Any]] = []
    for symbol in card_symbols:
        mapping = map_instrument(symbol)
        trend = compute_trend_frame(
            frames.get(symbol),
            benchmark_frames=benchmark_frames,
            theme_basket_close=_theme_basket_close(mapping["theme"]),
        )
        capability = options_provider.get_capability_snapshot(symbol)
        card = build_focus_card(
            symbol,
            trend,
            thesis_state="watch",  # thesis 來源未接;honest default,不假裝 intact
            options_capability=capability,
            valuation_status="not_connected",
            reference_date=reference_date,
        )
        cards.append({k: v for k, v in card.items() if k in _ALLOWED_CARD_KEYS})

    rotation_panel = build_rotation_panel(frames, benchmark_frames)

    exposure_summary = None
    if positions is not None:
        private_exposure = build_private_exposure(positions)
        exposure_summary = public_exposure_summary(private_exposure)

    volatility_available = True
    try:
        volatility_state = PublicVolatilityIndexProvider().get_volatility_state()
        if volatility_state.get("vix") is None:
            volatility_available = False
    except Exception as exc:
        logger.warning(f"focus shadow: volatility fetch failed: {type(exc).__name__}")
        volatility_state = None
        volatility_available = False

    health = _build_health(
        total_symbols=len(all_syms),
        unavailable=unavailable,
        benchmark_missing=benchmark_missing,
        positions_status=positions_status,
        volatility_available=volatility_available,
    )

    return build_focus_payload(
        cards=cards,
        rotation_panel=rotation_panel,
        exposure_summary=exposure_summary,
        volatility_state=volatility_state,
        health=health,
    )


def _build_health(
    total_symbols: int,
    unavailable: list[str],
    benchmark_missing: list[str],
    positions_status: str,
    volatility_available: bool,
) -> dict[str, Any]:
    """Compute a public-safe workflow health status (generic codes, no symbols).

    A shadow run must not disguise partial/stale/provider failures as success:
    any degradation surfaces here and drives the runner's non-zero exit.
    """
    error_codes: list[str] = []
    if benchmark_missing:
        error_codes.append("benchmark_price_unavailable")
    if unavailable:
        error_codes.append("partial_price_coverage")
    if not volatility_available:
        error_codes.append("volatility_index_unavailable")
    if positions_status == "malformed":
        error_codes.append("positions_input_malformed")
    elif positions_status == "unconfigured":
        error_codes.append("positions_unconfigured")

    if benchmark_missing or positions_status == "malformed":
        workflow_status = "degraded"
    elif error_codes:
        workflow_status = "partial"
    else:
        workflow_status = "healthy"

    return {
        "workflow_status": workflow_status,
        "degraded": workflow_status in {"degraded", "partial"},
        "error_codes": error_codes,
        "unavailable_symbol_count": len(unavailable),
        "total_symbol_count": total_symbols,
        "positions_status": positions_status,
        "privacy": "generic_codes_no_identifiers",
    }


def _assert_public_safe(state: dict[str, Any]) -> None:
    """Fail closed if any focus card leaks a non-allowed key into public state."""
    data = state.get("data") or {}
    for card in data.get("focus_securities") or []:
        leaked = set(card) - _ALLOWED_CARD_KEYS
        if leaked:
            raise ValueError(f"focus card would leak non-public keys: {sorted(leaked)}")


def _positions_status() -> tuple[dict[str, Any] | None, list[str], str]:
    """Load private positions and classify input health without leaking contents.

    Returns (positions, holdings, status) where status is one of
    unconfigured / malformed / ok. Malformed present input must not be silently
    treated as an empty portfolio success.
    """
    import json
    import os

    from src.management.current_positions import (
        POSITIONS_ENV,
        _validate_positions,
        get_holdings_symbols,
        load_positions,
    )

    raw = os.getenv(POSITIONS_ENV, "").strip()
    if raw:
        try:
            _validate_positions(json.loads(raw))
        except Exception:
            # Present but malformed: surface as degraded, do not fake empty success.
            return None, [], "malformed"
    try:
        positions = load_positions()
        holdings = get_holdings_symbols()
    except Exception as exc:
        logger.warning(f"focus shadow: private positions unavailable: {type(exc).__name__}")
        return None, [], "malformed"

    from src.management.current_positions import _is_positions_empty

    if not raw and _is_positions_empty(positions):
        return positions, holdings, "unconfigured"
    return positions, holdings, "ok"


def main() -> int:
    from src.storage.state_manager import write_json

    if not focus_engine_enabled():
        logger.info("focus shadow: FOCUS_ENGINE_ENABLED != 1; writing disabled envelope")
        write_json(OUTPUT_FILE, build_focus_payload())
        return 0

    logger.info(f"focus shadow: running in {focus_engine_mode()} mode")
    positions, holdings, positions_status = _positions_status()

    state = build_shadow_state(
        holdings=holdings,
        positions=positions,
        positions_status=positions_status,
    )
    _assert_public_safe(state)
    if not write_json(OUTPUT_FILE, state):
        logger.error("focus shadow: failed to write state")
        return 1

    health = state.get("health") or {}
    data = state.get("data") or {}
    logger.info(
        "focus shadow: wrote %d cards, mode=%s, workflow_status=%s, codes=%s"
        % (
            len(data.get("focus_securities") or []),
            state.get("mode"),
            health.get("workflow_status"),
            health.get("error_codes"),
        )
    )
    # Fail closed: an enabled run that is degraded/partial must be operationally
    # visible (non-zero), not disguised as success. Paging itself is controlled by
    # alert routing, not by this exit code.
    if health.get("degraded"):
        logger.warning(
            f"focus shadow: degraded run, workflow_status={health.get('workflow_status')}"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
