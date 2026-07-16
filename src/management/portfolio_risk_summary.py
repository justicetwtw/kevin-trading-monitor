"""Private portfolio risk analysis and Telegram brief formatting.

This module may process exact holdings in memory and produce a private Telegram
message. It must never write its detailed payload to repository state or logs.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from typing import Any

from loguru import logger

from src.data.greeks_calculator import calc_all_greeks, calc_bs_price
from src.data.iv_rank import get_atm_iv
from src.data.price_data import get_latest_price
from src.management.current_positions import get_account_snapshot
from src.storage.state_manager import read_json

RISK_FREE_RATE = 0.045


def _position_sign(option_type: str) -> int:
    return -1 if option_type.startswith("short_") else 1


def _option_kind(option_type: str) -> str:
    return "call" if "call" in option_type else "put"


def _theme_maps() -> tuple[dict[str, str], set[str]]:
    document = read_json("thesis_tracker.json", default={})
    if not isinstance(document, dict):
        return {}, set()
    symbol_to_theme = {
        str(item.get("symbol")): str(item.get("theme"))
        for item in (document.get("symbols") or [])
        if isinstance(item, dict) and item.get("symbol") and item.get("theme")
    }
    theme_ids = {
        str(item.get("id"))
        for item in (document.get("themes") or [])
        if isinstance(item, dict) and item.get("id")
    }
    return symbol_to_theme, theme_ids


def _resolve_theme(
    position: dict[str, Any],
    symbol_to_theme: dict[str, str],
    known_theme_ids: set[str],
) -> tuple[str, bool]:
    explicit = position.get("thesis_id")
    if isinstance(explicit, str) and explicit:
        return explicit, explicit in known_theme_ids
    inferred = symbol_to_theme.get(str(position.get("symbol")))
    if inferred:
        return inferred, False
    return "unmapped", False


def analyze_private_portfolio(
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate in-memory delta/theta/vega and concentration metrics."""
    snapshot = snapshot or get_account_snapshot()
    stocks = snapshot.get("stocks") or []
    options = snapshot.get("options") or []
    symbol_to_theme, known_theme_ids = _theme_maps()

    rows: list[dict[str, Any]] = []
    missing_market_data: list[str] = []
    explicit_thesis_links = 0

    for stock in stocks:
        symbol = str(stock.get("symbol") or "")
        shares = float(stock.get("shares", 0) or 0)
        theme, explicit_valid = _resolve_theme(
            stock, symbol_to_theme, known_theme_ids
        )
        if explicit_valid:
            explicit_thesis_links += 1
        try:
            price = get_latest_price(symbol)
        except Exception as exc:
            logger.warning(f"private stock price lookup failed for {symbol}: {exc}")
            price = None
        if price is None:
            missing_market_data.append(f"{symbol}:price")
            rows.append({
                "kind": "stock",
                "symbol": symbol,
                "theme": theme,
                "quantity": shares,
                "market_data_ok": False,
            })
            continue
        delta_shares = shares
        delta_notional = delta_shares * float(price)
        rows.append({
            "kind": "stock",
            "symbol": symbol,
            "theme": theme,
            "quantity": shares,
            "price": float(price),
            "market_value": delta_notional,
            "delta": 1.0,
            "delta_equivalent_shares": delta_shares,
            "delta_notional": delta_notional,
            "theta_per_day": 0.0,
            "vega_per_1pct": 0.0,
            "market_data_ok": True,
        })

    today = datetime.now(timezone.utc).date()
    for option in options:
        symbol = str(option.get("symbol") or "")
        option_type = str(option.get("type") or "")
        contracts = int(option.get("contracts", 1) or 1)
        sign = _position_sign(option_type)
        theme, explicit_valid = _resolve_theme(
            option, symbol_to_theme, known_theme_ids
        )
        if explicit_valid:
            explicit_thesis_links += 1
        try:
            price = get_latest_price(symbol)
            iv = get_atm_iv(symbol)
        except Exception as exc:
            logger.warning(f"private option market lookup failed for {symbol}: {exc}")
            price = None
            iv = None
        try:
            expiry = datetime.strptime(
                str(option.get("expiry")), "%Y-%m-%d"
            ).date()
            dte = (expiry - today).days
        except ValueError:
            dte = -1

        if price is None or iv is None or dte <= 0:
            missing_parts = []
            if price is None:
                missing_parts.append("price")
            if iv is None:
                missing_parts.append("iv")
            if dte <= 0:
                missing_parts.append("expiry")
            missing_market_data.append(f"{symbol}:{'+'.join(missing_parts)}")
            rows.append({
                "kind": option_type or "option",
                "symbol": symbol,
                "theme": theme,
                "contracts": contracts,
                "strike": option.get("strike"),
                "expiry": option.get("expiry"),
                "dte": dte,
                "market_data_ok": False,
            })
            continue

        underlying = float(price)
        volatility = float(iv)
        strike = float(option["strike"])
        time_years = dte / 365
        bs_kind = _option_kind(option_type)
        greeks = calc_all_greeks(
            S=underlying,
            K=strike,
            T=time_years,
            r=RISK_FREE_RATE,
            sigma=volatility,
            option_type=bs_kind,
        )
        per_share_value = calc_bs_price(
            S=underlying,
            K=strike,
            T=time_years,
            r=RISK_FREE_RATE,
            sigma=volatility,
            option_type=bs_kind,
        )
        multiplier = 100 * contracts * sign
        delta_signed = float(greeks["delta"]) * sign
        delta_shares = float(greeks["delta"]) * 100 * contracts * sign
        rows.append({
            "kind": option_type,
            "symbol": symbol,
            "theme": theme,
            "contracts": contracts,
            "strike": strike,
            "expiry": option.get("expiry"),
            "dte": dte,
            "price": underlying,
            "iv": volatility,
            "market_value": per_share_value * multiplier,
            "delta": delta_signed,
            "delta_equivalent_shares": delta_shares,
            "delta_notional": delta_shares * underlying,
            "theta_per_day": float(greeks["theta"]) * multiplier,
            "vega_per_1pct": float(greeks["vega"]) * multiplier,
            "market_data_ok": True,
        })

    valid_rows = [row for row in rows if row.get("market_data_ok")]
    net_delta_notional = sum(
        float(row.get("delta_notional", 0) or 0) for row in valid_rows
    )
    gross_delta_notional = sum(
        abs(float(row.get("delta_notional", 0) or 0)) for row in valid_rows
    )
    theta_per_day = sum(
        float(row.get("theta_per_day", 0) or 0) for row in valid_rows
    )
    vega_per_1pct = sum(
        float(row.get("vega_per_1pct", 0) or 0) for row in valid_rows
    )

    symbol_delta: dict[str, float] = defaultdict(float)
    theme_delta: dict[str, float] = defaultdict(float)
    for row in valid_rows:
        delta_notional = float(row.get("delta_notional", 0) or 0)
        symbol_delta[str(row.get("symbol"))] += delta_notional
        theme_delta[str(row.get("theme"))] += delta_notional

    symbol_exposure = []
    for symbol, delta_notional in symbol_delta.items():
        symbol_exposure.append({
            "symbol": symbol,
            "delta_notional": delta_notional,
            "gross_weight": (
                abs(delta_notional) / gross_delta_notional
                if gross_delta_notional
                else 0.0
            ),
            "delta_equivalent_shares": sum(
                float(row.get("delta_equivalent_shares", 0) or 0)
                for row in valid_rows
                if row.get("symbol") == symbol
            ),
        })
    symbol_exposure.sort(
        key=lambda item: abs(item["delta_notional"]), reverse=True
    )

    theme_exposure = []
    for theme, delta_notional in theme_delta.items():
        theme_exposure.append({
            "theme": theme,
            "delta_notional": delta_notional,
            "gross_weight": (
                abs(delta_notional) / gross_delta_notional
                if gross_delta_notional
                else 0.0
            ),
        })
    theme_exposure.sort(
        key=lambda item: abs(item["delta_notional"]), reverse=True
    )

    total_positions = len(stocks) + len(options)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "configured": total_positions > 0,
        "position_source": snapshot.get("position_source"),
        "position_count": total_positions,
        "estimated_account_value": snapshot.get("total_estimated_value"),
        "net_delta_notional": net_delta_notional,
        "gross_delta_notional": gross_delta_notional,
        "theta_per_day": theta_per_day,
        "vega_per_1pct": vega_per_1pct,
        "explicit_thesis_links": explicit_thesis_links,
        "thesis_coverage_pct": (
            explicit_thesis_links / total_positions if total_positions else None
        ),
        "symbol_exposure": symbol_exposure,
        "theme_exposure": theme_exposure,
        "rows": rows,
        "missing_market_data": sorted(set(missing_market_data)),
    }


def _money(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def format_private_portfolio_brief(summary: dict[str, Any]) -> str:
    """Format a compact HTML Telegram message; caller must mark it sensitive."""
    if not summary.get("configured"):
        return "🔒 <b>部位風險摘要</b>\n未載入有效私有部位。"

    coverage = summary.get("thesis_coverage_pct")
    coverage_text = (
        f"{coverage * 100:.0f}%" if isinstance(coverage, (int, float)) else "—"
    )
    lines = [
        "🔒 <b>部位風險摘要（私有）</b>",
        (
            f"估計帳戶：{_money(summary.get('estimated_account_value'))} | "
            f"部位：{summary.get('position_count', 0)}"
        ),
        (
            f"淨 Delta 名目：{_money(summary.get('net_delta_notional'))} | "
            f"總 Delta 名目：{_money(summary.get('gross_delta_notional'))}"
        ),
        (
            f"每日 Theta：{_money(summary.get('theta_per_day'))} | "
            f"Vega / IV 1%：{_money(summary.get('vega_per_1pct'))}"
        ),
        f"明確 thesis 連結覆蓋：{coverage_text}",
    ]

    symbols = summary.get("symbol_exposure") or []
    if symbols:
        lines.append("\n<b>主要 Delta 曝險</b>")
        for item in symbols[:6]:
            weight = float(item.get("gross_weight", 0) or 0) * 100
            lines.append(
                f"• {escape(str(item.get('symbol')))}："
                f"{_money(item.get('delta_notional'))} "
                f"({weight:.0f}%，Δ股數 {item.get('delta_equivalent_shares', 0):,.0f})"
            )

    themes = summary.get("theme_exposure") or []
    if themes:
        lines.append("\n<b>主題曝險</b>")
        for item in themes[:5]:
            weight = float(item.get("gross_weight", 0) or 0) * 100
            lines.append(
                f"• {escape(str(item.get('theme')))}："
                f"{_money(item.get('delta_notional'))} ({weight:.0f}%)"
            )

    option_rows = [
        row
        for row in (summary.get("rows") or [])
        if row.get("kind") != "stock" and row.get("market_data_ok")
    ]
    if option_rows:
        lines.append("\n<b>選擇權風險</b>")
        for row in option_rows[:8]:
            lines.append(
                f"• {escape(str(row.get('symbol')))} "
                f"{escape(str(row.get('kind')))} {row.get('strike'):g} "
                f"DTE {row.get('dte')} | Δ {row.get('delta'):+.2f} | "
                f"θ {_money(row.get('theta_per_day'))}/日"
            )

    gaps = summary.get("missing_market_data") or []
    if gaps:
        lines.append(
            "\n⚠ 資料缺口：" + escape("、".join(str(item) for item in gaps[:8]))
        )
    if coverage is not None and coverage < 1:
        lines.append("⚠ 尚有部位未明確填入 thesis_id。")

    lines.append("\n<i>僅供決策輔助；不產生自動下單。</i>")
    return "\n".join(lines)
