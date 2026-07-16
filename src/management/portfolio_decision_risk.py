"""Private portfolio decision-risk overlay.

Detailed basket names and exposures stay in the private Telegram message. Public
state receives aggregate counts/ratios only so holdings cannot be reconstructed.
"""

from __future__ import annotations

from collections import defaultdict
from html import escape
from typing import Any

from src.storage.state_manager import read_json

BASKET_REVIEW_WEIGHT = 0.50


def _theme_context() -> tuple[dict[str, set[str]], set[str]]:
    """Return symbol basket mapping and approved theme/subtheme thesis IDs."""
    document = read_json("thesis_tracker.json", default={})
    mapping: dict[str, set[str]] = defaultdict(set)
    valid_ids: set[str] = set()
    if not isinstance(document, dict):
        return mapping, valid_ids

    for theme in document.get("themes") or []:
        if not isinstance(theme, dict):
            continue
        theme_id = str(theme.get("id") or "").strip()
        if theme_id:
            valid_ids.add(theme_id)
        for subtheme in theme.get("subthemes") or []:
            if not isinstance(subtheme, dict):
                continue
            sub_id = str(subtheme.get("id") or "").strip()
            if sub_id:
                valid_ids.add(sub_id)
            for symbol in subtheme.get("symbols") or []:
                symbol_text = str(symbol).strip()
                if not symbol_text:
                    continue
                if theme_id:
                    mapping[symbol_text].add(theme_id)
                if sub_id:
                    mapping[symbol_text].add(sub_id)

    for thesis in document.get("symbols") or []:
        if not isinstance(thesis, dict):
            continue
        symbol = str(thesis.get("symbol") or "").strip()
        theme = str(thesis.get("theme") or "").strip()
        if symbol and theme:
            mapping[symbol].add(theme)
            valid_ids.add(theme)
    return mapping, valid_ids


def analyze_portfolio_decision_risk(
    summary: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    positions = list(snapshot.get("stocks") or []) + list(
        snapshot.get("options") or []
    )
    basket_map, valid_thesis_ids = _theme_context()
    thesis_ids = [
        str(item.get("thesis_id") or "").strip()
        if isinstance(item, dict)
        else ""
        for item in positions
    ]
    missing_thesis_ids = sum(1 for value in thesis_ids if not value)
    invalid_thesis_ids = sum(
        1
        for value in thesis_ids
        if value and value not in valid_thesis_ids
    )

    gross = float(summary.get("gross_delta_notional", 0) or 0)
    basket_gross: dict[str, float] = defaultdict(float)
    unmapped_symbols: set[str] = set()
    positive_delta = 0.0
    negative_delta = 0.0
    roll_counts = {
        "dte_le_90": 0,
        "dte_le_180": 0,
        "dte_le_270": 0,
    }

    for row in summary.get("rows") or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "")
        delta_notional = (
            float(row.get("delta_notional", 0) or 0)
            if row.get("market_data_ok")
            else 0.0
        )
        if delta_notional >= 0:
            positive_delta += delta_notional
        else:
            negative_delta += abs(delta_notional)
        baskets = set(basket_map.get(symbol) or set())
        explicit_theme = str(row.get("theme") or "")
        if explicit_theme and explicit_theme != "unmapped":
            baskets.add(explicit_theme)
        if not baskets:
            unmapped_symbols.add(symbol)
        for basket in baskets:
            basket_gross[basket] += abs(delta_notional)
        dte = row.get("dte")
        if isinstance(dte, int) and row.get("kind") != "stock":
            if dte <= 90:
                roll_counts["dte_le_90"] += 1
            if dte <= 180:
                roll_counts["dte_le_180"] += 1
            if dte <= 270:
                roll_counts["dte_le_270"] += 1

    basket_exposure = [
        {
            "basket": basket,
            "gross_delta_notional": value,
            "gross_weight": value / gross if gross else 0.0,
        }
        for basket, value in basket_gross.items()
    ]
    basket_exposure.sort(
        key=lambda item: item["gross_delta_notional"], reverse=True
    )
    max_weight = (
        basket_exposure[0]["gross_weight"] if basket_exposure else 0.0
    )
    hedge_coverage = (
        negative_delta / positive_delta if positive_delta > 0 else None
    )
    flags = []
    if missing_thesis_ids:
        flags.append("position_thesis_id_missing")
    if invalid_thesis_ids:
        flags.append("position_thesis_id_invalid")
    if unmapped_symbols:
        flags.append("position_correlation_basket_unmapped")
    if max_weight > BASKET_REVIEW_WEIGHT:
        flags.append("correlated_basket_weight_over_50pct")
    if roll_counts["dte_le_90"]:
        flags.append("option_roll_window_le_90d")
    return {
        "position_count": len(positions),
        "missing_thesis_id_count": missing_thesis_ids,
        "invalid_thesis_id_count": invalid_thesis_ids,
        "unmapped_symbol_count": len(unmapped_symbols),
        "basket_exposure": basket_exposure,
        "max_basket_gross_weight": max_weight,
        "positive_delta_notional": positive_delta,
        "protective_negative_delta_notional": negative_delta,
        "hedge_coverage_ratio": hedge_coverage,
        "roll_window_counts": roll_counts,
        "review_flags": flags,
        "threshold_origin": "repo_default_pending_kevin_confirmation",
        "basket_review_weight": BASKET_REVIEW_WEIGHT,
        "private_detail": True,
    }


def public_decision_risk_state(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "missing_thesis_id_count": int(
            value.get("missing_thesis_id_count", 0) or 0
        ),
        "invalid_thesis_id_count": int(
            value.get("invalid_thesis_id_count", 0) or 0
        ),
        "unmapped_symbol_count": int(
            value.get("unmapped_symbol_count", 0) or 0
        ),
        "max_basket_gross_weight": value.get(
            "max_basket_gross_weight"
        ),
        "hedge_coverage_ratio": value.get("hedge_coverage_ratio"),
        "roll_window_counts": dict(value.get("roll_window_counts") or {}),
        "review_flags": list(value.get("review_flags") or []),
        "threshold_origin": value.get("threshold_origin"),
        "privacy": "aggregate_decision_risk_only",
    }


def format_private_decision_risk(value: dict[str, Any]) -> str:
    lines = ["\n<b>決策風險與相關曝險（私有）</b>"]
    missing = int(value.get("missing_thesis_id_count", 0) or 0)
    invalid = int(value.get("invalid_thesis_id_count", 0) or 0)
    unmapped = int(value.get("unmapped_symbol_count", 0) or 0)
    lines.append(
        f"Thesis ID 缺口：{missing} | 無效：{invalid} | "
        f"未映射 basket：{unmapped}"
    )
    coverage = value.get("hedge_coverage_ratio")
    coverage_text = (
        f"{float(coverage) * 100:.1f}%"
        if isinstance(coverage, (int, float))
        else "—"
    )
    lines.append(
        f"Protective negative Delta / positive Delta：{coverage_text}"
    )
    baskets = value.get("basket_exposure") or []
    if baskets:
        lines.append("<b>相關 basket gross Delta</b>")
        for item in baskets[:8]:
            lines.append(
                f"• {escape(str(item.get('basket')))}："
                f"${float(item.get('gross_delta_notional', 0) or 0):,.0f} "
                f"({float(item.get('gross_weight', 0) or 0) * 100:.0f}%)"
            )
    rolls = value.get("roll_window_counts") or {}
    lines.append(
        "Roll windows："
        f"≤90d {int(rolls.get('dte_le_90', 0) or 0)} / "
        f"≤180d {int(rolls.get('dte_le_180', 0) or 0)} / "
        f"≤270d {int(rolls.get('dte_le_270', 0) or 0)}"
    )
    flags = value.get("review_flags") or []
    if flags:
        lines.append(
            "⚠ Review flags："
            + escape("、".join(str(item) for item in flags))
        )
    lines.append(
        "<i>50% basket threshold 是待 Kevin 確認的 review gate，"
        "不是自動減碼指令。</i>"
    )
    return "\n".join(lines)
