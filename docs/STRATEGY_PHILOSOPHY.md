# 策略哲學(brief_generator / InvestorView 顯示用)

> 這份檔案是「給人看」的哲學摘要,**對應 Phase 2.5.2 的 InvestorView 三段候選邏輯**。
> 完整 v4 規格在 `PHASE_2_STRATEGY_AND_DATA.md`,這裡只提取「使用者每天打開 brief 想看到什麼」的視角。

---

## 1. Sell PUT(系統 #2 — Wheel Strategy)

### 你在等什麼

**好標的的好價格**。Sell PUT 是在 Tier A/B 白名單(NVDA / TSM / MSFT / GOOG / META / AVGO / AMZN
+ AMD / ASML / ORCL / AAPL / MU / GOOGL,共 13 檔)上,等深度回檔 + IV 偏高時收權利金。

**不在白名單(PLTR / TSLA / 觀察池)永遠不賣 PUT** — 這是學習鎖第 5 條,寫死。

### 三條件(brief 顯示用)

| 條件 | 門檻 | 為什麼 |
|------|------|--------|
| 距 52W 高 | ≤ -15% | 確保不是在高位賣 PUT(會被指派接到貴貨) |
| RSI(14) | < 35 | 短線 oversold,反彈機率 ↑ |
| IVR | ≥ 30 | 學習鎖第 2 條:IV 不夠高就不收權利金 |

### IVR n/a 的處理

`data_store/iv_history.json` 沒累積到 30 天 → IVR 回 None。
此時 **conditions_total 動態 = 2,IVR 那條不計入分母**(否則永遠湊不齊 3/3,系統失能)。

### 結論句怎麼寫

- **3/3 全條件達標** → 強烈候選,可考慮進場
- **2/3 或 1/2** → 部分條件達,等剩下條件補齊
- **0/N** → 全 universe 距條件仍遠,等市場回檔

---

## 2. Sell CALL(系統 #1 — Covered / Diagonal)

### 你在等什麼

**手上持倉漲到 overbought + IV 偏高**,順勢收一輪權利金。

**沒持倉就沒得賣**(Naked Call 違反學習鎖 L2「require_covered_for_short_call」)。
所以 brief 在 `positions.json` 為空 / 全 `_example` 時整段不顯示。

### 兩 / 三條件(brief 顯示用)

對 LEAPS 持倉(long_call):

| 條件 | 門檻 | 為什麼 |
|------|------|--------|
| 距 52W 高 | ≥ -3% | 接近高點時 call premium 才肥 |
| RSI(14) | > 65 | 短線 overbought,回檔機率 ↑ |
| IVR | ≥ 30 | 學習鎖第 2 條 |

對現股持倉:沒「LEAPS +50% 鎖利變 diagonal」的概念,所以只算 2 條件(距高 + RSI),IVR n/a 同理跳過。

### Sell CALL 在 brief 裡的關係

Sell CALL 是「持倉防守 / 增益」,不是進場訊號。所以:
- 持倉空 → 整段(連標題)不顯示
- 持倉有 → 對每筆持倉算條件,top 3 候選

---

## 3. LEAPS 進場(系統 #3 — Long Call ≥ 12 個月)

### 你在等什麼

**深度回檔 + 波動 sweet spot**。LEAPS 是長期看多部位,要在 fear 強、IV 高(但不極端)時建。

### 三條件(brief 顯示用)

| 條件 | 門檻 | 為什麼 |
|------|------|--------|
| 距 52W 高 | ≤ -25% | 真深度回檔(不是小拉回) |
| RSI(14) | < 30 | oversold panic |
| VIX | 20-30 | 不太低(沒 fear premium)也不太高(怕崩盤再蔓延) |

### VIX n/a 的處理

VIX 從 `data_store/layer0_history.json["submodules"]["vix_structure"]["snapshot"]["vix"]` 讀。
讀不到 → conditions_total 動態 = 2,VIX 那條不計入分母。

### 為何不用 IVR 當 LEAPS 條件

LEAPS 對個股 IV 的敏感度沒 short premium 那麼絕對。
v4 spec(`signals/leaps_entry_scorer.py`)在 IVR 30-70 sweet spot 給滿分 20,
但 brief 顯示用三條件用 VIX(整體市場環境)更貼近「使用者每天會想看的訊號」。

---

## 共通設計

### 動態 conditions_total

任何「資料拿不到」的條件 → 從分母拿掉,**不算「未達」**(否則資料沒到位的 universe 永遠湊不齊)。
但顯示文字保留(讓使用者知道「IVR n/a」/「VIX n/a」原因)。

### 結論句根據實況動態

- 有 fully_met → 列出 symbols,寫「條件齊備,強烈候選」
- 沒 fully_met 但有 partial_met → 列出 partial_met symbols + 缺什麼
- 全 none_met → 「全 universe 距條件仍遠,等市場回檔」

### 排序規則

按 `conditions_met` 降序、平手按距 52W 高升序(更深回檔優先)。
取 top N(預設 N=3),不是 top 5。

### Top N 預設 = 3

跟其他 brief 一致(原本 us_eod 的 EOD scan 也是 top 3)。
LEAPS / Sell PUT / Sell CALL 三段全用 top 3。
