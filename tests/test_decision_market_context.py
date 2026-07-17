import pandas as pd

from src.runners import run_decision_market_context as runner


def _frame(rows=260, end="2026-07-16"):
    index = pd.date_range(end=end, periods=rows, freq="B", tz="America/New_York")
    close = pd.Series([100 + index * 0.25 for index in range(rows)], dtype=float)
    return pd.DataFrame(
        {
            "Close": close.values,
            "High": (close + 2).values,
            "Low": (close - 2).values,
        },
        index=index,
    )


_TODAY = pd.Timestamp("2026-07-17").date()


def test_summarize_history_produces_timing_context_not_valuation():
    row = runner.summarize_history("MU", _frame(), today=_TODAY)
    assert row["status"] == "healthy"
    assert row["current_price"] > 0
    assert row["return_1m"] is not None
    assert row["return_3m"] is not None
    assert row["return_6m"] is not None
    assert row["realized_vol_20d"] is not None
    assert "not valuation" in row["limitations"][1]


def test_empty_history_is_explicitly_unavailable():
    row = runner.summarize_history("MU", pd.DataFrame())
    assert row["status"] == "unavailable"
    assert row["error_code"] == "empty_price_history"


def test_complete_but_stale_history_is_unavailable_not_healthy():
    """A frozen-but-complete series must fail the wall-clock bound (R2)."""
    stale = runner.summarize_history("MU", _frame(end="2026-06-01"), today=_TODAY)
    assert stale["status"] == "unavailable"
    assert stale["error_code"] == "stale_price_history"
    assert "return_1m" not in stale
    boundary = runner.summarize_history(
        "MU", _frame(end="2026-07-13"), today=_TODAY
    )
    assert boundary["status"] == "healthy"


def test_empty_candidate_list_is_no_candidates_and_nonzero(monkeypatch):
    """An emptied allocation doc must never produce a healthy run (R4)."""
    monkeypatch.setattr(runner, "read_json", lambda *args, **kwargs: {})
    writes = {}
    monkeypatch.setattr(
        runner,
        "write_json",
        lambda filename, value: writes.setdefault(filename, value) is value,
    )
    assert runner.main() == 1
    state = writes[runner.OUTPUT_FILE]
    assert state["status"] == "no_candidates"
    assert state["rows"] == []


def test_main_writes_safe_state_then_returns_nonzero_on_missing_symbol(monkeypatch):
    monkeypatch.setattr(
        runner,
        "read_json",
        lambda *args, **kwargs: {"candidates": [{"symbol": "MU"}, {"symbol": "NVDA"}]},
    )
    fresh = _frame(end=pd.Timestamp.now(tz="America/New_York").normalize())
    monkeypatch.setattr(
        runner,
        "fetch_history",
        lambda symbol, **kwargs: fresh if symbol == "MU" else pd.DataFrame(),
    )
    writes = {}
    monkeypatch.setattr(
        runner,
        "write_json",
        lambda filename, value: writes.setdefault(filename, value) is value,
    )
    assert runner.main() == 1
    state = writes[runner.OUTPUT_FILE]
    assert state["status"] == "degraded"
    assert state["safe_error_symbols"] == ["NVDA"]
