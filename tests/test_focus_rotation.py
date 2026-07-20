"""Theme rotation regression: constituents-only baskets, no ETF double-count."""

import numpy as np
import pandas as pd

from src.focus.rotation import build_rotation_panel, theme_rotation_row
from src.focus.universe import THEME_CONSTITUENTS


def _frame(seed):
    n = 200
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    rng = np.linspace(10, 10 + seed, n)
    return pd.DataFrame(
        {"Close": rng, "High": rng * 1.01, "Low": rng * 0.99, "Volume": [1e6] * n},
        index=idx,
    )


def test_constituents_exclude_etf_proxies():
    # ai_compute rotation basket must be pure single names — no SMH/SOXX.
    for etf in ("SMH", "SOXX", "QQQ", "SPY"):
        assert etf not in THEME_CONSTITUENTS["ai_compute"]


def test_rotation_row_uses_constituents_not_proxy():
    # Build frames for constituents + benchmark. If the basket wrongly included
    # SMH, adding an SMH frame would change the basket; it must not.
    members = {sym: _frame(i + 1) for i, sym in enumerate(THEME_CONSTITUENTS["ai_compute"])}
    benchmarks = {"QQQ": _frame(3), "SMH": _frame(4)}

    row_without_smh_in_members = theme_rotation_row("ai_compute", members, benchmarks)

    polluted = dict(members)
    polluted["SMH"] = _frame(99)  # would only matter if basket pulled SMH in
    row_with_smh_available = theme_rotation_row("ai_compute", polluted, benchmarks)

    assert row_without_smh_in_members["return_20d"] == row_with_smh_available["return_20d"]


def test_rotation_row_reports_leadership_fields():
    members = {sym: _frame(i + 1) for i, sym in enumerate(THEME_CONSTITUENTS["ai_compute"])}
    benchmarks = {"QQQ": _frame(3), "SMH": _frame(4)}
    row = theme_rotation_row("ai_compute", members, benchmarks)
    assert row["status"] == "ok"
    assert "rs_acceleration" in row
    assert row["leadership_direction"] in {"accelerating", "deteriorating", "flat", "unknown"}
    assert "breakout_20d_share" in row
    assert "breakout_55d_share" in row


def test_panel_produces_theme_percentile_and_rank():
    # theme_percentile_rank / theme_rank are now produced across themes.
    members = {}
    for theme, syms in THEME_CONSTITUENTS.items():
        for i, s in enumerate(syms):
            members[s] = _frame(i + 1)
    benchmarks = {"QQQ": _frame(3), "SMH": _frame(4)}
    panel = build_rotation_panel(members, benchmarks)
    ranked = [r for r in panel["rows"] if r.get("theme_rank") is not None]
    assert ranked, "at least one theme should be ranked"
    for r in ranked:
        assert 0.0 <= r["theme_percentile_rank"] <= 1.0
        assert 1 <= r["theme_rank"] <= r["theme_count_ranked"]


def test_panel_marks_price_return_proxy():
    members = {sym: _frame(i + 1) for i, sym in enumerate(THEME_CONSTITUENTS["ai_compute"])}
    benchmarks = {"QQQ": _frame(3), "SMH": _frame(4)}
    panel = build_rotation_panel(members, benchmarks)
    assert panel["metric_kind"] == "price_return_proxy"
    assert "fund flow" in panel["disclaimer"].lower()


def _dated(n, start_date, level):
    idx = pd.date_range(start_date, periods=n, freq="B")
    c = np.linspace(level, level + 5, n)
    return pd.DataFrame({"Close": c, "High": c * 1.01, "Low": c * 0.99, "Volume": [1e6] * n}, index=idx)


def test_rotation_row_carries_as_of_and_coverage():
    from src.focus.universe import THEME_CONSTITUENTS
    syms = THEME_CONSTITUENTS["ai_compute"]
    members = {s: _dated(300, "2024-06-03", i + 10) for i, s in enumerate(syms)}
    benchmarks = {"QQQ": _dated(300, "2024-06-03", 20), "SMH": _dated(300, "2024-06-03", 30)}
    row = theme_rotation_row("ai_compute", members, benchmarks)
    assert row["status"] == "ok"
    assert row["as_of"] is not None
    assert row["member_coverage"] == 1.0
    assert row["valid_member_count"] == len(syms)


def test_rotation_refuses_rank_when_coverage_low_via_stale_members():
    from datetime import date
    from src.focus.universe import THEME_CONSTITUENTS
    syms = THEME_CONSTITUENTS["ai_compute"]
    # all members are old (2024) → stale vs a 2026 reference → coverage 0
    members = {s: _dated(300, "2024-06-03", i + 10) for i, s in enumerate(syms)}
    benchmarks = {"QQQ": _dated(300, "2024-06-03", 20), "SMH": _dated(300, "2024-06-03", 30)}
    row = theme_rotation_row("ai_compute", members, benchmarks, reference_date=date(2026, 7, 20))
    assert row["status"] in {"insufficient_coverage", "insufficient_data"}
    assert row.get("rs_vs_qqq_20") is None  # no rank/RS when coverage insufficient


def test_basket_date_aligned_with_mixed_listing_starts():
    from src.focus.rotation import _basket_close
    # one member lists later and one has a gap; basket must still align on dates
    a = _dated(300, "2024-01-01", 10)
    b = _dated(200, "2024-04-01", 12)  # later listing start
    frames = {"A": a, "B": b}
    basket = _basket_close(frames, ["A", "B"])
    assert basket is not None
    # basket starts at the common aligned date, not A's first date
    assert basket.index[0] >= b.index[0]
