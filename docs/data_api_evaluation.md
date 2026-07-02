# Options / Market Data API 評估 v0.1

建立日期:2026-07-02
目的:評估 Kevin Smart Alpha Hybrid Dashboard 的資料來源,特別是 options / volatility / flow 層(IV rank、skew、OI concentration、unusual option activity、gamma wall、synthetic short 警訊)。
結論先講:**第一階段不新增任何 paid API key**;先把 adapter interface 做好(`src/data/options_provider.py`),等真的要接再採購。

---

## 1. Free / existing layer(現況已使用或零成本可用)

| 來源 | 提供 | 現有使用點 | 限制 |
|---|---|---|---|
| **yfinance** | 價格、volume、OHLC、簡易 option chain(IV、OI 快照) | `src/data/price_data.py`、`src/data/iv_rank.py`(ATM IV → 自建 252 日 IV history) | 非官方 API,option 資料延遲且欄位不穩;無歷史 options 資料、無 skew 時序 |
| **FRED** | 利率、殖利率曲線、HY OAS、宏觀 | `src/data/fred_api.py`(`FRED_API_KEY`) | 無個股資料 |
| **SEC EDGAR** | 8-K、13F、Form 4、buyback | `src/data/sec_edgar.py`、`form4_insider.py`、`institutional_holdings.py`(`SEC_EDGAR_USER_AGENT`) | 13F 延遲 45 天;需自行解析 |
| **Cboe public data** | 市場層級 put/call ratio、volume、歷史 options volume | `src/data/put_call_ratio.py` | 市場層級,無個股 skew / OI 分佈 |
| **RSS / official filings / company IR** | 新聞、政策、財報事件 | `src/data/rss_feeds.py`、`trump_truth.py`、`earnings_calendar.py` | 需分類降噪(已有 news_classifier) |
| **TSMC 月營收 / 台股公開資訊** | 台股基本面與籌碼 | `src/data/tsmc_revenue.py`、`twstock_data.py` | 台股 options 資料不在範圍 |

**Free layer 能撐起**:regime overview、fundamental pillar、IVR/IVP(自建歷史)、市場 P/C、VIX 結構、事件監控。
**Free layer 撐不起**:個股 put skew 時序、OI concentration / gamma wall、unusual option activity、opening vs closing、深 ITM call 賣出 / synthetic short 偵測、歷史 options 回測資料。這些是付費層的採購理由。

---

## 2. Paid options layer 候選

### 2.1 ORATS — 優先候選

- **提供**:IV rank、skew(含時序)、historical options data、near-EOD options history、proprietary indicators(smoothed IV、earnings effect 等)。
- **為什麼適合**:Kevin 的決策節奏是 EOD / swing / LEAPS,不是 intraday tick;ORATS 的 near-EOD 精度與 20+ 年歷史正好覆蓋「IV rank / skew / 回測」需求,API 對 Python 友善。
- **定位**:第一個真正要買的 options 資料源。
- **Secret 名稱(屆時)**:`ORATS_API_KEY`。

### 2.2 Massive(前 Polygon.io)— 第二候選

- **提供**:options chain snapshot、trades、quotes、greeks、IV、OI;WebSocket / REST 工程整合成熟。
- **為什麼是第二**:偏 intraday / tick 級,適合未來要做盤中 flow dashboard 或 UOA 即時偵測時再上;研究型歷史指標(skew rank 等)不如 ORATS 現成。
- **Secret 名稱(屆時)**:`POLYGON_API_KEY`(沿用 `docs/codex_environment.md` 已預留的命名;若官方 SDK 改用 Massive 命名,以 repo AGENTS.md 更新為準)。

### 2.3 Tradier — 輕量候選

- **提供**:options chain + greeks(broker API 附帶)。
- **定位**:輕量 chain 查詢 / 驗價用,不是完整研究資料源;無深度歷史。若未來以 Tradier 做 broker,可順帶用。
- **Secret 名稱(屆時)**:`TRADIER_ACCESS_TOKEN`。

### 2.4 Cboe DataShop / LiveVol / OptionMetrics — institutional / future research

- 資料品質最高(學術級、逐筆),但價格與交付方式(bulk file、機構授權)不符合「零月費、個人使用」現況。列為未來研究選項,**不作為第一階段必要採購**。

---

## 3. 結論與第一階段做法

1. **第一階段不新增 paid API key**。免費層已足夠支撐 dashboard MVP 的所有 Phase 1 欄位。
2. **先把 adapter interface 做好**(本 PR 已建立):
   - `src/data/options_provider.py` — `OptionsProvider` 抽象介面 + 統一輸出 schema(IV metrics / options snapshot),`YFinanceOptionsProvider` 為免費預設實作。
   - `src/data/options_orats.py` — ORATS stub(未實作,宣告 `SECRET_NAME = "ORATS_API_KEY"`)。
   - `src/data/options_massive.py` — Massive/Polygon stub(`SECRET_NAME = "POLYGON_API_KEY"`)。
   - `src/data/options_tradier.py` — Tradier stub(`SECRET_NAME = "TRADIER_ACCESS_TOKEN"`)。
3. **Secret 紀律**(與 AGENTS.md 一致):
   - stub 只宣告 secret「名稱」,不接收、不保存、不輸出實際值;在程式碼真的實作 API 呼叫之前,**不要**在 GitHub 加任何對應 secret。
   - 所有 secret 只允許透過 GitHub Actions secrets 注入(`${{ secrets.NAME }}`),不得寫入 repo,不得建立 `.env`。
   - 新增 secret 時同步更新 `AGENTS.md` 與 `docs/codex_environment.md` 的 secrets 現況表。
4. **採購觸發條件**(何時值得付錢):
   - Watchlist options pillar 因缺 skew / OI 長期只能 display-only,且實戰上多次因看不到 put skew / UOA 而誤判 →先訂 ORATS 入門方案。
   - 要做盤中 flow dashboard 或即時 UOA → 再評估 Massive。
5. **接入方式**:實作對應 `options_*.py` → `get_provider()` 依環境變數選擇 provider → dashboard 欄位(put_skew / oi_concentration / unusual_activity)自動填充,schema 不變。
