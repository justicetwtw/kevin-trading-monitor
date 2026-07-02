"""Dashboard / options provider 共用 schema 定義與輕量驗證。

不引入 pydantic / jsonschema 等新依賴,用「欄位 → (允許型別, 是否必填)」
的宣告式 spec + validate_record() 做最小驗證。
schema 是 dashboard JSON 與付費 options provider 接入的合約:
provider 換掉(yfinance → ORATS / Massive / Tradier)時欄位不變。
"""

from typing import Any

NoneType = type(None)
Num = (int, float)

SCHEMA_VERSION = 1

# ============================================
# Watchlist score 權重(與 docs/strategy_v4.md §8 一致,總和必為 100)
# ============================================

SCORE_WEIGHTS = {
    "fundamental_catalyst": 35,
    "trend_momentum": 20,
    "options_flow": 20,
    "valuation_expectation": 10,
    "risk_macro_geopolitical": 15,
}

# total_score 對應行動區間(僅決策輔助,不是下單訊號)
ACTION_BANDS = [
    (80, "core_long"),        # 核心多頭,可持有/加碼,可用 LEAPS
    (65, "hold_no_chase"),    # 可持有,不追高,控制槓桿
    (50, "watch_deleverage"), # 觀察/降槓桿
    (35, "tactical_only"),    # 只做短線,不當核心
    (0, "exit_or_avoid"),     # 出場或避開
]

# ============================================
# Field specs:{field: (allowed_types, required)}
# ============================================

ENVELOPE_SPEC = {
    "schema_version": ((int,), True),
    "generated_at": ((str,), True),
    "source_files": ((list,), True),
    "data": ((dict, list), True),
}

PILLAR_SPEC = {
    "score": (Num + (NoneType,), True),
    "max": ((int,), True),
    "status": ((str,), True),
}

WATCHLIST_ROW_SPEC = {
    "symbol": ((str,), True),
    "tier": ((str, NoneType), True),
    "pillars": ((dict,), True),
    "total_score": (Num + (NoneType,), True),
    "coverage": (Num, True),          # 已有分數 pillar 的滿分佔比 0-1
    "action_band": ((str, NoneType), True),
    "not_a_trade_signal": ((bool,), True),
    "notes": ((list,), False),
}

OPTIONS_FLOW_ROW_SPEC = {
    "symbol": ((str,), True),
    "ivr": (Num + (NoneType,), True),
    "ivp": (Num + (NoneType,), True),
    "current_iv": (Num + (NoneType,), True),
    "samples": ((int,), True),
    "put_skew": (Num + (NoneType,), True),           # 需付費資料,Phase 1 = None
    "oi_concentration": ((dict, NoneType), True),    # 需付費資料,Phase 1 = None
    "unusual_activity": ((dict, NoneType), True),    # 需付費資料,Phase 1 = None
    "status": ((str,), True),
}

LEAPS_POSITION_SPEC = {
    "id": ((str, NoneType), True),
    "symbol": ((str,), True),
    "type": ((str,), True),
    "strike": (Num, True),
    "expiry": ((str,), True),
    "dte": ((int,), True),
    "contracts": ((int,), True),
    "cost_per_contract": (Num, True),
    "roll_warning": ((bool,), True),
    "delta": (Num + (NoneType,), True),
    "theta": (Num + (NoneType,), True),
    "vega": (Num + (NoneType,), True),
    "equivalent_exposure": (Num + (NoneType,), True),
    "status": ((str,), True),
}

EVENT_ROW_SPEC = {
    "timestamp": ((str,), True),
    "source": ((str,), True),
    "category": ((str,), True),
    "symbol": ((str, NoneType), True),
    "priority": ((str, NoneType), True),
    "title": ((str,), True),
    "routed_to": ((str,), True),   # telegram / dashboard_only
}

DECISION_LOG_SPEC = {
    "date": ((str,), True),
    "symbol": ((str,), True),
    "action": ((str,), True),      # add / trim / exit / hedge / no_trade
    "thesis": ((str,), True),
    "invalidation": ((str,), True),
    "result": ((str, NoneType), False),
    "followed_rules": ((bool, NoneType), False),
    "review_notes": ((str, NoneType), False),
}

# Options provider 統一輸出(免費/付費 provider 都得符合)
IV_METRICS_SPEC = {
    "symbol": ((str,), True),
    "ivr": (Num + (NoneType,), True),
    "ivp": (Num + (NoneType,), True),
    "current_iv": (Num + (NoneType,), True),
    "samples": ((int,), True),
    "source": ((str,), True),
    "as_of": ((str, NoneType), True),
}

OPTIONS_SNAPSHOT_SPEC = {
    "symbol": ((str,), True),
    "put_call_volume_ratio": (Num + (NoneType,), True),
    "put_skew": (Num + (NoneType,), True),
    "oi_concentration": ((dict, NoneType), True),
    "unusual_activity": ((dict, NoneType), True),
    "source": ((str,), True),
    "as_of": ((str, NoneType), True),
}


def validate_record(record: Any, spec: dict, where: str = "record") -> list[str]:
    """回傳錯誤訊息 list;空 list = 通過。"""
    if not isinstance(record, dict):
        return [f"{where}: expected dict, got {type(record).__name__}"]
    errors = []
    for field, (types, required) in spec.items():
        if field not in record:
            if required:
                errors.append(f"{where}: missing required field '{field}'")
            continue
        if not isinstance(record[field], types):
            errors.append(
                f"{where}.{field}: expected {[t.__name__ for t in types]}, "
                f"got {type(record[field]).__name__}"
            )
    return errors


def validate_watchlist_row(row: dict, where: str = "watchlist_row") -> list[str]:
    """WATCHLIST_ROW_SPEC + 五 pillar 完整性與滿分正確性。"""
    errors = validate_record(row, WATCHLIST_ROW_SPEC, where)
    pillars = row.get("pillars")
    if not isinstance(pillars, dict):
        return errors
    for name, weight in SCORE_WEIGHTS.items():
        if name not in pillars:
            errors.append(f"{where}.pillars: missing pillar '{name}'")
            continue
        errors.extend(validate_record(pillars[name], PILLAR_SPEC, f"{where}.pillars.{name}"))
        if pillars[name].get("max") != weight:
            errors.append(
                f"{where}.pillars.{name}: max should be {weight}, got {pillars[name].get('max')}"
            )
    extra = set(pillars) - set(SCORE_WEIGHTS)
    if extra:
        errors.append(f"{where}.pillars: unexpected pillars {sorted(extra)}")
    return errors


def action_band_for(total_score) -> str | None:
    """total_score → 行動區間;None → None。"""
    if total_score is None:
        return None
    for floor, band in ACTION_BANDS:
        if total_score >= floor:
            return band
    return "exit_or_avoid"
