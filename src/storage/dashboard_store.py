"""Dashboard payload 聚合層:唯讀 data_store/ 既有 state → dashboard JSON。

原則:
- 純檔案讀取,不打任何外部 API(建置不需要 secret,可在無網路環境跑)。
- 資料不足的欄位一律 None + status 標示,不用中性值硬補。
- watchlist 分數是決策輔助(not_a_trade_signal),pillar 未齊時 total 為 None。
- heuristic v0 計分只是 Phase 1 佔位,規則變更需依 AGENTS.md 紀律記錄。
"""

import csv
from datetime import datetime, timezone

from loguru import logger

from src.config.settings import TIMEZONE_USER
from src.config.universe import TIER_A_CORE, TIER_B_SATELLITE, get_tier
from src.models.signal_schema import (
    SCHEMA_VERSION, SCORE_WEIGHTS, action_band_for,
)
from src.storage.state_manager import DATA_STORE_DIR, read_json

WATCHLIST_SYMBOLS = list(dict.fromkeys(TIER_A_CORE + TIER_B_SATELLITE))

DISCLAIMER = (
    "決策輔助,不是自動下單訊號;最終交易決策由 Kevin 做出。"
    "Repo 是 single source of truth。"
)

# 策略 v5:LEAPS 到期剩 6-9 個月開始評估 roll → 以 9 個月(270 天)觸發警示
ROLL_WARNING_DTE_DAYS = 270


def _envelope(data, source_files: list[str]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(TIMEZONE_USER).isoformat(),
        "source_files": source_files,
        "data": data,
    }


# ============================================
# 1. Regime Overview
# ============================================

def build_regime_payload() -> dict:
    macro = read_json("layer_macro_regime_state.json", default={})
    layer0 = read_json("layer0_history.json", default={})

    submodules = {}
    for name, sub in (layer0.get("submodules") or {}).items():
        if isinstance(sub, dict):
            submodules[name] = {
                "regime": sub.get("regime"),
                "modifier": sub.get("modifier"),
                "fetched_at": sub.get("fetched_at"),
            }

    data = {
        "regime": macro.get("regime"),
        "modifier": macro.get("modifier"),
        "indicators": macro.get("indicators") or {},
        "risk_on_count": macro.get("risk_on_count"),
        "risk_off_count": macro.get("risk_off_count"),
        "layer0_scan_time": layer0.get("scan_time"),
        "submodules": submodules,
        "taiwan_geopolitical": {
            "level": None,  # 1-10 分級,strategy v5 §9;Phase 2 接資料源前不得亂填
            "status": "not_implemented_phase_1",
        },
    }
    return _envelope(
        data, ["layer_macro_regime_state.json", "layer0_history.json"],
    )


# ============================================
# 2. Watchlist Score Table
# ============================================

def _pillar(score, status: str, max_score: int) -> dict:
    return {"score": score, "max": max_score, "status": status}


def _score_fundamental(f: dict | None) -> dict:
    """heuristic v0:營收/獲利成長 + 毛利率 → 0-35。佔位實作,非最終模型。"""
    m = SCORE_WEIGHTS["fundamental_catalyst"]
    if not f:
        return _pillar(None, "no_data", m)
    score = 14.0  # 有基本面資料的中性起點
    rev = f.get("rev_growth_yoy")
    if isinstance(rev, (int, float)):
        score += 10 if rev >= 0.30 else 5 if rev >= 0.10 else 0 if rev >= 0 else -6
    eps = f.get("earnings_growth_yoy")
    if isinstance(eps, (int, float)):
        score += 6 if eps >= 0.50 else 3 if eps >= 0.10 else 0 if eps >= 0 else -4
    gm = f.get("gross_margin")
    if isinstance(gm, (int, float)):
        score += 5 if gm >= 0.50 else 2 if gm >= 0.30 else 0
    return _pillar(round(min(max(score, 0), m), 1), "heuristic_v0", m)


def _score_valuation(f: dict | None) -> dict:
    """heuristic v0:PEG / forward P/E → 0-10。佔位實作。"""
    m = SCORE_WEIGHTS["valuation_expectation"]
    if not f:
        return _pillar(None, "no_data", m)
    peg = f.get("peg")
    if isinstance(peg, (int, float)) and peg > 0:
        score = 9 if peg < 1.0 else 7 if peg < 1.5 else 5 if peg < 2.5 else 2
        return _pillar(score, "heuristic_v0", m)
    pe_f = f.get("pe_forward")
    if isinstance(pe_f, (int, float)) and pe_f > 0:
        score = 8 if pe_f < 15 else 6 if pe_f < 25 else 4 if pe_f < 40 else 2
        return _pillar(score, "heuristic_v0_pe_only", m)
    return _pillar(None, "no_data", m)


def _score_risk_macro(regime: str | None) -> dict:
    """heuristic v0:Layer 0 regime → 0-15(台海分級接入前只反映宏觀面)。"""
    m = SCORE_WEIGHTS["risk_macro_geopolitical"]
    mapping = {"risk_on": 12, "neutral": 8, "risk_off": 3}
    if regime in mapping:
        return _pillar(mapping[regime], "heuristic_v0_macro_only", m)
    return _pillar(None, "no_data", m)


def build_watchlist_scores() -> dict:
    fundamentals = (
        read_json("layer_fundamentals_dashboard_state.json", default={})
        .get("dashboard") or {}
    )
    macro = read_json("layer_macro_regime_state.json", default={})
    regime = macro.get("regime")

    from src.data.options_provider import YFinanceOptionsProvider
    provider = YFinanceOptionsProvider()

    rows = []
    for sym in WATCHLIST_SYMBOLS:
        f = fundamentals.get(sym)
        iv = provider.get_iv_metrics(sym)

        pillars = {
            "fundamental_catalyst": _score_fundamental(f),
            # 需要價格歷史(相對 QQQ/SMH/SOXX 3M/6M/12M 強度),Phase 1.1 接入
            "trend_momentum": _pillar(
                None, "planned_phase_1_1", SCORE_WEIGHTS["trend_momentum"]),
            # IVR/IVP 先呈現;skew/OI/UOA 齊備前不計分,避免半套資料誤導
            "options_flow": _pillar(
                None,
                "display_only_phase_1" if iv.get("ivr") is not None
                else "insufficient_iv_history",
                SCORE_WEIGHTS["options_flow"]),
            "valuation_expectation": _score_valuation(f),
            "risk_macro_geopolitical": _score_risk_macro(regime),
        }

        scored = [p for p in pillars.values() if p["score"] is not None]
        coverage = round(sum(p["max"] for p in scored) / 100, 2)
        total = (
            round(sum(p["score"] for p in scored), 1)
            if len(scored) == len(SCORE_WEIGHTS) else None
        )

        rows.append({
            "symbol": sym,
            "tier": get_tier(sym),
            "pillars": pillars,
            "total_score": total,
            "coverage": coverage,
            "action_band": action_band_for(total),
            "not_a_trade_signal": True,
            "notes": [n for n in [
                f"ivr={iv.get('ivr')} ivp={iv.get('ivp')} samples={iv.get('samples')}",
            ] if n],
        })

    payload = _envelope(
        {"disclaimer": DISCLAIMER, "regime": regime, "rows": rows},
        ["layer_fundamentals_dashboard_state.json",
         "layer_macro_regime_state.json", "iv_history.json"],
    )
    return payload


# ============================================
# 3. Options / Flow
# ============================================

def build_options_flow() -> dict:
    from src.data.options_provider import YFinanceOptionsProvider
    provider = YFinanceOptionsProvider()

    rows = []
    for sym in WATCHLIST_SYMBOLS:
        iv = provider.get_iv_metrics(sym)
        rows.append({
            "symbol": sym,
            "ivr": iv.get("ivr"),
            "ivp": iv.get("ivp"),
            "current_iv": iv.get("current_iv"),
            "samples": int(iv.get("samples", 0) or 0),
            "put_skew": None,
            "oi_concentration": None,
            "unusual_activity": None,
            "status": ("ok" if iv.get("ivr") is not None
                       else "insufficient_iv_history"),
        })

    data = {
        "rows": rows,
        "market": {
            "put_call": read_json("layer_put_call_state.json", default={}),
            "vix_structure": read_json("layer_vix_structure_state.json", default={}),
        },
        "paid_data_note": (
            "put_skew / oi_concentration / unusual_activity 需付費 options 資料,"
            "見 docs/data_api_evaluation.md(ORATS 優先候選)"
        ),
    }
    return _envelope(
        data,
        ["iv_history.json", "layer_put_call_state.json",
         "layer_vix_structure_state.json"],
    )


# ============================================
# 4. LEAPS Exposure
# ============================================

def build_leaps_exposure() -> dict:
    pos = read_json("positions.json", default={"stocks": [], "options": []})
    today = datetime.now(timezone.utc).date()

    rows = []
    for opt in (pos.get("options") or []):
        if not isinstance(opt, dict) or opt.get("_example"):
            continue
        try:
            expiry = datetime.strptime(opt["expiry"], "%Y-%m-%d").date()
            dte = (expiry - today).days
            rows.append({
                "id": opt.get("id"),
                "symbol": opt["symbol"],
                "type": opt.get("type", "long_call"),
                "strike": float(opt["strike"]),
                "expiry": opt["expiry"],
                "dte": dte,
                "contracts": int(opt.get("contracts", 0) or 0),
                "cost_per_contract": float(opt.get("cost_per_contract", 0) or 0),
                "roll_warning": dte < ROLL_WARNING_DTE_DAYS,
                "delta": None,
                "theta": None,
                "vega": None,
                "equivalent_exposure": None,  # contracts × 100 × delta × 股價
                "status": "requires_live_pricing",
            })
        except Exception as e:
            logger.error(f"leaps exposure row failed ({opt.get('id')}): {e}")

    # cost_per_contract 是每股 premium → 名目成本 = premium × 100 × 口數
    total_cost = round(
        sum(r["cost_per_contract"] * 100 * r["contracts"] for r in rows), 2)
    data = {
        "positions": rows,
        "totals": {
            "position_count": len(rows),
            "total_contracts": sum(r["contracts"] for r in rows),
            "total_premium_at_cost": total_cost,
            "total_delta_exposure": None,
            "status": "greeks_require_live_pricing_phase_1_1",
        },
        "roll_warning_dte_days": ROLL_WARNING_DTE_DAYS,
    }
    return _envelope(data, ["positions.json"])


# ============================================
# 5. Event Monitor
# ============================================

def build_events(max_alerts: int = 100) -> dict:
    alerts = []
    log_path = DATA_STORE_DIR / "alerts_log.csv"
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                reader = list(csv.DictReader(fh))
            for r in reader[-max_alerts:]:
                priority = r.get("priority") or None
                alerts.append({
                    "timestamp": r.get("timestamp") or "",
                    "source": r.get("signal_type") or "unknown",
                    "category": "signal",
                    "symbol": r.get("symbol") or None,
                    "priority": priority,
                    "title": (r.get("message_preview") or "")[:200],
                    # P0/P1 推 Telegram;P2/P3 只進 dashboard / digest
                    "routed_to": ("telegram" if priority in ("P0", "P1")
                                  else "dashboard_only"),
                })
        except Exception as e:
            logger.error(f"read alerts_log.csv failed: {e}")

    earnings = read_json("earnings_calendar.json", default={})
    upcoming = sorted(
        (
            {"symbol": v.get("symbol", k), "earnings_date": v.get("earnings_date")}
            for k, v in earnings.items()
            if isinstance(v, dict) and v.get("earnings_date")
        ),
        key=lambda x: x["earnings_date"],
    )

    data = {"alerts": alerts, "earnings_calendar": upcoming}
    return _envelope(data, ["alerts_log.csv", "earnings_calendar.json"])


# ============================================
# 6. Decision Log / Review Loop
# ============================================

DECISION_LOG_TEMPLATE = {
    "date": "YYYY-MM-DD",
    "symbol": "MU",
    "action": "add | trim | exit | hedge | no_trade",
    "thesis": "進場/調整理由",
    "invalidation": "失效條件",
    "result": None,
    "followed_rules": None,
    "review_notes": None,
}


def build_decision_log() -> dict:
    entries = read_json("decision_log.json", default=[])
    if not isinstance(entries, list):
        logger.error("decision_log.json is not a list; treating as empty")
        entries = []
    data = {
        "entries": entries,
        "template": DECISION_LOG_TEMPLATE,
        "note": "由 Kevin 手動維護 data_store/decision_log.json;dashboard 原樣呈現",
    }
    return _envelope(data, ["decision_log.json"])
