# Taiwan-first market clock and Trump Truth Social monitoring

Date: 2026-07-16  
Status: implemented in PR #7; live source path verified from GitHub Actions

## 1. Canonical market times

All user-facing times are **Asia/Taipei**. GitHub Actions cron expressions remain UTC because that is the scheduler format, but UTC must never be shown to Kevin as the primary time.

### Taiwan equities

- Order entry / pre-open: 08:30
- Regular trading opens: **09:00**
- Regular trading closes: **13:30**

Therefore an 08:30 message is a **台股盤前 brief**, not a 台股開盤 brief.

### U.S. core equity session

NYSE/Nasdaq regular session is 09:30-16:00 America/New_York.

Converted to Taipei:

| U.S. clock | Taipei open | Taipei close |
|---|---:|---:|
| Daylight time | 21:30 | 04:00 next day |
| Standard time | 22:30 | 05:00 next day |

The system must distinguish:

- exact exchange open/close
- a premarket observation message
- an after-close brief dispatched after data has settled

A 22:00 daylight-time message is 30 minutes after the U.S. opening bell; it must not be labeled as the exact open.

### Known limitation

`market_clock.py` is exact for regular weekday clock conversion and U.S. DST. It does not claim holiday or special early-close awareness. Those require a maintained exchange-calendar source. The limitation is explicit in `session_snapshot()` rather than being hidden.

## 2. Corrected brief and scan dispatch

### Market Brief

- Taiwan pre-open brief: 08:30; copy states formal open is 09:00.
- Taiwan close brief: 13:40 primary, after formal 13:30 close.
- U.S. exact open brief:
  - 21:30 Taipei in daylight time
  - 22:30 Taipei in standard time
- U.S. EOD brief:
  - 04:30 Taipei in daylight time
  - 05:30 Taipei in standard time
- U.S. midday brief:
  - 01:00 Taipei in daylight time
  - 02:00 Taipei in standard time

Backup crons run 30 minutes later and are deduplicated.

### Signal Scan EOD

The EOD signal scan now runs 15 minutes after the actual core close:

- 04:15 Taipei in daylight time
- 05:15 Taipei in standard time

Both UTC crons exist, with a DST gate so only the correct one runs.

### Signal Scan Intraday

The cron covers a wide UTC range, but the runner's authoritative gate remains 09:30-16:00 ET. Comments now show the correct UTC and Taipei conversions.

## 3. Why the old Trump monitor was not real monitoring

The previous primary source was a broad CNN Truth Social archive. The repository's `trump_seen_posts.json` was populated on 2026-07-15 with January 2023 rows, proving the old pipeline did not correctly isolate current activity. Because the archive JSON was non-empty, the code did not attempt the official Truth Social fallback.

The old pipeline also contained:

```python
if tier == "tier3":
    continue
```

and the runner sent only Tier 1 / Tier 2 posts. This contradicted the requirement to capture posts even when they appear unrelated to stocks. War, policy, diplomacy, regulation or sentiment can be relevant without matching a predefined market keyword.

## 4. Actual source availability on 2026-07-16

A blocking source probe was run from a GitHub-hosted Actions runner, without exposing post text.

Result:

```json
{
  "status": "healthy",
  "source": "cnn_historical_archive",
  "latest_post_at": "2026-07-15T22:54:07.591000+00:00",
  "raw_count": 28037,
  "official_api_status": "unavailable",
  "official_api_error": "HTTPStatusError"
}
```

Converted to Taipei, the newest mirrored activity was **2026-07-16 06:54**.

The honest conclusion is:

- The official Truth Social public API is **not currently reachable from the GitHub runner**.
- The CNN archive endpoint is currently updating and can serve as a fresh mirror.
- The system is not allowed to call that mirror healthy merely because it is non-empty; the newest timestamp must remain within 48 hours.
- Mission Control exposes that the current source is a mirror and the official API attempt failed.

## 5. New Trump monitoring contract

### Source priority

1. Official Truth Social public account lookup and statuses API.
2. CNN archive only if its latest post is demonstrably fresh within 48 hours.
3. Otherwise status is `unavailable`; no stale archive is presented as live.

The configured official account ID remains a fallback if account lookup fails.

### Bounded source window and cold start

The fresh CNN mirror returned about 28,037 historical rows. Processing that entire archive on every five-minute run would be wasteful, and treating it all as new would flood Telegram.

The monitor therefore:

- sorts activities by timestamp
- retains only the latest 1,000 source rows per poll
- establishes a capture checkpoint on first activation
- backfills only the previous 24 hours on first activation
- reuses the checkpoint on later runs so temporary workflow downtime is recovered
- excludes timestamp-invalid rows and reports their count in health state

This means **all activity from activation onward** is captured, while 2023–2026 historical rows are not falsely delivered as new.

### All-post capture

Every unseen activity after the capture checkpoint is normalized and retained:

- original posts
- replies
- ReTruths
- posts without market keywords
- Tier 3 posts
- text plus URL, activity type, media count and original account metadata

Tier is metadata only. It controls notification urgency but never capture or delivery eligibility.

### Delivery

All new posts are delivered to Telegram.

- Tier 1 / Tier 2 chunks use a normal notification.
- Tier 3-only chunks are silent but still delivered.
- Long posts are split into multiple Telegram messages without truncating the text.
- Plain-text Telegram mode is used so arbitrary post text is not interpreted as HTML.
- Posts are marked seen only after their delivery chunk succeeds, so a failed chunk is retried.

### State

- `trump_posts_archive.json`: rolling, deduplicated archive of captured posts.
- `trump_seen_posts.json`: successfully delivered IDs.
- `trump_monitor_health.json`: source status, attempts, latest post time, source counts, checkpoint, delivery status and policies.
- `layer_trump_classifier_state.json`: all newly classified posts, including Tier 3.
- Mission Control: current source, official/mirror attempts, freshness, counts and capture policy, with no post text.

### Failure behavior

If there is no current source:

- runner exits non-zero
- workflow is visibly red
- `trump_monitor_health.json` says `unavailable`
- Mission Control raises a P0 source-health item
- Telegram receives a throttled source-unavailable warning
- no empty or stale response is called healthy

## 6. Continuous live-source proof

Mock tests are not proof of external availability. PR CI includes a blocking `trump-source-probe` job that runs from a GitHub-hosted runner and writes only:

- source status
- source name
- latest post timestamp
- bounded fetched count
- source attempts and error types

It never writes post content. If this job becomes red, the correct conclusion is that the current GitHub-hosted architecture cannot access a reliable fresh source; the PR/workflow must not claim otherwise.
