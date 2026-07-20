"""Focus universe + instrument mapping(docs/focus_trading_engine_v1.md §4)。

在既有 broad universe(src/config/universe.py)之上疊一層 focus overlay:

- 定義 AI compute / memory(HBM·DRAM·NAND)/ optical / equipment / power 主題群組。
- 把槓桿 ETF、ADR、主題 ETF 映射回 underlying 與 theme,避免把相同曝險當成分散。
- runtime priority 以真實持倉(private)為第一優先,其次才是 focus 名單。

紅線:
- 這是 research / risk mapping,不代表全部是持倉或推薦。
- 未知 instrument 一律標 ``unmapped_instrument`` fail closed,不得靜默歸零。
- 不把 price action 當 thesis;本模組不產生任何 buy/sell 指令。
"""

from __future__ import annotations

from typing import Any

# ============================================
# Theme groups(§4.2)。value 為該主題的 underlying 代表名單。
# ============================================

THEME_GROUPS: dict[str, list[str]] = {
    "ai_compute": ["NVDA", "AMD", "TSM", "AVGO", "SMH", "SOXX"],
    "memory_hbm_dram": ["MU", "SKHY", "DRAM"],
    "memory_nand_storage": ["SNDK", "WDC", "STX", "285A", "DISK"],
    "optical_interconnect": [
        "LITE", "COHR", "AAOI", "MRVL", "CRDO", "ALAB", "AXTI", "GLW",
    ],
    "semi_equipment_upstream": ["ASML", "AMAT", "LRCX", "KLAC", "TSEM", "GFS"],
    "ai_power_energy": ["VRT", "ETN", "GEV", "VST", "CEG", "BE"],
    "portfolio_hedge": ["QQQ", "SPY", "SMH"],
}

#: memory 必須分 HBM / commodity DRAM / NAND thesis(§5 Layer A)。
MEMORY_SUBTHEMES = {
    "hbm": "memory_hbm_dram",
    "commodity_dram": "memory_hbm_dram",
    "nand": "memory_nand_storage",
}

# ============================================
# Theme constituents vs tradable proxies(§5 Layer C rotation)。
#
# rotation basket 只能用「單一成分股」計算,不得把 ETF proxy(SMH/SOXX...)或
# basket pseudo-ticker(DRAM/DISK...)混進成分再拿去跟同一支 ETF 比較 —— 那會
# 對相同風險重複加權。THEME_CONSTITUENTS 只含 clean single-name;ETF proxy 與
# benchmark 分開列在 THEME_PROXIES。
# ============================================

THEME_CONSTITUENTS: dict[str, list[str]] = {
    "ai_compute": ["NVDA", "AMD", "TSM", "AVGO"],
    "memory_hbm_dram": ["MU"],
    "memory_nand_storage": ["SNDK", "WDC", "STX"],
    "optical_interconnect": [
        "LITE", "COHR", "AAOI", "MRVL", "CRDO", "ALAB", "AXTI", "GLW",
    ],
    "semi_equipment_upstream": ["ASML", "AMAT", "LRCX", "KLAC", "TSEM", "GFS"],
    "ai_power_energy": ["VRT", "ETN", "GEV", "VST", "CEG", "BE"],
}

#: 各 theme 的可交易 ETF proxy(僅供對照/工具映射,不進 rotation basket 計算)。
THEME_PROXIES: dict[str, list[str]] = {
    "ai_compute": ["SMH", "SOXX"],
    "memory_hbm_dram": [],
    "memory_nand_storage": [],
    "optical_interconnect": [],
    "semi_equipment_upstream": [],
    "ai_power_energy": [],
}

#: 公開 ETF proxy / benchmark(可安全進 public card universe)。
PUBLIC_ETF_PROXIES = ["SMH", "SOXX", "QQQ", "SPY"]

# ============================================
# Benchmarks(RS 計算基準,§5 Layer C)
# ============================================

BENCHMARK_BROAD = "QQQ"
BENCHMARK_SEMI = "SMH"

# ============================================
# Instrument mapping(§4.3)。
# 槓桿 ETF / ADR / 主題 ETF → (underlying, leverage)。
# leverage=1.0 代表 1:1 曝險(現股或 ADR);>1 代表槓桿倍數。
# ============================================

#: 單一 underlying 的槓桿工具:instrument → {underlying, leverage}
LEVERAGED_SINGLE_NAME: dict[str, dict[str, Any]] = {
    "MUU": {"underlying": "MU", "leverage": 2.0},
    "SNXX": {"underlying": "SNDK", "leverage": 2.0},
    "WDCX": {"underlying": "WDC", "leverage": 2.0},
    "NVDL": {"underlying": "NVDA", "leverage": 2.0},
    "AMDL": {"underlying": "AMD", "leverage": 2.0},
    "TSMX": {"underlying": "TSM", "leverage": 2.0},
    "AVGX": {"underlying": "AVGO", "leverage": 2.0},
    "LITX": {"underlying": "LITE", "leverage": 2.0},
    "MVLL": {"underlying": "MRVL", "leverage": 2.0},
    # 既有 v4.1 單股 2x(src/config/universe.py)一併納管,schema 一致。
    "GGLL": {"underlying": "GOOGL", "leverage": 2.0},
    "TSLL": {"underlying": "TSLA", "leverage": 2.0},
    "TSLT": {"underlying": "TSLA", "leverage": 2.0},
    "MSFU": {"underlying": "MSFT", "leverage": 2.0},
    "METU": {"underlying": "META", "leverage": 2.0},
    "FBL": {"underlying": "META", "leverage": 2.0},
    "AMZZ": {"underlying": "AMZN", "leverage": 2.0},
}

#: 映射到 theme basket(非單一 underlying)的工具:instrument → {theme, leverage}
BASKET_INSTRUMENTS: dict[str, dict[str, Any]] = {
    "DRAM": {"theme": "memory_hbm_dram", "leverage": 1.0},
    "RAM": {"theme": "memory_hbm_dram", "leverage": 1.0},
    "DISK": {"theme": "memory_nand_storage", "leverage": 1.0},
    "SMH": {"theme": "ai_compute", "leverage": 1.0},
    "SOXX": {"theme": "ai_compute", "leverage": 1.0},
    "SOXL": {"theme": "ai_compute", "leverage": 3.0},
}


def _theme_for_underlying(underlying: str) -> str | None:
    """回傳 underlying 所屬的第一個 theme;找不到回 None(不猜測)。"""
    for theme, names in THEME_GROUPS.items():
        if theme == "portfolio_hedge":
            continue
        if underlying in names:
            return theme
    return None


def map_instrument(symbol: str) -> dict[str, Any]:
    """把任一 instrument 映射回 underlying / theme 曝險。

    回傳 schema(永遠含這些 key,fail closed 用):
        {
          symbol, kind, underlying, theme, leverage, mapped, note
        }

    - kind: "single_name" | "leveraged_single" | "basket" | "underlying"
    - mapped=False 且 note="unmapped_instrument" 代表未知,呼叫方必須當成風險缺口,
      不得靜默把曝險視為 0。
    """
    sym = (symbol or "").strip().upper()
    base = {
        "symbol": sym,
        "kind": None,
        "underlying": None,
        "theme": None,
        "leverage": None,
        "mapped": False,
        "note": None,
    }
    if not sym:
        base["note"] = "unmapped_instrument"
        return base

    if sym in LEVERAGED_SINGLE_NAME:
        info = LEVERAGED_SINGLE_NAME[sym]
        underlying = info["underlying"]
        base.update(
            {
                "kind": "leveraged_single",
                "underlying": underlying,
                "theme": _theme_for_underlying(underlying),
                "leverage": float(info["leverage"]),
                "mapped": True,
            }
        )
        return base

    if sym in BASKET_INSTRUMENTS:
        info = BASKET_INSTRUMENTS[sym]
        base.update(
            {
                "kind": "basket",
                "underlying": None,
                "theme": info["theme"],
                "leverage": float(info["leverage"]),
                "mapped": True,
            }
        )
        return base

    theme = _theme_for_underlying(sym)
    if theme is not None or sym in THEME_GROUPS.get("portfolio_hedge", []):
        base.update(
            {
                "kind": "single_name",
                "underlying": sym,
                "theme": theme or "portfolio_hedge",
                "leverage": 1.0,
                "mapped": True,
            }
        )
        return base

    # 未在 focus overlay 內,但仍是可辨識的一般美股 → 視為 1:1 underlying,
    # theme 未知(honest None),而不是 unmapped。只有連 symbol 都無法判定
    # (空字串)才 fail closed 成 unmapped_instrument。
    base.update(
        {
            "kind": "underlying",
            "underlying": sym,
            "theme": None,
            "leverage": 1.0,
            "mapped": True,
            "note": "outside_focus_overlay",
        }
    )
    return base


def normalize_to_underlying(symbol: str, notional: float) -> dict[str, Any]:
    """把一個部位的名目曝險轉成 underlying-normalized 曝險(含槓桿放大)。

    未知 instrument 回 mapped=False,並保留 raw notional 供呼叫方標紅,不歸零。
    """
    mapping = map_instrument(symbol)
    if not mapping["mapped"]:
        return {
            **mapping,
            "raw_notional": float(notional),
            "underlying_notional": None,
        }
    leverage = mapping["leverage"] or 1.0
    return {
        **mapping,
        "raw_notional": float(notional),
        "underlying_notional": float(notional) * leverage,
    }


def static_focus_symbols() -> list[str]:
    """公開的 focus card universe —— **只**來自靜態公開名單。

    P0 privacy(review finding):public focus cards 的 symbol 集合絕不能受私有
    持倉影響,否則不在公開名單的私有持倉會變成可識別的 public card。因此 public
    cards 一律從這個純靜態、純公開的清單建立;holdings 只能影響 private 排序與
    aggregate exception,不得改變 public symbol 集合。
    """
    ordered: list[str] = []
    for theme, names in THEME_CONSTITUENTS.items():
        for sym in names:
            if sym not in ordered:
                ordered.append(sym)
    for sym in PUBLIC_ETF_PROXIES:
        if sym not in ordered:
            ordered.append(sym)
    for sym in LEVERAGED_SINGLE_NAME:
        if sym not in ordered:
            ordered.append(sym)
    return ordered


def runtime_focus_symbols(
    holdings: list[str] | None = None,
    kevin_focus: list[str] | None = None,
) -> list[dict[str, Any]]:
    """依 §4.1 runtime priority 建立 focus 名單(去重、保留優先級)。

    優先級 1-5:
      1. 真實持倉 underlying(private,呼叫方傳入)
      2. Kevin 明確指定的 focus symbols
      3. 高品質龍頭 / 主要產業代理(THEME_GROUPS 的 underlying 名單)
      4. 次要供應鏈 / research(暫與 3 併入 theme 名單)
      5. 槓桿 ETF / 交易工具

    回傳 [{symbol, priority, source, theme}],同一 symbol 只保留最高優先級。
    """
    ordered: list[tuple[str, int, str, str | None]] = []

    for sym in holdings or []:
        mapping = map_instrument(sym)
        underlying = mapping["underlying"] or sym.strip().upper()
        ordered.append((underlying, 1, "holding", mapping["theme"]))

    for sym in kevin_focus or []:
        mapping = map_instrument(sym)
        underlying = mapping["underlying"] or sym.strip().upper()
        ordered.append((underlying, 2, "kevin_focus", mapping["theme"]))

    for theme, names in THEME_GROUPS.items():
        for sym in names:
            ordered.append((sym, 3, "theme_leader", theme))

    for sym in LEVERAGED_SINGLE_NAME:
        ordered.append((sym, 5, "leveraged_instrument", map_instrument(sym)["theme"]))

    best: dict[str, dict[str, Any]] = {}
    for symbol, priority, source, theme in ordered:
        current = best.get(symbol)
        if current is None or priority < current["priority"]:
            best[symbol] = {
                "symbol": symbol,
                "priority": priority,
                "source": source,
                "theme": theme,
            }
    return sorted(best.values(), key=lambda row: (row["priority"], row["symbol"]))
