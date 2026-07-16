"""Regression tests for LEAPS per-share versus per-contract units."""

from unittest.mock import patch

from src.management import leaps_pnl_tracker


def test_calc_option_pnl_compares_per_contract_values():
    option = {
        "id": "UNIT_TEST",
        "symbol": "NVDA",
        "type": "long_call",
        "strike": 100,
        "expiry": "2027-12-17",
        "contracts": 1,
        "cost_per_contract": 4250.0,
    }

    with patch.object(leaps_pnl_tracker, "get_latest_price", return_value=150.0), \
         patch.object(leaps_pnl_tracker, "get_atm_iv", return_value=0.30), \
         patch.object(leaps_pnl_tracker, "calc_bs_price", return_value=42.50):
        result = leaps_pnl_tracker.calc_option_pnl(option)

    assert result["current_price_per_contract"] == 4250.0
    assert result["cost_per_contract"] == 4250.0
    assert result["pnl_pct"] == 0.0


def test_calc_option_pnl_positive_return_uses_same_unit():
    option = {
        "id": "UNIT_TEST",
        "symbol": "NVDA",
        "type": "long_call",
        "strike": 100,
        "expiry": "2027-12-17",
        "contracts": 1,
        "cost_per_contract": 4000.0,
    }

    with patch.object(leaps_pnl_tracker, "get_latest_price", return_value=150.0), \
         patch.object(leaps_pnl_tracker, "get_atm_iv", return_value=0.30), \
         patch.object(leaps_pnl_tracker, "calc_bs_price", return_value=60.0):
        result = leaps_pnl_tracker.calc_option_pnl(option)

    assert result["current_price_per_contract"] == 6000.0
    assert result["pnl_pct"] == 0.5
