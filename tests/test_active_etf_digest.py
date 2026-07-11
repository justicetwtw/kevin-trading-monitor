"""主動式 ETF 經理人共識 digest 測試(全 mock:不打網路、不寄信、不寫真 data_store)。"""

from unittest.mock import MagicMock, patch

import pytest

from src.config import active_etf_config as cfg
from src.twstock import active_etf_consensus as cons
from src.twstock import active_etf_digest as dig


# ============================================================
# config helpers
# ============================================================

@pytest.mark.parametrize("code,market", [
    ("2330", "tw"), ("0050", "tw"), ("00981A", "tw"),
    ("NVDA", "overseas"), ("TSLA", "overseas"), ("", "unknown"),
])
def test_classify_holding_market(code, market):
    assert cfg.classify_holding_market(code) == market


def test_history_retention_covers_long_window():
    assert cfg.HOLDINGS_HISTORY_DAYS >= cfg.LONG_WINDOW_DAYS


# ============================================================
# fund_holding_changes (純函式)
# ============================================================

def _hold(sym, w, name="", market="tw"):
    return {"symbol": sym, "name": name, "weight_pct": w, "market": market}


def test_fund_holding_changes_basic():
    fh = {
        "2026-06-01": [_hold("2330", 10.0, "台積電"), _hold("2454", 5.0, "聯發科")],
        "2026-06-12": [_hold("2330", 12.0, "台積電"), _hold("2454", 4.9, "聯發科")],
    }
    ch = cons.fund_holding_changes(fh, lookback_days=7, min_delta_pp=0.3)
    assert "2330" in ch and abs(ch["2330"]["delta_pp"] - 2.0) < 1e-9
    assert "2454" not in ch  # -0.1 < 0.3 門檻


def test_fund_holding_changes_needs_two_dates():
    fh = {"2026-06-12": [_hold("2330", 12.0)]}
    assert cons.fund_holding_changes(fh, 7, 0.3) == {}


def test_fund_holding_changes_no_baseline_within_window():
    # 兩個日期只差 2 天,lookback 7 → 找不到基準日
    fh = {
        "2026-06-10": [_hold("2330", 10.0)],
        "2026-06-12": [_hold("2330", 13.0)],
    }
    assert cons.fund_holding_changes(fh, 7, 0.3) == {}


# ============================================================
# build_consensus / rank / highlights (純函式)
# ============================================================

def _funds(*syms):
    return [{"symbol": s, "name": f"基金{s}", "market": "tw"} for s in syms]


def _two_day(sym, old_w, new_w, name="", market="tw"):
    return {
        "2026-06-01": [_hold(sym, old_w, name, market)],
        "2026-06-12": [_hold(sym, new_w, name, market)],
    }


def test_build_consensus_aggregates_across_funds():
    funds = _funds("F1", "F2", "F3")
    history = {
        "F1": _two_day("2330", 10.0, 12.0, "台積電"),
        "F2": _two_day("2330", 8.0, 9.5, "台積電"),
        "F3": _two_day("2330", 5.0, 5.6, "台積電"),
    }
    c = cons.build_consensus(history, funds, lookback_days=7, min_delta_pp=0.3)
    assert c["2330"]["n_increased"] == 3
    assert c["2330"]["n_decreased"] == 0
    assert abs(c["2330"]["net_delta_pp"] - (2.0 + 1.5 + 0.6)) < 1e-9
    assert len(c["2330"]["funds_increased"]) == 3


def test_build_consensus_ignores_unconfigured_funds():
    funds = _funds("F1")
    history = {
        "F1": _two_day("2330", 10.0, 12.0),
        "FX": _two_day("2330", 1.0, 9.0),  # 不在 funds 清單 → 忽略
    }
    c = cons.build_consensus(history, funds, lookback_days=7, min_delta_pp=0.3)
    assert c["2330"]["n_increased"] == 1


def test_build_consensus_increase_and_decrease():
    funds = _funds("F1", "F2")
    history = {
        "F1": _two_day("2454", 10.0, 12.0),   # +2
        "F2": _two_day("2454", 10.0, 7.0),    # -3
    }
    c = cons.build_consensus(history, funds, lookback_days=7, min_delta_pp=0.3)
    assert c["2454"]["n_increased"] == 1
    assert c["2454"]["n_decreased"] == 1


def test_rank_consensus_orders_and_caps():
    consensus = {
        "A": {"name": "", "market": "tw", "n_increased": 3, "n_decreased": 0,
              "net_delta_pp": 1.0, "funds_increased": [], "funds_decreased": []},
        "B": {"name": "", "market": "tw", "n_increased": 1, "n_decreased": 0,
              "net_delta_pp": 5.0, "funds_increased": [], "funds_decreased": []},
        "C": {"name": "", "market": "tw", "n_increased": 0, "n_decreased": 2,
              "net_delta_pp": -3.0, "funds_increased": [], "funds_decreased": []},
    }
    r = cons.rank_consensus(consensus, top_n=10)
    assert [i["symbol"] for i in r["top_buys"]] == ["A", "B"]  # A(3 funds) > B(1 fund)
    assert [i["symbol"] for i in r["top_sells"]] == ["C"]
    # top_n cap
    assert len(cons.rank_consensus(consensus, top_n=1)["top_buys"]) == 1


# ============================================================
# fetch_fund_holdings (provider dispatch)
# ============================================================

def test_fetch_fund_holdings_tw_tags_and_dedupes(monkeypatch):
    monkeypatch.setattr(cons, "_fetch_tw", lambda sym: [
        {"symbol": "2330", "name": "台積電", "weight_pct": 10, "shares": 1000},
        {"symbol": "2330", "name": "台積電", "weight_pct": 10.5, "shares": 1100},  # dup
    ])
    monkeypatch.setattr(cons, "_fetch_overseas", lambda fund: [])
    out = cons.fetch_fund_holdings({"symbol": "00981A.TW", "market": "tw"})
    assert len(out) == 1
    assert out[0]["market"] == "tw"


def test_fetch_fund_holdings_mixed_combines_markets(monkeypatch):
    monkeypatch.setattr(cons, "_fetch_tw", lambda sym: [
        {"symbol": "2330", "name": "台積電", "weight_pct": 8},
    ])
    monkeypatch.setattr(cons, "_fetch_overseas", lambda fund: [
        {"symbol": "NVDA", "name": "輝達", "weight_pct": 6},
    ])
    out = cons.fetch_fund_holdings({"symbol": "00988A.TW", "market": "mixed"})
    markets = {h["symbol"]: h["market"] for h in out}
    assert markets == {"2330": "tw", "NVDA": "overseas"}


def test_fetch_overseas_is_safe_stub():
    # 海外資料源待探針:必須安全回 [],不得拋例外
    assert cons._fetch_overseas({"symbol": "00990A.TW"}) == []


# ============================================================
# update_holdings (in-memory state)
# ============================================================

def test_update_holdings_writes_snapshot(monkeypatch):
    store = {}
    monkeypatch.setattr(cons, "read_json", lambda f, default=None: store.get(f, default if default is not None else {}))
    monkeypatch.setattr(cons, "write_json", lambda f, d, indent=2: store.__setitem__(f, d) or True)
    monkeypatch.setattr(cons, "fetch_fund_holdings",
                        lambda fund: [_hold("2330", 10.0, "台積電")])

    funds = [{"symbol": "F1.TW", "name": "基金1", "market": "tw"}]
    hist = cons.update_holdings(funds)
    assert "F1.TW" in hist
    # 當日 key 存在且含持股
    (date_key, holdings), = hist["F1.TW"].items()
    assert holdings[0]["symbol"] == "2330"


# ============================================================
# render (純函式)
# ============================================================

def _consensus_fixture():
    mk = lambda fund: {"fund": fund, "fund_name": f"基金{fund}", "delta_pp": 1.0}
    return {
        "2330": {"name": "台積電", "market": "tw", "n_increased": 3, "n_decreased": 0,
                 "net_delta_pp": 4.0,
                 "funds_increased": [mk("A"), mk("B"), mk("C")], "funds_decreased": []},
        "NVDA": {"name": "輝達", "market": "overseas", "n_increased": 2, "n_decreased": 0,
                 "net_delta_pp": 2.5,
                 "funds_increased": [mk("A"), mk("B")], "funds_decreased": []},
        "2454": {"name": "聯發科", "market": "tw", "n_increased": 0, "n_decreased": 2,
                 "net_delta_pp": -3.0,
                 "funds_increased": [], "funds_decreased": [mk("A"), mk("B")]},
    }


def test_render_digest_markdown_sections():
    md = dig.render_digest_markdown(_consensus_fixture(), {}, "2026-06-22")
    assert "主動 ETF 經理人共識 — 2026-06-22" in md
    assert "🔥 短期共識" in md          # 2330 被 3 位 ≥ 門檻
    assert "🇹🇼 台股加碼榜" in md
    assert "🌎 海外加碼榜" in md and "NVDA" in md
    assert "台股減碼榜" in md and "2454" in md


def test_render_digest_markdown_empty_returns_blank():
    assert dig.render_digest_markdown({}, {}, "2026-06-22") == ""


# ============================================================
# email
# ============================================================

def test_send_digest_email_missing_config_returns_false(monkeypatch):
    monkeypatch.setattr(dig, "GMAIL_SENDER", "")
    monkeypatch.setattr(dig, "GMAIL_APP_PASSWORD", "")
    monkeypatch.setattr(dig, "EMAIL_RECIPIENT", "")
    assert dig.send_digest_email("# x", "2026-06-22") is False


def test_send_digest_email_success(monkeypatch):
    monkeypatch.setattr(dig, "GMAIL_SENDER", "bot@gmail.com")
    monkeypatch.setattr(dig, "GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setattr(dig, "EMAIL_RECIPIENT", "kevin@gmail.com")
    server = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=server)
    cm.__exit__ = MagicMock(return_value=None)
    with patch("src.twstock.active_etf_digest.smtplib.SMTP_SSL", return_value=cm):
        ok = dig.send_digest_email("## 共識\n- **2330** 台積電", "2026-06-22")
    assert ok is True
    assert server.send_message.called
    # app password 去空格
    assert server.login.call_args[0][1] == "abcdefghijklmnop"


# ============================================================
# run() 串接
# ============================================================

def test_run_noop_when_no_history(monkeypatch):
    monkeypatch.setattr(dig, "update_holdings", lambda: {})
    monkeypatch.setattr(dig, "read_json", lambda f, default=None: {})
    sent = []
    monkeypatch.setattr(dig, "send_digest_email", lambda md, d: sent.append(md) or True)
    assert dig.run() == 0
    assert sent == []  # 無資料不寄


def test_run_sends_when_consensus(monkeypatch):
    history = {
        "00981A.TW": _two_day("2330", 10.0, 13.0, "台積電"),
        "00982A.TW": _two_day("2330", 8.0, 10.0, "台積電"),
        "00992A.TW": _two_day("2330", 5.0, 6.0, "台積電"),
    }
    monkeypatch.setattr(dig, "update_holdings", lambda: history)
    monkeypatch.setattr(dig, "read_json", lambda f, default=None: history)
    sent = []
    monkeypatch.setattr(dig, "send_digest_email", lambda md, d: sent.append(md) or True)
    rc = dig.run()
    assert rc == 0
    assert len(sent) == 1
    assert "2330" in sent[0]
