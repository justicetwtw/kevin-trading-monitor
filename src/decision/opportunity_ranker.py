"""Transparent investment-decision readiness and opportunity triage.

This module never emits an order or invents missing valuation inputs. Existing
watchlist scores remain screen evidence only. A candidate becomes review-ready
only when source/as-of, scenario probabilities and evidence posture are present.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from math import isfinite
from typing import Any

READINESS_ORDER = {
    "review_ready": 0,
    "screen_grade": 1,
    "not_decision_grade": 2,
    "re_underwrite": 3,
}

THESIS_BROKEN = {"broken", "invalidated", "retired"}
THESIS_WATCH = {"watch", "at_risk", "impaired", "changed"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def validate_scenario(scenario: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate a source-backed probability scenario and derive its skew."""
    errors: list[str] = []
    if not isinstance(scenario, dict):
        return None, ["scenario_missing"]
    current = _number(scenario.get("current_price"))
    as_of = _date(scenario.get("as_of"))
    source = scenario.get("source")
    cases = scenario.get("cases")
    if current is None or current <= 0:
        errors.append("scenario_current_price_missing")
    if as_of is None:
        errors.append("scenario_as_of_missing")
    if not isinstance(source, str) or not source.strip():
        errors.append("scenario_source_missing")
    if not isinstance(cases, list) or len(cases) < 2:
        errors.append("scenario_cases_missing")
        return None, errors

    normalized: list[dict[str, Any]] = []
    probability_sum = 0.0
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"scenario_case_{index}_invalid")
            continue
        probability = _number(case.get("probability"))
        terminal = _number(case.get("price"))
        name = str(case.get("name") or f"case_{index}")
        if probability is None or probability < 0 or probability > 1:
            errors.append(f"scenario_case_{index}_probability_invalid")
            continue
        if terminal is None or terminal <= 0:
            errors.append(f"scenario_case_{index}_price_invalid")
            continue
        probability_sum += probability
        normalized.append({"name": name, "probability": probability, "price": terminal})

    if abs(probability_sum - 1.0) > 0.0001:
        errors.append("scenario_probabilities_must_sum_to_one")
    if errors or current is None or current <= 0 or as_of is None:
        return None, sorted(set(errors))

    expected_price = sum(item["probability"] * item["price"] for item in normalized)
    returns = [(item["price"] / current) - 1 for item in normalized]
    expected_return = (expected_price / current) - 1
    downside = min(returns)
    upside = max(returns)
    downside_upside = abs(downside) / upside if downside < 0 < upside else None
    return {
        "current_price": current,
        "as_of": as_of.isoformat(),
        "source": source.strip(),
        "cases": normalized,
        "expected_price": round(expected_price, 4),
        "expected_return_pct": round(expected_return, 6),
        "downside_return_pct": round(downside, 6),
        "upside_return_pct": round(upside, 6),
        "downside_upside_ratio": round(downside_upside, 4) if downside_upside is not None else None,
        "probability_origin": scenario.get("probability_origin") or "analyst_assumption_unapproved",
        "approval_status": scenario.get("approval_status") or "draft_for_kevin_confirmation",
    }, []


def _market_context_quality(context: dict[str, Any]) -> tuple[str, list[str]]:
    missing = []
    as_of = _date(context.get("as_of"))
    price = _number(context.get("current_price"))
    if price is None or price <= 0:
        missing.append("market_current_price_missing")
    if as_of is None:
        missing.append("market_as_of_missing")
    if context.get("status") not in {"healthy", "partial"}:
        missing.append("market_context_unhealthy")
    return ("usable" if not missing else "insufficient"), missing


def assess_candidate(
    candidate: dict[str, Any],
    *,
    thesis: dict[str, Any] | None,
    watchlist: dict[str, Any] | None,
    options: dict[str, Any] | None,
    market_context: dict[str, Any] | None,
    regime: str | None,
) -> dict[str, Any]:
    """Assess one candidate without converting missing data into a neutral score."""
    symbol = str(candidate.get("symbol") or "")
    thesis = thesis or {}
    watchlist = watchlist or {}
    options = options or {}
    market_context = market_context or {}
    inputs = candidate.get("decision_inputs") if isinstance(candidate.get("decision_inputs"), dict) else {}

    thesis_status = str(thesis.get("status") or "missing")
    coverage = _number(watchlist.get("coverage"))
    screen_score = _number(watchlist.get("total_score"))
    scenario, scenario_errors = validate_scenario(inputs.get("scenario"))
    market_quality, market_errors = _market_context_quality(market_context)
    missing: list[str] = []
    missing.extend(scenario_errors)
    missing.extend(market_errors)
    if not thesis:
        missing.append("symbol_thesis_missing")
    if not thesis.get("invalidation"):
        missing.append("thesis_invalidation_missing")
    if not thesis.get("next_review"):
        missing.append("thesis_next_review_missing")
    if coverage is None:
        missing.append("watchlist_coverage_missing")
    elif coverage < 0.8:
        missing.append("watchlist_coverage_below_80pct")
    if screen_score is None:
        missing.append("complete_screen_score_missing")

    evidence = inputs.get("evidence") if isinstance(inputs.get("evidence"), dict) else {}
    evidence_quality = str(evidence.get("quality") or "unrated")
    evidence_as_of = _date(evidence.get("as_of"))
    evidence_sources = evidence.get("sources") if isinstance(evidence.get("sources"), list) else []
    if evidence_quality not in {"high", "medium"}:
        missing.append("evidence_quality_not_reviewable")
    if evidence_as_of is None:
        missing.append("evidence_as_of_missing")
    if not evidence_sources:
        missing.append("evidence_sources_missing")

    catalyst = inputs.get("next_catalyst") if isinstance(inputs.get("next_catalyst"), dict) else {}
    catalyst_date = _date(catalyst.get("date"))
    if catalyst_date is None:
        missing.append("dated_catalyst_missing")
    if not catalyst.get("source"):
        missing.append("catalyst_source_missing")

    correlation_baskets = [
        str(item) for item in (inputs.get("correlation_baskets") or []) if item
    ]
    instrument_lenses = [
        str(item) for item in (inputs.get("instrument_lenses") or []) if item
    ]
    if not correlation_baskets:
        missing.append("correlation_baskets_missing")
    if not instrument_lenses:
        missing.append("instrument_lenses_missing")

    if thesis_status in THESIS_BROKEN:
        readiness = "re_underwrite"
        posture = "re_underwrite"
        reason = "company thesis is broken/invalidated; security ranking is suspended"
    elif scenario is None or market_quality != "usable":
        readiness = "not_decision_grade"
        posture = "wait_for_proof"
        reason = "current price/source/as-of and a valid probability scenario are required"
    elif any(
        item in missing
        for item in {
            "evidence_quality_not_reviewable",
            "evidence_as_of_missing",
            "evidence_sources_missing",
            "dated_catalyst_missing",
            "catalyst_source_missing",
            "complete_screen_score_missing",
            "watchlist_coverage_below_80pct",
        }
    ):
        readiness = "screen_grade"
        posture = "wait_for_proof"
        reason = "scenario math exists, but evidence/screen/catalyst coverage is incomplete"
    else:
        readiness = "review_ready"
        expected = scenario.get("expected_return_pct") if scenario else None
        ratio = scenario.get("downside_upside_ratio") if scenario else None
        if expected is not None and expected <= 0:
            posture = "deprioritized"
            reason = "probability-weighted expected return is non-positive"
        elif ratio is not None and ratio > 1.0:
            posture = "deprioritized"
            reason = "credible downside exceeds modeled upside"
        elif thesis_status in THESIS_WATCH:
            posture = "re_underwrite"
            reason = "company thesis is on watch/impaired even though security inputs are complete"
        else:
            posture = "eligible_for_capital_review"
            reason = "inputs are sufficient for Kevin to review, not an automatic trade instruction"

    return {
        "symbol": symbol,
        "manual_rank": candidate.get("manual_rank"),
        "theme": candidate.get("theme"),
        "subtheme": candidate.get("subtheme"),
        "company_thesis_status": thesis_status,
        "security_readiness": readiness,
        "decision_posture": posture,
        "decision_reason": reason,
        "screen_score": screen_score,
        "screen_coverage": coverage,
        "screen_action_band": watchlist.get("action_band"),
        "market_context": {
            "status": market_context.get("status"),
            "current_price": market_context.get("current_price"),
            "as_of": market_context.get("as_of"),
            "return_1m": market_context.get("return_1m"),
            "return_3m": market_context.get("return_3m"),
            "return_6m": market_context.get("return_6m"),
            "pct_from_52w_high": market_context.get("pct_from_52w_high"),
            "realized_vol_20d": market_context.get("realized_vol_20d"),
            "source": market_context.get("source"),
        },
        "scenario": scenario,
        "evidence_quality": evidence_quality,
        "evidence_as_of": evidence_as_of.isoformat() if evidence_as_of else None,
        "evidence_sources": evidence_sources,
        "next_catalyst": {
            "date": catalyst_date.isoformat() if catalyst_date else None,
            "label": catalyst.get("label"),
            "source": catalyst.get("source"),
        },
        "correlation_baskets": sorted(set(correlation_baskets)),
        "instrument_lenses": instrument_lenses,
        "options_status": options.get("status"),
        "ivr": options.get("ivr"),
        "ivp": options.get("ivp"),
        "regime": regime,
        "missing_inputs": sorted(set(missing)),
        "threshold_origin": inputs.get("threshold_origin") or "draft_for_kevin_confirmation",
        "not_a_trade_signal": True,
    }


def rank_opportunities(
    candidates: list[dict[str, Any]],
    *,
    theses: list[dict[str, Any]],
    watchlist_rows: list[dict[str, Any]],
    option_rows: list[dict[str, Any]],
    market_rows: list[dict[str, Any]],
    regime: str | None,
) -> list[dict[str, Any]]:
    thesis_by_symbol = {
        str(item.get("symbol")): item for item in theses if isinstance(item, dict)
    }
    watch_by_symbol = {
        str(item.get("symbol")): item for item in watchlist_rows if isinstance(item, dict)
    }
    option_by_symbol = {
        str(item.get("symbol")): item for item in option_rows if isinstance(item, dict)
    }
    market_by_symbol = {
        str(item.get("symbol")): item for item in market_rows if isinstance(item, dict)
    }
    rows = [
        assess_candidate(
            candidate,
            thesis=thesis_by_symbol.get(str(candidate.get("symbol"))),
            watchlist=watch_by_symbol.get(str(candidate.get("symbol"))),
            options=option_by_symbol.get(str(candidate.get("symbol"))),
            market_context=market_by_symbol.get(str(candidate.get("symbol"))),
            regime=regime,
        )
        for candidate in candidates
        if isinstance(candidate, dict) and not candidate.get("_example")
    ]

    def sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
        scenario = row.get("scenario") or {}
        expected = scenario.get("expected_return_pct")
        expected_sort = -float(expected) if isinstance(expected, (int, float)) else float("inf")
        manual = row.get("manual_rank") if isinstance(row.get("manual_rank"), int) else 9999
        return (
            READINESS_ORDER.get(str(row.get("security_readiness")), 9),
            expected_sort,
            manual,
            row.get("symbol") or "",
        )

    return sorted(rows, key=sort_key)


def summarize_decision_log(log: Any) -> dict[str, Any]:
    rows = [item for item in (log or []) if isinstance(item, dict)] if isinstance(log, list) else []
    resolved = [item for item in rows if item.get("outcome") is not None]
    forecasts = [
        item for item in resolved
        if _number(item.get("forecast_probability")) is not None
        and isinstance(item.get("outcome"), bool)
    ]
    brier = None
    if forecasts:
        brier = sum(
            (float(item["forecast_probability"]) - (1.0 if item["outcome"] else 0.0)) ** 2
            for item in forecasts
        ) / len(forecasts)
    return {
        "decision_count": len(rows),
        "resolved_count": len(resolved),
        "calibrated_forecast_count": len(forecasts),
        "brier_score": round(brier, 6) if brier is not None else None,
        "status": "insufficient_history" if len(forecasts) < 10 else "calibration_available",
        "append_only": True,
    }


def build_decision_payload(
    *,
    allocation_doc: dict[str, Any],
    thesis_doc: dict[str, Any],
    watchlist_payload: dict[str, Any],
    options_payload: dict[str, Any],
    market_context_doc: dict[str, Any],
    decision_log: Any,
) -> dict[str, Any]:
    regime = watchlist_payload.get("data", {}).get("regime")
    rows = rank_opportunities(
        list(allocation_doc.get("candidates") or []),
        theses=list(thesis_doc.get("symbols") or []),
        watchlist_rows=list(watchlist_payload.get("data", {}).get("rows") or []),
        option_rows=list(options_payload.get("data", {}).get("rows") or []),
        market_rows=list(market_context_doc.get("rows") or []),
        regime=regime,
    )
    readiness_counts: dict[str, int] = {}
    basket_members: dict[str, list[str]] = {}
    for row in rows:
        readiness = str(row.get("security_readiness"))
        readiness_counts[readiness] = readiness_counts.get(readiness, 0) + 1
        for basket in row.get("correlation_baskets") or []:
            basket_members.setdefault(str(basket), []).append(str(row.get("symbol")))
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "readiness_counts": readiness_counts,
        "rows": rows,
        "correlation_baskets": [
            {"basket": basket, "symbols": sorted(set(symbols)), "candidate_count": len(set(symbols))}
            for basket, symbols in sorted(basket_members.items())
        ],
        "decision_log": summarize_decision_log(decision_log),
        "model_contract": {
            "company_security_action_separated": True,
            "scenario_probabilities_sum_to_one": True,
            "missing_data_never_neutral_filled": True,
            "score_is_screen_not_trade_instruction": True,
            "automatic_orders": False,
        },
    }
