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

## 7. 驗證

```bash
python -m pytest -q                                   # 535 passed, 1 skipped
python -m pytest -q tests/test_focus_*.py             # 68 focus tests
python scripts/verify_agent_workflow_contract.py      # passed
python scripts/agent_capability_watch.py --config .github/agent-capability-watch.json --offline  # ok
```
