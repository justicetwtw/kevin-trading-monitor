"""Dashboard 建置測試:schema、score table 完整性、smoke、no-secret-in-output。

全部離線:dashboard_store 只讀 repo 內 data_store/,build 不打網路。
"""

import json
import re

from src.dashboard.build_dashboard import build_all, build_payloads
from src.models.signal_schema import (
    ENVELOPE_SPEC, SCORE_WEIGHTS, action_band_for, validate_record,
    validate_watchlist_row,
)
from src.storage import dashboard_store


def test_score_weights_sum_to_100():
    assert sum(SCORE_WEIGHTS.values()) == 100
    assert SCORE_WEIGHTS == {
        "fundamental_catalyst": 35,
        "trend_momentum": 20,
        "options_flow": 20,
        "valuation_expectation": 10,
        "risk_macro_geopolitical": 15,
    }


def test_action_band_mapping():
    assert action_band_for(None) is None
    assert action_band_for(85) == "core_long"
    assert action_band_for(70) == "hold_no_chase"
    assert action_band_for(55) == "watch_deleverage"
    assert action_band_for(40) == "tactical_only"
    assert action_band_for(10) == "exit_or_avoid"


def test_watchlist_score_table_field_completeness():
    payload = dashboard_store.build_watchlist_scores()
    rows = payload["data"]["rows"]
    assert rows, "watchlist 不應為空"
    for row in rows:
        assert validate_watchlist_row(row) == []
        # 分數只是決策輔助,不是下單訊號
        assert row["not_a_trade_signal"] is True
        # pillar 未齊時 total 必須是 None(不用假設值補分)
        scored = [p for p in row["pillars"].values() if p["score"] is not None]
        if len(scored) < len(SCORE_WEIGHTS):
            assert row["total_score"] is None
            assert row["action_band"] is None
        assert 0 <= row["coverage"] <= 1


def test_all_payloads_pass_schema():
    payloads = build_payloads()  # 內部 schema 驗證失敗會 raise
    assert set(payloads) == {
        "regime", "watchlist_scores", "options_flow",
        "leaps_exposure", "events", "decision_log",
    }
    for name, payload in payloads.items():
        assert validate_record(payload, ENVELOPE_SPEC, name) == []


def test_regime_payload_has_taiwan_placeholder():
    payload = dashboard_store.build_regime_payload()
    geo = payload["data"]["taiwan_geopolitical"]
    # Phase 1 沒有資料來源,不得亂填 1-10 分級
    assert geo["level"] is None
    assert geo["status"] == "not_implemented_phase_1"


def test_build_dashboard_smoke(tmp_path):
    out = tmp_path / "dashboard"
    build_all(out)

    index = out / "index.html"
    assert index.exists()
    html_text = index.read_text(encoding="utf-8")
    for anchor in ("Regime Overview", "Watchlist Score Table",
                   "Options / Flow", "LEAPS Exposure", "Event Monitor",
                   "Taiwan / Geopolitical", "Backtest / EV",
                   "Decision Log"):
        assert anchor in html_text, f"index.html 缺區塊: {anchor}"

    for name in ("regime", "watchlist_scores", "options_flow",
                 "leaps_exposure", "events", "decision_log"):
        p = out / "data" / f"{name}.json"
        assert p.exists(), f"缺 {p}"
        payload = json.loads(p.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
        assert payload["generated_at"]


def test_no_secret_in_output(tmp_path, monkeypatch):
    """輸出檔案不得含任何 secret 值或 token 樣式字串。"""
    sentinels = {
        "TELEGRAM_BOT_TOKEN": "1234567890:AAtestSENTINELtokenvalue_do_not_leak00",
        "TELEGRAM_CHAT_ID": "-100987654321sentinel",
        "FRED_API_KEY": "fredsentinelapikey0123456789abcdef",
        "SEC_EDGAR_USER_AGENT": "Sentinel Name sentinel@example.com",
        "ORATS_API_KEY": "orats-sentinel-key-000",
        "POLYGON_API_KEY": "polygon-sentinel-key-000",
        "TRADIER_ACCESS_TOKEN": "tradier-sentinel-token-000",
    }
    for k, v in sentinels.items():
        monkeypatch.setenv(k, v)

    out = tmp_path / "dashboard"
    build_all(out)

    telegram_token_pattern = re.compile(r"\d{8,10}:[A-Za-z0-9_-]{30,}")
    for path in out.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for name, value in sentinels.items():
            assert value not in text, f"{path.name} 洩漏 {name}"
        assert not telegram_token_pattern.search(text), (
            f"{path.name} 含 telegram token 樣式字串"
        )
