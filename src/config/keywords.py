"""Trump Truth Social 三級關鍵字字典"""

# Tier 1 - 高影響(立即推播 + 60 分內訊號加標籤)
TIER1_KEYWORDS = {
    "tariff": [
        "tariff", "tariffs", "60%", "100%", "200%",
        "trade war", "trade restrictions",
    ],
    "company_named": [
        "NVDA", "Nvidia", "TSMC", "TSM", "Taiwan Semi",
        "Apple", "AAPL", "Tesla", "TSLA", "Intel", "INTC",
        "Microsoft", "MSFT", "Google", "Alphabet", "Meta",
        "Amazon", "AMZN", "AMD", "Broadcom",
    ],
    "war_escalation": [
        "strike", "attack", "Hormuz", "missile", "bomb",
        "military action", "invasion", "war",
    ],
    "fed_intervention": [
        "Powell", "fire Powell", "fire", "Fed",
        "Federal Reserve", "cut rates now", "lower rates",
    ],
    "currency": [
        "dollar", "currency manipulation",
        "yuan", "renminbi", "devaluation",
    ],
}

# Tier 2 - 中影響(推播但不加標籤)
TIER2_KEYWORDS = {
    "trade_general": [
        "trade deal", "China", "deal", "negotiation",
        "tariff threat",
    ],
    "energy": [
        "oil", "drilling", "OPEC", "energy", "gas prices",
    ],
    "market_general": [
        "stock market", "economy", "recession",
        "growth", "GDP",
    ],
    "tech_broad": [
        "chips", "AI", "artificial intelligence", "technology",
        "semiconductor",
    ],
}

# Tier 3 - 低影響(僅紀錄)- 用「none of above」判斷,不需明確列表

# 國家/地區關鍵字(用於 tariff 場景)
COUNTRIES_KEYWORDS = {
    "high_impact": ["China", "Taiwan", "Iran", "Russia", "North Korea"],
    "medium_impact": ["Mexico", "Canada", "Europe", "EU", "Japan", "Korea"],
}

def classify_post(text: str) -> str:
    """
    分類 Trump 貼文等級
    返回: "tier1" / "tier2" / "tier3"
    """
    text_lower = text.lower()

    # 檢查 Tier 1
    for category, keywords in TIER1_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                return "tier1"

    # 檢查 Tier 2
    for category, keywords in TIER2_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                return "tier2"

    return "tier3"

def get_matched_keywords(text: str) -> dict:
    """返回貼文命中的所有關鍵字分類(用於受影響部位映射)"""
    text_lower = text.lower()
    matched = {"tier1": {}, "tier2": {}}

    for category, keywords in TIER1_KEYWORDS.items():
        hits = [kw for kw in keywords if kw.lower() in text_lower]
        if hits:
            matched["tier1"][category] = hits

    for category, keywords in TIER2_KEYWORDS.items():
        hits = [kw for kw in keywords if kw.lower() in text_lower]
        if hits:
            matched["tier2"][category] = hits

    return matched
