# Context: 資料來源（Data Sources）

> 來源：`src/data/*.py`、`src/config/rss_sources.py`、`src/config/settings.py`（已實際讀檔查證）。
> 設計原則：**失敗不阻塞**（單一來源失敗回 `None` / 空，不讓整個 scan 崩）、**不偽造中性值**（抓不到就 None，不假裝 0 / 正常）、**全部走免費源**以維持 $0/月。

## 1. 所需金鑰 / Secrets（名稱固定，不得更名）

| Secret / Env | 用途 | 缺少時行為 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram 推播 | 無法推播（`TelegramNotifier` raise）|
| `TELEGRAM_CHAT_ID` | 收件 chat（逗號分隔可多人）| 同上 |
| `FRED_API_KEY` | FRED 宏觀資料 | `fred_api.get_fred_client()` raise（不 fallback 假資料）|
| `SEC_EDGAR_USER_AGENT` | SEC EDGAR 請求識別 | raise（避免無 identity 被 SEC IP ban）|

純環境變數（非 secret，有預設值）：`POSITION_MODE`(預設 `mode_2`)、`ENVIRONMENT`(預設 `production`)、`LOG_LEVEL`(預設 `INFO`)。

> 設定教學：`docs/github_secrets_setup.md`、`docs/telegram_bot_setup.md`。**這些名稱是紅線，不得重命名或新增。**

## 2. 資料源總表（22 個模組）

| 模組 | 抓什麼 | 外部來源 | 需金鑰 |
|---|---|---|---|
| `price_data.py` | 歷史價、即時報價、選擇權鏈 | yfinance (Yahoo) | — |
| `iv_rank.py` | ATM IV、IVR / IVP（維護 300 日歷史）| yfinance 選擇權鏈 | — |
| `greeks_calculator.py` | Black-Scholes Delta/Gamma/Theta/Vega | 無（純計算）| — |
| `earnings_calendar.py` | 下次財報日 | yfinance.calendar | — |
| `fundamentals.py` | P/E、PEG、FCF Yield、margins、EPS 連衰偵測 | yfinance.info | — |
| `analyst_actions.py` | 分析師升降評（7 日）| yfinance.upgrades_downgrades | — |
| `fred_api.py` | 殖利率(10Y/2Y/3M)、HY/IG 利差、DXY、VIX、CPI、GDP… | FRED (fred.stlouisfed.org) | `FRED_API_KEY` |
| `sec_edgar.py` | 8-K filings（依 Item 分優先級）| SEC EDGAR (edgartools) | `SEC_EDGAR_USER_AGENT` |
| `form4_insider.py` | Form 4 內部人交易、cluster buying、CEO/CFO 大額買 | SEC EDGAR (edgartools) | `SEC_EDGAR_USER_AGENT` |
| `institutional_holdings.py` | 13F 機構持股變化（12 家機構）| SEC EDGAR 13F-HR | `SEC_EDGAR_USER_AGENT` |
| `trump_truth.py` | Trump Truth Social 貼文（主：CNN 鏡像 JSON，備：Truth API）| CNN mirror / Truth Social | — |
| `rss_feeds.py` | Reuters / AP / Fed 新聞（關鍵字過濾）| RSS endpoints | — |
| `breadth_data.py` | 市場廣度（$SPXA50R/$SPXA200R/$NYHL/$NYAD）| StockCharts (scraping) | — |
| `bubble_indicators.py` | Buffett Indicator / Shiller CAPE / 集中度 | currentmarketvaluation / multpl / slickcharts | — |
| `put_call_ratio.py` | PCR（主 CBOE 未實作，備 yfinance ^CPC）| CBOE / yfinance | — |
| `vix_structure.py` | VIX / VIX9D / VIX3M 結構與倒掛 | yfinance VIX 指數 | — |
| `tsmc_revenue.py` | TSMC(2330) 月營收 + YoY | MOPS 公開資訊觀測站 (HTML, big5) | — |
| `etf_flows.py` | SMH/QQQ/SPY 資金流（Phase 2 走 cache fallback）| etfdb (scraping) / cache | — |
| `etf_liquidity.py` | ETF 選擇權流動性分級（openInterest 遲滯）| yfinance 選擇權鏈 | — |
| `value_thesis.py` | 讀 value_thesis 評級（無外部抓取）| `data_store/universe_with_thesis.json` | — |
| `twstock_data.py` | 台股價量（.TW）| yfinance（主）+ twstock 套件（備）| — |
| `twstock_active_etf.py` | 台股主動 ETF 持股（6 檔）| TWSE OpenAPI | — |

> `src/data/__init__.py` 為空檔（正常）。

## 3. 來源穩定性筆記（給 AI 排查用）

- **scraping 類**（StockCharts、bubble 指標、etfdb、MOPS）最脆弱，網站改版即失效；模組設計為失敗回 None。排查推播缺值時優先看這幾類。
- **IVR 需累積**：`iv_rank` 樣本 < 30 天回 `None` → 訊號的 IVR 條件以動態 conditions_total 處理（不算未達）。`iv_history.json` 由 `run_iv_history_update` 每日累積（見 `contexts/github-actions.md`）。
- **SEC 類**共用 `SEC_EDGAR_USER_AGENT`；未設會 raise，這是刻意的（避免 IP ban）。
- 真實外部 URL / series id / 機構 CIK 等定義在 `src/config/rss_sources.py`、`fred_api.py: FRED_SERIES`、`src/config/institutions.py`。要查確切值讀那些檔，不要憑記憶。

## 4. 紅線

- 不改資料抓取邏輯（屬 trading logic）；不改 secrets 名稱。
- 不把「抓不到 → 用假中性值頂替」當修法（違反既有「不偽造中性值」原則）。
- 新增資料源若需付費 / 額度受限 API → 先問使用者（見 `AGENTS.md` §4.7）。
