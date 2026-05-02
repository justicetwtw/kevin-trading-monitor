"""Batch 10 — alerts/ 4 模組 unit tests(test-first)。

涵蓋:
- 三 format 函式(美股 / 部位 / 新聞)
- dedup:24h 擋 / 升級 override / Trump tag override
- daily quota:達上限擋 / 跨日 reset / P2/P3 不推
- 1 分鐘冷卻
- tag_attacher:部位加 / drawdown 不加 / 新聞不加 / 已有 tags 不覆蓋
- determine_priority:台股各 emoji → 正確 priority
- 冷啟動全綠
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


# ============================
# Fixtures
# ============================

@pytest.fixture
def isolated_data_store(tmp_path, monkeypatch):
    fake = tmp_path / "data_store"
    fake.mkdir()
    monkeypatch.setattr("src.storage.state_manager.DATA_STORE_DIR", fake)
    return fake


# ============================
# alert_formatter
# ============================

def test_format_signal_alert_basic():
    from src.alerts.alert_formatter import format_signal_alert
    sig = {
        "signal_type": "sell_call", "symbol": "NVDA", "final_score": 78.5,
        "alert_level": "green", "price": 950.0, "iv_rank": 65,
    }
    msg = format_signal_alert(sig)
    assert "NVDA" in msg
    assert "賣 CALL" in msg
    assert "78.5" in msg
    assert "🟢" in msg


def test_format_signal_alert_with_tags_and_vetoes():
    from src.alerts.alert_formatter import format_signal_alert
    sig = {
        "signal_type": "leaps_entry", "symbol": "MSFT", "final_score": 82,
        "alert_level": "green", "price": 410.0,
        "tags": ["⚠Trump_Tier1", "⚠Trump_Semi_Risk"],
        "vetoes": [],
    }
    msg = format_signal_alert(sig)
    assert "⚠Trump_Tier1" in msg
    assert "LEAPS" in msg


def test_format_position_alert_leaps_pnl():
    from src.alerts.alert_formatter import format_position_alert
    msg = format_position_alert({
        "kind": "leaps_pnl", "option_id": "NVDA_2027C_120",
        "level": "+100", "action": "賣 1/3 鎖利",
    })
    assert "📈" in msg
    assert "NVDA_2027C_120" in msg or "+100" in msg


def test_format_position_alert_drawdown():
    from src.alerts.alert_formatter import format_position_alert
    msg = format_position_alert({
        "kind": "drawdown", "alert_level": "level_2",
        "drawdown_pct": -0.22, "action": "強制檢視 LEAPS",
    })
    assert "🛑" in msg


def test_format_news_alert_trump_tier1():
    from src.alerts.alert_formatter import format_news_alert
    msg = format_news_alert({
        "source": "Trump", "tier": 1,
        "title": "Trump posts about tariffs on China",
        "url": "https://example.com",
    })
    assert "🚨" in msg
    assert "Trump" in msg


def test_format_html_escapes_user_input():
    """HTML 注入防禦:title 含 <script> 應被 escape"""
    from src.alerts.alert_formatter import format_news_alert
    msg = format_news_alert({
        "source": "RSS", "tier": 2,
        "title": "<script>alert(1)</script>",
    })
    assert "<script>" not in msg
    assert "&lt;script&gt;" in msg or "alert(1)" in msg  # escape 過或被剝除


# ============================
# deduplication
# ============================

def test_dedup_first_send_not_duplicate(isolated_data_store):
    from src.alerts import deduplication
    alert = {"symbol": "NVDA", "signal_type": "sell_call", "alert_level": "green"}
    assert deduplication.is_duplicate(alert) is False


def test_dedup_within_24h_blocks(isolated_data_store):
    from src.alerts import deduplication
    alert = {"symbol": "NVDA", "signal_type": "sell_call", "alert_level": "green"}
    deduplication.mark_sent(alert)
    assert deduplication.is_duplicate(alert) is True


def test_dedup_after_24h_passes(isolated_data_store):
    from src.alerts import deduplication
    alert = {"symbol": "NVDA", "signal_type": "sell_call", "alert_level": "green"}
    deduplication.mark_sent(alert)
    # 假裝 25 小時前
    state_path = isolated_data_store / "alert_dedup.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    key = list(state.keys())[0]
    state[key]["last_sent"] = old_time
    state_path.write_text(json.dumps(state), encoding="utf-8")
    assert deduplication.is_duplicate(alert) is False


def test_dedup_upgrade_override_white_to_green(isolated_data_store):
    """white → green 升級 → 突破 dedup"""
    from src.alerts import deduplication
    old = {"symbol": "NVDA", "signal_type": "sell_call", "alert_level": "white"}
    deduplication.mark_sent(old)
    new = {"symbol": "NVDA", "signal_type": "sell_call", "alert_level": "green"}
    assert deduplication.is_duplicate(new) is False


def test_dedup_downgrade_no_override(isolated_data_store):
    """green → white 降級 → 仍 dedup"""
    from src.alerts import deduplication
    old = {"symbol": "NVDA", "signal_type": "sell_call", "alert_level": "green"}
    deduplication.mark_sent(old)
    new = {"symbol": "NVDA", "signal_type": "sell_call", "alert_level": "white"}
    assert deduplication.is_duplicate(new) is True


def test_dedup_trump_tag_override(isolated_data_store):
    """同 key 但有 ⚠Trump_Tier1 → 突破 dedup"""
    from src.alerts import deduplication
    old = {"symbol": "NVDA", "signal_type": "sell_call", "alert_level": "green", "tags": []}
    deduplication.mark_sent(old)
    new = {"symbol": "NVDA", "signal_type": "sell_call", "alert_level": "green",
           "tags": ["⚠Trump_Tier1"]}
    assert deduplication.is_duplicate(new) is False


def test_dedup_cleans_old_entries(isolated_data_store):
    """7 天前的紀錄應被清掉"""
    from src.alerts import deduplication
    state_path = isolated_data_store / "alert_dedup.json"
    very_old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    state_path.write_text(json.dumps({
        "OLD::sell_call": {"last_sent": very_old, "alert_level": "green"},
    }), encoding="utf-8")
    deduplication.mark_sent({"symbol": "NEW", "signal_type": "sell_put",
                             "alert_level": "green"})
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "OLD::sell_call" not in state
    assert "NEW::sell_put" in state


# ============================
# tag_attacher
# ============================

def _write_trump_state(data_store, last_tier1_iso: str | None):
    """寫 layer_trump_classifier_state.json,classified list 含一筆 tier1。"""
    data = {"classified": [], "fetched_at": datetime.now(timezone.utc).isoformat()}
    if last_tier1_iso:
        data["classified"] = [{
            "post_id": "p1", "tier": "tier1",
            "text": "...", "created_at": last_tier1_iso,
            "matched_keywords": [], "events": [],
            "scan_time": last_tier1_iso,
        }]
    (data_store / "layer_trump_classifier_state.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def test_tag_recent_trump_tier1_within_60min(isolated_data_store):
    from src.alerts import tag_attacher
    recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    _write_trump_state(isolated_data_store, recent)
    assert tag_attacher.has_recent_trump_tier1() is True


def test_tag_no_recent_trump_tier1_after_60min(isolated_data_store):
    from src.alerts import tag_attacher
    old = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
    _write_trump_state(isolated_data_store, old)
    assert tag_attacher.has_recent_trump_tier1() is False


def test_tag_cold_start_no_state_file(isolated_data_store):
    from src.alerts import tag_attacher
    assert tag_attacher.has_recent_trump_tier1() is False


def test_attach_tags_to_position_alert(isolated_data_store):
    """部位 alert(leaps_pnl)→ 加 ⚠Trump_Tier1"""
    from src.alerts import tag_attacher
    recent = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    _write_trump_state(isolated_data_store, recent)
    out = tag_attacher.attach_context_tags({
        "kind": "leaps_pnl", "option_id": "X", "action": "賣 1/3"
    })
    assert "⚠Trump_Tier1" in out.get("tags", [])


def test_attach_tags_skip_drawdown(isolated_data_store):
    """drawdown alert → 不加(回撤跟即時事件無關)"""
    from src.alerts import tag_attacher
    recent = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    _write_trump_state(isolated_data_store, recent)
    out = tag_attacher.attach_context_tags({"kind": "drawdown", "drawdown_pct": -0.25})
    assert "⚠Trump_Tier1" not in out.get("tags", [])


def test_attach_tags_skip_news(isolated_data_store):
    """新聞 alert → 不加(事件本身就是事件)"""
    from src.alerts import tag_attacher
    recent = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    _write_trump_state(isolated_data_store, recent)
    out = tag_attacher.attach_context_tags({"kind": "news", "source": "RSS", "tier": 1})
    assert "⚠Trump_Tier1" not in out.get("tags", [])


def test_attach_tags_no_overwrite_existing(isolated_data_store):
    """final_scorer 已注入 tags → 不重複加 / 不蓋掉"""
    from src.alerts import tag_attacher
    recent = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    _write_trump_state(isolated_data_store, recent)
    existing = ["⚠Trump_Semi_Risk", "⚠Trump_Tier1"]
    out = tag_attacher.attach_context_tags({
        "signal_type": "sell_call", "symbol": "NVDA",
        "tags": list(existing),
    })
    # 不重複(已有 ⚠Trump_Tier1 不再加)
    assert out["tags"].count("⚠Trump_Tier1") == 1
    assert "⚠Trump_Semi_Risk" in out["tags"]


# ============================
# alert_router — determine_priority
# ============================

def test_priority_drawdown_level2_is_p0():
    from src.alerts.alert_router import determine_priority
    assert determine_priority({"kind": "drawdown", "level": "level_2"}) == "P0"


def test_priority_trump_tier1_is_p0():
    from src.alerts.alert_router import determine_priority
    assert determine_priority({"source": "Trump", "tier": 1, "kind": "news"}) == "P0"


def test_priority_sec_8k_is_p0():
    from src.alerts.alert_router import determine_priority
    assert determine_priority({"source": "SEC/NVDA", "form_type": "8-K", "kind": "news"}) == "P0"


def test_priority_red_alert_level_is_p0():
    """台股 C 級 / VIX>35 → red → P0"""
    from src.alerts.alert_router import determine_priority
    assert determine_priority({"alert_level": "red", "tier": "C"}) == "P0"


def test_priority_orange_is_p1():
    """台股 ETF Tier 2 共識 → orange → P1"""
    from src.alerts.alert_router import determine_priority
    assert determine_priority({"alert_level": "orange", "tier": 2}) == "P1"


def test_priority_green_is_p1():
    from src.alerts.alert_router import determine_priority
    assert determine_priority({"alert_level": "green"}) == "P1"


def test_priority_yellow_is_p2():
    from src.alerts.alert_router import determine_priority
    assert determine_priority({"alert_level": "yellow"}) == "P2"


def test_priority_white_is_p3():
    from src.alerts.alert_router import determine_priority
    assert determine_priority({"alert_level": "white"}) == "P3"


# ============================
# alert_router — should_send (daily quota + 1min cooldown)
# ============================

def test_should_send_p2_p3_blocked(isolated_data_store):
    """P2/P3 quota=None → 不推"""
    from src.alerts.alert_router import should_send
    assert should_send({"symbol": "X", "signal_type": "y"}, "P2") is False
    assert should_send({"symbol": "X", "signal_type": "y"}, "P3") is False


def test_should_send_p0_under_quota(isolated_data_store):
    from src.alerts.alert_router import should_send
    assert should_send({"symbol": "X", "signal_type": "y"}, "P0") is True


def test_should_send_p0_over_daily_quota(isolated_data_store):
    """P0 quota=5,已推 5 則 → 第 6 個擋"""
    from src.alerts.alert_router import should_send, mark_sent_quota
    for i in range(5):
        mark_sent_quota({"symbol": f"S{i}", "signal_type": "sell_call"}, "P0")
    assert should_send({"symbol": "S6", "signal_type": "sell_call"}, "P0") is False


def test_should_send_p1_over_daily_quota(isolated_data_store):
    from src.alerts.alert_router import should_send, mark_sent_quota
    for i in range(10):
        mark_sent_quota({"symbol": f"S{i}", "signal_type": "sell_put"}, "P1")
    assert should_send({"symbol": "S11", "signal_type": "sell_put"}, "P1") is False


def test_should_send_quota_resets_next_day(isolated_data_store):
    """昨日 P0 滿,今日歸零"""
    from src.alerts.alert_router import should_send, ROUTING_FILE
    from src.storage.state_manager import write_json
    yesterday = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
    write_json(ROUTING_FILE, {
        "daily_quota": {yesterday: {"P0": 99, "P1": 99}},
        "last_send_per_key": {},
    })
    assert should_send({"symbol": "X", "signal_type": "y"}, "P0") is True


def test_should_send_1min_cooldown(isolated_data_store):
    """同 key 1 分鐘內第二次推 → 擋(防 routing loop)"""
    from src.alerts.alert_router import should_send, mark_sent_quota
    alert = {"symbol": "NVDA", "signal_type": "sell_call"}
    mark_sent_quota(alert, "P1")
    assert should_send(alert, "P1") is False  # 立刻再推


def test_should_send_after_1min_cooldown_passes(isolated_data_store):
    from src.alerts.alert_router import should_send, mark_sent_quota, ROUTING_FILE
    from src.storage.state_manager import read_json, write_json
    alert = {"symbol": "NVDA", "signal_type": "sell_call"}
    mark_sent_quota(alert, "P1")
    state = read_json(ROUTING_FILE, default={})
    state["last_send_per_key"]["NVDA::sell_call"] = (
        datetime.now(timezone.utc) - timedelta(minutes=2)
    ).isoformat()
    write_json(ROUTING_FILE, state)
    assert should_send(alert, "P1") is True


# ============================
# alert_router — route_alert 端到端
# ============================

def test_route_alert_sends_first_time(isolated_data_store):
    from src.alerts import alert_router
    alert = {"symbol": "NVDA", "signal_type": "sell_call",
             "alert_level": "green", "message": "hi", "final_score": 75}
    with patch("src.alerts.alert_router.send_telegram", return_value=True) as m:
        ok = alert_router.route_alert(alert)
    assert ok is True
    assert m.call_count == 1


def test_route_alert_dedup_blocks_second(isolated_data_store):
    from src.alerts import alert_router
    alert = {"symbol": "NVDA", "signal_type": "sell_call",
             "alert_level": "green", "message": "hi"}
    with patch("src.alerts.alert_router.send_telegram", return_value=True) as m:
        alert_router.route_alert(alert)
        # 立刻再推同一個 → 1min cooldown 或 dedup 任一擋住即可
        ok2 = alert_router.route_alert(alert)
    assert ok2 is False
    assert m.call_count == 1


def test_route_alert_send_failure_does_not_mark(isolated_data_store):
    """send_telegram 回 False → 不寫 dedup / 不扣 quota,下次仍可重試"""
    from src.alerts import alert_router, deduplication
    alert = {"symbol": "NVDA", "signal_type": "sell_call",
             "alert_level": "green", "message": "hi"}
    with patch("src.alerts.alert_router.send_telegram", return_value=False):
        ok = alert_router.route_alert(alert)
    assert ok is False
    assert deduplication.is_duplicate(alert) is False
