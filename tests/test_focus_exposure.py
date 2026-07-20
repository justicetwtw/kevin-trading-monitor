"""Private exposure / hedge overlay + privacy tests(驗收 #5, #7)。"""

from src.focus.exposure import build_private_exposure, public_exposure_summary


def _positions():
    return {
        "stocks": [
            {"symbol": "NVDA", "shares": 100, "last_price": 100.0},   # 10,000 long
            {"symbol": "NVDL", "shares": 100, "last_price": 50.0},    # 5,000 * 2x = 10,000 to NVDA
            {"symbol": "MU", "shares": 100, "last_price": 80.0},      # 8,000 to memory
        ],
        "options": [
            {"symbol": "NVDA", "type": "long_put", "strike": 90, "contracts": 5, "expiry": "2027-01-15"},
            {"symbol": "NVDA", "type": "short_call", "strike": 120, "contracts": 5, "expiry": "2027-01-15"},
        ],
    }


def test_leveraged_etf_maps_into_same_underlying():
    exp = build_private_exposure(_positions())
    nvda = exp["by_underlying"]["NVDA"]
    # 10k stock + 10k from NVDL 2x, long side, aggregated onto NVDA
    assert nvda["long_notional"] >= 20000.0


def test_short_call_is_not_counted_as_protection():
    exp = build_private_exposure(_positions())
    # Only the long put is a protective position; the short call is delta offset.
    assert exp["protective_position_count"] == 1
    assert "delta offset" in exp["hedge_contract"].lower()


def test_hedge_coverage_ratio_is_unavailable_without_greeks():
    # Strike notional must NOT be turned into a fake coverage ratio.
    exp = build_private_exposure(_positions())
    assert exp["hedge_coverage_ratio"] is None
    assert exp["hedge_coverage_status"] == "unavailable_no_greeks"


def test_short_stock_is_recognized_as_protective():
    positions = {
        "stocks": [
            {"symbol": "NVDA", "shares": 100, "last_price": 100.0},
            {"symbol": "NVDA", "shares": -50, "last_price": 100.0},  # short stock hedge
        ],
        "options": [],
    }
    exp = build_private_exposure(positions)
    assert exp["protective_position_count"] == 1


def test_unmapped_instrument_is_flagged_not_zeroed():
    # A non-empty but unmappable symbol (whitespace) must surface as a risk gap,
    # not be silently dropped to zero exposure.
    positions = {
        "stocks": [{"symbol": "   ", "shares": 100, "last_price": 10.0}],
        "options": [],
    }
    exp = build_private_exposure(positions)
    assert exp["unmapped_instruments"] == ["   "]
    summary = public_exposure_summary(exp)
    assert summary["unmapped_instrument_count"] == 1
    assert summary["has_unmapped_risk_gap"] is True


def test_theme_concentration_computed():
    exp = build_private_exposure(_positions())
    assert "ai_compute" in exp["by_theme"]
    assert exp["by_theme"]["ai_compute"]["concentration_of_long"] is not None


def test_public_summary_has_no_identifiers():
    exp = build_private_exposure(_positions())
    summary = public_exposure_summary(exp)
    text = str(summary)
    # No symbol, strike or cost identifier may appear anywhere in the summary.
    for identifier in ("NVDA", "NVDL", "MU", "strike", "90", "120", "10000", "45000"):
        assert identifier not in text
    # Explicit key checks: only bands and counts, no symbol/strike/cost fields
    assert set(summary) >= {
        "theme_count",
        "underlying_count",
        "max_theme_concentration_band",
        "hedge_coverage_band",
        "unmapped_instrument_count",
        "privacy",
    }
    assert "by_underlying" not in summary
    assert "by_theme" not in summary
    assert summary["privacy"] == "aggregate_only_no_identifiers"


def test_public_summary_bands_are_categorical():
    exp = build_private_exposure(_positions())
    summary = public_exposure_summary(exp)
    assert summary["max_theme_concentration_band"] in {"low", "medium", "high", "unknown"}
    assert summary["hedge_coverage_band"] in {
        "none",
        "light",
        "material",
        "no_protection",
        "has_protection_uncomputed",
    }
    # With a long put present but no Greeks, coverage is honestly uncomputed.
    assert summary["hedge_coverage_band"] == "has_protection_uncomputed"
    assert summary["hedge_coverage_status"] == "unavailable_no_greeks"
    assert summary["has_protective_position"] is True
