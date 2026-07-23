# Kevin Trading Mission Control v2
## 台美分流、主動 ETF 情報、價值／波段與期權工具選擇 Spec

> Status: implementation contract for Draft PR  
> Date: 2026-07-24  
> Product owner / final authority: Kevin  
> Implementation owner: Codex  
> Target branch: `codex/mission-control-v2-active-etf-spec`  
> Product boundary: decision support only; no broker execution, no automatic orders.

---

## 1. Goal / Outcome

把現有 `kevin-trading-monitor` 從多套並行、局部可用的 scanner／dashboard，整合成一套完整的 **thesis-first Trading Mission Control v2**：

1. **基本面、產業週期與估值決定長期方向與可接受價格。**
2. **市場結構、相對強度、價格／動能與波動率決定波段節奏與工具選擇。**
3. **台股與美股分開建模、分開評估、分開顯示，不把不同市場的資料與規則混成一個總分。**
4. **跨市場仍保留供應鏈、產業與隔夜 lead/lag 關聯，作為 context，不互相覆寫結論。**
5. **台股主動式 ETF 每日揭露的實際投資組合，升級為正式的 manager-intelligence／industry-rotation／research-candidate layer。**
6. **美股建立完整的波段／期權工具選擇狀態機：Sell Call、Buy Put、Sell Put、Buy Call、回補 Short Premium。**
7. **Dashboard 第一屏回答「現在要注意什麼、研究什麼、用什麼工具、為什麼、缺什麼資料」，而不是只展示寬表與分數。**
8. **所有資料都有 source、as-of、freshness、coverage、capability、blocker；缺資料不得補中性值。**
9. **先 shadow／display-only、回測與 live observation，再由 Kevin 核准是否升級 Telegram 通知。**

本模型的核心風格：

> 高品質企業與產業瓶頸的價值投資  
> ＋ 機構趨勢／相對強度的右側波段  
> ＋ 主動 ETF 經理人每日操作的研究情報  
> ＋ 期權與波動率的 premium harvesting／hedge／entry tool selection。

---

## 2. Permanent Strategy Semantics

### 2.1 永久分離四件事

任何 symbol 都必須分別保存，不得互相覆寫：

1. `company_thesis_state`
   - `strengthening`
   - `intact`
   - `watch`
   - `impaired`
   - `broken`

2. `valuation_state`
   - `deep_value`
   - `attractive`
   - `fair`
   - `full`
   - `expensive`
   - `not_decision_grade`

3. `timing_state`
   - `trend_healthy`
   - `pullback_test`
   - `bottom_watch`
   - `reclaim_confirmed`
   - `breakout_confirmed`
   - `overheated`
   - `trend_damaged`
   - `insufficient_data`

4. `action_posture`
   - `hold_core`
   - `add_stock_watch`
   - `add_stock_ready`
   - `buy_call_watch`
   - `buy_call_ready`
   - `sell_put_watch`
   - `sell_put_ready`
   - `sell_call_watch`
   - `sell_call_ready`
   - `buy_put_watch`
   - `buy_put_ready`
   - `close_short_premium`
   - `reduce_leverage`
   - `re_underwrite`
   - `insufficient_data`

價格上漲／下跌本身不是 thesis evidence；基本面良好也不代表現在適合追價、加槓桿或賣 Put。

### 2.2 工具選擇語意

同一個長期看多 thesis，在不同價格與 IV 狀態下應使用不同工具：

| Thesis / valuation | Timing | Volatility | Action lens |
|---|---|---|---|
| intact + attractive | 尚未止跌 | 高 IV | `sell_put_watch` 或等待 proof；不得把超賣當底部確認 |
| intact + attractive | reclaim / breakout confirmed | IV 正常或下降 | 現股、深 ITM LEAPS、Call spread、回補 Short Call |
| intact + fair/full | trend healthy | IV 正常 | 持有核心，讓 Delta 奔跑 |
| intact + full/expensive | overheated / upper-band failure | 高 IV 開始轉弱 | Sell Call／Diagonal Call；必要時 Put spread |
| intact 但短期破位 | downside pressure 剛開始、IV 尚低 | IV 低或剛升 | Buy Put／Put spread／Collar |
| thesis impaired/broken | 任意 | 任意 | `re_underwrite`；不得用賣 Put 或技術超賣掩蓋基本面破壞 |

---

## 3. Verified Current Repo Gaps

### 3.1 Active ETF P0 source bug

目前 `src/data/twstock_active_etf.py` 把：

```text
https://openapi.twse.com.tw/v1/opendata/t187ap47_L
```

當成主動 ETF 每日持股資料源；但 TWSE 官方 Swagger 對 `t187ap47_L` 的定義是 **基金基本資料彙總表**，不是每日實際投資組合。

因此目前以下假設不得再進 production：

- `t187ap47_L` 有 `持股代號／持股名稱／持股比例／持股股數`。
- 用該 endpoint 直接篩基金代號即可得到每日持股。
- 未抓到資料可視為基金沒有操作。

Implementation 必須先修正 source contract；現有 Active ETF digest 在 source 未驗證前只能標 `degraded/source_invalid`，不得宣稱已使用「法定每日持股公告」。

### 3.2 Active ETF universe 固定清單已失效

目前 Active ETF 清單在 `src/config/universe.py` 與 `src/config/active_etf_config.py` 重複硬編碼，且只涵蓋早期商品；市場已持續出現新的 `0040xA` 等股票型主動 ETF。

必須改成：

- 官方基金 master 動態 discovery。
- 股票型主動 ETF 依官方類型／代號第六碼 `A` 辨識。
- 上市／下市／更名／合併由 official metadata 更新。
- 靜態 override 只放人工補充的 strategy label、approved benchmark、issuer adapter，不保存易過期的規模、基金名稱或完整商品清單。

### 3.3 Weight delta 不等於經理人買賣

目前模型以：

```text
今日持股權重 - N 日前持股權重
```

直接判斷加／減碼。這會把以下情況誤判成經理人操作：

- 股價漲跌造成的被動權重漂移。
- ETF 申購／贖回造成所有持股股數同步放大或縮小。
- 匯率、現金、期貨、應收應付款變動。
- 股票分割、減資、合併與代號變更。

V2 必須計算 `drift_adjusted_allocation_delta`，weight change only 只能標為描述值，不得直接叫「買進／賣出」。

### 3.4 現有共識沒有 manager quality 與 independence

目前共識主要依「幾檔基金同方向」和淨權重變化排序，沒有：

- 基金過去績效／超額報酬品質。
- 經理人／投信同源產品去重。
- 基金策略差異與 benchmark 差異。
- source coverage 與歷史長度。
- AUM／流動性／持股集中度。

三檔同一投信、同一經理人、相似策略的產品，不應等同三個獨立機構觀點。

### 3.5 歷史保留不足且無可稽核 ledger

目前只保留約 45／60 天 full snapshot，不足以：

- 衡量經理人持續性。
- 建立 60／120／252 日績效與 rotation。
- 做 walk-forward active-ETF event study。
- 重建當日 source、revision 與 actionability timestamp。

V2 必須使用 append-only／可重建的 daily ledger，並控制 repo 體積。

### 3.6 Focus Engine 尚未完成 swing tool selection

現有 Focus Engine 已有 20／50／200DMA、RS、Donchian、ATR、RSI、BB、volume percentile 與 options provider schema，但仍缺：

- RSI14 的 SMA14 signal line、cross 與 slope。
- BB upper-band re-entry、BandWidth delta、上／中軌 slope。
- IV Rank／IV Percentile 的歷史轉折序列。
- Sell Call／Buy Put／Sell Put／Buy Call 各自獨立 state machine。
- 快速 Short Premium profit-taking 與 re-entry cadence。

---

## 4. Market Separation Architecture

### 4.1 Taiwan Engine 與 U.S. Engine 不共用總分

建立兩個一級 engine：

```text
Taiwan Engine
  ├─ Taiwan market regime
  ├─ Industry / group RRG
  ├─ Active ETF intelligence
  ├─ TW institutional / margin / warning state
  ├─ Taiwan fundamentals / monthly revenue / valuation
  └─ TW focus security timing

U.S. Engine
  ├─ U.S. market regime
  ├─ U.S. theme rotation
  ├─ Company thesis / estimates / valuation
  ├─ Options / volatility structure
  ├─ U.S. focus security timing
  └─ Swing / options action state
```

不得把台股三大法人、主動 ETF 共識、月營收與美股 IV／skew 混成單一 100 分。

### 4.2 Cross-market bridge 只提供 context

新增 `cross_market_bridge`：

- 台積電 ADR `TSM` ↔ `2330`。
- AI compute ↔ 台灣伺服器／散熱／電源／PCB／光通訊供應鏈。
- Memory / HBM / NAND ↔ 台灣記憶體與控制器供應鏈。
- U.S. hyperscaler capex ↔ 台灣設備／零組件受益鏈。
- 前一晚 U.S. sector move ↔ 次日台股 related basket context。

Cross-market evidence 可以：

- 提高 research priority。
- 標記 overnight context。
- 觸發「檢查相關台股」或「檢查美股 read-through」。

但不得：

- 直接把 NVDA 上漲當成台股個股買進訊號。
- 用台股主動 ETF 持股變動改寫美股公司 thesis。
- 將 ADR／本地股重複計為分散曝險。

---

## 5. Active ETF Intelligence v2

### 5.1 Product universe discovery

新增 `ActiveEtfMasterProvider`：

最低輸出：

```json
{
  "fund_id": "00981A",
  "exchange_symbol": "00981A.TW",
  "official_name": "...",
  "issuer": "...",
  "fund_type": "active_equity",
  "investment_region": "tw | overseas | mixed | unknown",
  "listing_date": "YYYY-MM-DD",
  "delisting_date": null,
  "official_benchmark": null,
  "benchmark_status": "official | none | unknown",
  "source": "TWSE fund master",
  "as_of": "...",
  "status": "ok | partial | stale | unavailable"
}
```

Rules：

- `t187ap47_L` 只能作 fund master／discovery，不得作 holdings parser。
- 每日重新確認商品 master；新增 ETF 自動進 source onboarding queue。
- 商品沒有 official benchmark 時，不得捏造 benchmark；可另外提供 `research_proxy_benchmark`，但 UI 與 schema 必須清楚標 `proxy`。
- 基金名稱、規模、經理人、benchmark 都要有 source/as-of，不以 config 中的手填數字當真相。

### 5.2 Official portfolio provider registry

臺灣主動式 ETF 的實際投資組合由各投信於每營業日 NAV 結算後在官方網站揭露。建立 provider-neutral registry：

```text
ActiveEtfPortfolioProvider
  ├─ issuer id
  ├─ supported fund ids
  ├─ official source URL/template
  ├─ fetch()
  ├─ parse()
  ├─ schema version/fingerprint
  └─ source health
```

最低 holdings row：

```json
{
  "fund_id": "00981A",
  "effective_date": "YYYY-MM-DD",
  "published_at": "ISO-8601 or null",
  "observed_at": "ISO-8601",
  "security_id": "2330",
  "security_name": "台積電",
  "market": "TW",
  "asset_type": "equity | cash | futures | fx | other",
  "shares": 1234567,
  "weight_pct": 9.49,
  "currency": "TWD",
  "source": "issuer_official",
  "source_url": "...",
  "parser_version": "...",
  "revision": 0
}
```

Source priority：

1. 投信官方 daily actual portfolio。
2. TWSE／MOPS official linked source（若提供完整同日實際投資組合）。
3. 第三方只能作 manual cross-check／screen-grade；不得默默升為 decision-grade fallback。

Provider rules：

- HTTP 200 + 空表 ≠ 正常；必須 fail closed。
- 驗證 row count、weight sum、日期、fund id、重複 securities、未知 asset type、schema fingerprint。
- Weight sum 未達可解釋區間時，列出 cash／derivative／other coverage；不得自動正規化到 100% 掩蓋缺口。
- Source HTML／CSV schema 改變要標 `schema_changed` 並停止產生操作訊號。
- 海外成分必須保存 stable identifier；ticker mapping 不確定時保留原始代號與 `mapping_status=unresolved`。

### 5.3 Publication and actionability semantics

每日 holdings 是收盤後揭露的 `effective_date` 組合；最早只能在下一個可交易 session 使用。

每筆 snapshot 必須有：

- `effective_date`
- `published_at`（來源有提供才填）
- `observed_at`
- `first_actionable_session`
- `source_freshness`

Backtest 不得使用同日收盤前不可得的持股資訊。

### 5.4 Durable storage

避免每天重寫巨大 full-history JSON：

```text
data_store/active_etf_v2/
  master.json
  latest/<fund_id>.json
  checkpoints/<fund_id>/<YYYY-MM>.json
  deltas/<YYYY-MM>.jsonl
  source_health.json
  fund_performance.json
  consensus_latest.json
  industry_flow_latest.json
```

Storage contract：

- `latest`: 每基金最新完整 snapshot。
- `checkpoints`: 每月第一個有效交易日 full snapshot，供重建。
- `deltas`: append-only daily changes/revisions。
- 同一 effective date 重抓到不同內容時追加 revision，不覆寫舊觀測。
- JSONL row 必須有 deterministic idempotency key。
- 保留至少 3 年 derived ledger；若 repo size 超過預算，先提出 migration proposal，不得自行啟用新 DB／service。

### 5.5 Drift-adjusted allocation change

真正要找的是經理人主動配置變動，不是 raw weight drift。

對每一持股，先用前一日持股與當日價格推導「假設完全沒交易」的預期權重：

```text
predicted_weight_i,t
= weight_i,t-1 × (1 + return_i,t)
  / Σ_j [weight_j,t-1 × (1 + return_j,t)]
```

再計算：

```text
drift_adjusted_delta_pp
= actual_weight_i,t - predicted_weight_i,t
```

最低分類：

- `new_position`
- `add`
- `trim`
- `exit`
- `hold`
- `weight_change_only`
- `unresolved`

Rules：

- `shares_delta` 是驗證證據，不是唯一買賣判斷，因為申購／贖回會同比例改變 shares。
- 所有持股 shares 同比例變化、weights 大致不變，優先標 `fund_flow_scaling`，不是 manager conviction。
- 缺價格或 corporate-action data 時，不得計算 drift-adjusted action；標 `unresolved`。
- 股票分割／合併／減資／代號變更需 corporate-action normalization。
- AUM 有 official source 時，可提供 `estimated_active_notional`;否則保持 `None`。

### 5.6 Fund performance qualification

只追蹤「有績效證據的經理人操作」，但不得在短歷史下製造假精確。

每檔基金依自身官方 benchmark；無 official benchmark 時用 approved research proxy，並清楚標示：

- 20／60／120／252 日 total return。
- Excess return vs benchmark。
- Rolling 20D／60D excess hit rate。
- Information ratio（樣本足夠才算）。
- Max drawdown。
- Downside capture。
- Recovery time。
- Turnover proxy。
- Concentration（top 5／10 weight、effective number of holdings）。
- ETF liquidity、AUM、premium/discount health。

History readiness：

```text
< 60 trading days   → insufficient_history
60–125              → provisional
126–251             → screen_grade
>= 252              → mature_history
```

這些是 initial defaults，必須集中設定、接受 sensitivity test；不得把未滿樣本的基金判為「差基金」。

`fund_quality_weight`：

- 只使用 signal date 以前的 performance data。
- 0–1 bounded、component visible。
- 缺 benchmark／history／source 時為 `None`，不得補 0.5。
- 不允許單一短期漲幅主導權重。
- manager quality 只調整 research priority，不直接生成 buy order。

### 5.7 Independence adjustment

建立：

```text
manager_identity = issuer + named_manager + strategy_family
```

同一 manager／issuer／高度重疊策略：

- raw fund count 保留顯示。
- consensus 使用 `independent_view_count`。
- 同一 manager family 的總 vote weight 必須 cap，避免同源產品重複投票。
- 若 manager 名稱缺失，只能用 issuer-level conservative grouping。

### 5.8 Active ETF consensus state

逐 symbol 輸出：

```json
{
  "symbol": "2330",
  "effective_date": "YYYY-MM-DD",
  "raw_fund_count_add": 5,
  "independent_view_count_add": 3,
  "qualified_fund_count_add": 2,
  "drift_adjusted_net_delta_pp": 1.35,
  "quality_weighted_consensus": 0.72,
  "new_position_count": 1,
  "persistent_add_days_5": 3,
  "persistent_add_days_20": 8,
  "estimated_active_notional": null,
  "source_coverage": 0.86,
  "confidence": "medium",
  "status": "accumulating | trimming | mixed | flat | insufficient_data"
}
```

不得再以固定「3檔／5檔」忽略 universe coverage；同樣 3 檔共識，在 4 檔有效資料與 30 檔有效資料中意義不同。

Consensus 最低同時考慮：

- independent manager count。
- qualified manager count。
- quality-weighted allocation delta。
- persistence。
- source coverage。
- fund strategy diversity。
- new position／full exit。

### 5.9 Industry / theme aggregation

每檔台股同時有兩種分類：

1. `official_industry`: TWSE／TPEx official industry taxonomy。
2. `research_theme`: AI server、HBM、CPO、散熱、PCB、電源、設備、金融、航運等 repo thesis taxonomy。

產業 flow 需輸出：

- qualified active ETF active allocation delta。
- independent manager participation。
- new position breadth。
- 5D／20D persistence。
- industry return／RS／RRG quadrant。
- valuation breadth。
- earnings／monthly revenue confirmation coverage。

主動 ETF flow 只能叫：

- `active_manager_allocation_proxy`
- `portfolio_disclosure_consensus`

不得宣稱是全市場真實 fund flow。

### 5.10 Candidate funnel

Active ETF 只負責把公司推入研究與 timing funnel：

```text
ETF disclosure change
→ drift-adjusted manager allocation
→ performance/independence-weighted consensus
→ industry RRG / RS confirmation
→ company thesis & valuation research
→ right-side timing gate
→ action posture
```

候選狀態：

- `research_candidate`
- `value_watch`
- `right_side_watch`
- `right_side_add_ready`
- `overextended_do_not_chase`
- `manager_consensus_reversing`
- `rejected_by_fundamentals`
- `insufficient_data`

`right_side_add_ready` 最低要求：

- thesis 不為 impaired／broken。
- valuation 有 approved evidence，或明確標 `valuation_pending` 並保持 screen-grade。
- 股價站在非下降的 50DMA 上方。
- RS vs TAIEX／0050 及自身產業至少一個正向且改善。
- 所屬產業 RRG 為 `improving` 或 `leading`，或有等價 leadership evidence。
- 主動 ETF consensus source coverage 足夠。
- 非處置／重大警示 blocker。

---

## 6. Taiwan Engine v2

### 6.1 Taiwan market regime

獨立輸出 `tw_market_regime`：

- TAIEX、OTC、0050、00631L vs 20／50／200DMA。
- Market breadth above 20／50／200DMA。
- 上市／上櫃漲跌家數、創新高／新低。
- 成交值與量能 regime。
- 三大法人 market-level flow。
- 融資餘額／維持率可得性。
- 台股風險偏好 proxy。
- 台海／政策／匯率 context。

State：

- `risk_on`
- `selective_risk_on`
- `neutral`
- `risk_off`
- `geopolitical_stress`
- `insufficient_data`

### 6.2 MOFI concept adoption boundary

參考 `mophyfei/MOFI_XQ` 的觀測面與 UX，但：

- 不複製受限制／綁碼的 XScript 原始碼。
- 不複製圖片、版面資產或商標化命名。
- 只採用公開、通用、可獨立實作與回測的概念。
- 所有公式與參數由本 repo 重新定義、測試與揭露。

採納項目：

1. **Industry RRG**
   - X: RS-Ratio。
   - Y: RS-Momentum。
   - quadrants: `leading / weakening / lagging / improving`。
   - 20／60／120／240 日 views。
   - 基準：TAIEX／0050／OTC，依 basket 類型設定。
   - Dashboard 顯示 trails、quadrant transition 與 ranking。

2. **Risk appetite ratio**
   - 台股 primary proxy：電子類／金融類 ratio。
   - 可加入 OTC／TAIEX、small/large、cyclical/defensive approved proxy。
   - Ratio 與 trend band 的狀態只作 market context，不是進出場訊號。

3. **Continuous RS / RS leads price**
   - symbol/benchmark ratio series。
   - short/long RS smoothing。
   - RS zero/neutral crossing。
   - RS new high。
   - RS new high while price not new high (`rs_leads_price`)。
   - benchmark 依標的使用 TAIEX／0050／OTC／industry basket。

4. **Historical valuation channel**
   - trailing／NTM／FY2 multiple 的 historical z-score／percentile。
   - ±1SD／±2SD 作 context，不當 fair value 本身。
   - cyclical、loss-making、memory 公司不得只用 P/E；需 approved alternate multiple。

5. **Institution / broker strength**
   - 外資／投信／自營商 official net flow。
   - 分點 concentration 只有在合法、穩定 source 可得時才接。
   - 不把分點買賣直接等同特定最終受益人。

6. **Squeeze / momentum release**
   - 使用 BB BandWidth、ATR、Donchian、volume 與 RS 自主實作。
   - 不複製專有 `EXCEED CHARGE` formula。

7. **Warning / disposition countdown**
   - TWSE／TPEx official 注意／處置資料。
   - 顯示開始、預計結束、交易限制與 data freshness。
   - 作為 liquidity／execution blocker。

8. **Decision-card, multi-tab dashboard UX**
   - 一頁一問題。
   - Exceptions first。
   - 狀態卡取代一整面寬表。
   - 圖表下方一定有 source/as-of/blockers。

### 6.3 Taiwan focus security card

每檔至少顯示：

- company thesis state。
- valuation state / approved range。
- monthly revenue trend。
- EPS／margin trend。
- price vs 20／50／200DMA。
- RS vs TAIEX／0050／industry。
- RRG quadrant and transition。
- active ETF consensus。
- foreign/investment-trust/dealer flow。
- warning/disposition state。
- timing state。
- action posture。
- source/as-of/coverage/blockers。

---

## 7. U.S. Swing / Options Action Engine

### 7.1 Core indicators

人工 TradingView 與 repo 模型保持一致：

- BB: 20 SMA, close, 2 standard deviations。
- RSI: Wilder RSI14。
- RSI signal: SMA14 of RSI14。
- IV: actual options-chain ATM IV。
- IV Rank: 252-trading-day range。
- IV Percentile: 252-trading-day percentile。

TradingView proxy 可作 screen-grade visual cross-check；正式模型優先使用 options provider 的真實 IV。若只有 proxy，欄位與 UI 必須明確標 `proxy`。

### 7.2 Required trend features

新增：

```text
rsi_sma_14
rsi_cross_up
rsi_cross_down
rsi_slope_1d
rsi_slope_3d
rsi_bearish_divergence
rsi_bullish_divergence

bandwidth_change_1d
bandwidth_change_3d
upper_band_slope
mid_band_slope
outside_upper_count_3d
outside_lower_count_3d
upper_band_reentry
lower_band_reentry
atr_extension
atr_extension_percentile

iv_rank_change_1d
iv_rank_change_3d
iv_percentile_change_1d
iv_percentile_change_3d
iv_peak_candidate
iv_rollover_confirmed
iv_trough_candidate
actual_target_contract_iv
```

### 7.3 Sell Call state machine

States：

- `not_ready`
- `upper_band_continuation`
- `sell_call_watch`
- `sell_call_ready`
- `sell_call_late`
- `blocked_by_breakout`
- `blocked_by_event`
- `insufficient_data`

`upper_band_continuation` / block：

- BB upper-band walk / BandWidth expanding。
- RSI above RSI-SMA14 and rising。
- 20D／55D breakout with volume。
- RS leadership improving。

`sell_call_ready` minimum：

- Price in BB upper half; preferably recent upper-band touch/outside close and re-entry。
- RSI14 crosses below RSI-SMA14 or confirmed high-level momentum rollover。
- IVR／IVP high and beginning to roll over, while target Call IV remains attractive。
- No fresh 20D／55D breakout continuation。
- No earnings／major catalyst veto。
- Position context permits short-call Delta and expiry structure。

### 7.4 Buy Put state machine

Best use case：

- Long-term thesis intact, but short-term downside risk rising。
- Price still near upper/mid area or has just broken structure。
- RSI／RS deterioration begins。
- IV low or just starting to rise, not already at panic extreme。

If IV already extreme：

- prefer Put spread／Collar／reduce leverage review。
- naked Put buying should be marked `expensive_hedge` unless explicitly approved。

### 7.5 Sell Put state machine

Minimum：

- Thesis intact/strengthening。
- Price inside approved value/assignment zone。
- Assignment capacity, cash/margin and theme concentration acceptable。
- IVR／IVP high enough to compensate risk。
- Trend either `bottom_watch` with conservative posture or `reclaim_confirmed`。
- No thesis break / earnings veto / account exposure veto。

`bottom_watch` 不代表底部已確定；UI 必須區分：

- `sell_put_for_assignment`：真的願意接貨。
- `premium_only_not_allowed`：只是因為 IV 高但不願接貨。

### 7.6 Buy Call / add-long state machine

Minimum：

- Thesis and valuation pass。
- reclaim／breakout／trend confirmation。
- RS improving / leadership。
- IV context determines instrument：
  - high IV → stock／deep ITM LEAPS／Call spread／Sell Put。
  - low/normal IV → Call／LEAPS can be eligible。

### 7.7 Short premium exit cadence

`close_short_premium` triggers：

- 30% profit: review／fast capture eligible。
- 50% profit: default high-priority close candidate。
- 70% profit: hard review ceiling; do not hold solely for remaining premium。
- IV compressed materially。
- Price reached BB mid/lower target。
- Delta/reversal risk worsens。

Fast 1–2 day gains must be decomposed：

- Delta contribution。
- Vega contribution。
- Theta contribution。

Do not attribute a 1–2 day 30–50% premium gain primarily to Theta without evidence。

---

## 8. Dashboard Information Architecture

Build Mission Control v2 as a static-data multi-tab application generated by GitHub Actions; no new server or paid infrastructure in this PR.

### 8.1 Tab order

1. **Home / Exceptions**
2. **U.S. Market**
3. **Taiwan Market**
4. **Active ETF Intelligence**
5. **Theme Rotation / Cross-market Map**
6. **Research & Valuation**
7. **Portfolio / Options**
8. **Events / Catalysts**
9. **Backtest / Decision Journal / Data Health**

### 8.2 Home / Exceptions first

First screen must answer：

- Current U.S. and Taiwan regimes。
- Portfolio exceptions and concentration。
- Action-ready states。
- Thesis break / re-underwrite。
- Active ETF qualified consensus changes。
- Source outage / stale data / schema change。
- Upcoming earnings / disposition / roll deadlines。

No normal-state wall of tables before exceptions。

### 8.3 U.S. Market tab

- U.S. composite regime。
- Theme rotation / RRG-like panel。
- Focus holdings first。
- BB／RSI／IVR／IVP swing action cards。
- Sell Call／Buy Put／Sell Put／Buy Call queues。
- Options structure and data capability gaps。

### 8.4 Taiwan Market tab

- Taiwan regime。
- Industry RRG with trails and transitions。
- Electronic/financial risk appetite ratio。
- Active manager allocation summary。
- Three-institution flow and breadth。
- Monthly revenue / fundamentals / valuation candidates。
- Warning / disposition countdown。
- Right-side candidate cards。

### 8.5 Active ETF Intelligence tab

Sections：

1. **Fund leaderboard**
   - performance readiness。
   - excess return / drawdown / downside capture。
   - source health。
   - strategy / benchmark / manager identity。

2. **Daily manager actions**
   - new position / add / trim / exit。
   - raw weight delta vs drift-adjusted delta。
   - fund-flow scaling warning。

3. **Consensus heatmap**
   - symbols × qualified independent managers。
   - 1D／5D／20D persistence。
   - source coverage。

4. **Industry allocation map**
   - active-manager allocation proxy。
   - RRG quadrant。
   - breadth / valuation / revenue confirmation。

5. **Candidate funnel**
   - research candidate。
   - value watch。
   - right-side watch／ready。
   - rejected/blockers。

6. **Source health**
   - each issuer/fund fetch status。
   - last effective date。
   - publication lag。
   - schema fingerprint。
   - row/weight coverage。

### 8.6 Theme Rotation / Cross-market tab

- Separate Taiwan and U.S. RRG panels。
- Cross-market theme cards: AI compute, memory, optical, equipment, power, Taiwan supply chain。
- ADR/local mapping。
- Lead/lag context with no causal claim。
- Group/basket composite chart; do not use a single stock as a whole-theme proxy without visible label。

### 8.7 Research & Valuation tab

- Company thesis evidence pack。
- approved bear/base/bull scenario。
- estimate revisions。
- historical valuation channel。
- industry-cycle KPI。
- active ETF reason for entering research queue。
- confirming and disconfirming evidence。

### 8.8 Portfolio / Options tab

Private workflow / Telegram：

- underlying-normalized Delta notional。
- Gamma／Vega／Theta where available。
- core/tactical/leveraged/hedge split。
- theme concentration。
- short premium open positions and profit capture candidates。
- assignment exposure。
- roll windows。

Public dashboard remains aggregate/redacted per existing privacy contract。

### 8.9 Data-card contract

Every visible card/table/chart must include：

- `source`
- `as_of`
- `observed_at`
- `freshness`
- `coverage`
- `status`
- `readiness`
- `blockers`
- `methodology_version`

No decorative green state when data is missing。

---

## 9. Alert / Delivery Contract

### 9.1 Telegram

Telegram only sends actionable exceptions, not every daily ETF change。

Eligible categories after shadow validation and Kevin approval：

- P0: thesis break, portfolio risk breach, source false-green risk, major regime shift。
- P1: qualified active-manager consensus + right-side confirmation + valuation/thesis pass。
- P1: Sell Call / Buy Put / Sell Put / Buy Call state transition to `ready` for holdings/focus symbols。
- P1: short premium 50% profit capture candidate or Delta risk threshold。
- P2: active ETF daily/weekly digest, RRG transitions, research queue changes。

### 9.2 Email / Dashboard

- Existing Active ETF email digest may continue only after V2 source correctness is proven。
- Daily digest shows source coverage and effective date。
- Dashboard stores all screen-grade evidence and rejected candidates。
- No email subject/body may claim「經理人買進」when only raw weight change is available。

### 9.3 Dedup and state transition

Alerts trigger on state transition, not every repeated scan：

```text
watch → ready
ready → invalidated
short premium open → profit_capture
source ok → degraded/schema_changed
```

---

## 10. Backtest and Validation

### 10.1 Active ETF event study

Signal action time：

- holdings effective date D is published after D close。
- earliest tradable signal is D+1 session。
- use next open / next close variants; never use D close as fill。

Baselines：

1. Raw weight delta only。
2. Drift-adjusted delta。
3. Equal-weight all active ETFs consensus。
4. Performance-qualified consensus。
5. Performance + independence-adjusted consensus。
6. Consensus + industry RS/RRG。
7. Full candidate funnel with thesis/valuation/timing available。

Metrics：

- Forward 1／5／20／60D return。
- Excess return vs market / industry。
- Hit rate。
- Information ratio。
- Max adverse / favorable excursion。
- Drawdown and recovery。
- Turnover / signal count。
- Sector-neutral result。
- Publication-lag sensitivity。
- Transaction costs / liquidity。

Bias controls：

- Dynamic universe by historical listing date。
- No survivorship-only current list。
- Fund quality uses only prior data。
- Corporate-action adjusted prices and shares。
- Walk-forward / out-of-sample。
- Separate market regimes。
- Insufficient sample remains explicitly insufficient。

### 10.2 Swing / options validation

Price-only features can be fully backtested；options history lacking an approved provider remains `shadow/not_validated`。

Compare：

1. BB touch only。
2. BB + RSI rollover。
3. BB + RSI + IVR/IVP rollover。
4. Full state machine with RS/Donchian/event veto。

For Sell Call：

- premium P&L 1／2／5／10D。
- 30／50／70% profit hit time。
- missed upside / forced roll rate。
- max adverse move。
- underlying Delta reduction。
- IV vs Delta contribution。

For Sell Put / Buy Call：

- assignment-adjusted return。
- entry cost vs approved value zone。
- rebound capture。
- IV crush impact。

---

## 11. Implementation Workstreams

One branch, one implementation owner. Codex may adjust filenames but must keep coherent ownership.

### Workstream A — P0 source correction

- Remove `t187ap47_L` holdings assumption。
- Implement fund master provider。
- Implement issuer portfolio provider contract and source-health probe。
- Mark current digest degraded until verified official holdings adapters exist。

### Workstream B — Active ETF ledger and allocation model

Likely files：

```text
src/twstock/active_etf_master.py
src/twstock/active_etf_providers.py
src/twstock/active_etf_ledger.py
src/twstock/active_etf_allocation.py
src/twstock/active_etf_performance.py
src/twstock/active_etf_intelligence.py
src/config/active_etf_v2.py
```

Migrate/deprecate：

```text
src/data/twstock_active_etf.py
src/twstock/active_etf_consensus.py
src/twstock/active_etf_signals.py
src/config/active_etf_config.py
```

Do not delete old path until V2 shadow comparison and rollback are proven。

### Workstream C — Taiwan regime / RRG / RS

```text
src/twstock/market_regime.py
src/twstock/rrg.py
src/twstock/relative_strength.py
src/twstock/industry_mapping.py
src/twstock/market_risk_appetite.py
src/twstock/warning_state.py
```

### Workstream D — Swing action engine

Prefer new module instead of expanding the legacy 100-point scorer：

```text
src/focus/swing_features.py
src/focus/swing_action_state.py
src/focus/short_premium_management.py
```

Legacy Sell Call / Sell Put scorer remains secondary evidence until V2 validation。

### Workstream E — Mission Control v2 payload and UI

```text
src/storage/mission_control_v2_store.py
src/dashboard/build_mission_control_v2.py
src/runners/run_mission_control_v2.py
public/dashboard-v2/
```

May reuse current storage/render helpers, but do not make one monolithic untestable HTML function。

### Workstream F — Backtest / evaluation

```text
src/evaluation/active_etf_event_study.py
src/evaluation/swing_action_backtest.py
tests/fixtures/active_etf/
tests/fixtures/swing/
```

---

## 12. Feature Flags and Rollout

Required flags：

```text
MISSION_CONTROL_V2_ENABLED=0
ACTIVE_ETF_INTELLIGENCE_V2_ENABLED=0
SWING_ACTION_ENGINE_ENABLED=0
ACTIVE_ETF_V2_ALERTS_ENABLED=0
```

Rollout：

1. Contract + provider/source probe。
2. P0 source correction and source-health dashboard。
3. Active ETF V2 forward collection in shadow for at least 20 valid trading sessions。
4. Mission Control v2 display-only。
5. Backtest/event study and live observation。
6. Kevin separately approves P1 alerts。
7. Old dashboard/workflows remain rollback path until explicit migration approval。

No merge, deploy, Pages switch, production workflow activation or new secret without Kevin’s explicit authorization for that action。

---

## 13. Acceptance Evidence

Implementation PR cannot be considered complete without：

### Source correctness

1. Regression proving `t187ap47_L` is not parsed as holdings。
2. Dynamic master fixture discovers new active equity ETFs without hard-coded list。
3. At least one official issuer adapter end-to-end fixture plus live probe evidence。
4. Empty/changed schema fails closed and is visible in source health。
5. effective/published/observed/actionable timestamps tested。

### Allocation correctness

6. Price rises 10% with no manager trade → drift-adjusted delta approximately zero。
7. All shares scale from fund subscription/redemption with stable weights → no conviction signal。
8. New position, add, trim, exit and corporate-action fixtures。
9. Weight sum/cash/derivative coverage test。
10. Revision/idempotency/durable ledger test。

### Fund quality / consensus

11. No look-ahead in fund performance weight。
12. Insufficient-history funds remain provisional/insufficient, not low-quality。
13. Same issuer/manager products are independence-capped。
14. Consensus changes with source coverage and universe denominator。
15. Raw fund count and independent qualified count both visible。

### Taiwan model

16. Deterministic RRG quadrant and transition fixtures。
17. RS new high / RS leads price fixtures。
18. Taiwan and U.S. regime payloads remain separate。
19. Warning/disposition blocks action-ready where required。
20. Active ETF consensus cannot bypass thesis/valuation blockers。

### Swing model

21. RSI14 + SMA14 cross matches TradingView settings。
22. BB upper/lower re-entry and BandWidth delta fixtures。
23. IVR/IVP rollover requires history; latest value alone cannot claim peak。
24. Upper-band breakout continuation blocks Sell Call ready。
25. Panic IV + lower-band oversold does not create new Sell Call ready。
26. Short premium 30/50/70% exit-state tests。

### Dashboard / privacy / quality

27. V2 tabs render with empty/partial/stale data visibly degraded。
28. Every decision card has source/as-of/coverage/blockers。
29. Public payload does not expose private symbols, strikes, contracts, costs, account value or exact Greeks。
30. No proprietary MOFI code/assets copied into repo。
31. Full `python -m pytest -q` green on Python 3.11。
32. Relevant deterministic scripts and live source probes documented。
33. Current remote HEAD, SHA-bound `agent-routing-report:v1`, actual CI evidence。
34. Fresh-context independent review by non-owner; material findings resolved。
35. Kevin explicit authorization before Ready/merge/activation。

---

## 14. Definition of Done

完成不是「多幾個指標或多一張表」，而是：

- 台股與美股各自有正確的 regime、research、timing 與 action semantics。
- 主動 ETF 每日揭露被轉成可稽核、去價格漂移、績效與獨立性調整的研究情報。
- Dashboard 能從「經理人正在把配置移向哪裡」一路 drill down 到產業、公司 thesis、估值與右側 timing。
- BB／RSI／IVR／IVP 被正確用於波段與 premium timing，不取代基本面。
- Sell Call、Buy Put、Sell Put、Buy Call 與 Short Premium 回補有不同 state machine。
- 老墨 repo 的 RRG、risk appetite、RS leads price、valuation channel、warning countdown 與 multi-tab UX 被獨立、可測試地重新實作，沒有複製專有程式或資產。
- 缺資料、source 失效、歷史不足與 provider capability gaps 全部可見且 fail closed。
- 所有輸出可回測、可稽核、可降級、可回滾；永不自動下單。
