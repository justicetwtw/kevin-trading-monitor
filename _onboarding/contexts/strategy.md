# Context: 策略（Strategy）

> ⚠️ **P0 缺口公告（最重要，先讀）**
>
> `docs/strategy_v4.md` 目前**仍是 placeholder**（內容只有「待補」大綱，無實際策略全文）。
> **策略全文尚未補入 repo。AI 不得自行推導、不得補寫、不得用記憶或訓練資料填空。**
> 在使用者親自把「完整投資策略架構 v4」全文貼進 `docs/strategy_v4.md` 之前，任何「策略應該是這樣」的內容都視為臆測，禁止寫入 repo。

本檔只做兩件事：(1) 標清楚「策略現在在哪、哪裡是空的」；(2) 把**已經寫在程式碼裡的、可查證的**結構骨架列出來，方便 AI 不誤改。**本檔不是策略建議，也不是投資建議。**

## 1. 策略目前實際散落在哪

| 來源 | 內容 | 權威程度 |
|---|---|---|
| `docs/strategy_v4.md` | **placeholder**，只有大綱（投資哲學 / 帳戶配置 / 三大訊號 / Layer 0,0+,F / 出場規則 / 學習鎖 / 季節性 / EV）| ❌ 空，待使用者補全文 |
| `src/config/thresholds.py` | 權重、門檻、學習鎖（`HARD_RULES`）、各 Tier 規則 — **實際跑的數字** | ✅ 程式碼即真相 |
| `src/signals/*.py` | 三大訊號評分 + `veto_checker` + `exit_rules` 的**實作** | ✅ |
| `src/config/universe.py` | 標的分層（Tier A–G、白名單、掃描池） | ✅ |
| `docs/STRATEGY_PHILOSOPHY.md` | 「使用者每天打開 brief 想看到什麼」的人看版哲學摘要 | ✅（但只是 brief 視角，非全策略） |
| `PHASE_2_STRATEGY_AND_DATA.md` | 階段 2 的大型實作規格（含學習鎖列表、模組清單）| ✅ 局部（部分段落已 deprecated，見 `docs/PHASE_2_NOTES.md`） |

**結論**：策略的「執行細節」可在程式碼查證；但策略的「完整論述全文」（為什麼這樣設計、帳戶配置邏輯、季節性節律全貌等）**不在 repo**，等使用者補 `strategy_v4.md`。

## 2. 已寫死、可查證的結構骨架（不得擅改）

下列為**程式碼中實際存在**的事實，列出是為了讓 AI 知道紅線在哪，不是叫 AI 去「優化」它們。

### 三大核心訊號（評分目標）

- **Sell CALL**（系統 #1，covered / diagonal）— 須有持倉（學習鎖 L2「require_covered_for_short_call」），無持倉不顯示。
- **Sell PUT**（系統 #2，Wheel）— 限 `SELL_PUT_WHITELIST`（Tier A + Tier B）；白名單外永不賣 PUT。
- **LEAPS 進場**（系統 #3，long call ≥ 12 個月）— 排除單股 2x ETF。

各訊號的條件門檻（距 52W 高 / RSI / IVR / VIX 等）以 `thresholds.py` 與 `docs/STRATEGY_PHILOSOPHY.md` 為準。資料拿不到的條件採「動態 conditions_total」（從分母剔除，不算未達）。

### 學習鎖（Hard Rules — 寫死禁區，`src/signals/veto_checker.py` + `thresholds.py: HARD_RULES`）

依程式碼，否決檢查涵蓋（摘要，**權威以程式碼為準**）：

1. LEAPS（long call）DTE 須 ≥ 365 天。
2. IVR 不足不 short premium（個股 / ETF 門檻不同）。
3. 財報黑窗：依 value_thesis 動態（一般短、expensive 較長、review/exit 視為永久禁）。
4. 連續多日高 VIX 期間禁建 long premium / LEAPS。
5. 特定高 beta 標的（如 PLTR / TSLA 所屬 Tier）不賣 PUT。
6. 單股 2x ETF：不開 LEAPS、不賣 covered call。
7. 其他：short call 須有 cover、對沖 DTE 下限、帳戶回撤門檻擋新部位等。

> 這些規則的數值與細節會隨 sprint 演進（例如某條曾「反向」過）。**要確認某條當前行為，讀 `veto_checker.py` 與最新 handoff，不要憑記憶。**

### 出場規則

`src/signals/exit_rules.py` 實作數條技術 / 基本面 / 季節性出場規則，並有 `value_thesis` 例外覆寫。細節以程式碼為準。

## 3. 風險與決策定位（紅線）

- 本系統是**決策輔助**：產出「分數 / 觸發了哪些條件 / 哪些被否決」，**不產生下單指令**。
- AI 在任何文件、commit、回覆中**不得**把系統輸出改寫為「建議買進 / 應該賣出 / 該進場」等直接投資建議。中性描述範例：「NVDA 的 Sell PUT 訊號評為 72，距 52W 高 -18%、RSI 31、IVR n/a（樣本不足）」。
- 「最終決策權在使用者」是設計原則（見 README §設計哲學）。

## 4. 給 AI 的待辦提示（不要自己動手補）

- `docs/strategy_v4.md` 補全文 = **使用者的工作**，不是 AI 的。AI 可在使用者明確提供全文時協助貼入 / 排版，但不得無中生有。
- 若使用者問「策略是什麼」，回答應指向上述可查證來源 + 明說「完整 v4 全文尚未入 repo」，**不要從程式碼反推出一套你以為的完整策略論述當答案**。
