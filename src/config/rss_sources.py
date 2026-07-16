"""RSS and public-source URL configuration."""

RSS_SOURCES = {
    "reuters_business": "https://feeds.reuters.com/reuters/businessNews",
    "reuters_markets": "https://feeds.reuters.com/reuters/USMarketsNews",
    "ap_top": "https://apnews.com/index.rss",
    "fed_press": "https://www.federalreserve.gov/feeds/press_all.xml",
}

SEC_8K_FEED_TEMPLATE = (
    "https://www.sec.gov/cgi-bin/browse-edgar?"
    "action=getcompany&CIK={cik}&type=8-K&output=atom"
)

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
        "Meta", "Amazon", "AMD", "AI", "semiconductor", "chips",
    ],
}

# Trump / Truth Social
#
# `truth_api_*` is the only configured live source. The CNN JSON URL is a
# historical archive: in July 2026 it returned posts from January 2023. It must
# never be treated as a healthy current feed merely because the JSON is nonempty.
TRUMP_TRUTH_SOURCES = {
    "truth_account_lookup": (
        "https://truthsocial.com/api/v1/accounts/lookup?acct=realDonaldTrump"
    ),
    "truth_statuses_template": (
        "https://truthsocial.com/api/v1/accounts/{account_id}/statuses"
    ),
    "truth_profile": "https://truthsocial.com/@realDonaldTrump",
    "configured_account_id": "107780257626128497",
    "cnn_historical_archive": (
        "https://ix.cnn.io/data/truth-social/truth_archive.json"
    ),
}

CBOE_PCR_URL = "https://www.cboe.com/us/options/market_statistics/daily/?dt={date}"
AAII_SENTIMENT_URL = "https://www.aaii.com/sentimentsurvey/sent_results"
