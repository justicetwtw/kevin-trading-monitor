"""觀察池清單 v4.1 - 13 主題 / 7 級 Tier(~115 檔)+ 台股

v4.1 §2.2 完整 Universe(從 v4 的 48 檔擴至 ~115 檔):
- Tier A 16 檔:巨型成熟,賣 PUT/CALL/LEAPS 全 ✅
- Tier B 25 檔:中大型成長,賣 PUT/CALL/LEAPS ✅
- Tier C 15 檔:中型 / 中等 beta,嚴篩賣方,LEAPS ⚠
- Tier D 23 檔:高 beta 投機,全部 ❌(學習鎖第 5 條 tier_c_no_sell_put 仍只擋 PLTR/TSLA,
  Kevin 後續決定是否擴大到全 Tier D)
- Tier E ETF 13 檔:流動性好(SPY/QQQ/VOO/...)
- Tier F ETF 8 檔:主題 ETF(PPA/UFO/URNM/...),由 Sprint 2.6.9 流動性檢查 dynamic 升降
- Tier G 15 檔:槓桿 / 單股 2x ETF(QLD/SSO/KORU/NVDL/...)

行為變更:
- SELL_PUT_WHITELIST = TIER_A + TIER_B 自動從 13 → 41 檔(訊號量 3 倍)
- ALL_US_STOCKS 自動從 23 → 79 檔
- ALL_TICKERS_SCAN 自動從 40 → ~115 檔(signal_scan wall time 風險,15 分 cron 要監控)
- WATCHLIST_OBSERVATION 留空 list(向下相容,v4.1 觀察清單概念被 Tier C 取代)
"""

# ============================================
# Tier A:巨型成熟($500B+)
# ============================================

TIER_A_CORE = [
    "NVDA", "TSM", "AVGO", "MU",
    "MSFT", "GOOG", "GOOGL", "META", "AMZN",
    "CAT", "LMT", "RTX",
    "WMT", "COST",
    "XOM", "CVX",
]

# ============================================
# Tier B:中大型成長($50B-500B)
# ============================================

TIER_B_SATELLITE = [
    "AMD", "ASML", "QCOM",
    "AAPL", "ORCL", "NOW", "CRM", "CRWD", "ADBE",
    "VRT", "AMAT", "LRCX", "KLAC", "ANET", "APH", "GLW", "SNPS",
    "CEG", "VST", "ETN", "GEV", "NEE", "SO",
    "VLO",
    "MELI",
]

# ============================================
# Tier C:中型 / 中等 beta(賣方嚴篩)
# ============================================

TIER_C_HIGH_POTENTIAL = [
    "INTC", "ARM", "SMCI", "MRVL", "NBIS",
    "WDC", "SNDK", "STX", "BESI", "DD",
    "BE", "CCJ", "MIR", "FLS",
    "FCX",
]

# ============================================
# Tier D:高 beta 投機(全部 ❌,不賣方不 LEAPS)
# ============================================

TIER_D_HIGH_BETA = [
    "PLTR", "TSLA",
    "AVAV", "KTOS", "ONDS", "CRDO", "SHLD",
    "OKLO", "LEU", "SMR", "NNE", "EOSE",
    "ASTS", "RKLB",
    "SOFI",
    "TMDX",
    "CRWV", "RBRK",
    "MP", "UEC", "USAR", "UUUU", "UAMY",
]

# 觀察清單(v4 遺留,v4.1 概念被 Tier C 取代,留空 list 向下相容)
WATCHLIST_OBSERVATION: list[str] = []

# 賣 PUT 白名單(Wheel Strategy 第一道閘門)
# v4.1:Tier A + Tier B = 41 檔(從 v4 的 13 檔擴大 3 倍)
SELL_PUT_WHITELIST = TIER_A_CORE + TIER_B_SATELLITE

# ============================================
# ETF Tier E:流動性好
# ============================================

ETF_HEDGE = [
    "QQQ", "SPY", "SMH", "SOXL",
    "VOO", "VTI", "VT",
    "EWY",
    "USO",
    "GLD", "GDX", "SLV",
    "URA",
]

# ============================================
# ETF Tier F:主題 ETF 流動性檢查(動態 Tier,Sprint 2.6.9)
# ============================================

ETF_THEMATIC = [
    "PPA", "UFO",
    "URNM", "COPX", "REMX", "SILJ", "SIVR", "CPER",
]

# ============================================
# ETF Tier G:槓桿 / 單股 2x ETF(波段持有,不賣方)
# ============================================

ETF_LEVERAGED_INDEX = [
    "QLD", "SSO", "KORU",
]

# 單股 2x ETF - v4.1:持現股波段操作,不賣 covered call(學習鎖第 6 條反向)
ETF_LEVERAGED_SINGLE_STOCK = {
    "NVDL": "NVDA",
    "AMDL": "AMD",
    "GGLL": "GOOGL",
    "TSLL": "TSLA",
    "TSLT": "TSLA",
    "MSFU": "MSFT",
    "METU": "META",
    "FBL":  "META",
    "AVGX": "AVGO",
    "AMZZ": "AMZN",
    "TSMX": "TSM",
    "MUU":  "MU",
}

# ============================================
# 13 主題分類(供日報 / brief 群組顯示用)
# ============================================

THEMES = {
    "ai_semiconductor": ["NVDA", "TSM", "AVGO", "AMD", "ASML", "MU", "QCOM", "INTC", "ARM", "SMCI"],
    "cloud_saas":        ["MSFT", "GOOG", "GOOGL", "META", "AMZN", "ORCL", "AAPL", "NOW", "CRM", "CRWD", "ADBE"],
    "ai_infrastructure": ["VRT", "AMAT", "LRCX", "KLAC", "ANET", "APH", "GLW", "CAT", "MRVL", "NBIS", "CRWV", "RBRK"],
    "memory_storage":    ["MU", "WDC", "SNDK", "STX", "BESI", "SNPS", "DD"],
    "defense_drone":     ["LMT", "RTX", "PLTR", "AVAV", "KTOS", "ONDS", "CRDO", "SHLD"],
    "energy_nuclear":    ["CEG", "VST", "ETN", "GEV", "NEE", "SO", "BE", "CCJ", "OKLO", "LEU", "SMR", "NNE", "MIR", "FLS", "EOSE"],
    "oil_gas":           ["XOM", "CVX", "VLO", "USO"],
    "space":             ["ASTS", "RKLB", "PPA", "UFO"],
    "metals_rare":       ["MP", "FCX", "UEC", "USAR", "UUUU", "UAMY", "GLD", "GDX", "SLV", "SILJ", "SIVR", "CPER", "COPX", "URNM", "URA", "REMX"],
    "retail_med_fin":    ["WMT", "COST", "TMDX", "SOFI", "MELI"],
    "broad_market_etf":  ["SPY", "QQQ", "VOO", "VTI", "VT", "SMH", "SOXL", "EWY"],
    "leveraged_etf":     ["QLD", "SSO", "KORU", "NVDL", "AMDL", "GGLL", "TSLL", "TSLT", "MSFU", "METU", "FBL", "AVGX", "AMZZ", "TSMX", "MUU"],
    "high_beta":         ["PLTR", "TSLA"],
}

# ============================================
# 台股(獨立帳戶)
# ============================================

TWSTOCK_CORE = [
    "00631L.TW",
    "2330.TW",
]

TWSTOCK_ACTIVE_ETFS = [
    {"symbol": "00981A.TW", "name": "主動統一台股增長", "manager": "陳釧瑤", "size_billion_ntd": 1800, "focus": "AI 供應鏈,大型成長", "holdings_count": 30},
    {"symbol": "00982A.TW", "name": "主動群益台灣強棒", "manager": "群益投信", "size_billion_ntd": 156, "focus": "量化選股 + 中小型成長", "holdings_count": 50},
    {"symbol": "00992A.TW", "name": "主動群益科技創新", "manager": "群益投信", "size_billion_ntd": 100, "focus": "純科技主題", "holdings_count": 40},
    {"symbol": "00980A.TW", "name": "主動野村台灣優選", "manager": "野村投信", "size_billion_ntd": 100, "focus": "AI + 大型權值", "holdings_count": 50},
    {"symbol": "00985A.TW", "name": "主動野村台灣 50", "manager": "野村投信", "size_billion_ntd": 80, "focus": "對標 0050 的主動版", "holdings_count": 50},
    {"symbol": "00987A.TW", "name": "主動野村臺灣科技 50", "manager": "野村投信", "size_billion_ntd": 80, "focus": "純科技 50 檔", "holdings_count": 50},
]

# ============================================
# 標的優先級
# ============================================

def get_priority(symbol: str, current_holdings: list = None) -> str:
    """返回 P0/P1/P2/P3(v4.1:走 get_tier helper)。"""
    if current_holdings and symbol in current_holdings:
        return "P0"
    return TIER_TO_PRIORITY.get(get_tier(symbol), "P3")

# v4.1:79 檔個股
ALL_US_STOCKS = (
    TIER_A_CORE
    + TIER_B_SATELLITE
    + TIER_C_HIGH_POTENTIAL
    + TIER_D_HIGH_BETA
    + WATCHLIST_OBSERVATION
)

# v4.1:~115 檔(個股 + ETF + 主題 ETF)
ALL_TICKERS_SCAN = (
    ALL_US_STOCKS
    + list(ETF_LEVERAGED_SINGLE_STOCK.keys())
    + ETF_HEDGE
    + ETF_LEVERAGED_INDEX
    + ETF_THEMATIC
)


# ============================================
# 資產類別判定(v4.1 IVR 閾值分流用)
# ============================================

def is_etf_symbol(symbol: str) -> bool:
    """判定 symbol 是否為 ETF。"""
    if symbol in ETF_HEDGE:
        return True
    if symbol in ETF_LEVERAGED_INDEX:
        return True
    if symbol in ETF_LEVERAGED_SINGLE_STOCK:
        return True
    if symbol in ETF_THEMATIC:
        return True
    return False


# ============================================
# v4.1:7 級 Tier 體系
# ============================================

TIER_TO_PRIORITY = {
    "A": "P0",
    "B": "P1",
    "C": "P2",
    "D": "P3",
    "E": "P2",
    "F": "P3",
    "G": "P3",
    "unknown": "P3",
}


def get_tier(symbol: str) -> str:
    """返回 v4.1 7 級 Tier:'A'/'B'/'C'/'D'/'E'/'F'/'G'/'unknown'。"""
    if symbol in TIER_A_CORE:
        return "A"
    if symbol in TIER_B_SATELLITE:
        return "B"
    if symbol in TIER_C_HIGH_POTENTIAL:
        return "C"
    if symbol in TIER_D_HIGH_BETA:
        return "D"
    if symbol in WATCHLIST_OBSERVATION:
        return "C"
    if symbol in ETF_LEVERAGED_SINGLE_STOCK:
        return "G"
    if symbol in ETF_LEVERAGED_INDEX:
        return "G"
    if symbol in ETF_HEDGE:
        return _get_dynamic_etf_tier(symbol, default="E")
    if symbol in ETF_THEMATIC:
        return _get_dynamic_etf_tier(symbol, default="F")
    return "unknown"


def _get_dynamic_etf_tier(symbol: str, default: str = "F") -> str:
    """從 etf_liquidity_state.json 讀 ETF 動態 Tier(E / F)。"""
    import json
    from pathlib import Path

    state_path = Path(__file__).parent.parent.parent / "data_store" / "etf_liquidity_state.json"
    if not state_path.exists():
        return default
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
        tier = data.get("tickers", {}).get(symbol, {}).get("tier", default)
        if tier not in ("E", "F"):
            return default
        return tier
    except Exception:
        return default
