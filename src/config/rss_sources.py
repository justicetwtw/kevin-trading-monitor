"""RSS Feed URL 清單"""

RSS_SOURCES = {
    "reuters_business": "https://feeds.reuters.com/reuters/businessNews",
    "reuters_markets": "https://feeds.reuters.com/reuters/USMarketsNews",
    "ap_top": "https://apnews.com/index.rss",
    "fed_press": "https://www.federalreserve.gov/feeds/press_all.xml",
}

# SEC EDGAR 8-K Atom feed 範本
SEC_8K_FEED_TEMPLATE = (
    "https://www.sec.gov/cgi-bin/browse-edgar?"
    "action=getcompany&CIK={cik}&type=8-K&output=atom"
)

# 關鍵字過濾(用於 RSS 內容)
NEWS_FILTER_KEYWORDS = {
    "macro": [
        "Fed", "FOMC", "CPI", "jobs", "GDP", "recession",
        "Powell", "rate cut", "rate hike", "inflation",
    ],
    "geopolitical": [
        "Iran", "Hormuz", "Taiwan", "China military",
        "Russia", "North Korea", "war",
    ],
    "tech": [
        "Nvidia", "TSMC", "Apple", "Microsoft", "Google",
        "Meta", "Amazon", "AMD", "AI", "semiconductor",
        "chips",
    ],
}

# Trump Truth Social 端點
TRUMP_TRUTH_SOURCES = {
    "primary_cnn_mirror": "https://ix.cnn.io/data/truth-social/truth_archive.json",
    "fallback_truth_api": (
        "https://truthsocial.com/api/v1/accounts/"
        "107780257626128497/statuses"
    ),
}

# CBOE Put/Call Ratio
CBOE_PCR_URL = "https://www.cboe.com/us/options/market_statistics/daily/?dt={date}"
# 備援:yfinance ^CPC (注意有時候 yfinance 沒這 ticker,需 fallback)

# CNN Fear & Greed (備用,但不在 v4 內)

# AAII Sentiment Survey
AAII_SENTIMENT_URL = "https://www.aaii.com/sentimentsurvey/sent_results"
