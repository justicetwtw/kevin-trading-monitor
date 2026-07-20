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


def test_rotation_row_reports_leadership_fields_and_not_produced():
    members = {sym: _frame(i + 1) for i, sym in enumerate(THEME_CONSTITUENTS["ai_compute"])}
    benchmarks = {"QQQ": _frame(3), "SMH": _frame(4)}
    row = theme_rotation_row("ai_compute", members, benchmarks)
    assert row["status"] == "ok"
    assert "rs_acceleration" in row
    assert "breakout_20d_share" in row
    assert "theme_percentile_rank" in row["not_produced"]


def test_panel_marks_price_return_proxy():
    members = {sym: _frame(i + 1) for i, sym in enumerate(THEME_CONSTITUENTS["ai_compute"])}
    benchmarks = {"QQQ": _frame(3), "SMH": _frame(4)}
    panel = build_rotation_panel(members, benchmarks)
    assert panel["metric_kind"] == "price_return_proxy"
    assert "fund flow" in panel["disclaimer"].lower()
