# Kevin Trading Monitor — Taiwan Market Clock & Trump Monitor Handoff

> **日期**: 2026-07-16  
> **里程碑**: 修正台北市場時間、拆穿假 Trump 監控，改成 all-post capture + live source health  
> **承接**: `2026-07-16-trading-monitor-mission-control.md`  
> **下一篇**: PR #7 merge / production activation / exchange-calendar support

---

## 1. 執行摘要

Kevin 指出兩個問題：市場開收盤時間錯誤，以及 Trump 發文沒有照要求完整擷取。兩者皆經 repo 與 live GitHub Actions 驗證為真。

市場時間方面，舊系統把 brief 發送時間冒充交易所開收盤時間：08:30 被稱為台股開盤；美股夏令開盤被寫成 22:00，而真正核心開盤是台北 21:30。現在所有 user-facing copy 以 Asia/Taipei 為唯一主顯示：

- 台股正式交易 09:00–13:30；08:30 只能稱盤前。
- 美股夏令 21:30–翌日 04:00。
- 美股冬令 22:30–翌日 05:00。

Trump 方面，舊程式把 CNN broad archive 的非空回應當 live feed，造成 2026-07 寫入 2023-01 歷史貼文；同時 classifier/runner 明確丟棄 Tier 3，只推 Tier 1/2。現在分類只決定提示強度，不決定是否擷取或送達。

最終 live probe 證實：GitHub-hosted runner 目前無法使用官方 Truth Social API（HTTPStatusError）；可用的是持續更新的 CNN mirror。系統會擷取並送出 mirror 提供的每一則新活動，但不能聲稱 mirror 與官方 100% 一致。這項限制已進 health state、Mission Control、文件與 CI。

---

## 2. Canonical market clock

新增 `src/config/market_clock.py`，集中管理：

- Taiwan regular session: 09:00–13:30 Asia/Taipei
- U.S. regular session: 09:30–16:00 America/New_York
- U.S. DST → Taipei 21:30–04:00 next day
- U.S. standard → Taipei 22:30–05:00 next day
- DST conversion / session diagnostics / corrected brief copy

已修：

- `market_brief.yml`
- `signal_scan_eod.yml`
- `signal_scan_intraday.yml`
- `brief_sanity.yml`
- `iv_history_update.yml` comments
- `position_check.yml` comments
- `run_market_brief.py`
- `run_brief_sanity.py`
- `scripts/preview_briefs.py`

正確 dispatch：

- TW pre-open brief 08:30，文案明示正式開盤 09:00。
- TW close brief 13:40，正式收盤 13:30。
- U.S. open brief: DST 21:30 / standard 22:30.
- U.S. EOD brief: DST 04:30 / standard 05:30.
- U.S. EOD signal scan: DST 04:15 / standard 05:15.
- Brief sanity: 23:45 / 23:55，並檢查同日凌晨的 us_midday / us_eod。

限制：目前 regular weekday clock + DST 是正確的，但尚未接交易所 holiday / special early-close calendar。程式明示 `holiday_aware=false`，不得假裝已支援。

---

## 3. 舊 Trump 監控的真實問題

### 3.1 假 live source

舊 primary source：

```text
https://ix.cnn.io/data/truth-social/truth_archive.json
```

非空即成功，沒有 freshness validation。`trump_seen_posts.json` 在 2026-07-15 出現 2023-01 貼文，證實 current isolation 失效。

### 3.2 Tier 3 被丟掉

舊 classifier：

```python
if tier == "tier3":
    continue
```

舊 runner 也只送 Tier 1/2。這與「表面和股票無關仍可能涉及戰爭、政策、外交、監管」的需求相反。

### 3.3 其他漏文邊界

對抗式檢查再找到：

- 巨大 mirror cold start 可能灌爆歷史資料。
- 超長貼文分段後，早期分段成功可能過早 mark seen，導致後段失敗後永不重送。
- 沒有文字的純圖片／影片／連結貼文可能被過濾。
- arbitrary post text 用 HTML parse mode 可能發送失敗。

上述均已修正。

---

## 4. 新 Trump monitoring contract

### Source priority / honesty

1. Official Truth Social public API.
2. CNN mirror only when newest timestamp <= 48h old.
3. Neither current → `unavailable`, workflow red, Mission Control P0, throttled Telegram warning.

健康不再由「回傳非空」決定，而是由最新 timestamp、來源狀態、delivery state 決定。

### All-post capture

從 capture checkpoint 起，所有 source 提供的新活動都保留：

- original posts
- replies
- ReTruths
- Tier 3 / no keyword match
- media-only / textless / link-only posts
- long posts

Tier 只控制 audible/silent：

- Tier 1/2 → normal notification
- Tier 3-only → silent notification，但仍送達

### Cold start / archive bound

CNN mirror 含多年資料。現在：

- 每輪按 timestamp 取最新 1,000 筆。
- 首次啟用只 backfill 24 小時。
- capture checkpoint 持久化，短暫 downtime 後可補送。
- timestamp-invalid rows 排除並計入 health gap。

### Delivery correctness

- Plain-text Telegram mode，避免 post text 被當 HTML。
- 長貼文不截斷，分段送出。
- 只有最後一段成功才 mark whole post seen。
- 中途失敗寧可下輪重複，不可漏後段。
- media-only post 顯示 `[無文字內容]`、URL、附件數，不可刪掉。

---

## 5. Live source proof

Final inspected CI head:

```text
6b44be187d1e893be9eb67b995994ca5cdca01d3
```

GitHub Actions run #85:

- tests: **382 passed / 1 skipped in 5.47s**
- `trump-source-probe`: success
- source: `cnn_historical_archive`
- latest post: `2026-07-16T03:15:35.234000+00:00`
- latest Taipei time: **2026-07-16 11:15**
- source raw rows: **34,699**
- bounded rows: **1,000 / 1,000**
- official API: `unavailable`
- official error: `HTTPStatusError`

Honest interpretation:

- Current mirror path works from GitHub-hosted runner.
- Official API path does not.
- Every new activity supplied by the mirror after checkpoint is captured/delivered.
- **100% official completeness is not independently verified.**

CI includes a blocking, content-free live probe. If freshness/source fails later, PR/workflow cannot remain green and cannot claim healthy monitoring.

---

## 6. Mission Control changes

New Trump source section shows only safe health metadata:

- status/current source
- official and mirror attempts
- latest post/check time
- raw/bounded/eligible/new/delivered counts
- capture checkpoint/backfill
- capture/keyword policy
- delivery status
- completeness limitation

No post text is included in public Mission Control.

Attention rules:

- no health / stale → P1
- no current source → P0
- delivery partial → P0
- not all-post / keyword acts as filter → P0
- mirror healthy but official unavailable → P2 explicit warning

---

## 7. Main files

- `src/config/market_clock.py`
- `src/runners/run_market_brief.py`
- `src/runners/run_brief_sanity.py`
- `.github/workflows/market_brief.yml`
- `.github/workflows/signal_scan_eod.yml`
- `.github/workflows/signal_scan_intraday.yml`
- `.github/workflows/brief_sanity.yml`
- `src/config/rss_sources.py`
- `src/data/trump_truth.py`
- `src/layers/trump_classifier.py`
- `src/runners/run_trump_monitor.py`
- `src/runners/run_trump_source_probe.py`
- `.github/workflows/trump_monitor.yml`
- `.github/workflows/ci.yml`
- `src/storage/mission_control_store.py`
- `src/dashboard/build_mission_control.py`
- `docs/market_clock_and_trump_monitor.md`

---

## 8. Tests added/updated

- `tests/test_market_clock_taipei.py`
- `tests/test_run_brief_sanity.py`
- `tests/test_trump_all_posts.py`
- `tests/test_trump_media_only.py`
- `tests/test_telegram_privacy.py`
- Mission Control smoke/contract tests

Coverage includes exact DST conversion, correct cron mapping, sanity deadlines, stale mirror rejection, live-source bound, Tier 3 delivery, replies/ReTruths, media-only posts, cold start, checkpoint reuse, no truncation, final-chunk acknowledgement and explicit source failure.

---

## 9. Remaining yellow flags

1. Official Truth Social API is currently inaccessible from GitHub runner.
2. CNN mirror parity with official Truth Social cannot be proven.
3. Mirror freshness threshold 48h may alert during unusually long posting silence; this is preferable to silently accepting stale data.
4. Exchange holiday/special early-close support still needs a maintained exchange calendar.
5. PR #7 remains open / ready for review; do not merge without owner instruction.

---

## 10. Next session

1. Read this handoff, `docs/market_clock_and_trump_monitor.md`, PR #7 and Issue #6.
2. Check latest PR head after docs commits and ensure both CI jobs are green.
3. Review live probe artifact; do not infer official completeness from mirror freshness.
4. Update PR/Issue with final head/test/source result.
5. Do not merge unless Kevin explicitly authorizes it.
