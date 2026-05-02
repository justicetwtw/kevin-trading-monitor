"""觀察池清單 - Tier A/B/C + ETF + 台股 + 主動 ETF"""

# ============================================
# 美股白名單
# ============================================

TIER_A_CORE = [
    "NVDA",   # Nvidia - 半導體龍頭
    "TSM",    # TSMC ADR
    "MU",     # Micron - 記憶體龍頭
    "MSFT",   # Microsoft
    "GOOG",   # Alphabet C
    "GOOGL",  # Alphabet A
    "META",   # Meta Platforms
    "AVGO",   # Broadcom
    "AMZN",   # Amazon
]

TIER_B_SATELLITE = [
    "AMD",    # AMD
    "ASML",   # ASML(EUV 設備)
    "ORCL",   # Oracle
    "AAPL",   # Apple
]

# Tier C 高潛力但不賣 PUT
TIER_C_HIGH_POTENTIAL = [
    "PLTR",   # Palantir
    "TSLA",   # Tesla
]

# 觀察名單 - 訊號掃描但暫不交易
WATCHLIST_OBSERVATION = [
    "INTC", "CRM", "ADBE", "CRWD", "NOW", "SMCI", "ARM",
    "SNDK",  # 使用者特別關注
]

# 賣 PUT 白名單(Wheel Strategy 第一道閘門)
SELL_PUT_WHITELIST = TIER_A_CORE + TIER_B_SATELLITE
# ⚠ Tier C 永遠不在賣 PUT 白名單

# ============================================
# ETF 工具
# ============================================

ETF_HEDGE = ["QQQ", "SPY", "SMH", "SOXL"]      # 大盤對沖
ETF_LEVERAGED_INDEX = ["QLD", "SSO"]            # 大盤型 2x ETF (Sleeve 2a)

# 單股 2x ETF - 僅交易選擇權,不長持現股(學習鎖第 6 條)
ETF_LEVERAGED_SINGLE_STOCK = {
    "NVDL": "NVDA",
    "AMDL": "AMD",
    "GGLL": "GOOGL",
    "TSLL": "TSLA",
    "TSLT": "TSLA",
    "MSFU": "MSFT",
    "METU": "META",
    "FBL": "META",
    "AVGX": "AVGO",
    "AMZZ": "AMZN",
    "TSMX": "TSM",
}

# ============================================
# 台股
# ============================================

TWSTOCK_CORE = [
    "00631L.TW",  # 元大台灣 50 正 2
    "2330.TW",    # 台積電
]

# 台股主動 ETF 監測(精選 6 檔,規模 ≥100 億 + 運作 ≥6 個月 + AI/科技主題)
TWSTOCK_ACTIVE_ETFS = [
    {
        "symbol": "00981A.TW",
        "name": "主動統一台股增長",
        "manager": "陳釧瑤",
        "size_billion_ntd": 1800,
        "focus": "AI 供應鏈,大型成長",
        "holdings_count": 30,
    },
    {
        "symbol": "00982A.TW",
        "name": "主動群益台灣強棒",
        "manager": "群益投信",
        "size_billion_ntd": 156,
        "focus": "量化選股 + 中小型成長",
        "holdings_count": 50,
    },
    {
        "symbol": "00992A.TW",
        "name": "主動群益科技創新",
        "manager": "群益投信",
        "size_billion_ntd": 100,  # 估計
        "focus": "純科技主題",
        "holdings_count": 40,
    },
    {
        "symbol": "00980A.TW",
        "name": "主動野村台灣優選",
        "manager": "野村投信",
        "size_billion_ntd": 100,  # 估計
        "focus": "AI + 大型權值",
        "holdings_count": 50,
    },
    {
        "symbol": "00985A.TW",
        "name": "主動野村台灣 50",
        "manager": "野村投信",
        "size_billion_ntd": 80,  # 估計
        "focus": "對標 0050 的主動版",
        "holdings_count": 50,
    },
    {
        "symbol": "00987A.TW",
        "name": "主動野村臺灣科技 50",
        "manager": "野村投信",
        "size_billion_ntd": 80,  # 估計
        "focus": "純科技 50 檔",
        "holdings_count": 50,
    },
]

# ============================================
# 標的優先級(用於三層篩選器第二層)
# ============================================

def get_priority(symbol: str, current_holdings: list = None) -> str:
    """
    返回標的優先級
    P0: Tier A + 你的持倉
    P1: Tier B
    P2: 觀察清單其他
    P3: Tier C (不推,只入庫)
    """
    if current_holdings and symbol in current_holdings:
        return "P0"
    if symbol in TIER_A_CORE:
        return "P0"
    if symbol in TIER_B_SATELLITE:
        return "P1"
    if symbol in WATCHLIST_OBSERVATION:
        return "P2"
    if symbol in TIER_C_HIGH_POTENTIAL:
        return "P3"
    return "P3"

# 全部要掃描的美股標的
ALL_US_STOCKS = TIER_A_CORE + TIER_B_SATELLITE + TIER_C_HIGH_POTENTIAL + WATCHLIST_OBSERVATION

# 全部要掃描的標的(美股 + 對應的單股 2x ETF + 大盤 ETF)
ALL_TICKERS_SCAN = (
    ALL_US_STOCKS
    + list(ETF_LEVERAGED_SINGLE_STOCK.keys())
    + ETF_HEDGE
    + ETF_LEVERAGED_INDEX
)
