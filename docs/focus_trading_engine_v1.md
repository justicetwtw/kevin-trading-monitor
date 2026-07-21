# Focus Trading Engine v1 — AI／Memory Thesis-first Timing & Risk Monitor

> Status: implementation contract for Draft PR
> Date: 2026-07-19
> Product owner: Kevin
> Implementation owner: Claude on `claude/focus-trading-engine-v1`
> Product boundary: decision support only; no broker execution, no automatic orders.

## 1. Goal / Outcome

把現有 Trading Monitor 從廣泛 watchlist／heuristic score，升級為一套以 Kevin 真實關注與持倉為中心的 **thesis-first 曝險節奏控制器**：

1. 長期方向由公司品質、產業結構、EPS／營收預期與估值決定。
2. 中短期曝險由機構常看的趨勢、相對強度、期權定位與市場波動決定。
3. 核心倉、波段倉、槓桿倉分開；相同 underlying／theme 的曝險不得被誤認為分散。
4. 第一屏優先回答：現在應持有、避險、等待確認、提高曝險，還是重新承保。
5. 任何缺資料、付費資料未接、方向假設不明的欄位都必須 fail closed，不得補中性值或偽裝成 decision-grade。

本模型的核心風格是：

> 高品質龍頭與結構性瓶頸的價值投資 + 機構趨勢／相對強度的波段交易 + 期權／波動率的風險與 timing 確認。

Serenity／其他公開交易者只可作為 research idea source，不可被當成持倉真相、權重依據或自動訊號。

## 2. Relevant context / verified repo gaps

- `docs/strategy_v4.md` 已定義「基本面決定方向，trend/options 輔助 timing」。
- 現有 `leaps_entry_scorer.py` 仍會因 RSI 超賣、碰 BB 下軌、跌離 50MA、距高點跌深而加分，可能在下降趨勢中越跌越想買。
- `trend_momentum` pillar 尚未真正計算 RS；目前是 planned／None。
- options layer 主要只有 IVR／IVP；put skew、OI concentration、UOA、gamma 仍缺資料。
- `decision_market_context` 只覆蓋少量 capital-allocation candidates，未以 runtime holdings + focus universe 為中心。
- `fundamentals.py` 預設只掃 Tier A／B，會漏掉部分 Kevin 高優先研究標的。
- public repo 不得保存真實持倉、帳戶價值、完整付費 options chain 或可反推出私有部位的資料。

## 3. Strategy semantics

### 3.1 三件事必須永久分離

1. `company_thesis_state`
   - `strengthening`
   - `intact`
   - `watch`
   - `impaired`
   - `broken`

2. `timing_state`
   - `trend_healthy`
   - `pullback_test`
   - `bottom_watch`
   - `reclaim_confirmed`
   - `breakout_confirmed`
   - `overheated`
   - `trend_damaged`
   - `insufficient_data`

3. `exposure_posture`
   - `core_hold`
   - `hold_hedged`
   - `wait_for_proof`
   - `tactical_add_ready`
   - `press_trend`
   - `reduce_leverage`
   - `re_underwrite`

價格下跌本身不是 thesis evidence；公司論點正確也不代表現在適合增加槓桿。

### 3.2 部位分層

- `core`: 高品質龍頭／高 conviction 長期曝險；主要由 thesis、估值、EPS path 決定。
- `tactical`: 趨勢波段；由 50DMA、RS、突破與 options 結構決定。
- `leveraged`: 2x ETF、額外 LEAPS、margin、積極 short put；只在趨勢與風險結構確認後使用。
- `hedge`: long put、short stock 或明確風險對沖；short call 只能算 Delta offset，不得算下檔保護。

### 3.3 50DMA 規則

Production v1 使用市場最普遍的：

- 20DMA：短期節奏／BB 中軌。
- 50DMA：中期機構趨勢與新增風險 gate。
- 200DMA：長期 market／security regime。

預設規則：

- 收盤低於下降中的 50DMA：不得新增 `tactical`／`leveraged` 多頭。
- 核心高品質長倉是否保留，由 thesis、估值與 portfolio risk 決定，不因單日跌破 50DMA 全部退出。
- 低於 50DMA 的逆勢價值加碼先做 `shadow/backtest only`，production 預設 disabled；不得默認抄底。
- 重新站回 50DMA、50DMA slope 改善、RS 改善、options 壓力停止惡化後，才可升為 `tactical_add_ready`。
- 突破 20D／55D high 且基本面未惡化，可升為 `breakout_confirmed`／`press_trend`。

### 3.4 BB／RSI 的角色

保留：

- RSI(14)
- Bollinger Bands(20, 2σ)
- BandWidth／%B

但它們只判讀「位置／波動型態」，不得獨立生成抄底訊號：

- 上升 50DMA 上方的 RSI 35–50 + BB lower-band test 可標記 healthy pullback。
- 下降 50DMA 下方的 RSI < 30 + 沿下軌走，應標記 falling-knife／trend damaged，而不是提高 long-entry score。
- BB squeeze 必須搭配 RS、volume、breakout 與 options context 才能升級。

### 3.5 海龜交易可移植部分

只吸收可驗證、與本策略互補的元素：

- 20D breakout
- 55D breakout
- ATR(14)／N-style volatility sizing
- 只對有利方向的 tactical exposure 加碼

不把原始海龜期貨系統完整硬套到個股；50DMA 不是海龜規則。

## 4. Focus universe

新增 focus overlay，不取代既有 broad universe：

### 4.1 Runtime priority

排序優先級：

1. `POSITIONS_JSON` 中的真實持倉 underlying 與 hedge（private only）。
2. Kevin 明確指定的 focus symbols。
3. 高品質龍頭／主要產業代理。
4. 次要供應鏈與高風險 research watch。
5. 槓桿 ETF／交易工具。

### 4.2 Theme groups

最低需支援：

- `ai_compute`: NVDA, AMD, TSM, AVGO, SMH, SOXX
- `memory_hbm_dram`: MU, SKHY, DRAM
- `memory_nand_storage`: SNDK, WDC, STX, Kioxia/285A, DISK
- `optical_interconnect`: LITE, COHR, AAOI, MRVL, CRDO, ALAB, AXTI, GLW
- `semi_equipment_upstream`: ASML, AMAT, LRCX, KLAC, TSEM, GFS
- `ai_power_energy`: VRT, ETN, GEV, VST, CEG, BE
- `portfolio_hedge`: QQQ, SPY, SMH and approved hedge instruments

這是 research／risk mapping，不代表全部是持倉或推薦。

### 4.3 Instrument mapping

槓桿 ETF／ADR／主題 ETF 必須映射回 underlying／theme；不可當成獨立 alpha：

- MUU → MU
- SNXX → SNDK
- WDCX → WDC
- NVDL → NVDA
- AMDL → AMD
- TSMX → TSM
- AVGX → AVGO
- LITX → LITE
- MVLL → MRVL
- DRAM／RAM／DISK → memory baskets
- 其他現有與新增 2x instruments 依相同 schema 管理

新增 mapping 時要有測試，未知 instrument 必須標 `unmapped_instrument`，不能靜默歸零。

## 5. Model layers

### Layer A — Company quality / thesis / valuation

最低欄位：

- thesis state + invalidation + next proof point
- revenue／EPS actual trend
- FY1／FY2 EPS estimate（若 provider 支援）
- EPS revision 1M／3M（若 provider 支援）
- trailing P/E、NTM P/E、FY2 P/E
- analyst-approved bear／base／bull multiple
- bear／base／bull fair-value range
- source, as_of, coverage, approval_status

不得只用單一 forward P/E 就宣稱便宜；memory 必須分 HBM／commodity DRAM／NAND thesis。

### Layer B — Market regime

最低欄位：

- SPY／QQQ／SMH／SOXX vs 20／50／200DMA
- breadth（focus baskets above 20／50／200DMA）
- VIX, VIX9D, VIX3M, VVIX
- COR1M
- VIX term structure／inversion
- market put-call and credit context where available

Market regime 只限制曝險上限，不預測隔日漲跌。

### Layer C — Trend / momentum / rotation

每個 focus symbol：

- price vs 20／50／200DMA
- 20／50／200DMA slope
- 20D／55D Donchian breakout state
- ATR14／realized vol
- RSI14／BB20(2σ)／BandWidth／%B
- volume confirmation／volume percentile
- RS20／RS63／RS126 vs QQQ
- RS20／RS63／RS126 vs SMH（半導體相關）
- RS vs own theme basket
- theme percentile rank and RS acceleration

Theme rotation panel：

- 5D／20D／63D return
- RS vs QQQ／SMH
- breadth above 20／50／200DMA
- number／share of 20D and 55D breakouts
- leadership acceleration / deterioration

若沒有穩定 ETF flow source，名稱必須是 `rotation/leadership proxy`，不得宣稱真實 fund flow。

### Layer D — Options / volatility positioning

個股最低 capability schema：

- current ATM IV
- IV rank／IV percentile
- 25Δ put skew and 5D／20D change
- IV term structure
- put/call volume ratio
- put/call OI ratio
- expected move
- strike OI concentration and day-over-day OI change
- gamma concentration by strike／expiry
- gamma flip proxy
- estimated dealer GEX with explicit assumption + confidence
- option source, as_of, latency, capability status

市場層：

- VIX options volume／OI by expiry and strike
- VIX call/put demand change
- VIX／VVIX／COR1M joint state

重要：

- OI 不能直接證明客戶買或賣；dealer gamma 必須標 `estimated`，含 assumption／confidence。
- 單日 VIX call volume 不可直接被描述成市場確定押注暴跌；需隔日 OI／成交位置確認。
- provider 不支援的欄位必須是 `None` + capability gap。

### Layer E — Position / correlation / hedge risk

Private-only：

- net／gross Delta notional
- theta, vega, gamma where available
- core／tactical／leveraged／hedge exposure
- overlapping theme Delta
- underlying-normalized exposure（含 2x ETF mapping）
- long-put protective Delta and hedge coverage ratio
- stress P&L under theme moves and VIX shocks
- cash／margin buffer and assignment exposure
- DTE roll windows

Public dashboard 只能顯示非識別 aggregate health／counts／generic blockers。

## 6. Decision gates

### `bottom_watch`

- thesis intact／strengthening
- valuation has approved upside or price is inside approved value band
- price below 50DMA or 50DMA not yet recovered
- options fear／negative-gamma proxy still elevated or incomplete
- posture: `core_hold`／`hold_hedged`／`wait_for_proof`

### `reclaim_confirmed`

最低要求：

- close reclaims 50DMA using configurable confirmation window
- 50DMA slope not materially declining
- RS vs QQQ/SMH/theme improving
- put skew／gamma pressure not worsening
- thesis not impaired

### `breakout_confirmed`

- 20D or 55D high breakout
- volume confirmation
- RS leadership
- estimates/thesis intact
- no extreme call-chase warning

### `overheated`

- price materially extended from 20DMA／50DMA or ATR bands
- IV／call skew／call concentration extreme
- RS still strong but entry risk poor
- posture: hold core, no chase, consider hedge/profit protection review

### `trend_damaged`

- sustained below 50DMA
- 50DMA slope rolls over
- RS makes new lows
- failed reclaim(s)
- options downside pricing worsens

Thesis intact 時不自動退出 core；但 tactical／leveraged exposure 應降低或等待。

### `re_underwrite`

- thesis impaired/broken
- FY1/FY2 estimates or key industry KPI materially deteriorate
- valuation scenario invalid/stale
- security ranking suspended until new evidence pack

## 7. Provider architecture / API boundaries

本 PR 不得自行購買、安裝或啟用付費 API，也不得新增 secret，除非 Kevin 另行明確批准。

Claude 必須先建立／擴充 provider-neutral contracts：

- `OptionsProvider`
- `EstimatesProvider`
- `VolatilityIndexProvider`
- capability flags per field
- source/as_of/latency/status/error contract

要求：

- yfinance／public Cboe 只能作 delayed／screen-grade fallback。
- 未連接的 paid skew／OI history／GEX history 保持 honest null。
- paid raw chain 不得 commit 到 public repo、Actions artifact 或 Pages。
- public Pages 只顯示 derived state；private detail 僅 process memory／private Telegram／approved private storage。
- 新 provider／secret 名稱必須另經 Kevin 明確批准並同步安全文件。

## 8. Dashboard product requirements

第一屏順序：

1. **Market Regime** — VIX complex, COR1M, QQQ/SMH/SOXX trend, breadth, data health.
2. **Portfolio Exceptions** — private workflow health, hedge gaps, leverage/theme concentration generic summary.
3. **Theme Rotation** — AI compute, memory, optical, equipment, power/energy leadership.
4. **Focus Securities** — holdings first; thesis, timing state, valuation, RS, options risk, posture.
5. **Options Structure** — IV/skew/OI/gamma walls and capability gaps.
6. **Research Queue** — only names with missing proof, emerging leadership, or upcoming catalyst.

每檔 focus card 至少顯示：

- company thesis state
- price / 20 / 50 / 200DMA
- 50DMA slope
- RS20 / RS63 vs benchmark
- RSI / BB setup label
- 20D / 55D breakout
- NTM/FY2 valuation status
- IVP / skew change / gamma proxy status
- timing state
- exposure posture
- source/as_of/readiness blockers

不得以單一 100 分掩蓋缺口。既有 watchlist score 可保留為 secondary evidence，但 focus engine 以 gates／state machine 為主。

## 9. Backtest and validation plan

本 PR 的 implementation 必須讓 price／trend／RS 模型可回測；完整 options 歷史 backtest 在付費歷史資料核准前只能標 shadow／not validated。

### 9.1 Baselines

至少比較：

1. Buy and hold
2. 50DMA-only exposure filter
3. 50DMA + RS
4. 50DMA + RS + breakout/ATR
5. Full available model（不含未取得的 options history）

### 9.2 Robustness

- Production 使用 50DMA；63DMA／10W 僅作 robustness sensitivity，不建立第二套 production signal。
- 避免參數網格挖礦；預先固定 20／50／200, RSI14, BB20/2, ATR14, Donchian20/55。
- walk-forward／out-of-sample
- splits/dividends adjusted prices
- transaction cost/slippage
- no look-ahead／survivorship leakage
- separate regimes: pre-2020, 2020–2022, 2023+ and memory-cycle windows where data exists

### 9.3 Metrics

- CAGR / total return
- max drawdown
- Calmar / Sharpe / Sortino
- downside capture
- time in market
- turnover / trade count
- hit rate and average win/loss
- recovery time
- exposure by theme and leveraged instrument

不得因單一期間勝出就宣稱有效；少量樣本必須標 insufficient history。

## 10. Suggested implementation workstreams

Claude 可自行調整檔案命名，但需保持 single owner 並避免平行 write ownership。

1. Focus universe + instrument mapping schema
2. Trend／RS／rotation calculations
3. Focus timing state machine
4. Provider capability contracts
5. Mission Control payload + UI
6. Private position correlation／hedge overlay
7. Backtest harness + fixtures
8. Tests, docs, privacy and fail-closed review

可能涉及：

- `src/config/universe.py` or a new focus overlay module
- `src/indicators/basic.py` and new RS／Donchian helpers
- `src/decision/*`
- `src/data/options_provider.py` and new provider contracts
- `src/runners/run_decision_market_context.py`
- `src/storage/*`
- `src/dashboard/*`
- `src/management/*`
- `src/evaluation/*`
- state schemas／tests／docs

## 11. Boundaries / Approval

- 不自動下單、不接 broker execution。
- 不 merge、不 deploy、不啟用 Pages／production workflow；Kevin 最終批准。
- 不處理或輸出真實 secret、精確持倉、帳戶值。
- 不把 Serenity／社群觀察清單當成已確認持倉。
- 不把 price action 當 thesis evidence。
- 不用缺資料的中性值完成 score。
- 不宣稱 fund flow、dealer gamma、opening/closing 或 consensus revision，除非來源真的支援。
- 不新增付費 API、secret、plugin、MCP 或未知基礎設施，除非 Kevin 另行批准。
- 不以漂亮 dashboard 取代 source/as_of/coverage/readiness。

## 12. Acceptance evidence

Implementation PR 完成前必須具備：

1. Strategy semantics and schema tests：company thesis、timing、exposure posture 分離。
2. 50DMA rule regression tests：下降趨勢中的 RSI/BB 超賣不得提高 long eligibility。
3. RS and rotation deterministic fixtures，含 benchmark missing／stale／partial。
4. 20D／55D breakout、ATR、BB／RSI setup tests。
5. Instrument mapping tests：2x ETF exposure 正確映射；未知 instrument fail closed。
6. Options capability tests：unsupported fields remain `None`，estimated gamma includes assumption/confidence。
7. Position privacy tests：public payload 無 symbols／strikes／contracts／costs／account value。
8. Dashboard render/snapshot tests：第一屏聚焦 holdings／themes／exceptions，缺資料可見。
9. Backtest tests：no look-ahead、adjusted price、costs、baseline comparison、insufficient history。
10. Full `python -m pytest -q` and relevant deterministic scripts green on Python 3.11。
11. Current remote HEAD、`agent-routing-report:v1`、actual CI evidence。
12. Non-owner fresh-context review，重點檢查 strategy semantics、false precision、privacy、stale data、overfitting、workflow false green。
13. Kevin explicit merge authorization；review pass 不等於 merge。

## 13. Rollout / rollback

- 新 focus engine 先以 shadow／display-only 模式運行，不覆蓋既有 alerts。
- 與現有 watchlist／Decision Engine 並行觀察至少一個合理市場窗口。
- 未通過回測與 live observation 前，不得把 timing state 直接升格為 Telegram P0/P1 trade-style alert。
- rollout 需 feature flag；關閉後回到既有 Decision Engine，不破壞原 state files。
- provider failure、stale data 或 partial data 必須降級並使 operational health 可見。

## 14. Definition of done

完成不是「多了更多指標」，而是：

- Kevin 的真實持倉與 AI半導體／記憶體優先主題被正確聚焦；
- 光通訊、設備、能源作為相關輪動與次要機會被監測；
- 基本面、趨勢、期權、部位風險各自有清楚責任；
- 50DMA／RS／options 只控制曝險節奏，不任意推翻 thesis；
- 高品質核心倉不因正常波動被機械洗出，但槓桿不會在下降趨勢中被無限制增加；
- 所有判斷可稽核、可回測、可降級、可回滾。
