# positions.json 規格

放在 `data_store/positions.json`(該目錄已 gitignore)。**不要把真實部位 commit 到 git**。

## 三模式(由環境變數 `POSITION_MODE` 控制)

| Mode | 行為 | 適用情境 |
|------|------|---------|
| `mode_1` | 必填。positions.json 為空 → `logger.warning` 一次 + Telegram 推一次 + 寫 `data_store/mode1_warned.flag` 防重複,系統繼續以空部位運行 | 你重視部位準確性,不容許忘記更新 |
| `mode_2` | 選填(**預設**)。空部位 → 靜默,系統照跑 | 你想觀察訊號,部位資料只在 LEAPS PnL / Short Delta / Hedge DTE / Drawdown 觸發時才需要 |
| `mode_3` | 不填。完全不讀檔,所有 management getter 直接回 `[]`、snapshot `total_estimated_value=None` | 純訊號模式,不關心部位管理 |

> 改 mode 後想重置 mode_1 警告 → 刪 `data_store/mode1_warned.flag` 即可。

## Schema

```json
{
  "stocks": [
    {
      "symbol": "NVDA",
      "shares": 100,
      "avg_cost": 480.50,
      "_example": false
    }
  ],
  "options": [
    {
      "id": "NVDA_2027C_120",
      "symbol": "NVDA",
      "type": "long_call",
      "strike": 120.0,
      "expiry": "2027-01-15",
      "contracts": 1,
      "cost_per_contract": 4250.0,
      "_example": false
    }
  ]
}
```

### 欄位說明

**stocks[]**
- `symbol`(必填)— 股票代號,大寫,例:`NVDA` / `2330.TW`
- `shares`(必填)— 股數
- `avg_cost`(選填)— 平均成本(目前未用,Phase 3 會用)
- `_example`(選填,bool)— `true` 視為範本不算真實部位,留作填表參考

**options[]**
- `symbol`(必填)— 標的代號
- `type`(必填)— 必為 `long_call` / `long_put` / `short_call` / `short_put` 之一
- `strike`(必填,float)— 履約價
- `expiry`(必填,字串)— 到期日 `YYYY-MM-DD`
- `contracts`(選填,預設 1)— 口數
- `cost_per_contract`(LEAPS 必填,float)— **整口成本(per contract)**,單位 USD,等於 `成交價 × 100`
  - 例:成交 `$42.50/share` × 1 口 = `cost_per_contract: 4250.0`
- `id`(建議填)— 唯一識別字串,觸發提醒時方便對照
- `_example`(選填,bool)— 同上

## 對沖認定(`hedge_dte_tracker` 用)

被視為「對沖部位」的條件(滿足任一即是):
- `symbol` 屬於 `ETF_HEDGE = ["QQQ", "SPY", "SMH", "SOXL"]` 的任何 long option
- 任何 `type == "long_put"`(個股保險型 put 也算)

## 範本(複製貼上即可,記得改 `_example: false`)

```json
{
  "stocks": [
    {
      "symbol": "NVDA",
      "shares": 0,
      "avg_cost": 0,
      "_example": true
    }
  ],
  "options": [
    {
      "id": "EXAMPLE_LEAPS",
      "symbol": "NVDA",
      "type": "long_call",
      "strike": 0,
      "expiry": "2027-01-15",
      "contracts": 1,
      "cost_per_contract": 0,
      "_example": true
    },
    {
      "id": "EXAMPLE_SHORT",
      "symbol": "NVDA",
      "type": "short_call",
      "strike": 0,
      "expiry": "2026-06-19",
      "contracts": 1,
      "_example": true
    }
  ]
}
```
