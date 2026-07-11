"""股癌 Podcast Digest 設定集中地(gooaye-digest)。

放:RSS URL、上限常數、Gemini 兩段 prompt 模板、ticker 詞庫 builder。
純加法,不依賴交易監控既有行為;universe.py 只讀不改。
"""

from src.config import universe

# ============================================
# 來源 / 排程上限
# ============================================

# 股癌 (Gooaye 股癌,謝孟恭) SoundOn RSS feed
GOOAYE_RSS_URL = (
    "https://feeds.soundon.fm/podcasts/"
    "954689a5-3096-43a4-a80b-7810b219cef3.xml"
)

# 每次 run 最多處理幾集(紅線 §3:dedup 之外的新集上限)
MAX_EPISODES_PER_RUN = 2

# 首次執行(seen 空)只處理最新幾集,其餘整個 back catalog 標 seen 不轉(紅線 §6)
BOOTSTRAP_PROCESS_COUNT = 1

# seen 狀態檔(比照 trump_seen_posts.json / rss_seen.json 慣例,放 data_store/)
GOOAYE_SEEN_FILE = "gooaye_seen.json"

# 逐字稿輸出 token 上限:50 分鐘中文逐字稿很長,給大一點避免被截斷(§14 已知風險)。
# gemini-2.5-flash 支援的大輸出;若實測仍截斷 → §7.2 chunking fallback(TODO)。
TRANSCRIBE_MAX_OUTPUT_TOKENS = 65536

# 摘要輸出 token 上限(摘要短,給中等即可)
SUMMARIZE_MAX_OUTPUT_TOKENS = 8192

# ============================================
# Ticker 中文名詞庫(供逐字稿對齊拼寫)
# ============================================
# universe.py 只有美股代號(無中文名),這裡補一份「股癌常提標的」的中文名 map。
# 只收錄有把握的中文名;沒把握的留空,glossary 該行只出代號(避免餵錯名誤導辨識)。
# 此 map 為本功能私有,universe.py 不動(紅線 §8 純加法)。
TICKER_CN_NAMES = {
    # AI / 半導體
    "NVDA": "輝達 / Nvidia",
    "TSM": "台積電 / TSMC",
    "AVGO": "博通 / Broadcom",
    "MU": "美光 / Micron",
    "AMD": "超微 / AMD",
    "ASML": "艾司摩爾 / ASML",
    "QCOM": "高通 / Qualcomm",
    "INTC": "英特爾 / Intel",
    "ARM": "安謀 / Arm",
    "SMCI": "美超微 / Supermicro",
    "MRVL": "邁威爾 / Marvell",
    "AMAT": "應用材料 / Applied Materials",
    "LRCX": "科林研發 / Lam Research",
    "KLAC": "科磊 / KLA",
    "ANET": "Arista",
    "MELI": "MercadoLibre",
    # 雲端 / 軟體 / 大型科技
    "MSFT": "微軟 / Microsoft",
    "GOOG": "谷歌 / Alphabet",
    "GOOGL": "谷歌 / Alphabet",
    "META": "Meta / 臉書",
    "AMZN": "亞馬遜 / Amazon",
    "AAPL": "蘋果 / Apple",
    "ORCL": "甲骨文 / Oracle",
    "CRM": "Salesforce",
    "ADBE": "Adobe",
    "CRWD": "CrowdStrike",
    "NOW": "ServiceNow",
    "PLTR": "Palantir",
    # 工業 / 國防
    "CAT": "開拓重工 / Caterpillar",
    "LMT": "洛克希德馬丁 / Lockheed Martin",
    "RTX": "雷神 / RTX",
    "ETN": "伊頓 / Eaton",
    # 消費 / 零售
    "WMT": "沃爾瑪 / Walmart",
    "COST": "好市多 / Costco",
    "TSLA": "特斯拉 / Tesla",
    # 能源 / 核能 / 公用
    "XOM": "埃克森美孚 / ExxonMobil",
    "CVX": "雪佛龍 / Chevron",
    "VLO": "Valero",
    "CEG": "Constellation Energy",
    "VST": "Vistra",
    "NEE": "NextEra",
    "CCJ": "Cameco",
    "OKLO": "Oklo",
    # 金屬 / 礦業
    "FCX": "自由港 / Freeport-McMoRan",
    "MP": "MP Materials",
    "GLD": "黃金 ETF / GLD",
    # 常見 ETF
    "SPY": "標普 500 ETF / SPY",
    "QQQ": "那斯達克 100 ETF / QQQ",
    "VOO": "Vanguard 標普 500 / VOO",
    "SMH": "半導體 ETF / SMH",
    "SOXL": "半導體 3x ETF / SOXL",
}


def build_ticker_glossary() -> str:
    """從 universe.py 組『代號 — 中文名』多行字串,注入 TRANSCRIBE_PROMPT。

    來源:
      - universe.ALL_TICKERS_SCAN(~115 檔美股 + ETF)→ 代號,有中文名就附上
      - universe.TWSTOCK_CORE / TWSTOCK_ACTIVE_ETFS → 台股代號 + 中文名

    保序去重;沒中文名的標的只出代號(不硬編造)。
    """
    lines: list[str] = []
    seen: set[str] = set()

    def _add(symbol: str, name: str = "") -> None:
        if not symbol or symbol in seen:
            return
        seen.add(symbol)
        cn = name or TICKER_CN_NAMES.get(symbol, "")
        lines.append(f"- {symbol} — {cn}" if cn else f"- {symbol}")

    # 美股 + ETF
    for sym in universe.ALL_TICKERS_SCAN:
        _add(sym)

    # 台股(universe 自帶中文名)
    for sym in universe.TWSTOCK_CORE:
        _add(sym)
    for etf in universe.TWSTOCK_ACTIVE_ETFS:
        _add(etf.get("symbol", ""), etf.get("name", ""))

    return "\n".join(lines)


# ============================================
# Gemini Prompt 模板(設計決策,照抄精神;§7.2 / §7.3)
# ============================================

# 逐字稿:繁中、逐字、不摘要、餵詞庫。{ticker_glossary} 由 build_transcribe_prompt 注入。
TRANSCRIBE_PROMPT = """你是專業逐字稿員。請把這集中文 podcast 完整轉成逐字稿。
要求:
- 一律輸出繁體中文(台灣用語)。
- 逐字、完整,不要摘要、不要省略、不要改寫。
- 中英夾雜照原樣(如 Fed、FOMC、guidance 等英文詞保留)。
- 股票代號與公司名請盡量正確;以下是可能出現的標的詞庫供你對齊拼寫:
{ticker_glossary}
- 開頭的廠商業配 / 廣告段落可標記 [業配] 但仍照錄。
只輸出逐字稿本文,不要前言或結語。"""

# 摘要:吃純文字逐字稿,輸出結構化 Markdown。
SUMMARIZE_PROMPT = """以下是股癌 podcast 某集的逐字稿。請產出結構化摘要,繁體中文。
請輸出以下區塊(用 Markdown):

## 一句話總結
(這集主軸)

## 提到的產業 / 主題
- 逐點,每點註明他的看法傾向(看多 / 看空 / 中性 / 觀察)

## 提到的個股 / 標的
- 代號 + 名稱 + 他講了什麼(含任何進出、加減碼、價位、理由)
- 沒明確代號的就寫名稱

## 核心觀點 / 可操作重點
- 他這集真正想傳達的判斷,挑 3–6 點

## 風險 / 反指標提醒
- 他有沒有提到要小心的東西

只根據逐字稿內容,不要自行補充逐字稿沒講的資訊。逐字稿若辨識有誤導致代號存疑,標註(待確認)。

逐字稿如下:
---
{transcript}"""


def build_transcribe_prompt() -> str:
    """注入 ticker 詞庫,回傳完整逐字稿 prompt。"""
    return TRANSCRIBE_PROMPT.format(ticker_glossary=build_ticker_glossary())


def build_summarize_prompt(transcript: str) -> str:
    """注入逐字稿,回傳完整摘要 prompt。"""
    return SUMMARIZE_PROMPT.format(transcript=transcript)
