"""Position exceptions must route to Telegram instead of silent P2."""

from src.alerts.alert_router import determine_priority
from src.runners import run_position_check


def test_standard_position_exception_maps_to_p1():
    level = run_position_check._position_alert_level(
        {"level": "-30"}, "leaps_pnl"
    )
    assert level == "green"
    assert determine_priority({"alert_level": level}) == "P1"


def test_severe_leaps_exception_maps_to_p1_orange():
    for trigger in ("+100", "-40"):
        level = run_position_check._position_alert_level(
            {"level": trigger}, "leaps_pnl"
        )
        assert level == "orange"
        assert determine_priority({"alert_level": level}) == "P1"


def test_short_delta_and_hedge_dte_map_to_p1():
    for kind in ("short_delta", "hedge_dte"):
        level = run_position_check._position_alert_level({}, kind)
        assert determine_priority({"alert_level": level}) == "P1"


def test_explicit_alert_level_is_preserved():
    assert (
        run_position_check._position_alert_level(
            {"alert_level": "red"}, "leaps_pnl"
        )
        == "red"
    )
