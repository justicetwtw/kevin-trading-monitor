"""Focus universe + instrument mapping tests(驗收 #5)。"""

from src.focus.universe import (
    THEME_GROUPS,
    map_instrument,
    normalize_to_underlying,
    runtime_focus_symbols,
)


def test_leveraged_single_name_maps_to_underlying_with_leverage():
    m = map_instrument("NVDL")
    assert m["mapped"] is True
    assert m["kind"] == "leveraged_single"
    assert m["underlying"] == "NVDA"
    assert m["leverage"] == 2.0
    assert m["theme"] == "ai_compute"


def test_memory_leveraged_names_map_back():
    assert map_instrument("MUU")["underlying"] == "MU"
    assert map_instrument("SNXX")["underlying"] == "SNDK"
    assert map_instrument("WDCX")["underlying"] == "WDC"


def test_basket_instrument_maps_to_theme_not_single_name():
    m = map_instrument("DRAM")
    assert m["kind"] == "basket"
    assert m["theme"] == "memory_hbm_dram"
    assert m["underlying"] is None


def test_unknown_empty_symbol_fails_closed_as_unmapped():
    m = map_instrument("")
    assert m["mapped"] is False
    assert m["note"] == "unmapped_instrument"


def test_unlisted_but_valid_symbol_is_underlying_not_unmapped():
    # A real ticker outside the focus overlay should be treated as 1:1
    # underlying with honest None theme, not silently zeroed.
    m = map_instrument("ZZZZ")
    assert m["mapped"] is True
    assert m["kind"] == "underlying"
    assert m["leverage"] == 1.0
    assert m["theme"] is None
    assert m["note"] == "outside_focus_overlay"


def test_normalize_applies_leverage_to_notional():
    out = normalize_to_underlying("NVDL", 1000.0)
    assert out["underlying"] == "NVDA"
    assert out["underlying_notional"] == 2000.0


def test_normalize_unmapped_keeps_raw_notional_not_zero():
    out = normalize_to_underlying("", 1000.0)
    assert out["mapped"] is False
    assert out["raw_notional"] == 1000.0
    assert out["underlying_notional"] is None


def test_runtime_priority_holdings_win_over_theme_leaders():
    rows = runtime_focus_symbols(holdings=["NVDA"], kevin_focus=["MU"])
    by_symbol = {row["symbol"]: row for row in rows}
    assert by_symbol["NVDA"]["priority"] == 1
    assert by_symbol["NVDA"]["source"] == "holding"
    assert by_symbol["MU"]["priority"] == 2
    assert by_symbol["MU"]["source"] == "kevin_focus"


def test_runtime_priority_holding_via_leveraged_maps_to_underlying():
    rows = runtime_focus_symbols(holdings=["NVDL"])
    by_symbol = {row["symbol"]: row for row in rows}
    # holding the 2x maps the priority-1 slot onto the underlying NVDA
    assert by_symbol["NVDA"]["priority"] == 1


def test_theme_groups_cover_required_themes():
    for theme in (
        "ai_compute",
        "memory_hbm_dram",
        "memory_nand_storage",
        "optical_interconnect",
        "semi_equipment_upstream",
        "ai_power_energy",
    ):
        assert theme in THEME_GROUPS
        assert THEME_GROUPS[theme]
