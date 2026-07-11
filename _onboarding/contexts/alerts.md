# Context: 推播與 Brief（Alerts）

> 來源：`src/alerts/*.py`、`src/storage/state_manager.py`（已實際讀檔查證）。
> 定位：把訊號轉成 Telegram 訊息，並用去重 / 優先級 / 配額 / cooldown 控制「不洗版」。
> **紅線**：推播是決策輔助通知，**訊息內容不得寫成直接投資建議**（見 `AGENTS.md` §4.5、`contexts/strategy.md` §3）。

## 1. Pipeline（七階段）

```
訊號 / 事件
  └─ alert_formatter   格式化成 HTML 訊息（所有使用者字串走 escape，防 parse_mode=HTML 注入）
        └─ alert_router  路由主流程：
              ├─ deduplication   24h 去重（同 symbol::signal_type）
              ├─ determine_priority  P0 / P1 / P2 / P3
              ├─ should_send     每日配額 + 60 秒 cooldown
              └─ send_telegram   送出 → mark_sent 記錄
（並行）brief_generator  6 種排程 brief（被動推送，不走去重 / 配額）
        └─ investor_view  候選評估與排序
（旁路）tag_attacher     對部位 / 訊號類 alert 貼 ⚠Trump_Tier1 情境標籤（60 分內）
傳輸層 telegram_bot      httpx 直打 Telegram HTTP API（多 chat_id，任一成功即算成功）
```

## 2. 優先級與配額（`alert_router.py`）

- **優先級判定**：drawdown level_2/3 = P0；Trump tier1 = P0；SEC 8-K/10-K = P0；alert_level=red = P0；orange/green = P1；yellow = P2；其他 = P3。
- **每日配額**（按台北日期計）：**P0 ≤ 5/日、P1 ≤ 10/日；P2 / P3 不即時推**（只進每日 brief）。
- **Cooldown**：同一 `symbol::signal_type` key 60 秒內不重送。
- 配額 / last_send 記錄超過 7 天自動清理。

## 3. 去重（`deduplication.py`）

- 窗口 `DEDUP_WINDOW_HOURS = 24`，key = `symbol::signal_type`，存於 `data_store/alert_dedup.json`。
- **升級例外**：alert_level 升階（white→yellow/green/orange、yellow→green/orange）會打破去重，重新推。
- **Trump 例外**：24h 內若舊紀錄無 ⚠Trump_Tier1 標籤、新 alert 有 → 視為情境改變，重新推。
- 紀錄保留 `RETENTION_DAYS = 7` 後清理。

## 4. 每日 Brief（`brief_generator.py` + `investor_view.py`）

- 6 種 brief（`VALID_BRIEF_TYPES`）：`us_eod`、`tw_open`、`tw_close`、`us_premarket`、`us_open`、`us_midday`（排程見 `contexts/github-actions.md` 的 Market Brief，含 DST 變體與主 / 備雙 cron）。
- 段落（依 brief 種類組裝，抓取失敗以 `_safe()` 顯示「資料抓取失敗」不中斷）：市場環境（SPY/QQQ/VIX + Layer0 modifier）、Sell PUT / Sell CALL / LEAPS 候選、部位健康度、今日事件、台股訊號、主動 ETF…
- **持倉相關段（Sell CALL、部位健康度）在 `positions.json` 為空 / 全 `_example` 時整段不顯示。**
- 候選排序：`conditions_met` 降序、平手按距 52W 高升序（更深回檔優先），取 top 3。動態 conditions_total（IVR / VIX 拿不到時剔除分母，不算未達）。
- Brief 為**被動排程推送**，不套用去重 / 配額 / cooldown；另有 `run_brief_sanity` 在台北 23:00 檢查當日該推的 brief 是否都推了。

## 5. 傳輸層（`telegram_bot.py`）

- 直接用 `httpx.AsyncClient` 打 `https://api.telegram.org/bot{token}/sendMessage`，**不依賴 python-telegram-bot library**（Phase 2.5.7 hotfix）。
- 支援多 chat_id（`TELEGRAM_CHAT_ID` 逗號分隔 → `TELEGRAM_CHAT_IDS`）；對每個 chat 嘗試，**任一成功即回 True**（避免單一 chat 失效拖垮整體）。
- 顯式 30 秒 timeout。
- 注意：`requirements.txt` 仍列 `python-telegram-bot>=20.0`，但傳輸層已改用 httpx；移除該依賴是已知待辦（見 handoffs），**屬於依賴清理、非行為變更**——若要動需走正常 PR，不在「改 workflow 行為」紅線內，但仍建議先與使用者確認。

## 6. 狀態持久化（`state_manager.py`）

- 讀寫 `data_store/*.json`：`read_json` / `write_json`(ensure_ascii=False 保中文) / `update_json` / `append_to_list_json`。
- 所有操作 fail-safe（記 log 不丟例外）。
- 推播相關 state：`alert_dedup.json`、`alert_routing_state.json`、`brief_sent_today.json`、`alerts_log.csv`、`layer_trump_classifier_state.json`（tag_attacher 讀）。

## 7. 紅線

- 改推播文案時保持**中性描述**，不得寫成「建議買 / 賣」。
- 不改去重 / 配額 / cooldown 的數值與行為，除非使用者明確要求（會直接影響洗版與成本）。
- 不主動觸發額外收費推播管道。
