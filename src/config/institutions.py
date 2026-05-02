"""13F 追蹤機構名單(精選 12 家,以 AI/科技主題為主)"""

INSTITUTIONS_TO_TRACK = [
    # 巨型多元
    {"name": "Berkshire Hathaway", "cik": "0001067983", "category": "mega_diverse"},
    {"name": "Bridgewater Associates", "cik": "0001350694", "category": "mega_diverse"},

    # 量化巨頭
    {"name": "Renaissance Technologies", "cik": "0001037389", "category": "quant_giant"},
    {"name": "Two Sigma Investments", "cik": "0001179392", "category": "quant_giant"},
    {"name": "D.E. Shaw", "cik": "0001009207", "category": "quant_giant"},
    {"name": "Citadel Advisors", "cik": "0001423053", "category": "quant_giant"},

    # 成長/科技
    {"name": "Tiger Global Management", "cik": "0001167483", "category": "growth_tech"},
    {"name": "Coatue Management", "cik": "0001135730", "category": "growth_tech"},
    {"name": "Whale Rock Capital", "cik": "0001583602", "category": "growth_tech"},
    {"name": "Lone Pine Capital", "cik": "0001061165", "category": "growth_tech"},

    # 科技專注
    {"name": "ARK Invest", "cik": "0001697748", "category": "tech_focused"},
    {"name": "Light Street Capital", "cik": "0001551327", "category": "tech_focused"},
]

# CIK 是 SEC 中央索引號,EdgarTools 用此 ID 抓 filings
# 注意:CIK 編號可能會變,實際使用前需驗證(階段 2 實作時 verify)
