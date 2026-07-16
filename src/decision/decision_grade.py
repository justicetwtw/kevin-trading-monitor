"""Final fail-closed gates for production decision readiness.

The base ranker validates scenario mathematics. This layer additionally requires
Kevin-approved assumptions, fresh evidence, a future proof point and fully healthy
market context before a row can remain ``review_ready``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.decision.opportunity_ranker import (
    READINESS_ORDER,
    build_decision_payload as build_base_payload,
)

APPROVED_VALUES = {"approved", "approved_by_kevin"}
MAX_EVIDENCE_MARKET_GAP_DAYS = 45


def _date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _candidate_map(allocation_doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("symbol")): item
        for item in (allocation_doc.get("candidates") or [])
        if isinstance(item, dict) and item.get("symbol") and not item.get("_example")
    }


def _quality_gaps(
    row: dict[str, Any],
    candidate: dict[str, Any],
) -> list[str]:
    gaps: list[str] = []
    inputs = (
        candidate.get("decision_inputs")
        if isinstance(candidate.get("decision_inputs"), dict)
        else {}
    )
    scenario = row.get("scenario") if isinstance(row.get("scenario"), dict) else None
    if scenario is not None:
        approval = str(scenario.get("approval_status") or "")
        if approval not in APPROVED_VALUES:
            gaps.append("scenario_approval_required")

    threshold_origin = str(
        inputs.get("threshold_origin")
        or row.get("threshold_origin")
        or ""
    )
    if threshold_origin not in APPROVED_VALUES:
        gaps.append("threshold_origin_unapproved")

    market = row.get("market_context") or {}
    market_date = _date(market.get("as_of"))
    if market.get("status") == "partial":
        gaps.append("market_context_partial")

    evidence_date = _date(row.get("evidence_as_of"))
    if market_date and evidence_date:
        if evidence_date > market_date:
            gaps.append("evidence_after_market_context")
        elif (market_date - evidence_date).days > MAX_EVIDENCE_MARKET_GAP_DAYS:
            gaps.append("evidence_stale_vs_market")

    catalyst = row.get("next_catalyst") or {}
    catalyst_date = _date(catalyst.get("date"))
    if market_date and catalyst_date and catalyst_date <= market_date:
        gaps.append("catalyst_not_future")
    return gaps


def apply_quality_gates(
    payload: dict[str, Any],
    allocation_doc: dict[str, Any],
) -> dict[str, Any]:
    """Downgrade optimistic rows without inventing replacement scores."""
    candidates = _candidate_map(allocation_doc)
    rows = payload.get("rows") or []
    readiness_counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        gaps = _quality_gaps(
            row,
            candidates.get(str(row.get("symbol")), {}),
        )
        row["missing_inputs"] = sorted(
            set(row.get("missing_inputs") or []) | set(gaps)
        )
        if gaps and row.get("security_readiness") == "review_ready":
            row["security_readiness"] = "screen_grade"
            row["decision_posture"] = "wait_for_proof"
            row["decision_reason"] = (
                "scenario math is available, but approval/freshness/"
                "future-proof-point gates are incomplete"
            )
        readiness = str(row.get("security_readiness") or "unknown")
        readiness_counts[readiness] = readiness_counts.get(readiness, 0) + 1

    rows.sort(
        key=lambda row: (
            READINESS_ORDER.get(str(row.get("security_readiness")), 9),
            -float((row.get("scenario") or {}).get("expected_return_pct"))
            if isinstance(
                (row.get("scenario") or {}).get("expected_return_pct"),
                (int, float),
            )
            else float("inf"),
            row.get("manual_rank")
            if isinstance(row.get("manual_rank"), int)
            else 9999,
            row.get("symbol") or "",
        )
    )
    payload["rows"] = rows
    payload["readiness_counts"] = readiness_counts
    payload.setdefault("model_contract", {})[
        "approved_fresh_inputs_required_for_review_ready"
    ] = True
    payload["quality_gate_contract"] = {
        "approved_values": sorted(APPROVED_VALUES),
        "max_evidence_market_gap_days": MAX_EVIDENCE_MARKET_GAP_DAYS,
        "partial_market_context_is_screen_only": True,
        "future_catalyst_required": True,
        "threshold_origin": "repo_default_pending_kevin_confirmation",
    }
    return payload


def build_decision_grade_payload(**kwargs: Any) -> dict[str, Any]:
    allocation_doc = kwargs.get("allocation_doc")
    if not isinstance(allocation_doc, dict):
        allocation_doc = {}
    payload = build_base_payload(**kwargs)
    return apply_quality_gates(payload, allocation_doc)
