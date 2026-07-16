# Decision Engine v1 — 從監測到可稽核決策準備度

> Status: implementation contract, 2026-07-16
> Scope: public-safe opportunity triage、scenario skew、evidence/readiness、correlation basket 與 decision calibration。
> Out of scope: broker execution、無人核准交易、把 screen score 當成 price target、用公開 dashboard 洩漏私有持倉。

## 1. 核心分離

系統不得把三件事混在一起：

1. **Company thesis status**：公司／產業論點是否 active、watch、broken。
2. **Security readiness**：以當前價格、估值／scenario、來源與 as-of 看，這個證券是否已可進入資本配置 review。
3. **Decision posture**：`wait_for_proof`、`re_underwrite`、`eligible_for_capital_review`、`deprioritized`；這些都是 review posture，不是交易指令。

價格漲跌本身不是 thesis evidence；好公司也可能因價格／skew 不佳而不是好的 security setup。

## 2. Readiness

### `not_decision_grade`

任一核心條件缺失：

- current price 或 as-of；
- source-backed probability scenario；
- 至少兩個 case、每個正價格、機率 0–1 且總和 100%；
- scenario 的 current price 與 market context 相差超過 5%，或 as-of 相差超過 3 天；
- company thesis 或 invalidation；
- market context unavailable。

系統仍可顯示 manual research rank、market timing context 與缺口，但不得計算可信 EV 或稱為決策就緒。

### `screen_grade`

Scenario math 存在，但任一 approval／freshness／coverage gate 未完成：

- `approval_status` 不是 `approved`／`approved_by_kevin`；
- threshold origin 尚未由 Kevin 核准；
- market context 僅為 `partial`；
- evidence 比 market as-of 舊超過 45 天，或 evidence 日期晚於 market context；
- next catalyst／proof point 已過期或不是未來日期；
- evidence、screen coverage、source posture 不足。

可用於研究優先順序，不能作 senior capital-allocation decision。45 天 evidence gate 是 repo default，仍需 Kevin 確認，不是自然定律。

### `review_ready`

最低條件：

- valid current price／as-of／source；
- valid probability scenario，且 assumptions 已由 Kevin 核准；
- scenario 與 current market anchor 一致；
- company thesis active；
- market context `healthy`；
- evidence quality 至少 medium，含來源與 as-of，且未超過 freshness gate；
- 未來 dated next catalyst／proof point；
- watchlist coverage ≥80% 且完整 screen score；
- correlation baskets 與 instrument lenses 已列出；
- threshold origin 已核准。

`review_ready` 只表示「可以交 Kevin review」，不表示應買進。

### `re_underwrite`

Company thesis broken／invalidated，或 active thesis 已降為 watch/impaired。此時 security ranking 暫停或要求重新承保。

## 3. Scenario contract

`capital_allocation.json` 每個 candidate 的 `decision_inputs.scenario`：

```json
{
  "current_price": 100.0,
  "as_of": "2026-07-16",
  "source": "named market-data source",
  "probability_origin": "analyst_assumption_pending_kevin",
  "approval_status": "draft_for_kevin_confirmation",
  "cases": [
    {"name": "down", "probability": 0.25, "price": 70.0},
    {"name": "base", "probability": 0.50, "price": 120.0},
    {"name": "up", "probability": 0.25, "price": 170.0}
  ]
}
```

Derived values：

- probability-weighted expected price／return；
- minimum downside return；
- maximum upside return；
- downside/upside ratio。

機率不完整、不等於 100%、current/source/as-of 缺失或價格不正，整個 scenario 無效；不能只丟棄壞 case 後假裝成功。數學有效但尚未核准的 scenario 只能是 `screen_grade`，不能升為 `review_ready`。

## 4. Market timing context

`Decision Market Context` workflow 在台北時間週二至週六 06:20 更新候選標的：

- current close 與 as-of；
- 1M／3M／6M return；
- 距 52-week high；
- 20-day annualized realized volatility。

來源目前是 yfinance 延遲公開資料，**只供 timing／risk context，不是 official tape、valuation 或 price target**。任一候選 unavailable 會先 commit 安全 state，再使 workflow 失敗；Mission Control 必須顯示 degraded，而不是空表。`partial` 可保留研究脈絡，但最多只到 `screen_grade`。

## 5. Screen score 的限制

既有 watchlist score 是 heuristic screen：

- 只在所有 pillars 有分數時才有 total；
- coverage 與 component status 必須一起顯示；
- 缺 pillar 不補中性值；
- 不用 score 直接推導 expected return、position size 或 order。

Decision Engine 只繼承它做 secondary screen evidence，不再創造第二個假精準總分。

## 6. Correlation baskets

至少拆分：

- `ai_capex`
- `memory_cycle`
- `hbm`
- `commodity_dram`
- `nand`
- `compute`
- `optical_interconnect`
- `portfolio_hedge`

MU 可同時屬於 AI capex 與多個 memory subthemes；不能把它們當成五個獨立 alpha。Basket gross weights 可重疊，因此不應被解讀成總和必須等於 100% 的 allocation table。Public dashboard 顯示 research-candidate overlap；私有 position risk 才能顯示實際 dollar/Delta exposure。

每個 production position 的 `thesis_id` 必須對應 `thesis_tracker.json` 中已存在的 theme／subtheme。空值與不存在的 ID 分別產生 `position_thesis_id_missing`、`position_thesis_id_invalid`，都會讓 workflow 降級。

## 7. Decision log 與 calibration

`data_store/decision_log.json` 是 append-only。每筆應包含：

```json
{
  "decision_id": "uuid-or-stable-id",
  "created_at": "ISO-8601",
  "symbol": "MU",
  "head_sha": "40-char-sha",
  "posture": "wait_for_proof",
  "horizon_date": "2026-12-31",
  "forecast_probability": 0.65,
  "forecast_event": "defined falsifiable event",
  "scenario_snapshot": {},
  "evidence_snapshot": {},
  "outcome": null,
  "resolved_at": null,
  "notes": ""
}
```

舊 row 不覆寫；結果以 resolver 追加／版本化。只有 outcome 為 boolean 且 probability 有效的 resolved forecasts 才進 Brier score。少於 10 筆明確標示 `insufficient_history`，不得拿一兩次命中宣稱模型有效。

目前 v1 只有讀取、摘要與空白 journal initialization；尚未建立 append-only writer／resolver。文件上的 append-only 是資料契約，不應誤稱為已由 storage layer 強制執行。

## 8. Model risk 與下一階段

Decision Engine v1 改善的是「資料缺口與決策準備度」，不是證明策略有 alpha。成為真正可配置資本的系統仍需要：

- source-backed issuer/sector KPIs 與 consensus/variant estimates；
- current valuation 與 price-implied expectations；
- out-of-sample／walk-forward baseline；
- transaction cost、options spread、liquidity、tax 與 execution feasibility；
- decision journal 足夠樣本後的 calibration、hit rate、drawdown、capital efficiency 與 baseline comparison；
- paid options source 選定後的 skew/OI/UOA history。

這些缺失應顯示為 blocker，不可由 LLM 敘事或漂亮 UI 補洞。
