# Architecture（onboarding 視角）

> 這份是**地圖**，幫 AI 在不載入整個 codebase 的前提下知道「東西放哪、一次掃描怎麼流動」。
> 評分公式的權威版在 [`../docs/architecture.md`](../docs/architecture.md)；策略邏輯權威版散落在 `src/config/thresholds.py`、`src/signals/`、`docs/STRATEGY_PHILOSOPHY.md`、`PHASE_2_STRATEGY_AND_DATA.md`。本檔不取代它們，衝突時以程式碼與 `docs/` 為準。

## 1. 高層資料流

```
GitHub Actions 排程 (cron)
        │  python -m src.runners.run_*
        ▼
src/data/*      抓外部資料（yfinance / FRED / SEC EDGAR / RSS / 各網站）
        ▼
src/indicators/*  純函式技術指標（RSI / BB / MA / ADX / 派發日）
        ▼
src/layers/*    Layer 0（宏觀）/ 0+（事件）/ F（基本面、機構、內部人）
        ▼                         │
src/signals/*  三大訊號評分  ◄──  modifier_aggregator（Layer 0 → modifier）
        │  base + Layer0 modifier + LayerF modifier，否決則歸 0
        ▼
src/alerts/*   format → route(dedup→priority→quota→cooldown→send) / brief
        ▼
Telegram 推播（src/alerts/telegram_bot.py，直接打 Telegram HTTP API）
        ▼
src/storage/state_manager.py → data_store/*.json（commit-state 自動 commit）
```

對應的台股分支：`src/twstock/*`（00631L + 2330 三級加碼、主動 ETF 跟單），由 `run_twstock_signal` 驅動。
部位管理分支：`src/management/*`（LEAPS 損益 / Short Delta / 對沖 DTE / 帳戶回撤），由 `run_position_check` 驅動。

## 2. 目錄職責

| 目錄 | 職責 | 是否屬「trading logic」紅線 |
|---|---|---|
| `src/config/` | 設定集中管理：`settings.py`(secrets/時區)、`thresholds.py`(權重/門檻/學習鎖)、`universe.py`(標的分層)、`keywords.py`、`institutions.py`、`rss_sources.py`、`position_mapping.py` | ✅ 是（除 settings 中的環境讀取外，門檻/分層屬策略） |
| `src/data/` | 22 個資料抓取模組，全部 try/except + retry，失敗回 None 不阻塞 | ✅ 是（資料邏輯） |
| `src/indicators/` | 技術指標純函式 | ✅ 是 |
| `src/layers/` | Layer 0 / 0+ / F 評估與 modifier 聚合 | ✅ 是 |
| `src/signals/` | 三大訊號評分 + 否決 + 最終分數 + 出場規則 | ✅ 是（核心） |
| `src/management/` | 部位健康度監測（5 模組） | ✅ 是 |
| `src/twstock/` | 台股訊號 | ✅ 是 |
| `src/alerts/` | 格式化 / 路由 / 去重 / 推播 / 每日 brief | ⚠️ 行為敏感，改前先問 |
| `src/storage/` | `state_manager` 讀寫 `data_store/*.json` | ⚠️ |
| `src/runners/` | GitHub Actions 進入點（`run_*`）；`_cold_start.py` 冷啟動保護 | ⚠️ |
| `src/evaluation/` | EV / 回測（Phase 3，尚未完整） | — |

> AI 預設**不更動**上表中標 ✅ 的任何檔；標 ⚠️ 的改前先與使用者確認（見 `AGENTS.md` §4）。

## 3. 評分與篩選（摘要，權威見 docs/architecture.md + thresholds.py）

```
最終分數 = max(0, 底層訊號 raw 分數
                 + Layer 0 modifier（聚合後 clip 到 -30 ~ +20）
                 + Layer F modifier（內部人 / 分析師 / 基本面，依訊號上限不同）)
        ；任一否決（veto）觸發 → 直接 0

評級門檻（docs/architecture.md）：
  ≥ 70 → 推播
  50–69 → 進每日 brief
  < 50 → 不通知
```

三層篩選器：(1) 評分閾值 → (2) 標的優先級 P0/P1/P2/P3 → (3) 推播頻率上限（P0 ≤5/日、P1 ≤10/日；細節見 `contexts/alerts.md`）。

三大核心訊號（評分目標）：**Sell CALL**、**Sell PUT(Wheel)**、**LEAPS 進場**。各訊號的條件門檻屬策略，定義在 `thresholds.py` 與 `docs/STRATEGY_PHILOSOPHY.md`。

## 4. 學習鎖（Hard Rules，寫死禁區）

實作在 `src/signals/veto_checker.py`（權威），thresholds.py `HARD_RULES`。共 6 條使用者層 + v4 spec 規則，例如：LEAPS DTE 須 ≥365 天、IVR 不足不 short premium、財報前禁建 short premium、連續高 VIX 禁建 long premium、特定標的不賣 PUT、單股 2x ETF 限制。**AI 不得放寬或改動這些規則。** 細節與完整列表見 `contexts/strategy.md` 與程式碼。

## 5. 一次掃描的生命週期（以 signal_scan 為例）

1. workflow `signal_scan_intraday` / `signal_scan_eod` 觸發 → `run_signal_scan_*`。
2. `final_scorer.scan_all_signals()` 對 universe 跑三個 scorer。
3. 每檔：`base_scorer` 算 raw → 加 Layer0 / LayerF modifier → `veto_checker` 否決 → 得最終分。
4. ≥ 門檻者進 `alert_router`：去重（24h）→ 定優先級 → 配額 / cooldown → `send_telegram`。
5. 狀態寫回 `data_store/*.json`；workflow 末端 `commit-state` 自動 commit。

## 6. 重要事實校正（避免被舊文件誤導）

- README / `PHASE_2_STRATEGY_AND_DATA.md` 提到「13 個 workflow / 13 runner」是**階段 2 當時的規格**；**實際現況是 17 個 workflow**（見 `contexts/github-actions.md`）。文件未必同步更新時，**以 `.github/workflows/` 與 `src/runners/` 實際檔案為準**。
- `settings.py` 的 `VERSION = "0.1.0"` 是**程式包版本**；handoffs 與規格中的「v4 / v4.1」是**策略 / sprint 版本**，兩者不同層次，別混。
