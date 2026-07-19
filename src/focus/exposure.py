"""Private exposure / correlation / hedge overlay(docs/focus_trading_engine_v1.md §5 Layer E)。

輸入:private positions(src/management/current_positions.load_positions 的 schema)。
輸出:
  - build_private_exposure():完整、含 symbol 的私有明細(僅 process memory / 私有通道)。
  - public_exposure_summary():去識別 aggregate,可安全進 public state。

紅線:
  - 相同 underlying / theme 的曝險必須合併,槓桿 ETF 依倍數放大後映射回 underlying,
    不得被當成分散(§1.3, §4.3)。
  - short call 只算 Delta offset,不得算下檔保護(§3.2);hedge 只認 long put / short stock。
  - 未知 instrument 標 unmapped,計入 risk gap,不靜默歸零。
  - public summary 不得含 symbol / strike / contract / cost / account value(§5 Layer E 結尾)。
"""

from __future__ import annotations

from typing import Any

from src.focus.universe import map_instrument

#: hedge 認列:只有這些才算真正的下檔保護。
PROTECTIVE_OPTION_TYPES = {"long_put"}
#: short call 算 delta offset,不是保護。
DELTA_OFFSET_OPTION_TYPES = {"short_call"}


def _stock_notional(stock: dict[str, Any]) -> float | None:
    shares = stock.get("shares")
    price = stock.get("last_price", stock.get("avg_cost"))
    if not isinstance(shares, (int, float)) or not isinstance(price, (int, float)):
        return None
    return float(shares) * float(price)


def _option_notional(option: dict[str, Any]) -> float | None:
    """以名目(strike * 100 * contracts)近似 option 曝險大小。

    真實 Delta notional 需要即時報價與 IV;這裡不打網路,用可得欄位近似,
    並在 summary 標明是 notional proxy 而非精算 Delta。
    """
    strike = option.get("strike")
    contracts = option.get("contracts", 1)
    if not isinstance(strike, (int, float)) or not isinstance(contracts, int):
        return None
    return float(strike) * 100.0 * float(contracts)


def _signed(option_type: str, notional: float) -> float:
    """long → +曝險;short put → +(承接義務,偏多);short call → -(空頭 delta)。"""
    if option_type in {"long_call", "short_put"}:
        return notional
    if option_type in {"long_put", "short_call"}:
        return -notional
    return 0.0


def build_private_exposure(positions: dict[str, Any]) -> dict[str, Any]:
    """把私有部位聚合成 underlying-normalized、theme-level 曝險明細。"""
    stocks = [s for s in (positions.get("stocks") or []) if not s.get("_example")]
    options = [o for o in (positions.get("options") or []) if not o.get("_example")]

    by_underlying: dict[str, dict[str, Any]] = {}
    by_theme: dict[str, dict[str, Any]] = {}
    unmapped: list[str] = []
    protective_by_underlying: dict[str, float] = {}
    long_notional = 0.0

    def _bucket(key: str, store: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return store.setdefault(
            key,
            {"long_notional": 0.0, "short_notional": 0.0, "net_notional": 0.0},
        )

    def _record(symbol: str, signed_notional: float, is_protective: bool) -> None:
        nonlocal long_notional
        mapping = map_instrument(symbol)
        if not mapping["mapped"]:
            unmapped.append(symbol)
            return
        leverage = mapping["leverage"] or 1.0
        underlying = mapping["underlying"] or symbol.strip().upper()
        theme = mapping["theme"]
        norm = signed_notional * leverage

        u_bucket = _bucket(underlying, by_underlying)
        if norm >= 0:
            u_bucket["long_notional"] += norm
            long_notional += norm
        else:
            u_bucket["short_notional"] += -norm
        u_bucket["net_notional"] += norm

        if theme:
            t_bucket = _bucket(theme, by_theme)
            if norm >= 0:
                t_bucket["long_notional"] += norm
            else:
                t_bucket["short_notional"] += -norm
            t_bucket["net_notional"] += norm

        if is_protective:
            protective_by_underlying[underlying] = (
                protective_by_underlying.get(underlying, 0.0) + abs(signed_notional * leverage)
            )

    for stock in stocks:
        symbol = stock.get("symbol")
        notional = _stock_notional(stock)
        if not symbol or notional is None:
            continue
        _record(symbol, notional, is_protective=False)

    for option in options:
        symbol = option.get("symbol")
        option_type = str(option.get("type", ""))
        notional = _option_notional(option)
        if not symbol or notional is None:
            continue
        signed = _signed(option_type, notional)
        _record(
            symbol,
            signed,
            is_protective=option_type in PROTECTIVE_OPTION_TYPES,
        )

    # theme 集中度:單一 theme 的 |net| 佔總 long 的比例。
    for theme, bucket in by_theme.items():
        bucket["concentration_of_long"] = (
            round(abs(bucket["net_notional"]) / long_notional, 4)
            if long_notional > 0
            else None
        )

    total_protective = sum(protective_by_underlying.values())
    hedge_coverage_ratio = (
        round(total_protective / long_notional, 4) if long_notional > 0 else None
    )

    return {
        "by_underlying": by_underlying,
        "by_theme": by_theme,
        "unmapped_instruments": sorted(set(unmapped)),
        "long_notional": round(long_notional, 2),
        "protective_notional": round(total_protective, 2),
        "hedge_coverage_ratio": hedge_coverage_ratio,
        "hedge_contract": (
            "Only long puts / short stock count as downside protection. "
            "Short calls are delta offset, not protection."
        ),
        "notional_basis": "strike/last-price notional proxy; not live Greeks",
    }


def public_exposure_summary(private_exposure: dict[str, Any]) -> dict[str, Any]:
    """把私有明細降解成去識別 aggregate,可安全寫入 public state。

    嚴禁輸出 symbol / underlying / strike / contract / cost / account value。
    只保留:計數、是否有槓桿、是否有 hedge gap、集中度分級(low/medium/high)、
    unmapped 缺口計數。
    """
    by_theme = private_exposure.get("by_theme", {})
    by_underlying = private_exposure.get("by_underlying", {})
    unmapped = private_exposure.get("unmapped_instruments", [])
    coverage = private_exposure.get("hedge_coverage_ratio")

    concentrations = [
        bucket.get("concentration_of_long")
        for bucket in by_theme.values()
        if bucket.get("concentration_of_long") is not None
    ]
    max_conc = max(concentrations) if concentrations else None
    if max_conc is None:
        concentration_band = "unknown"
    elif max_conc >= 0.5:
        concentration_band = "high"
    elif max_conc >= 0.3:
        concentration_band = "medium"
    else:
        concentration_band = "low"

    if coverage is None:
        hedge_band = "unknown"
    elif coverage <= 0.0:
        hedge_band = "none"
    elif coverage < 0.25:
        hedge_band = "light"
    else:
        hedge_band = "material"

    return {
        "theme_count": len(by_theme),
        "underlying_count": len(by_underlying),
        "max_theme_concentration_band": concentration_band,
        "hedge_coverage_band": hedge_band,
        "unmapped_instrument_count": len(unmapped),
        "has_unmapped_risk_gap": bool(unmapped),
        "privacy": "aggregate_only_no_identifiers",
        "not_a_trade_signal": True,
    }
