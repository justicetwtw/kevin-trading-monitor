# Focus Trading Engine v1 — Implementation Notes

> Status: implementation slice for Draft PR #9(`docs/focus_trading_engine_v1.md` contract)
> Date: 2026-07-19
> Owner: Claude(single implementation owner)
> Rollout: shadow / display-only,feature flag 預設 OFF

本檔記錄第一個 coherent vertical slice 的實作對應、邊界與已知限制。契約仍以
`docs/focus_trading_engine_v1.md` 為準;本檔只補充「做了什麼、故意沒做什麼」。

## 1. 模組地圖

| 契約 workstream | 檔案 | 說明 |
|---|---|---|
| Feature flag / rollout | `src/focus/config.py` | `FOCUS_ENGINE_ENABLED` / `FOCUS_ENGINE_MODE`,預設 OFF、fail closed |
| Focus universe + instrument mapping | `src/focus/universe.py` | theme groups、runtime priority、槓桿/ADR → underlying/theme、未知 fail closed |
| Trend / RS / rotation | `src/focus/trend.py`, `src/focus/rotation.py` | SMA20/50/200+slope、Donchian20/55、ATR14、RSI/BB、RS20/63/126、rotation proxy |
| Timing / thesis / exposure state machine | `src/focus/state_machine.py` | 三狀態分離 + §6 gates + 50DMA falling-knife 規則 |
| Provider capability contracts | `src/focus/providers.py` | options / estimates / volatility 能力 schema、honest null、estimated GEX |
| Private exposure / hedge overlay | `src/focus/exposure.py` | underlying-normalized 曝險、hedge 認列、public redaction |
| Payload / dashboard | `src/focus/payload.py` + `src/storage/mission_control_store.py` | holdings-first focus payload、shadow envelope |
| Backtest harness | `src/focus/backtest.py` | 5 條 baseline、next-bar 無 look-ahead、成本、metrics、insufficient history |
| Shadow runner | `src/runners/run_focus_shadow.py` | 抓價 → 算狀態 → 只寫 public-safe aggregate |

## 2. 策略語意如何落地(對應契約 §3 / §6)

- **三狀態永久分離**:`evaluate_symbol()` 分別輸出 `company_thesis_state`、
  `timing_state`、`exposure_posture`,互不覆寫。thesis 由外部輸入(未接來源時
  honest default `watch`),timing 只由價量,exposure 由兩者綜合。
- **50DMA falling-knife 規則(§3.3/§3.4,驗收 #2)**:收盤在「下降中的 50DMA」之下時,
  RSI 超賣 / 觸 BB 下軌一律標 `falling_knife_oversold_not_a_buy`,`long_entry_eligible`
  強制 False。相同結構下,加入超賣**不會**提高 eligibility(見
  `tests/test_focus_state_machine.py::test_oversold_does_not_flip_eligibility_vs_neutral`)。
- **thesis intact 不機械洗出核心**:trend_damaged 且 thesis 仍 intact →
  `hold_hedged`(保留核心 + 對沖),不是全數退出;有槓桿才降 `reduce_leverage`。
- **thesis impaired/broken → `re_underwrite`**,曝險評級暫停,與 timing 無關。

## 3. 誠實邊界(對應契約 §7 boundaries)

- 未接任何付費 API、未新增 secret、未新增 plugin/MCP。
- Options skew / OI history / gamma / dealer GEX 一律 `None` + capability gap;
  `estimate_dealer_gex()` 永遠標 `estimated=True` + assumption + confidence,
  不宣稱真實 dealer 部位。
- Rotation 一律標 `metric_kind="price_return_proxy"`,不宣稱真實 fund flow。
- VVIX / COR1M 無穩定免費來源 → `None` + capability gap。
- 完整 options 歷史回測標 `not_validated_shadow_only`,不偽造歷史驗證。

## 4. 隱私邊界(對應契約 §5 Layer E / §11)

- Private 曝險明細(含 symbol/underlying)只在 process memory:
  `build_private_exposure()`。
- 寫入 public state 前一律經 `public_exposure_summary()` 降解成
  aggregate(counts + 分級 band),不含 symbol/strike/contract/cost/account value。
- Shadow runner 以 `_ALLOWED_CARD_KEYS` allow-list + `_assert_public_safe()`
  fail closed:任何 focus card 夾帶非白名單欄位會直接 raise,不寫檔。
- Public dashboard(`mission_control_store`)只讀已 redact 的
  `focus_engine_state.json`,自身不抓價、不載入私有部位。

## 5. Rollout / rollback(對應契約 §13)

- `FOCUS_ENGINE_ENABLED != 1` 時:payload 回 disabled envelope,dashboard 不顯示
  focus 區塊,既有 Decision Engine / alerts 完全不受影響。
- Shadow runner 在 flag OFF 時只寫 disabled envelope,exit 0,不 page。
- 未通過回測 + Kevin 核准前,timing state **不**升格為 Telegram P0/P1 trade alert。
- 關閉 flag 即回到既有行為,不破壞任何既有 state 檔。

## 6. 已知限制 / 尚未涵蓋(明確標記,不假裝完成)

- Thesis / estimates / valuation 來源尚未接,focus card 的 thesis 為 honter default
  `watch`、valuation 為 `not_connected` blocker。真實 Layer A 數據待後續 PR。
- Options Layer D 只有 yfinance put/call volume;skew/OI/gamma/GEX 待核准付費來源。
- 單標的 backtest 的 RS 以「自身動能」代理;跨標的相對 benchmark 的完整 RS 回測
  待價格快取歷史齊備後擴充。
- Shadow runner 需在有網路的 Actions 環境才會產出真實 focus_engine_state.json;
  本 PR 不新增自動排程 workflow(避免在未核准前消耗資源 / 改變 production 行為)。
- 尚未接 Telegram private focus brief(display-only,待 Kevin 核准觀察窗)。

## 7. Review round 1 — 已修正 findings

針對 PR #10 的 fresh-context `CHANGES_REQUIRED`(1 P0 + 7 P1),以 code + regression 修正:

- **P0 private-holding leak**:public focus cards 改為只來自
  `static_focus_symbols()`(純公開靜態名單);private holdings 不再進入 public symbol 集合,
  只影響 private aggregate。regression:不在公開名單的私有 symbol 不出現在任何 public payload。
- **P1 fail-green runner**:runner 區分 unconfigured / malformed / partial / stale /
  provider failure,寫 public-safe `workflow_status` + generic error codes,enabled degraded
  run 回 non-zero(paging 由 alert routing 控制,不靠假綠燈)。
- **P1 add gate / reclaim**:`classify_timing` 納入 benchmark RS(available/leadership/improving);
  缺 RS 或 RS 未領先不得升 add-ready;breakout 需真實 volume 確認(None ≠ OK);
  `reclaim_confirmed` 以 `reclaim_state()` 的 confirmation window 變為可達且可測。
- **P1 hedge honesty**:沒有 option Greeks 時 `hedge_coverage_ratio` 一律 `None` +
  `unavailable_no_greeks`,不用 strike notional 偽造覆蓋率;short stock(負 shares)認列為保護,
  short call 仍只算 delta offset。
- **P1 options capability consistency**:`YFinanceFocusOptionsProvider` 實際接上既有
  `options_provider` / iv history 填 current IV / IV rank / IV percentile / put-call ratio;
  supported flag 與是否取數一致,regression 檢查 capability=true 欄位確實有取數路徑。
- **P1 backtest**:修正 next-bar 執行語意(賺報酬的部位=計入 time-in-market 的部位,消除
  off-by-one);RS 改為 benchmark-relative(未給 benchmark 標 `benchmark_required`,不用自身動能冒充);
  `dma50_rs_breakout_atr` 誠實改名;walk-forward / OOS / regime split / ATR sizing 列 `not_implemented`。
- **P1 theme rotation**:`THEME_CONSTITUENTS`(純成分股)與 ETF proxy / benchmark 分離,
  basket 不再混入 SMH/SOXX 再跟 SMH 比較;補 `rs_acceleration`、`breakout_20d_share`,
  其餘 leadership 欄位列 `not_produced`。
- **P1 as-of / render**:`compute_trend_frame` 輸出 `as_of`;card 缺 as_of 或超過
  `MAX_CARD_AGE_DAYS` 標 `as_of_missing` / `price_stale`;Mission Control 新增可見的
  Focus Engine render section,含 snapshot regression。

## 8. Round 2 — 完成不需付費資料源的剩餘項目

依 Kevin 的 Round 2 continuation,完成以下(仍不新增付費 API／secret／provider):

- **ATR / N-style sizing**:`backtest.atr_sizer` 以波動目標(`TARGET_ATR_PCT`)反向縮放倉位,
  低波放大、高波縮小;新增 `dma50_rs_atr_sized` baseline。`run_strategy` 支援分數倉位、
  rebalance threshold 與 |Δfraction| 成本,執行語意仍一致(no look-ahead)。
- **Walk-forward / OOS + regime split**:`backtest.walk_forward`(連續、不重疊 OOS 段)與
  `backtest.regime_splits`(pre-2020 / 2020–2022 / 2023+ 預先宣告邊界,避免 data snooping;
  樣本不足標 insufficient)。
- **完整 metrics**:recovery_bars、downside_capture、hit_rate、avg_win/avg_loss 皆已輸出。
  `not_implemented` 只剩真正未做的 `paid_options_history_validation`、`monte_carlo_resampling`。
- **Rotation leadership**:新增 theme_rank / theme_percentile_rank(跨 theme)、
  leadership_direction、breakout_20d_share / breakout_55d_share;仍只用 constituents,不混 ETF proxy。
- **Freshness(`src/focus/freshness.py`)**:security / benchmark / volatility 皆有 as-of + stale 檢查。
  benchmark stale/missing → 不餵 RS(RS unavailable),card 標 `rs_benchmark_stale`;
  volatility stale → market regime 降級;runner health 新增 `benchmark_price_stale`。
- **Stale/partial 擋 add-ready**:`evaluate_symbol(data_blocked=True)` 強制關閉 add-ready 並降為
  `wait_for_proof`;card 只要有 stale/missing/incomplete blocker 就 data_blocked。
- **Options-pressure 成為真正 gate**:`downside_pressure_worsening` 在 breakout / trend_healthy /
  pullback 也會擋掉 add eligibility。
- **First-screen render**:Mission Control 明確渲染 Market Regime、Portfolio Exceptions、
  Theme Rotation、Focus Securities 四個 sub-section,含 source/as-of/blockers。

仍為 honest capability gap(未新增付費源):historical skew/OI/gamma/GEX、COR1M/VVIX、
estimate history。

## 9. Review round 2(incremental)— 已修正 findings

針對第二次 incremental `CHANGES_REQUIRED`(4 P1)以 code + regression 修正:

- **walk_forward 真正 OOS**:`run_strategy(metrics_start_index=)` 讓訊號用全序列暖身、但
  equity/報酬/turnover 只從 OOS 起結算;benchmark 依「日期」對齊到 window(不再被二次
  reindex 成 None,RS 會實際交易);sequential OOS 另外彙總(`oos_aggregate`)。並區分
  daily-bar 口徑(`daily_hit_rate` 等)與 trade-level 口徑(`trade_hit_rate`、
  `avg_trade_win/loss`、`closed_trade_count`)。
- **缺 valuation/options 不得放行 add**:`build_options_pressure` 三態(confirmed_ok /
  worsening / **unavailable**),不把 missing 當「未惡化」;screen-grade(無 skew/gamma)→
  unavailable。`build_focus_card` 將 valuation 未核准、options unavailable/worsening 全列為
  add-block,`evaluate_symbol(add_block_reasons=)` 強制降 `wait_for_proof`。runner 以 adapter
  把 snapshot 導成 pressure 傳入。
- **Market Regime 可操作**:`get_volatility_state` 以 `joint_state` 產出 `regime`,保留 None
  的 inversion(不 coerce False);`regime_exposure_cap` 把 regime 轉成 auditable 曝險上限
  (calm 1.0 / elevated 0.5 / stress 0 / 未知 0 fail-closed),stress/未知 regime 會擋 card add;
  Market Regime block 補 QQQ/SMH/SOXX vs 50/200DMA 與 focus breadth(缺者標記,不假裝)。
- **Rotation 對齊 + coverage**:basket 先依「日期」對齊到共同交易日再於共同起點 rebase(真正等權);
  剔除 stale 成員;輸出 theme `as_of`、valid/configured 成員與 `member_coverage`;coverage 低於
  門檻(0.6)拒絕給 RS/rank/percentile;RS 端點依日期對齊。

## 10. Review round 3(第二次 incremental)— 已修正 findings

針對第二次 incremental review(HEAD `dc856be`)的 5 個 P1 以 code + regression 修正:

- **options-pressure 不再 partial fail-open**:`build_options_pressure` 改為欄位級
  sufficiency —— 要到達 worsening/confirmed_ok 必須同時具備 `gamma_flip_proxy`(方向)與
  put skew「變化」(`put_skew_change_5d/20d`);單獨的絕對 skew 或 `strike_oi_concentration`
  不構成方向確認,一律 `unavailable`;有 `as_of` 時做 freshness,stale 視同 unavailable;
  回傳 `coverage`/`missing_fields` 供稽核。runner 傳入 `reference_date`。
- **Market Regime 真正 operational**:新增 `composite_market_regime` 把 VIX regime 與
  QQQ/SMH/SOXX 趨勢 + breadth 併算,兩大領先指標同破 200DMA 或 breadth 受損時「向上升級」
  regime(即使 VIX 低),缺資料標 capability gap;runner 先算 trend/breadth 再定 regime,
  cap 由 composite 決定。`elevated=0.5` 不再只顯示:`build_focus_card` 依 cap 產出
  `proposed_size_multiplier`(leveraged 依槓桿收斂 gross 曝險),stress/未知封頂擋 add。
- **trade-level metrics 顯式 ledger**:`run_strategy` 以進出場 ledger 計 trade,entry/
  rebalance/**exit 成本**都併入「當筆」trade;未平倉的 terminal trade 另計
  `open_terminal_trade`,不計入 `closed_trade_count`;walk-forward 段界不再把一筆連續持有
  拆成多筆假 closed trade。
- **rotation breadth/breakout 只用 fresh valid 成員**:`_breakout_share` 與 breadth 改用
  與 basket 相同的 `valid` 成員(stale 不再污染),並公開分母(`*_counted`);單一成分 theme
  (`memory_hbm_dram=[MU]`)以明示的 `single_name_proxy` 進榜,不再永遠 insufficient_data。
- **valuation 需 decision-grade evidence**:新增 `valuation_approved(evidence)`,要求
  source + 新鮮 as_of + coverage + value_band/approved_scenarios + approved 狀態;單一字串
  不再解鎖 add,缺/過期一律擋(fail closed)。

## 11. 驗證

```bash
python -m pytest -q                                   # 598 passed, 1 skipped
python -m pytest -q tests/test_focus_*.py             # 131 focus 測試(含 round 2/3/4 regression)
python scripts/verify_agent_workflow_contract.py      # passed
python scripts/agent_capability_watch.py --config .github/agent-capability-watch.json --offline  # ok
```
