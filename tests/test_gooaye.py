"""股癌 digest 單元測試:feed 解析 / dedup / bootstrap / email compose / pipeline。

全 mock 網路與 Gemini API:不打外部、不寄真信、不寫真 data_store。
"""

from unittest.mock import MagicMock, patch

import pytest

from src.gooaye import feed as feed_mod
from src.gooaye import emailer
from src.config import gooaye_config


# ============================================================
# 共用:假 RSS XML(SoundOn / 標準 podcast RSS 結構)
# ============================================================

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
  <title>Gooaye 股癌</title>
  <item>
    <title>EP100 最新一集</title>
    <guid isPermaLink="false">guid-100</guid>
    <pubDate>Mon, 22 Jun 2026 01:00:00 GMT</pubDate>
    <enclosure url="https://rec.soundon.fm/ep100.mp3" type="audio/mpeg" length="48000000"/>
    <itunes:duration>50:12</itunes:duration>
  </item>
  <item>
    <title>EP099 前一集</title>
    <guid isPermaLink="false">guid-099</guid>
    <pubDate>Fri, 19 Jun 2026 01:00:00 GMT</pubDate>
    <enclosure url="https://rec.soundon.fm/ep099.mp3" type="audio/mpeg" length="47000000"/>
    <itunes:duration>2820</itunes:duration>
  </item>
  <item>
    <title>EP098</title>
    <guid isPermaLink="false">guid-098</guid>
    <pubDate>Sun, 15 Jun 2026 01:00:00 GMT</pubDate>
    <enclosure url="https://rec.soundon.fm/ep098.mp3" type="audio/mpeg" length="46000000"/>
    <itunes:duration>00:45:00</itunes:duration>
  </item>
</channel>
</rss>
"""


def _patch_feed_httpx(text=SAMPLE_RSS, raise_exc=None):
    """patch src.gooaye.feed.httpx.Client → 回傳含 SAMPLE_RSS 的假 client。"""
    mock_resp = MagicMock()
    mock_resp.text = text
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    if raise_exc is not None:
        mock_client.get = MagicMock(side_effect=raise_exc)
    else:
        mock_client.get = MagicMock(return_value=mock_resp)

    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_client)
    cm.__exit__ = MagicMock(return_value=None)
    return patch("src.gooaye.feed.httpx.Client", return_value=cm)


# ============================================================
# feed 解析
# ============================================================

def test_fetch_feed_parses_all_fields():
    with _patch_feed_httpx():
        eps = feed_mod.fetch_feed("http://fake")
    assert len(eps) == 3
    newest = eps[0]
    assert newest["guid"] == "guid-100"
    assert newest["title"] == "EP100 最新一集"
    assert newest["audio_url"] == "https://rec.soundon.fm/ep100.mp3"
    assert newest["duration_sec"] == 50 * 60 + 12  # "50:12"
    assert newest["published"]  # 有 pubDate


def test_fetch_feed_newest_first():
    with _patch_feed_httpx():
        eps = feed_mod.fetch_feed("http://fake")
    assert [e["guid"] for e in eps] == ["guid-100", "guid-099", "guid-098"]


def test_fetch_feed_network_failure_returns_empty():
    with _patch_feed_httpx(raise_exc=RuntimeError("boom")):
        eps = feed_mod.fetch_feed("http://fake")
    assert eps == []


def test_fetch_feed_skips_items_without_audio():
    bad_rss = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>no audio</title><guid>g1</guid></item>
</channel></rss>"""
    with _patch_feed_httpx(text=bad_rss):
        eps = feed_mod.fetch_feed("http://fake")
    assert eps == []


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("50:12", 3012),
        ("2820", 2820),
        ("00:45:00", 2700),
        ("1:02:03", 3723),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_parse_duration(raw, expected):
    assert feed_mod._parse_duration(raw) == expected


# ============================================================
# dedup / bootstrap (filter_unseen,純函式)
# ============================================================

def _episodes():
    return [
        {"guid": "g100", "title": "EP100"},
        {"guid": "g099", "title": "EP099"},
        {"guid": "g098", "title": "EP098"},
    ]


def test_filter_unseen_bootstrap_processes_only_newest():
    eps = _episodes()
    to_process, to_mark = feed_mod.filter_unseen(
        eps, seen_guids=set(), max_n=1, is_bootstrap=True
    )
    # 只處理最新 1 集
    assert [e["guid"] for e in to_process] == ["g100"]
    # 其餘 back catalog 立即標 seen
    assert to_mark == {"g099", "g098"}


def test_filter_unseen_normal_caps_to_max_n():
    eps = _episodes()
    to_process, to_mark = feed_mod.filter_unseen(
        eps, seen_guids=set(), max_n=2, is_bootstrap=False
    )
    assert [e["guid"] for e in to_process] == ["g100", "g099"]
    # 一般模式不立即標 seen(超過上限的留待下次)
    assert to_mark == set()


def test_filter_unseen_excludes_already_seen():
    eps = _episodes()
    to_process, to_mark = feed_mod.filter_unseen(
        eps, seen_guids={"g100", "g099"}, max_n=2, is_bootstrap=False
    )
    assert [e["guid"] for e in to_process] == ["g098"]
    assert to_mark == set()


def test_filter_unseen_normal_all_seen_is_noop():
    eps = _episodes()
    to_process, to_mark = feed_mod.filter_unseen(
        eps, seen_guids={"g100", "g099", "g098"}, max_n=2, is_bootstrap=False
    )
    assert to_process == []
    assert to_mark == set()


# ============================================================
# ticker 詞庫
# ============================================================

def test_build_ticker_glossary_has_symbols_and_cn_names():
    glossary = gooaye_config.build_ticker_glossary()
    assert "NVDA — 輝達 / Nvidia" in glossary
    assert "TSM — 台積電 / TSMC" in glossary
    # 台股(universe 自帶中文名)
    assert "2330.TW" in glossary
    # 每行一個標的
    assert glossary.count("\n") > 50


def test_transcribe_prompt_injects_glossary():
    prompt = gooaye_config.build_transcribe_prompt()
    assert "{ticker_glossary}" not in prompt  # 已被替換
    assert "NVDA" in prompt
    assert "逐字" in prompt


# ============================================================
# email compose
# ============================================================

def test_compose_message_structure():
    msg = emailer.compose_message(
        title="EP100 測試集",
        summary_md="## 一句話總結\n測試摘要\n\n## 提到的個股 / 標的\n- NVDA 輝達",
        transcript_md="這是逐字稿內容，含中文。",
        published="Mon, 22 Jun 2026 01:00:00 GMT",
        sender="bot@gmail.com",
        recipients=["kevin@gmail.com"],
    )
    assert msg["Subject"] == "[股癌] EP100 測試集"
    assert msg["From"] == "bot@gmail.com"
    assert msg["To"] == "kevin@gmail.com"

    # 應有 HTML alternative
    html_parts = [p for p in msg.walk()
                  if p.get_content_type() == "text/html"]
    assert html_parts, "缺 HTML 內文"
    html_body = html_parts[0].get_content()
    assert "<h2>" in html_body          # ## → h2
    assert "一句話總結" in html_body

    # 逐字稿應為 .md 附檔,且內容相符
    attachments = [p for p in msg.walk()
                   if p.get_filename()]
    assert len(attachments) == 1
    att = attachments[0]
    assert att.get_filename() == "EP100 測試集.md"
    assert "這是逐字稿內容" in att.get_content()


def test_compose_message_multi_recipient():
    msg = emailer.compose_message(
        title="t", summary_md="s", transcript_md="x", published="",
        sender="bot@gmail.com", recipients=["a@x.com", "b@y.com"],
    )
    assert msg["To"] == "a@x.com, b@y.com"


def test_markdown_to_html_basics():
    html = emailer.markdown_to_html("## 標題\n- 項目一\n- 項目二\n\n一般段落 **粗體**")
    assert "<h2>標題</h2>" in html
    assert "<ul>" in html and "<li>項目一</li>" in html
    assert "<strong>粗體</strong>" in html


def test_markdown_to_html_escapes_injection():
    html = emailer.markdown_to_html("一般 <script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.parametrize(
    "title,expected",
    [
        ("EP100 正常標題", "EP100 正常標題"),
        ("含/斜線:冒號*星號", "含_斜線_冒號_星號"),
        ("", "transcript"),
    ],
)
def test_safe_filename(title, expected):
    assert emailer._safe_filename(title) == expected


def test_send_digest_missing_config_returns_false(monkeypatch):
    monkeypatch.setattr(emailer, "GMAIL_SENDER", "")
    monkeypatch.setattr(emailer, "GMAIL_APP_PASSWORD", "")
    monkeypatch.setattr(emailer, "EMAIL_RECIPIENT", "")
    assert emailer.send_digest("t", "s", "x") is False


def test_send_digest_success_mocks_smtp(monkeypatch):
    monkeypatch.setattr(emailer, "GMAIL_SENDER", "bot@gmail.com")
    monkeypatch.setattr(emailer, "GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setattr(emailer, "EMAIL_RECIPIENT", "kevin@gmail.com")

    sent = {}
    mock_server = MagicMock()

    def _login(user, pw):
        sent["user"] = user
        sent["pw"] = pw

    mock_server.login = MagicMock(side_effect=_login)
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_server)
    cm.__exit__ = MagicMock(return_value=None)

    with patch("src.gooaye.emailer.smtplib.SMTP_SSL", return_value=cm):
        ok = emailer.send_digest("EP100", "## 摘要", "逐字稿", "2026")
    assert ok is True
    # app password 去空格
    assert sent["pw"] == "abcdefghijklmnop"
    assert mock_server.send_message.called


# ============================================================
# pipeline:dedup gate + bootstrap + 容錯(全 mock)
# ============================================================

@pytest.fixture
def mem_state(monkeypatch):
    """以記憶體 dict 取代 state_manager 的 read_json/write_json(不寫真 data_store)。"""
    from src.gooaye import pipeline as pl

    store: dict = {}

    def fake_read(filename, default=None):
        return store.get(filename, default if default is not None else {})

    def fake_write(filename, data, indent=2):
        # 深拷貝避免外部後續 mutate 影響已存值
        import copy
        store[filename] = copy.deepcopy(data)
        return True

    monkeypatch.setattr(pl, "read_json", fake_read)
    monkeypatch.setattr(pl, "write_json", fake_write)
    return store


def _patch_pipeline_io(monkeypatch, episodes, send_results=None):
    """patch pipeline 的 feed / 下載 / Gemini / email,回傳 send_digest 呼叫記錄。"""
    from src.gooaye import pipeline as pl

    monkeypatch.setattr(pl, "fetch_feed", lambda url: list(episodes))
    monkeypatch.setattr(pl, "_download_mp3", lambda url: "/tmp/fake_gooaye.mp3")
    monkeypatch.setattr(pl, "_cleanup", lambda path: None)
    monkeypatch.setattr(pl, "transcribe", lambda path: "逐字稿內容")
    monkeypatch.setattr(pl, "summarize", lambda t: "## 摘要")

    calls = []
    results = list(send_results) if send_results is not None else None

    def fake_send(title, summary_md, transcript_md, published=""):
        calls.append(title)
        if results is not None:
            return results.pop(0)
        return True

    monkeypatch.setattr(pl.emailer, "send_digest", fake_send)
    return calls


def test_pipeline_bootstrap_processes_one_marks_rest(monkeypatch, mem_state):
    from src.gooaye import pipeline as pl

    eps = [
        {"guid": "g100", "title": "EP100", "audio_url": "u", "published": ""},
        {"guid": "g099", "title": "EP099", "audio_url": "u", "published": ""},
        {"guid": "g098", "title": "EP098", "audio_url": "u", "published": ""},
    ]
    calls = _patch_pipeline_io(monkeypatch, eps)

    rc = pl.run()
    assert rc == 0
    # 只寄最新 1 集
    assert calls == ["EP100"]
    # 全部 guid 都進 seen(處理的 + back catalog)
    seen = mem_state[gooaye_config.GOOAYE_SEEN_FILE]
    assert set(seen.keys()) == {"g100", "g099", "g098"}


def test_pipeline_dedup_second_run_is_noop(monkeypatch, mem_state):
    from src.gooaye import pipeline as pl

    eps = [
        {"guid": "g100", "title": "EP100", "audio_url": "u", "published": ""},
        {"guid": "g099", "title": "EP099", "audio_url": "u", "published": ""},
    ]
    calls = _patch_pipeline_io(monkeypatch, eps)

    pl.run()                      # 首跑(bootstrap)→ 寄 1 集,全標 seen
    first_count = len(calls)
    pl.run()                      # 再跑 → 全 seen,no-op
    assert len(calls) == first_count  # 沒有再多寄


def test_pipeline_new_episode_after_bootstrap(monkeypatch, mem_state):
    from src.gooaye import pipeline as pl

    eps = [
        {"guid": "g100", "title": "EP100", "audio_url": "u", "published": ""},
        {"guid": "g099", "title": "EP099", "audio_url": "u", "published": ""},
    ]
    calls = _patch_pipeline_io(monkeypatch, eps)
    pl.run()  # bootstrap:寄 EP100,標 g100/g099

    # 新集上架
    eps.insert(0, {"guid": "g101", "title": "EP101", "audio_url": "u", "published": ""})
    pl.run()
    assert calls == ["EP100", "EP101"]


def test_pipeline_failed_episode_not_marked_seen(monkeypatch, mem_state):
    """非 bootstrap:2 集中 1 集寄信失敗 → 該集不標 seen,下次重試;run 回 1。"""
    from src.gooaye import pipeline as pl

    # 先放一個已 seen 讓 is_bootstrap=False
    mem_state[gooaye_config.GOOAYE_SEEN_FILE] = {"gold": {"seen_at": "x", "title": "old"}}

    eps = [
        {"guid": "g100", "title": "EP100", "audio_url": "u", "published": ""},
        {"guid": "g099", "title": "EP099", "audio_url": "u", "published": ""},
    ]
    # EP100 寄信成功、EP099 失敗
    calls = _patch_pipeline_io(monkeypatch, eps, send_results=[True, False])

    rc = pl.run()
    assert rc == 1  # 有集失敗
    seen = mem_state[gooaye_config.GOOAYE_SEEN_FILE]
    assert "g100" in seen       # 成功的標 seen
    assert "g099" not in seen   # 失敗的不標,下次重試
    assert calls == ["EP100", "EP099"]


def test_pipeline_empty_feed_is_noop(monkeypatch, mem_state):
    from src.gooaye import pipeline as pl
    _patch_pipeline_io(monkeypatch, [])
    assert pl.run() == 0
