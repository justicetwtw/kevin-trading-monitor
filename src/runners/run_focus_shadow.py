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
    THEME_GROUPS,
    map_instrument,
    runtime_focus_symbols,
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
    for names in THEME_GROUPS.values():
        for sym in names:
            if sym not in seen:
                seen.append(sym)
    return seen


def _load_frames(symbols: list[str], fetch) -> dict[str, Any]:
    frames: dict[str, Any] = {}
    for sym in symbols:
        try:
            frames[sym] = fetch(sym, period="1y", interval="1d")
        except Exception as exc:
            logger.warning(f"focus shadow: price fetch failed for {sym}: {type(exc).__name__}")
            frames[sym] = None
    return frames


def build_shadow_state(
    holdings: list[str] | None = None,
    positions: dict[str, Any] | None = None,
    fetch=None,
) -> dict[str, Any]:
    """Build the public-safe focus engine state (dependency-injectable for tests)."""
    if fetch is None:
        from src.data.price_data import fetch_history as fetch

    focus_rows = runtime_focus_symbols(holdings=holdings)
    focus_symbols = [row["symbol"] for row in focus_rows]

    benchmark_syms = [BENCHMARK_BROAD, BENCHMARK_SEMI]
    member_syms = _theme_member_symbols()
    all_syms = sorted(set(focus_symbols) | set(member_syms) | set(benchmark_syms))
    frames = _load_frames(all_syms, fetch)
    benchmark_frames = {name: frames.get(name) for name in benchmark_syms}

    def _theme_basket_close(theme: str | None):
        if not theme:
            return None
        from src.focus.rotation import _basket_close

        return _basket_close(frames, THEME_GROUPS.get(theme, []))

    options_provider = YFinanceFocusOptionsProvider()
    cards: list[dict[str, Any]] = []
    for row in focus_rows:
        symbol = row["symbol"]
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
        )
        cards.append({k: v for k, v in card.items() if k in _ALLOWED_CARD_KEYS})

    rotation_panel = build_rotation_panel(frames, benchmark_frames)

    exposure_summary = None
    if positions is not None:
        private_exposure = build_private_exposure(positions)
        exposure_summary = public_exposure_summary(private_exposure)

    try:
        volatility_state = PublicVolatilityIndexProvider().get_volatility_state()
    except Exception as exc:
        logger.warning(f"focus shadow: volatility fetch failed: {type(exc).__name__}")
        volatility_state = None

    return build_focus_payload(
        cards=cards,
        rotation_panel=rotation_panel,
        exposure_summary=exposure_summary,
        volatility_state=volatility_state,
    )


def _assert_public_safe(state: dict[str, Any]) -> None:
    """Fail closed if any focus card leaks a non-allowed key into public state."""
    data = state.get("data") or {}
    for card in data.get("focus_securities") or []:
        leaked = set(card) - _ALLOWED_CARD_KEYS
        if leaked:
            raise ValueError(f"focus card would leak non-public keys: {sorted(leaked)}")


def main() -> int:
    from src.storage.state_manager import write_json

    if not focus_engine_enabled():
        logger.info("focus shadow: FOCUS_ENGINE_ENABLED != 1; writing disabled envelope")
        write_json(OUTPUT_FILE, build_focus_payload())
        return 0

    logger.info(f"focus shadow: running in {focus_engine_mode()} mode")
    try:
        from src.management.current_positions import get_holdings_symbols, load_positions

        holdings = get_holdings_symbols()
        positions = load_positions()
    except Exception as exc:
        logger.warning(f"focus shadow: private positions unavailable: {type(exc).__name__}")
        holdings, positions = [], None

    state = build_shadow_state(holdings=holdings, positions=positions)
    _assert_public_safe(state)
    if not write_json(OUTPUT_FILE, state):
        logger.error("focus shadow: failed to write state")
        return 1
    data = state.get("data") or {}
    logger.info(
        "focus shadow: wrote %d focus cards, mode=%s"
        % (len(data.get("focus_securities") or []), state.get("mode"))
    )
    # Shadow-only: never escalate to a non-zero "degraded" exit that would page.
    return 0


if __name__ == "__main__":
    sys.exit(main())
