# Kevin 投資策略總架構 v5

> 本文件是 Invest 專案的策略 single source of truth。系統、回測、Telegram alerts、未來 dashboard、Codex/Claude/ChatGPT 後續討論，都應以本文件作為共同基準。
>
> 核心原則：**基本面與產業週期決定方向，趨勢/動能/期權市場輔助 timing，ATR/曝險/台海風險決定倉位與風控。**

---

## 0. 策略定位

本策略不是傳統技術指標交易系統，不以 RSI/MACD/KD 之類單一指標作為核心 alpha。

投資流程分六層：

```text
1. Regime filter：現在能不能承擔風險？
2. Fundamental catalyst：哪個產業 / 標的是核心？
3. Trend & momentum：市場是否順風？
4. Options & flow：期權/籌碼是否確認或警告？
5. Risk engine：用什麼工具表達、承擔多少曝險？
6. Exit / review：什麼情況降槓桿、停損、roll、退出？
```

技術指標只作為「輔助濾網」：避免追太急、輔助 pullback/轉強 timing、估算停損距離。它不能取代基本面、產業週期、期權市場與風控。

---

## 1. 投資哲學

### 1.1 不把傳統技術指標當核心 alpha

RSI/MACD/KD 等傳統指標常見問題：

```text
1. 訊號高度重疊
   MACD 本質是均線差；RSI/KD 多半是短期漲跌速度或超買超賣的不同量化。

2. 單獨使用容易失效
   強勢股可以長期超買，弱勢股可以長期超賣；盤整時黃金交叉/翻紅容易來回打臉。

3. 最有用的位置是輔助，不是決策核心
   可用來避免短線追太急、或在核心名單已選好後協助 timing。
```

技術分析最大的坑是「看圖說故事」。若沒有明確規則、交易成本、停損、樣本外檢驗，很容易只是事後解釋。

### 1.2 真正值得保留的技術類訊號

相較 RSI/MACD/KD，本策略優先保留：

```text
1. 均線 / 趨勢濾網
   20 / 50 / 60 / 120 / 200MA，用來判斷是否順風，而不是精準預測。

2. 動能 / 相對強度
   3M / 6M / 12M 報酬，相對 QQQ / SMH / SOXX 強弱。

3. 成交量
   突破是否帶量、下跌是否恐慌放量、支撐區是否有承接。

4. 支撐壓力 / 前高前低 / 大量區
   用於風險報酬比、停損、停利、結構破壞判斷。

5. 波動度 / ATR
   不預測方向，但用於停損距離、部位大小與避免被正常波動掃掉。
```

---

## 2. Layer A：Regime filter（曝險環境）

Regime filter 決定是否能重倉、是否能用 LEAPS/槓桿、是否需要提高現金或避險。

### 2.1 四種 regime

```text
Risk-on
- QQQ/SPY/SMH 趨勢健康
- AI capex / 半導體循環仍向上
- VIX 與信用環境正常
- 台海/地緣風險低
→ 可持有 LEAPS、高 beta 科技、核心多頭部位。

Selective risk-on
- 大盤仍可，但分化嚴重
- 只有少數產業/個股續強
→ 只做最強產業與最強標的，不追弱股反彈。

Risk-off
- 大盤跌破長期趨勢或市場風險偏好急降
- 利率、美元、信用、VIX 對科技形成壓力
→ 降槓桿、提高現金，只留最高 conviction。

Geopolitical stress
- 台海/戰爭/制裁/供應鏈風險快速升高
→ 啟動台海預警模型；降低台股與高 beta 科技曝險，增加美元、現金、軍工或避險資產。
```

### 2.2 監控指標

```text
- QQQ / SPY 是否在 200MA 上
- SMH / SOXX 是否相對強於 QQQ
- VIX 與 VIX term structure 是否異常
- 美債利率、美元、信用利差是否壓制科技股
- 台海預警模型層級
- 核心產業 ETF breadth 與 leadership 是否擴散或收斂
```

Regime filter 不用來預測明天漲跌，而是決定「可承受曝險上限」。

---

## 3. Layer B：Fundamental catalyst（核心 alpha）

本策略的核心 alpha 來自產業週期、基本面、財報上修、資本支出與政策/事件催化，而不是短線指標。

### 3.1 最高優先主題

與 `docs/investment_context_v4_2.md` 保持一致：

```text
- Memory / storage / AI infrastructure
- Optical networking / CPO
- MLCC / passive components / power semiconductor
- AI capex beneficiaries and AI capex risk
- Government procurement and national-security beneficiaries
- Energy / nuclear / grid
- Taiwan semiconductor supply chain
```

### 3.2 半導體 / AI infrastructure 追蹤重點

以 MU / TSM / NVDA / AMD / SMH / SOXX 等為例：

```text
- HBM 供需與報價
- DRAM / NAND / SSD cycle
- AI server memory bandwidth bottleneck
- 毛利率拐點
- inventory cycle
- capex / order / backlog
- 財報 guidance 是否上修
- 分析師 EPS / revenue revision
- 大客戶 capex 是否續強或放緩
- 市場是否開始重估產業週期
```

### 3.3 Fundamental score

每個核心標的給 0–5 分：

```text
5 = thesis 明確上修，財報、產業數據、guidance、價格趨勢共同支持
4 = thesis 正常推進，可持有核心部位
3 = 還行但缺乏新催化，不追高
2 = thesis 鈍化，需要降槓桿或等待確認
1 = thesis 明顯破壞，應降部位
0 = 出場或只保留觀察倉
```

---

## 4. Layer C：Trend & momentum（順風確認）

Trend/momentum 是 timing 與風險濾網，不是核心 alpha。

### 4.1 趨勢條件

```text
- 價格在 50MA / 200MA 上
- 50MA 上彎，200MA 走平或上彎
- 回調守住前高、前低、均線或大量區
- 跌破後能否快速收復
- 是否創新高後量價配合，而非單日假突破
```

### 4.2 動能條件

```text
- 3M / 6M / 12M 報酬為正
- 相對 QQQ / SMH / SOXX 強勢
- 產業內排名靠前
- 強勢股 pullback 後重新轉強
```

### 4.3 禁止事項

```text
- 不因 RSI 超賣而接弱勢股
- 不因 RSI 超買而賣出仍在主升段的強勢股
- 不因 MACD 翻紅而忽略基本面破壞
- 不因 KD 黃金交叉而買入盤整區間中段
```

---

## 5. Layer D：Options & flow（期權/籌碼確認）

期權市場是本策略的重要優勢層。目標不是看單筆大單就跟單，而是判斷市場是否真的為上行/下行風險付錢。

### 5.1 觀察項目

```text
- 下跌時 IV 是否異常上升
- put skew 是否快速變貴
- call bid 是否仍在
- 大單是 opening 還是 closing
- 深 ITM call 賣出是否代表真實賣壓或 covered call / tax / rollover
- synthetic short 是否代表方向性看空或結構性 hedge
- OI / volume 是否集中在關鍵 strike
- gamma / dealer positioning 是否可能放大短線波動
- 關鍵價位附近是否有支撐/壓力與期權牆重合
```

### 5.2 四種狀態

```text
健康回調
- 股價跌，但 IV / skew 平靜
- 支撐區有量
- 沒有急著買 put 保護
→ 可觀察加碼或等待轉強。

恐慌下殺
- 股價跌，IV 飆升，put skew 大幅變貴
→ 不急著接，等波動消化。

逼空 / call chase
- 股價漲，短線 call IV 被大量買進
→ 不追，等待 pullback 或降低進場權重。

結構性賣壓
- 深 ITM call 大量賣出、synthetic short、財報後放量破位
→ 降低部位，不硬凹。
```

---

## 6. Layer E：Risk engine（工具、曝險、停損、hedge）

### 6.1 LEAPS 作為現股替代

LEAPS 的定位是資金效率更高的現股替代，不是短線 lotto。

規則：

```text
- 核心 LEAPS 優先 9–18 個月以上
- Delta 優先 0.8–0.95，使用 deep ITM / high delta
- 不用短天期 OTM 當核心部位
- 到期剩 6–9 個月開始評估 roll
- 若時間價值很低且主升段未完，可評估 exercise 或換現股
- thesis 破壞時不因是 LEAPS 就硬凹
```

### 6.2 等效現股曝險

LEAPS 風險不能只看權利金，要看 delta exposure：

```text
等效現股曝險 = contracts × 100 × delta × 股價
```

每週至少檢查：

```text
- total delta exposure
- 單一標的 delta exposure
- sector exposure
- cash buffer
- drawdown 情境
- 到期分布
- theta / vega exposure
```

### 6.3 ATR 與停損

ATR 不預測方向，但用於：

```text
- 停損距離
- position sizing
- 避免停損設在正常波動內
- 估算 reward/risk
```

原則：停損不應隨意設在剛好會被日常波動掃掉的位置，可參考 1.5–3 ATR，再結合前高前低、均線與大量區。

### 6.4 Put hedge / 降槓桿

遇到以下情境，優先考慮降槓桿或買 put hedge：

```text
- Regime 從 risk-on 轉向 risk-off
- 台海預警模型升級
- 核心部位等效現股曝險過高
- 財報前 IV 不合理但 downside event risk 高
- 期權市場顯示 put skew 快速變貴
```

---

## 7. Entry / add / reduce / exit 規則

### 7.1 進場類型

```text
Breakout entry
- 基本面強
- trend/momentum 強
- 放量突破前高或關鍵區間
- options flow 沒有明顯警告

Pullback entry
- 基本面強
- 長期趨勢未破
- 回測支撐/均線/大量區
- IV/skew 沒有恐慌式惡化

Event entry
- 財報、guidance、產業報價、政策催化確認 thesis 上修
- 市場尚未完全 price in
```

### 7.2 加碼條件

```text
- Fundamental score ≥ 4
- Regime = risk-on 或 selective risk-on
- 價格結構未破
- options flow 支持或至少沒有警告
- 等效曝險仍在上限內
```

### 7.3 減碼 / 出場條件

```text
Thesis break
- 基本面、產業週期、財報 guidance 或核心邏輯證偽

Structure break
- 跌破關鍵支撐且無快速收復

Volatility warning
- IV / put skew 顯示市場開始大量為下行付費

Position risk
- 等效現股曝險過高、cash buffer 不足、到期過近

Regime shift
- 大盤/台海/地緣/流動性風險轉壞
```

---

## 8. 量化評分框架

每個核心標的以 100 分評估：

```text
Fundamental / catalyst：35 分
Trend / momentum：20 分
Options / flow：20 分
Valuation / expectation：10 分
Risk / macro / geopolitical：15 分
```

對應行動：

```text
80–100：核心多頭，可持有 / 加碼；可使用 LEAPS
65–79：可持有，但不追高；控制槓桿
50–64：觀察 / 降低槓桿；等待催化或結構改善
35–49：只做短線，不當核心
0–34：出場或避開
```

此分數不是機械下單訊號，而是防止情緒化判斷與事後合理化的決策框架。

---

## 9. 台海 / 地緣風險接入倉位

台海預警模型不應只是政治分析，必須直接影響 portfolio sizing。

```text
台海風險 1–3
- 正常持倉
- 可依市場 regime 使用 LEAPS

台海風險 4–5
- 不新增高槓桿
- 降低台股與高度地緣敏感部位

台海風險 6–7
- 明顯降低科技 LEAPS
- 增加美元、現金、避險或軍工

台海風險 8–10
- 執行戰前去風險策略
- 出清或大幅降低台股與高 beta 科技
```

---

## 10. 回測與研究規則

### 10.1 不測一堆重疊指標

不要讓模型同時吃 RSI、KD、MACD、StochRSI，造成假訊號多數決。應以訊號家族測試：

```text
Trend：MA / price above MA
Momentum：3M / 6M / 12M relative strength
Volatility：ATR / realized vol
Volume：breakout volume / volume percentile
Options：IV rank / skew / put-call / OI concentration
Fundamental：earnings revision / margin / revenue guidance
```

### 10.2 回測必備條件

```text
- 明確規則
- 交易成本
- 滑價
- 稅費或至少估算
- 樣本外驗證
- 不同 regime 分段
- drawdown 與風險調整報酬
- 避免 data snooping
```

### 10.3 評估重點

```text
- 不是只看勝率
- 要看期望值、最大回撤、持倉時間、資金效率、最差情境
- 要比較 buy-and-hold / benchmark / simple momentum baseline
```

---

## 11. 不交易規則

好的策略大部分時間應該避免亂動。

```text
- 財報前 IV 過高，不買 call 追價
- 跌破 200MA 且 thesis 不明，不接刀
- 大盤 risk-off，不加高 beta LEAPS
- 期權流顯示恐慌避險，不因 RSI 超賣硬買
- 支撐破位未收復，不急著攤平
- 沒有明確 reward/risk，不為了有動作而交易
```

---

## 12. 系統實作方向

Trading Monitor / Telegram alerts / future dashboard 應把訊號分層，避免 noisy alert。

### 12.1 Alert 分級

```text
Red Alert
- thesis break
- risk regime shift
- options panic / structural selling
- 台海/地緣風險升級
- 核心部位風險超限

Market Brief
- 每日/每週 regime、watchlist、momentum、事件摘要

Noise Digest
- 低重要性新聞、重複 KOL 訊號、短線雜訊
```

### 12.2 資料需求

```text
- 價格 / volume / MA / ATR / relative strength
- 財報與 analyst revision
- ETF flow / 13F / Form 4 / buyback
- options IV / skew / OI / unusual activity
- event objects：政策、政府採購、財報、SEC 8-K、KOL/social
- portfolio exposure：delta、theta、vega、expiry、cash buffer
```

### 12.3 未來 dashboard 核心頁面

```text
- Regime dashboard
- Watchlist score table
- Options/flow dashboard
- LEAPS exposure dashboard
- Event monitor
- Taiwan/geopolitical risk dashboard
- Backtest / EV tracker
```

---

## 13. 後續討論使用方式

未來討論 MU、TSM、NVDA、AMD 或其他標的時，應固定套用此模板：

```text
1. Regime：現在能不能承擔風險？
2. Fundamental：thesis 是否上修/破壞？
3. Trend/momentum：是否順風？
4. Options/flow：市場是否支持或警告？
5. Risk：等效曝險、ATR、台海/宏觀風險如何？
6. Action：持有 / 加碼 / 降槓桿 / hedge / 出場 / 不交易
```

此文件會隨回測、實戰與系統開發持續更新。
