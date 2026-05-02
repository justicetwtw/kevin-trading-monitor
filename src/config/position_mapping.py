"""事件→受影響部位映射表"""

EVENT_TO_POSITIONS = {
    "china_tariff": {
        "affected_symbols": ["NVDA", "TSM", "AVGO", "MU", "AAPL"],
        "expected_direction": "down",
        "magnitude_pct": (-0.08, -0.03),
        "suggested_action": "暫停 short premium;檢視 SMH Put",
    },
    "hormuz_iran": {
        "affected_symbols": "ALL_SLEEVE_1",  # 全部
        "expected_direction": "down",
        "magnitude_pct": "vix_spike",
        "suggested_action": "暫停建倉;考慮獲利了結部分 LEAPS",
    },
    "fed_powell_conflict": {
        "affected_symbols": "ALL_LEAPS",
        "expected_direction": "down",
        "suggested_action": "拉高現金至 25%+",
    },
    "semiconductor_named": {
        "affected_symbols": ["NVDA", "TSM", "MU", "AVGO"],
        "expected_direction": "down",
        "magnitude_pct": (-0.15, -0.05),
        "suggested_action": "評估該股 LEAPS 是否減碼",
    },
    "positive_news": {
        "affected_symbols": "ALL_SLEEVE_1",
        "expected_direction": "up",
        "suggested_action": "賣 CALL 訊號 +15 加權(IV crush 機會)",
    },
}

def map_event_to_positions(matched_keywords: dict) -> list:
    """
    根據命中的關鍵字,返回受影響事件清單
    """
    events = []

    tier1 = matched_keywords.get("tier1", {})

    if "tariff" in tier1 and (
        "China" in str(tier1) or "Taiwan" in str(tier1)
    ):
        events.append("china_tariff")

    if "war_escalation" in tier1:
        events.append("hormuz_iran")

    if "fed_intervention" in tier1:
        events.append("fed_powell_conflict")

    if "company_named" in tier1:
        company_kws = tier1.get("company_named", [])
        if any(kw in ["NVDA", "TSMC", "Nvidia", "TSM"] for kw in company_kws):
            events.append("semiconductor_named")

    return events
