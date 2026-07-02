# Kevin Smart Alpha Hybrid Dashboard — MVP 設計 v0.1

建立日期:2026-07-02
狀態:Phase 1 雛形(靜態 HTML / JSON,由 GitHub Actions 產生)
上游依據:`docs/strategy_v4.md`(策略 v5)、`docs/investment_context_v4_2.md`

---

## 1. Dashboard 目的

1. **Telegram 只推需要 Kevin 注意的訊號**:Red Alert / Market Brief / Noise Digest 三層,不把所有雜訊都推播到 Telegram。
2. **Dashboard 用於主動查看全貌**:regime、watchlist 分數、options/flow、LEAPS 曝險、事件、台海風險、回測、決策紀錄,全部保存在 dashboard,想看時再看。
3. **Repo 是 single source of truth**:dashboard 只是 `data_store/` 狀態與策略文件的「呈現層」,不產生新的策略真相。策略規則改動一律先改 repo 文件,dashboard 跟著呈現。
4. **不自動下單**:dashboard 上所有分數與訊號都是決策輔助,最終交易決策由 Kevin 做出。

核心哲學(與 strategy v5 一致):本系統不以 RSI/MACD/KD 等傳統技術指標作為 alpha 核心;技術指標只作 timing filter、風控輔助與 ATR 停損距離估算。核心是 regime、industry-first screening、fundamental catalyst、institution/ownership/flow、options/volatility/flow、risk engine 與 review loop。

---

## 2. Dashboard 頁面(Phase 1 為單頁八區塊,錨點導覽)

| # | 頁面 / 區塊 | Phase 1 狀態 |
|---|---|---|
| 1 | Regime Overview | ✅ 由既有 Layer 0 狀態產生 |
| 2 | Watchlist Score Table | ✅ 欄位齊備;部分 pillar 資料未接,標示 `no_data` / `planned` |
| 3 | Options / Flow Dashboard | ✅ IVR/IVP + 市場 P/C、VIX 結構;skew/OI/UOA 待付費資料 |
| 4 | LEAPS Exposure Dashboard | ✅ 部位結構 + DTE/roll 警示;delta/theta/vega 待接 live pricing |
| 5 | Event Monitor | ✅ alerts_log + 財報日曆 |
| 6 | Taiwan / Geopolitical Risk | 🔶 佔位:1–10 分級欄位已定,尚無資料來源 |
| 7 | Backtest / EV Tracker | 🔶 佔位:Phase 3(vectorbt)接入後填充 |
| 8 | Decision Log / Review Loop | ✅ schema 已定,`data_store/decision_log.json` 由 Kevin 手動維護 |

### 2.1 Regime Overview

回答一個問題:**現在能不能承擔風險?**

| 欄位 | 定義 | 資料來源 |
|---|---|---|
| `regime` | risk_on / neutral / risk_off(未來擴充 selective risk-on / geopolitical stress) | `data_store/layer_macro_regime_state.json` |
| `modifier` | Layer 0 聚合 modifier | 同上 |
| `indicators` | yield curve / HY OAS / DXY / VIX / copper-gold 各自 regime | 同上(FRED + yfinance,由既有 `macro_layer` workflow 更新) |
| `submodules` | breadth / distribution / bubble / put-call / VIX 結構 / AAII 各子模組 regime 與 modifier | `data_store/layer0_history.json` |
| `taiwan_geopolitical` | 台海風險 1–10 級(見 §2.6) | Phase 1 佔位 `null` |

### 2.2 Watchlist Score Table

每個核心標的以 100 分評估,權重與 `docs/strategy_v4.md` §8 一致:

| Pillar | 滿分 | Phase 1 資料來源 | Phase 1 狀態 |
|---|---|---|---|
| Fundamental / catalyst | 35 | `layer_fundamentals_dashboard_state.json`(營收/獲利成長、毛利率)→ heuristic v0 | ✅ heuristic_v0 |
| Trend / momentum | 20 | 3M/6M/12M 相對強度、MA 結構(需價格歷史) | 🔶 `planned_phase_1_1` |
| Options / flow | 20 | IVR/IVP(既有 `iv_history.json`);skew/OI/UOA 需付費資料 | 🔶 display-only,分數待資料補齊 |
| Valuation / expectation | 10 | forward P/E、PEG(fundamentals state)→ heuristic v0 | ✅ heuristic_v0 |
| Risk / macro / geopolitical | 15 | Layer 0 regime + 台海分級 | ✅ regime 部分;台海待接 |

規則:

- 任一 pillar 無資料 → 該 pillar `score = null` 並標示 `status`;`total_score` 只有在五個 pillar 都有分數時才計算,否則為 `null` 並回報 `coverage`(已覆蓋滿分比例)。**不用假設值補分。**
- `total_score` 存在時對應行動區間(80–100 核心多頭 / 65–79 持有不追高 / 50–64 觀察降槓桿 / 35–49 只做短線 / 0–34 出場或避開)。
- 每列固定帶 `not_a_trade_signal: true`:**這個分數不是自動下單訊號,只是防止情緒化判斷的決策輔助。**
- heuristic v0 的計分規則寫在 `src/storage/dashboard_store.py`,屬於佔位實作;正式 pillar 模型變更需依 AGENTS.md 紀律在文件標明日期、假設、失效條件。

### 2.3 Options / Flow Dashboard

| 欄位 | 定義 | Phase 1 來源 |
|---|---|---|
| `ivr` / `ivp` / `current_iv` / `samples` | IV rank / percentile(252 日) | `data_store/iv_history.json`(既有 `iv_history_update` workflow) |
| `put_call_market` | 市場層級 put/call | `data_store/layer_put_call_state.json`(Cboe public data) |
| `vix_structure` | VIX term structure 狀態 | `data_store/layer_vix_structure_state.json` |
| `put_skew` | put 是否快速變貴 | 🔶 `null`,需付費 options 資料 |
| `oi_concentration` | OI 是否集中關鍵 strike(gamma wall / 支撐壓力推斷) | 🔶 `null`,需付費 options 資料 |
| `unusual_activity` | UOA / opening vs closing / 深 ITM call 賣出 / synthetic short 警訊 | 🔶 `null`,需付費 options 資料 |

付費資料評估見 `docs/data_api_evaluation.md`;adapter interface 已就位(`src/data/options_provider.py`),接入後這些欄位直接填充,不改 dashboard schema。

### 2.4 LEAPS Exposure Dashboard

| 欄位 | 定義 | Phase 1 來源 |
|---|---|---|
| `symbol / strike / expiry / contracts / cost_per_contract` | 部位結構 | `data_store/positions.json`(過濾 `_example`) |
| `dte` | 距到期日數 | 由 expiry 計算 |
| `roll_warning` | DTE < 270 天(策略:剩 6–9 個月評估 roll) | 計算 |
| `delta / theta / vega / equivalent_exposure` | 等效現股曝險 = contracts × 100 × delta × 股價 | 🔶 `null`,`requires_live_pricing`(Phase 1.1 由 position_check 寫入 state) |
| `totals` | 合約數、成本總額(premium × 100 × contracts) | 計算 |

### 2.5 Event Monitor

| 欄位 | 定義 | 來源 |
|---|---|---|
| 歷史訊號 | 已路由的 alert(含未推播的 P2/P3) | `data_store/alerts_log.csv` |
| 財報日曆 | 未來財報日 | `data_store/earnings_calendar.json` |
| 事件物件(方向/信心/重要性/影響主題/半衰期) | 政策、政府採購、SEC 8-K、KOL | 🔶 Phase 2,對齊 investment_context v4.2 的 event object 設計 |

### 2.6 Taiwan / Geopolitical Risk Dashboard

策略 v5 §9 的台海風險 1–10 分級必須直接影響 sizing。Phase 1 只放欄位佔位(`level: null`),資料來源(官方新聞、軍演、制裁、供應鏈訊號的結構化評分)是 Phase 2 工作;在有可信來源前**不得**用 heuristic 亂填分級。

### 2.7 Backtest / EV Tracker

Phase 3(vectorbt 啟用後):EV、最大回撤、持倉時間、資金效率、vs buy-and-hold / simple momentum baseline。Phase 1 佔位。

### 2.8 Decision Log / Review Loop

`data_store/decision_log.json`(list),每筆:

```json
{
  "date": "YYYY-MM-DD",
  "symbol": "MU",
  "action": "add | trim | exit | hedge | no_trade",
  "thesis": "進場/調整理由",
  "invalidation": "失效條件(什麼情況承認錯誤)",
  "result": "結果(事後回填)",
  "followed_rules": true,
  "review_notes": "是否符合規則、學到什麼"
}
```

由 Kevin 手動維護(或未來由 Telegram bot 指令寫入)。dashboard 原樣呈現,建立可回饋的決策系統。

---

## 3. Alert Routing(dashboard 與 Telegram 的分工)

| 層級 | 內容 | Telegram | Dashboard |
|---|---|---|---|
| **Red Alert** | thesis break、risk regime shift、options panic、structural selling、核心部位風險超限、台海/地緣風險升級 | ✅ 立即推(P0) | ✅ 保存 |
| **Market Brief** | 每日/每週 regime、watchlist、momentum、事件摘要 | ✅ 定時推 | ✅ 保存 |
| **Noise Digest** | 低重要性新聞、重複 KOL 訊號、短線雜訊 | 彙整推送(P2/P3 不即時推) | ✅ 保存 |

原則:**dashboard 保存全部訊號,Telegram 只推需要 Kevin 注意的**。既有 `alert_router` 的 P0–P3 quota 機制不變;dashboard 從 `alerts_log.csv` 讀取全量,不新增推播路徑。

---

## 4. 第一版技術選型

1. **GitHub Actions 產生靜態 HTML / JSON**(`.github/workflows/dashboard_build.yml`):
   - 讀 `data_store/` 既有 state(由既有 scheduled workflow 維護),**建置過程不打外部 API、不需要任何 secret**。
   - 輸出 `public/dashboard/index.html` + `public/dashboard/data/*.json`。
   - 同時 commit 到 repo(`[skip ci]`,與 commit-state 慣例一致)並 upload artifact。
2. **可部署到 GitHub Pages**:若啟用 Pages(main branch `/public` 或 Actions deploy),直接可看;未啟用時看 artifact 或 repo 內檔案。啟用 Pages 是 repo 設定變更,由 Kevin 決定。
3. **不引入需要長期維護的伺服器**:零月費、零維護原則不變。
4. **Streamlit / Dash 為 Phase 2**:若之後要互動式前端,JSON 資料層(`public/dashboard/data/`)就是它的 API,Phase 1 產出直接複用,不會被 Phase 1 阻礙。

---

## 5. 資料流

```text
既有 scheduled workflows(macro_layer / iv_history_update / market_brief / ...)
        │  寫入
        ▼
data_store/*.json + alerts_log.csv        ← single source of truth(狀態層)
        │  唯讀
        ▼
src/storage/dashboard_store.py            ← 聚合成 payload(schema: src/models/signal_schema.py)
        ▼
src/dashboard/build_dashboard.py          ← 驗證 schema、產 HTML/JSON
        ▼
public/dashboard/index.html + data/*.json ← GitHub Pages / artifact / repo 直接瀏覽
```

---

## 6. Phase 2 方向(不阻礙 Phase 1)

- Trend/momentum pillar 接價格歷史(相對 QQQ/SMH/SOXX 3M/6M/12M 強度)。
- 付費 options 資料接入(ORATS 優先,見 `docs/data_api_evaluation.md`)→ 填 skew / OI / UOA / gamma wall。
- 台海/地緣風險結構化分級來源。
- Event object(方向/信心/重要性/半衰期)與 KOL/social 去重評分。
- position_check 將 delta/theta/vega 寫入 state,LEAPS 頁填等效曝險。
- Streamlit / Dash 互動前端(讀同一份 JSON)。
- Decision log 經 Telegram bot 指令寫入。
