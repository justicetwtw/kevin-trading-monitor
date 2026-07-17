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
# Option kinds whose negative delta actually protects downside. Short calls
# are deliberately excluded: they offset delta without providing a floor.
PROTECTIVE_KINDS = {"long_put"}


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
    unmapped_positions = 0
    positive_delta = 0.0
    negative_delta = 0.0
    protective_delta = 0.0
    nonprotective_negative_delta = 0.0
    invalid_expiry_count = 0
    roll_counts = {
        "dte_le_90": 0,
        "dte_le_180": 0,
        "dte_le_270": 0,
    }

    positions_missing_market_data = 0
    for row in summary.get("rows") or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "")
        kind = str(row.get("kind") or "")
        if not row.get("market_data_ok"):
            # A failed lookup is unknown exposure, not zero exposure; the
            # aggregate ratios below must degrade instead of looking healthy.
            positions_missing_market_data += 1
        delta_notional = (
            float(row.get("delta_notional", 0) or 0)
            if row.get("market_data_ok")
            else 0.0
        )
        if delta_notional >= 0:
            positive_delta += delta_notional
        else:
            negative_delta += abs(delta_notional)
            # Negative delta is not synonymous with downside protection: a
            # short call caps upside and adds negative gamma but provides no
            # floor. Only long puts and short stock count as protective.
            if kind in PROTECTIVE_KINDS or kind == "stock":
                protective_delta += abs(delta_notional)
            else:
                nonprotective_negative_delta += abs(delta_notional)
        baskets = set(basket_map.get(symbol) or set())
        explicit_theme = str(row.get("theme") or "")
        if explicit_theme and explicit_theme != "unmapped":
            baskets.add(explicit_theme)
        if not baskets:
            unmapped_symbols.add(symbol)
            unmapped_positions += 1
        for basket in baskets:
            basket_gross[basket] += abs(delta_notional)
        dte = row.get("dte")
        if isinstance(dte, int) and kind != "stock" and dte < 0:
            # dte=-1 is the unparseable-expiry sentinel; counting it as a
            # roll window would fabricate an option_roll_window flag.
            invalid_expiry_count += 1
        elif isinstance(dte, int) and kind != "stock" and dte >= 0:
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
        protective_delta / positive_delta if positive_delta > 0 else None
    )
    delta_offset = (
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
    if invalid_expiry_count:
        flags.append("option_expiry_unparseable")
    if positions_missing_market_data:
        flags.append("position_market_data_missing")
    return {
        "status": (
            "degraded_market_data"
            if positions_missing_market_data
            else "ok"
        ),
        "positions_missing_market_data": positions_missing_market_data,
        "position_count": len(positions),
        "missing_thesis_id_count": missing_thesis_ids,
        "invalid_thesis_id_count": invalid_thesis_ids,
        "unmapped_symbol_count": len(unmapped_symbols),
        "unmapped_position_count": unmapped_positions,
        "basket_exposure": basket_exposure,
        "max_basket_gross_weight": max_weight,
        "positive_delta_notional": positive_delta,
        "negative_delta_notional": negative_delta,
        "protective_negative_delta_notional": protective_delta,
        "nonprotective_negative_delta_notional": nonprotective_negative_delta,
        "hedge_coverage_ratio": hedge_coverage,
        "delta_offset_ratio": delta_offset,
        "invalid_expiry_count": invalid_expiry_count,
        "roll_window_counts": roll_counts,
        "review_flags": flags,
        "threshold_origin": "repo_default_pending_kevin_confirmation",
        "basket_review_weight": BASKET_REVIEW_WEIGHT,
        "private_detail": True,
    }


def public_decision_risk_state(value: dict[str, Any]) -> dict[str, Any]:
    status = value.get("status") if isinstance(value, dict) else None
    if status not in {"ok", "degraded_market_data"}:
        # A crashed or skipped analysis must never be neutral-filled into
        # zero-gap counts on the public dashboard.
        return {
            "status": "analysis_unavailable",
            "privacy": "aggregate_decision_risk_only",
        }
    public = {
        "status": status,
        "missing_thesis_id_count": int(
            value.get("missing_thesis_id_count", 0) or 0
        ),
        "invalid_thesis_id_count": int(
            value.get("invalid_thesis_id_count", 0) or 0
        ),
        "unmapped_position_count": int(
            value.get("unmapped_position_count", 0) or 0
        ),
        "invalid_expiry_count": int(
            value.get("invalid_expiry_count", 0) or 0
        ),
        "roll_window_counts": dict(value.get("roll_window_counts") or {}),
        "review_flags": list(value.get("review_flags") or []),
        "threshold_origin": value.get("threshold_origin"),
        "privacy": "aggregate_decision_risk_only",
    }
    if status == "ok":
        # Exposure-derived aggregates are only publishable when every
        # position had market data; partial ratios would look healthy while
        # silently omitting unknown exposure.
        public["max_basket_gross_weight"] = value.get(
            "max_basket_gross_weight"
        )
        public["hedge_coverage_ratio"] = value.get("hedge_coverage_ratio")
        public["delta_offset_ratio"] = value.get("delta_offset_ratio")
    else:
        public["positions_missing_market_data"] = int(
            value.get("positions_missing_market_data", 0) or 0
        )
    return public


def format_private_decision_risk(value: dict[str, Any]) -> str:
    lines = ["\n<b>決策風險與相關曝險（私有）</b>"]
    missing_market = int(
        value.get("positions_missing_market_data", 0) or 0
    )
    if missing_market:
        lines.append(
            f"⚠ {missing_market} 個部位缺市場資料：以下曝險/避險比率為"
            "不完整估計（未知曝險未計入），不可作為健康訊號。"
        )
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
    offset = value.get("delta_offset_ratio")
    offset_text = (
        f"{float(offset) * 100:.1f}%"
        if isinstance(offset, (int, float))
        else "—"
    )
    lines.append(
        f"Protective negative Delta（long put／short stock）/ positive Delta：{coverage_text}"
    )
    lines.append(
        f"總 Delta offset（含 short call，非下檔保護）：{offset_text}"
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
