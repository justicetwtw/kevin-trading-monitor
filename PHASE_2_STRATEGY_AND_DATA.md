# PHASE 2: STRATEGY LOGIC + DATA INTEGRATION

> **For Claude Code**:這是策略邏輯與資料源整合階段。階段 1 已完成專案骨架(config / Telegram / health_check)。本階段要實作:
> - 全部 `src/data/*`(20 個資料抓取模組)
> - 全部 `src/indicators/*`(4 個技術指標模組)
> - 全部 `src/layers/*`(14 個 Layer 0/0+/F 模組)
> - 全部 `src/signals/*`(7 個訊號評分模組)
> - 全部 `src/management/*`(5 個部位管理模組)
> - 全部 `src/twstock/*`(3 個台股模組)
> - 補完 `src/alerts/*`(formatter/router/dedup/tag)
> - 全部 `src/runners/*`(13 個 runner)
> - 全部 `.github/workflows/*.yml`(13 個排程)
>
> 完成階段 2 後,使用者會在新對話交付 PHASE 3(EV 追蹤 + 20 年回測引擎)。

---

## 1. 階段 2 概述

### 1.1 設計原則

1. **資料優先,訊號其次**:資料源穩定才有訊號可信度;每個 fetcher 都要有 retry + fallback
2. **失敗不阻塞**:單一資料源失敗不能讓整個 scan 崩潰;用 `try/except + 預設值` 包覆
3. **快取為王**:同一交易日內重複呼叫的資料(價格、選擇權鏈)走 `data_store/price_cache.py`
4. **可離線回測**:所有 fetcher 都要回傳「可序列化」的 dict / DataFrame,方便階段 3 餵進回測引擎
5. **零硬編碼**:所有閾值、白名單、權重都從 `src/config/*` 讀,絕不寫死在邏輯模組

### 1.2 模組依賴圖

```
config/        ← settings / universe / thresholds / keywords
   ↓
data/          ← yfinance / FRED / SEC / RSS / scraping(下游全部依賴它)
   ↓
indicators/    ← 技術指標(純函式,輸入 DataFrame → 輸出 series/dict)
   ↓
layers/        ← Layer 0(macro)/ 0+(events)/ F(fundamental)
   ↓                              ↓
signals/  ←─────────────────  modifier_aggregator
   ↓ + management/
   ↓ + twstock/
   ↓
alerts/        ← formatter → router → dedup → telegram_bot
   ↓
runners/       ← GitHub Actions 進入點
```

### 1.3 學習鎖再強調(階段 2 必須在程式碼層面實作)

| # | 規則 | 實作位置 |
|---|---|---|
| 1 | 不買 DTE < 365 天的 Long Call | `signals/leaps_entry_scorer.py` 否決 |
| 2 | 不在 IVR < 30 時 short premium | `signals/sell_call_scorer.py` + `sell_put_scorer.py` 否決 |
| 3 | 不在財報前 7 天建 short premium | `signals/veto_checker.py` |
| 4 | 不在連 3 天 VIX > 30 時建 long premium | `signals/veto_checker.py` |
| 5 | Tier C(PLTR/TSLA)不賣 PUT | `signals/sell_put_scorer.py` 白名單檢查 |
| 6 | 單股 2x ETF 持現股波段+不賣 covered call(v4.1 反向) | LEAPS 仍擋(不對 2x ETF 開);新增 `signals/veto_checker.check_lock_2x_etf_no_short_call` 擋 covered call |

---

## 2. 完整實作清單

### 2.1 src/data/(20 個檔案)

```
src/data/
├── __init__.py
├── price_data.py                # yfinance 包裝(歷史價、即時報價、選擇權鏈)
├── greeks_calculator.py         # Black-Scholes Delta/Gamma/Theta/Vega
├── iv_rank.py                   # IVR/IVP 計算(維護 252 日 IV 歷史)
├── trump_truth.py               # CNN JSON 鏡像 + Truth Social fallback
├── rss_feeds.py                 # Reuters / AP / Fed RSS
├── sec_edgar.py                 # 8-K filings(EdgarTools)
├── form4_insider.py             # Form 4 内部人交易
├── institutional_holdings.py    # 13F 機構持股
├── earnings_calendar.py         # 財報日曆(yfinance.calendar)
├── fundamentals.py              # 基本面儀表板(P/E / PEG / FCF Yield)
├── analyst_actions.py           # 分析師上下調目標價
├── fred_api.py                  # FRED 殖利率/HY 利差/DXY
├── breadth_data.py              # StockCharts 市場廣度
├── bubble_indicators.py         # Buffett Indicator / Shiller CAPE / 集中度
├── put_call_ratio.py            # CBOE PCR(主)+ yfinance ^CPC(備)
├── vix_structure.py             # VIX / VIX9D / VIX3M 結構
├── tsmc_revenue.py              # MOPS 月營收
├── etf_flows.py                 # SMH/QQQ ETF 資金流(etf.com scraping)
├── twstock_data.py              # 台股價量(twstock 套件 + yfinance .TW 後綴)
└── twstock_active_etf.py        # 主動 ETF 持股(證交所 ETF 專區)
```

### 2.2 src/indicators/(4 個檔案)

```
src/indicators/
├── __init__.py
├── basic.py                     # RSI / BB / MA / ADX(pandas-ta-classic)
├── volume.py                    # 成交量分析、量價背離
├── pattern.py                   # 阻力/支撐區、52W 高低距離
└── distribution_days.py         # IBD 派發日演算法
```

### 2.3 src/layers/(14 個檔案)

```
src/layers/
├── __init__.py
├── macro_regime.py              # Layer 0.1 宏觀體制
├── breadth.py                   # Layer 0.2 市場廣度
├── distribution.py              # Layer 0.3 派發日
├── bubble.py                    # Layer 0.4 泡沫偵測
├── put_call.py                  # Layer 0.5 PCR
├── vix_structure_layer.py       # Layer 0.6 VIX 結構
├── aaii_sentiment.py            # Layer 0.7 AAII 情緒
├── trump_classifier.py          # Layer 0+.1 Trump 三級分類
├── news_classifier.py           # Layer 0+.2 RSS 新聞分類
├── fundamentals_dashboard.py    # Layer F.1 基本面
├── analyst_dashboard.py         # Layer F.2 分析師動向
├── institutional_dashboard.py   # Layer F.3 13F 動向
├── insider_signals.py           # Layer F.4 Insider Cluster Buying
└── modifier_aggregator.py       # 整合所有 Layer 0/F → 統一 modifier dict
```

### 2.4 src/signals/(7 個檔案)

```
src/signals/
├── __init__.py
├── base_scorer.py               # 共用評分基底(權重縮放、normalize)
├── sell_call_scorer.py          # 系統 #1 賣 CALL
├── sell_put_scorer.py           # 系統 #2 賣 PUT (Wheel)
├── leaps_entry_scorer.py        # 系統 #3 LEAPS 進場
├── veto_checker.py              # 否決乘數 ×0 檢查
├── final_scorer.py              # 整合 base + modifier + veto + 標籤 → 最終分數
└── exit_rules.py                # 5 大出場規則 + value_thesis 例外
```

### 2.5 src/management/(5 個檔案)

```
src/management/
├── __init__.py
├── leaps_pnl_tracker.py         # +50/+100/-30/-40 觸發
├── short_delta_monitor.py       # |Delta| > 0.35 警報
├── hedge_dte_tracker.py         # 對沖 DTE < 45 天提醒
├── account_drawdown.py          # -10/-20/-30 三級防線
└── current_positions.py         # positions.json 載入 + 三模式判斷
```

### 2.6 src/twstock/(3 個檔案)

```
src/twstock/
├── __init__.py
├── twstock_signals.py           # 00631L + 2330 三級加碼(A/B/C)
├── active_etf_signals.py        # 主動 ETF 三級訊號(Tier 1/2/3)
└── twstock_alerts.py            # 台股訊號統一格式化
```

### 2.7 src/alerts/(補完 4 個)

```
src/alerts/
├── alert_formatter.py           # 訊號 → Telegram 訊息字串(HTML 格式)
├── alert_router.py              # P0/P1/P2/P3 路由 + 頻率上限
├── deduplication.py             # 同一 (symbol, signal_type) 24h 去重
└── tag_attacher.py              # 60 分內 Trump Tier 1 → 加 ⚠ 標籤
```

### 2.8 src/runners/(13 個 runner)

```
src/runners/
├── run_trump_monitor.py
├── run_news_monitor.py
├── run_sec_monitor.py
├── run_signal_scan_intraday.py
├── run_signal_scan_eod.py
├── run_macro_layer.py
├── run_institutional_scan.py
├── run_earnings_update.py
├── run_tsmc_revenue.py
├── run_aaii_update.py
├── run_twstock_signal.py
└── (run_health_check.py 階段 1 已完成)
```

### 2.9 .github/workflows/(13 個 yml)

```
.github/workflows/
├── trump_monitor.yml            # 每 5 分鐘
├── news_monitor.yml             # 每 10 分鐘
├── sec_monitor.yml              # 每小時
├── signal_scan_intraday.yml     # 美股盤中每 15 分鐘
├── signal_scan_eod.yml          # 美股收盤後每日
├── macro_layer.yml              # 每日
├── institutional_scan.yml       # 每日
├── twstock_active_etf.yml       # 台股收盤後每日
├── earnings_calendar.yml        # 每日
├── tsmc_revenue.yml             # 每月 10 日
├── aaii_sentiment.yml           # 每週四
└── (health_check.yml 階段 1 已完成)
```

---

## 3. 階段 2 完成標準

### 3.1 功能驗收

完成階段 2 後,使用者執行以下流程應全部成功:

1. **手動觸發 macro_layer.yml** → Telegram 收到當日 Layer 0 摘要
2. **手動觸發 signal_scan_eod.yml** → Telegram 收到掃描結果(可能是「今日無 ≥70 訊號」)
3. **手動觸發 trump_monitor.yml** → 即使無新貼文也應在 log 顯示「No new posts」並退出
4. **手動觸發 institutional_scan.yml** → 至少抓到 1 家機構的 13F 並寫入 `data_store/`
5. **手動觸發 twstock_active_etf.yml** → 至少抓到主動 ETF 持股並寫入

### 3.2 資料完整性驗收

```
data_store/
├── price_history.parquet         ← 應含全 ALL_TICKERS_SCAN 1 年日線
├── trump_seen_posts.json         ← 應有 {} 或實際 post id list
├── earnings_calendar.json        ← 應有 14 檔白名單未來 60 天財報
├── layer0_history.json           ← 應有當日 7 個子模組 modifier 與分數
├── distribution_days_log.json    ← 應有 SPY 25 日內派發日紀錄
└── alerts_log.csv                ← 應有 header + 至少 health_check 紀錄
```

### 3.3 程式碼品質驗收

- 每個 fetcher 必須有 `try/except + loguru.error` 包覆
- 所有外部 API 呼叫使用 `tenacity.retry`(3 次,指數退避)
- 所有時間戳統一用 `datetime` + `pytz`,絕不裸 `datetime.now()`
- `pandas_ta_classic` import 為 `import pandas_ta_classic as ta`(注意是 `pandas_ta_classic` 不是 `pandas_ta`)

---

## 4. requirements.txt 更新

階段 1 的 `requirements.txt` 需要更新——`pandas-ta` 已停止維護,改用社群維護的 fork `pandas-ta-classic`:

```txt
# Core
pandas>=2.0.0
numpy>=1.24.0,<2.0.0          # pandas-ta-classic 對 numpy 2.x 尚未完全相容,鎖定 1.x

# Data sources
yfinance>=0.2.40
pandas-datareader>=0.10.0
fredapi>=0.5.1
edgartools>=2.0.0
feedparser>=6.0.0
httpx>=0.25.0
selectolax>=0.3.17
beautifulsoup4>=4.12.0           # 部分 scraping 用 BS4 較穩

# Technical analysis(★ 注意:pandas-ta 改為 pandas-ta-classic)
pandas-ta-classic>=0.4.0
scipy>=1.11.0

# Storage
pyarrow>=14.0.0

# Telegram
python-telegram-bot>=20.0

# Backtesting (階段 3)
vectorbt>=0.26.0

# Utilities
pytz>=2024.1
python-dateutil>=2.8.2
tenacity>=8.2.0
loguru>=0.7.0
requests>=2.31.0

# Twstock(台股)
twstock>=1.3.0                   # 台股報價套件(yfinance 替補)

# Testing
pytest>=7.4.0
pytest-cov>=4.1.0
```

**Import 範例(全專案統一)**:

```python
import pandas_ta_classic as ta  # ★ 注意是 pandas_ta_classic

df.ta.rsi(length=14, append=True)          # 仍可用 .ta accessor
df.ta.bbands(length=20, std=2, append=True)
df.ta.adx(length=14, append=True)
```

---

## 5. src/data/ 資料抓取層

### 5.1 src/data/__init__.py

```python
# 空檔
```

### 5.2 src/data/price_data.py

```python
"""yfinance 價格資料 + 選擇權鏈包裝"""

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import TIMEZONE_US_MARKET
from src.storage.state_manager import DATA_STORE_DIR

PRICE_CACHE_PATH = DATA_STORE_DIR / "price_history.parquet"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_history(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
) -> pd.DataFrame:
    """抓取單一標的歷史價格"""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=False)
        if df.empty:
            logger.warning(f"Empty history for {symbol}")
            return pd.DataFrame()
        df.index = df.index.tz_convert(TIMEZONE_US_MARKET) if df.index.tz else df.index
        df["Symbol"] = symbol
        return df
    except Exception as e:
        logger.error(f"fetch_history({symbol}) failed: {e}")
        raise


def fetch_history_batch(
    symbols: list,
    period: str = "1y",
    interval: str = "1d",
    sleep_sec: float = 0.5,
) -> dict:
    """批次抓取多檔(序列化以免被 rate limit)"""
    out = {}
    for s in symbols:
        try:
            out[s] = fetch_history(s, period=period, interval=interval)
        except Exception as e:
            logger.error(f"Skipping {s}: {e}")
            out[s] = pd.DataFrame()
        time.sleep(sleep_sec)
    return out


def get_latest_price(symbol: str) -> Optional[float]:
    """即時報價(15-20 分延遲)"""
    try:
        df = fetch_history(symbol, period="2d", interval="1m")
        if df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception as e:
        logger.error(f"get_latest_price({symbol}) failed: {e}")
        return None


def get_52w_high_low(symbol: str) -> dict:
    """52 週高低點"""
    df = fetch_history(symbol, period="1y")
    if df.empty:
        return {"high": None, "low": None, "current": None, "pct_from_high": None}
    high = float(df["High"].max())
    low = float(df["Low"].min())
    current = float(df["Close"].iloc[-1])
    return {
        "high": high,
        "low": low,
        "current": current,
        "pct_from_high": (current - high) / high,
        "pct_from_low": (current - low) / low,
    }


def fetch_option_chain(symbol: str, expiry: Optional[str] = None) -> dict:
    """抓取選擇權鏈
    回傳: {"calls": DataFrame, "puts": DataFrame, "expiry": str, "underlying": float}
    """
    try:
        ticker = yf.Ticker(symbol)
        expiries = ticker.options
        if not expiries:
            logger.warning(f"No options for {symbol}")
            return {}

        chosen = expiry if expiry in expiries else expiries[0]
        chain = ticker.option_chain(chosen)
        underlying = get_latest_price(symbol)
        return {
            "calls": chain.calls,
            "puts": chain.puts,
            "expiry": chosen,
            "underlying": underlying,
            "all_expiries": list(expiries),
        }
    except Exception as e:
        logger.error(f"fetch_option_chain({symbol}) failed: {e}")
        return {}


def find_option_by_dte_delta(
    symbol: str,
    target_dte_min: int,
    target_dte_max: int,
    target_delta: float,
    option_type: str = "call",  # "call" or "put"
) -> Optional[dict]:
    """根據 DTE + Delta 範圍找最接近的選擇權合約"""
    from src.data.greeks_calculator import calc_delta

    ticker = yf.Ticker(symbol)
    expiries = ticker.options
    if not expiries:
        return None

    underlying = get_latest_price(symbol)
    if underlying is None:
        return None

    today = datetime.now(TIMEZONE_US_MARKET).date()
    candidates = []

    for exp_str in expiries:
        exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        dte = (exp_date - today).days
        if not (target_dte_min <= dte <= target_dte_max):
            continue

        chain = ticker.option_chain(exp_str)
        df = chain.calls if option_type == "call" else chain.puts

        for _, row in df.iterrows():
            iv = row.get("impliedVolatility", 0.3)
            strike = float(row["strike"])
            delta = calc_delta(
                S=underlying, K=strike, T=dte / 365, r=0.045,
                sigma=iv, option_type=option_type,
            )
            candidates.append({
                "expiry": exp_str,
                "dte": dte,
                "strike": strike,
                "bid": float(row.get("bid", 0)),
                "ask": float(row.get("ask", 0)),
                "iv": iv,
                "delta": delta,
                "delta_diff": abs(abs(delta) - abs(target_delta)),
            })

    if not candidates:
        return None
    return min(candidates, key=lambda x: x["delta_diff"])


def cache_price_history(symbols: list, period: str = "1y") -> None:
    """更新價格快取(parquet)"""
    data = fetch_history_batch(symbols, period=period)
    rows = []
    for sym, df in data.items():
        if df.empty:
            continue
        df = df.copy()
        df["Symbol"] = sym
        rows.append(df.reset_index())
    if rows:
        combined = pd.concat(rows, ignore_index=True)
        combined.to_parquet(PRICE_CACHE_PATH, compression="snappy")
        logger.info(f"Cached {len(rows)} symbols → {PRICE_CACHE_PATH}")


def load_cached_history(symbol: str) -> pd.DataFrame:
    """從 cache 載入單檔(階段 3 回測用)"""
    if not PRICE_CACHE_PATH.exists():
        return pd.DataFrame()
    df = pd.read_parquet(PRICE_CACHE_PATH)
    return df[df["Symbol"] == symbol].copy()
```

### 5.3 src/data/greeks_calculator.py

```python
"""Black-Scholes Greeks 計算(IV 由 yfinance 取得)"""

import math
from scipy.stats import norm


def calc_d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple:
    """Black-Scholes d1 / d2"""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0, 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def calc_delta(
    S: float, K: float, T: float, r: float, sigma: float,
    option_type: str = "call",
) -> float:
    """Delta"""
    d1, _ = calc_d1_d2(S, K, T, r, sigma)
    if option_type == "call":
        return float(norm.cdf(d1))
    return float(norm.cdf(d1) - 1)


def calc_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1, _ = calc_d1_d2(S, K, T, r, sigma)
    return float(norm.pdf(d1) / (S * sigma * math.sqrt(T)))


def calc_theta(
    S: float, K: float, T: float, r: float, sigma: float,
    option_type: str = "call",
) -> float:
    """每日 Theta(年化 / 365)"""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1, d2 = calc_d1_d2(S, K, T, r, sigma)
    term1 = -(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T))
    if option_type == "call":
        term2 = -r * K * math.exp(-r * T) * norm.cdf(d2)
    else:
        term2 = r * K * math.exp(-r * T) * norm.cdf(-d2)
    return (term1 + term2) / 365


def calc_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0:
        return 0.0
    d1, _ = calc_d1_d2(S, K, T, r, sigma)
    return float(S * norm.pdf(d1) * math.sqrt(T) / 100)  # per 1% IV change


def calc_all_greeks(
    S: float, K: float, T: float, r: float, sigma: float,
    option_type: str = "call",
) -> dict:
    return {
        "delta": calc_delta(S, K, T, r, sigma, option_type),
        "gamma": calc_gamma(S, K, T, r, sigma),
        "theta": calc_theta(S, K, T, r, sigma, option_type),
        "vega": calc_vega(S, K, T, r, sigma),
    }
```

### 5.4 src/data/iv_rank.py

```python
"""IV Rank / IV Percentile 計算(維護 252 日歷史)"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf
from loguru import logger

from src.storage.state_manager import DATA_STORE_DIR

IV_HISTORY_PATH = DATA_STORE_DIR / "iv_history.json"


def get_atm_iv(symbol: str) -> float:
    """取當下 ATM 選擇權的 IV(取最近 30-45 DTE 那期的 ATM)"""
    try:
        ticker = yf.Ticker(symbol)
        if not ticker.options:
            return None
        # 取最接近 30 天的到期
        from src.config.settings import TIMEZONE_US_MARKET
        today = datetime.now(TIMEZONE_US_MARKET).date()
        best_exp = None
        best_dte_diff = 999
        for exp in ticker.options:
            dte = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
            if 25 <= dte <= 50 and abs(dte - 35) < best_dte_diff:
                best_exp = exp
                best_dte_diff = abs(dte - 35)
        if not best_exp:
            best_exp = ticker.options[0]

        chain = ticker.option_chain(best_exp)
        underlying = float(ticker.fast_info.get("lastPrice", 0)) or float(
            ticker.history(period="1d")["Close"].iloc[-1]
        )

        # 找最接近 ATM 的 call 與 put,取平均 IV
        calls = chain.calls.copy()
        puts = chain.puts.copy()
        calls["dist"] = (calls["strike"] - underlying).abs()
        puts["dist"] = (puts["strike"] - underlying).abs()
        atm_call_iv = calls.nsmallest(1, "dist")["impliedVolatility"].iloc[0]
        atm_put_iv = puts.nsmallest(1, "dist")["impliedVolatility"].iloc[0]
        return float((atm_call_iv + atm_put_iv) / 2)
    except Exception as e:
        logger.error(f"get_atm_iv({symbol}) failed: {e}")
        return None


def update_iv_history(symbol: str) -> None:
    """每日跑一次,把當日 ATM IV 記錄下來"""
    iv = get_atm_iv(symbol)
    if iv is None:
        return
    today = datetime.now().strftime("%Y-%m-%d")

    history = {}
    if IV_HISTORY_PATH.exists():
        with open(IV_HISTORY_PATH) as f:
            history = json.load(f)

    if symbol not in history:
        history[symbol] = {}
    history[symbol][today] = iv

    # 保留最近 300 天
    if len(history[symbol]) > 300:
        sorted_dates = sorted(history[symbol].keys())
        for d in sorted_dates[:-300]:
            del history[symbol][d]

    with open(IV_HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


def calc_iv_rank(symbol: str, lookback: int = 252) -> dict:
    """計算 IVR / IVP
    IVR = (current_IV - min_IV) / (max_IV - min_IV) × 100
    IVP = % of days IV was below current
    """
    if not IV_HISTORY_PATH.exists():
        return {"ivr": None, "ivp": None, "current_iv": None, "samples": 0}

    with open(IV_HISTORY_PATH) as f:
        history = json.load(f)

    if symbol not in history or len(history[symbol]) < 30:
        return {"ivr": None, "ivp": None, "current_iv": None,
                "samples": len(history.get(symbol, {}))}

    sorted_items = sorted(history[symbol].items())[-lookback:]
    ivs = [v for _, v in sorted_items]
    current = ivs[-1]
    min_iv = min(ivs)
    max_iv = max(ivs)

    ivr = ((current - min_iv) / (max_iv - min_iv) * 100) if max_iv > min_iv else 50
    ivp = sum(1 for iv in ivs if iv < current) / len(ivs) * 100

    return {
        "ivr": round(ivr, 1),
        "ivp": round(ivp, 1),
        "current_iv": round(current, 4),
        "min_iv": round(min_iv, 4),
        "max_iv": round(max_iv, 4),
        "samples": len(ivs),
    }
```

### 5.5 src/data/trump_truth.py

```python
"""Trump Truth Social 抓取 - CNN JSON 鏡像為主,Truth API 為備"""

import json
import httpx
from datetime import datetime
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.rss_sources import TRUMP_TRUTH_SOURCES
from src.storage.state_manager import read_json, write_json

SEEN_POSTS_FILE = "trump_seen_posts.json"


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, max=8))
def fetch_from_cnn_mirror() -> list:
    """主要來源:CNN 鏡像(穩定且不需 auth)"""
    url = TRUMP_TRUTH_SOURCES["primary_cnn_mirror"]
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            data = r.json()
            # 結構通常是 list of posts,每則含 id, content, created_at
            return data if isinstance(data, list) else data.get("posts", [])
    except Exception as e:
        logger.warning(f"CNN mirror failed: {e}")
        return []


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, max=8))
def fetch_from_truth_api() -> list:
    """備援:Truth Social 公開 API"""
    url = TRUMP_TRUTH_SOURCES["fallback_truth_api"]
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            r = client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json",
                },
            )
            r.raise_for_status()
            return r.json() if isinstance(r.json(), list) else []
    except Exception as e:
        logger.warning(f"Truth API failed: {e}")
        return []


def fetch_recent_posts() -> list:
    """主備雙重來源"""
    posts = fetch_from_cnn_mirror()
    if not posts:
        logger.info("CNN mirror empty, trying Truth API")
        posts = fetch_from_truth_api()
    return posts


def filter_new_posts(posts: list) -> list:
    """過濾掉已經處理過的"""
    seen = read_json(SEEN_POSTS_FILE, default={})
    new_posts = []
    for p in posts:
        pid = str(p.get("id") or p.get("post_id") or "")
        if not pid or pid in seen:
            continue
        new_posts.append(p)
        seen[pid] = {
            "seen_at": datetime.utcnow().isoformat(),
            "created_at": p.get("created_at", ""),
        }
    # 限制 seen 大小(保留最近 2000 個)
    if len(seen) > 2000:
        sorted_items = sorted(seen.items(), key=lambda x: x[1]["seen_at"])
        seen = dict(sorted_items[-2000:])
    write_json(SEEN_POSTS_FILE, seen)
    return new_posts


def extract_text(post: dict) -> str:
    """從不同來源結構中拉出純文字內容"""
    if "content" in post:
        # Truth Social API 的 content 是 HTML
        from selectolax.parser import HTMLParser
        try:
            return HTMLParser(post["content"]).text(strip=True)
        except Exception:
            return post["content"]
    return post.get("text", "") or post.get("body", "")
```

### 5.6 src/data/rss_feeds.py

```python
"""RSS 新聞抓取 - Reuters / AP / Fed"""

from datetime import datetime, timedelta
import feedparser
from loguru import logger

from src.config.rss_sources import RSS_SOURCES, NEWS_FILTER_KEYWORDS


def fetch_feed(url: str, lookback_minutes: int = 60) -> list:
    """抓單個 RSS,只回傳指定時間內的"""
    try:
        feed = feedparser.parse(url)
        cutoff = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        items = []
        for entry in feed.entries:
            pub = entry.get("published_parsed") or entry.get("updated_parsed")
            if pub:
                pub_dt = datetime(*pub[:6])
                if pub_dt < cutoff:
                    continue
            items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", ""),
                "published": entry.get("published", ""),
                "source": url,
            })
        return items
    except Exception as e:
        logger.error(f"fetch_feed({url}) failed: {e}")
        return []


def fetch_all_feeds(lookback_minutes: int = 15) -> list:
    """全 RSS 來源抓取"""
    all_items = []
    for name, url in RSS_SOURCES.items():
        items = fetch_feed(url, lookback_minutes)
        for it in items:
            it["feed_name"] = name
        all_items.extend(items)
    return all_items


def filter_by_keywords(items: list) -> list:
    """關鍵字過濾(macro/geopolitical/tech)"""
    flat_keywords = []
    for cat_kws in NEWS_FILTER_KEYWORDS.values():
        flat_keywords.extend(kw.lower() for kw in cat_kws)

    filtered = []
    for it in items:
        text = (it.get("title", "") + " " + it.get("summary", "")).lower()
        matched_kws = [kw for kw in flat_keywords if kw in text]
        if matched_kws:
            it["matched_keywords"] = matched_kws
            it["category"] = _categorize(matched_kws)
            filtered.append(it)
    return filtered


def _categorize(matched_kws: list) -> str:
    """簡單分類"""
    for cat, kws in NEWS_FILTER_KEYWORDS.items():
        if any(kw.lower() in matched_kws for kw in kws):
            return cat
    return "other"
```

### 5.7 src/data/sec_edgar.py

```python
"""SEC EDGAR 8-K filings 抓取(EdgarTools)"""

from datetime import datetime, timedelta
from loguru import logger

try:
    from edgar import Company, set_identity
    EDGAR_AVAILABLE = True
except ImportError:
    EDGAR_AVAILABLE = False
    logger.warning("edgartools not installed")


# SEC 要求 User-Agent 識別
set_identity("Kevin Trading Monitor monitor@example.com") if EDGAR_AVAILABLE else None


def fetch_recent_8k(symbol: str, lookback_hours: int = 2) -> list:
    """抓某檔股票最近的 8-K filings"""
    if not EDGAR_AVAILABLE:
        return []
    try:
        company = Company(symbol)
        filings = company.get_filings(form="8-K").head(10)
        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)

        results = []
        for f in filings:
            filing_date = f.filing_date
            if isinstance(filing_date, str):
                filing_date = datetime.strptime(filing_date, "%Y-%m-%d")
            if filing_date < cutoff:
                continue
            results.append({
                "symbol": symbol,
                "form": "8-K",
                "filing_date": filing_date.isoformat(),
                "accession_no": str(f.accession_no),
                "url": f.homepage_url,
                "items": _extract_8k_items(f),
            })
        return results
    except Exception as e:
        logger.error(f"fetch_recent_8k({symbol}) failed: {e}")
        return []


def _extract_8k_items(filing) -> list:
    """提取 8-K 涉及的 Item 編號(1.01 / 2.02 / 5.02 等)"""
    try:
        items = filing.items if hasattr(filing, "items") else []
        return [str(i) for i in items]
    except Exception:
        return []


def scan_watchlist_8k(symbols: list, lookback_hours: int = 2) -> list:
    """掃描白名單所有股票的 8-K"""
    all_filings = []
    for s in symbols:
        all_filings.extend(fetch_recent_8k(s, lookback_hours))
    return all_filings


# 8-K Item 重要性分類
ITEM_PRIORITY = {
    "1.01": "high",   # Material Definitive Agreement
    "1.02": "high",   # Termination of Material Agreement
    "2.01": "high",   # Acquisition/Disposition
    "2.02": "high",   # Earnings Release
    "2.05": "medium", # Costs from Exit
    "5.02": "medium", # Departure of Director/Officer
    "7.01": "medium", # Reg FD Disclosure
    "8.01": "low",    # Other Events
}


def classify_8k_priority(items: list) -> str:
    """回傳該 8-K 最高優先級"""
    priorities = [ITEM_PRIORITY.get(i, "low") for i in items]
    if "high" in priorities:
        return "high"
    if "medium" in priorities:
        return "medium"
    return "low"
```

### 5.8 src/data/form4_insider.py

```python
"""Form 4 內部人交易 - 雙模式(白名單監測 + 全市場 cluster 偵測)"""

from datetime import datetime, timedelta
from collections import defaultdict
from loguru import logger

try:
    from edgar import Company
    EDGAR_AVAILABLE = True
except ImportError:
    EDGAR_AVAILABLE = False


def fetch_form4(symbol: str, lookback_days: int = 30) -> list:
    """抓某檔股票過去 N 天的 Form 4"""
    if not EDGAR_AVAILABLE:
        return []
    try:
        company = Company(symbol)
        filings = company.get_filings(form="4").head(50)
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)

        results = []
        for f in filings:
            try:
                fd = f.filing_date
                if isinstance(fd, str):
                    fd = datetime.strptime(fd, "%Y-%m-%d")
                if fd < cutoff:
                    continue

                # 解析 Form 4 內容
                obj = f.obj()
                if not hasattr(obj, "transactions") or not obj.transactions:
                    continue

                for tx in obj.transactions:
                    results.append({
                        "symbol": symbol,
                        "filing_date": fd.isoformat(),
                        "insider_name": getattr(obj, "owner_name", "Unknown"),
                        "insider_title": getattr(obj, "owner_title", ""),
                        "transaction_code": getattr(tx, "code", ""),
                        "shares": float(getattr(tx, "shares", 0) or 0),
                        "price": float(getattr(tx, "price", 0) or 0),
                        "value_usd": (
                            float(getattr(tx, "shares", 0) or 0)
                            * float(getattr(tx, "price", 0) or 0)
                        ),
                        "transaction_type": (
                            "BUY" if getattr(tx, "code", "") == "P" else
                            "SELL" if getattr(tx, "code", "") == "S" else
                            "OTHER"
                        ),
                    })
            except Exception as inner_e:
                logger.debug(f"Skipping Form 4 row: {inner_e}")
                continue
        return results
    except Exception as e:
        logger.error(f"fetch_form4({symbol}) failed: {e}")
        return []


def detect_cluster_buying(
    symbol: str,
    lookback_days: int = 30,
    min_insiders: int = 3,
    min_total_usd: float = 500_000,
) -> dict:
    """偵測 Cluster Buying(同一公司 30 天內 ≥3 位內部人 P 代碼買入,總額 ≥$500k)"""
    txs = fetch_form4(symbol, lookback_days)
    buys = [t for t in txs if t["transaction_code"] == "P"]
    unique_insiders = set(t["insider_name"] for t in buys)
    total_value = sum(t["value_usd"] for t in buys)

    is_cluster = (
        len(unique_insiders) >= min_insiders
        and total_value >= min_total_usd
    )
    return {
        "symbol": symbol,
        "is_cluster": is_cluster,
        "n_insiders": len(unique_insiders),
        "total_value_usd": total_value,
        "transactions": buys,
    }


def detect_ceo_cfo_buy(symbol: str, lookback_days: int = 7,
                       min_usd: float = 250_000) -> list:
    """偵測 CEO / CFO 大額買入"""
    txs = fetch_form4(symbol, lookback_days)
    hits = []
    for t in txs:
        title = t["insider_title"].upper()
        is_top = any(role in title for role in ["CEO", "CFO", "PRESIDENT",
                                                  "CHAIRMAN", "CHIEF EXECUTIVE",
                                                  "CHIEF FINANCIAL"])
        if (
            t["transaction_code"] == "P"
            and is_top
            and t["value_usd"] >= min_usd
        ):
            hits.append(t)
    return hits


def scan_watchlist_form4(symbols: list, lookback_days: int = 30) -> dict:
    """整批掃白名單"""
    results = {}
    for s in symbols:
        results[s] = {
            "cluster": detect_cluster_buying(s, lookback_days),
            "ceo_cfo_buys": detect_ceo_cfo_buy(s, lookback_days=7),
        }
    return results
```

### 5.9 src/data/institutional_holdings.py

```python
"""13F 機構持股(EdgarTools)"""

from datetime import datetime
from collections import defaultdict
from loguru import logger

try:
    from edgar import Company
    EDGAR_AVAILABLE = True
except ImportError:
    EDGAR_AVAILABLE = False

from src.config.institutions import INSTITUTIONS_TO_TRACK


def fetch_13f(institution_cik: str) -> dict:
    """抓單一機構最新 13F"""
    if not EDGAR_AVAILABLE:
        return {}
    try:
        company = Company(institution_cik)
        filings = company.get_filings(form="13F-HR").head(2)  # 最近兩季
        if not filings:
            return {}

        latest = filings[0]
        previous = filings[1] if len(filings) > 1 else None

        latest_holdings = _extract_holdings(latest)
        previous_holdings = _extract_holdings(previous) if previous else {}

        # 計算變化
        changes = _calc_changes(latest_holdings, previous_holdings)

        return {
            "cik": institution_cik,
            "filing_date": str(latest.filing_date),
            "holdings": latest_holdings,
            "changes": changes,
        }
    except Exception as e:
        logger.error(f"fetch_13f({institution_cik}) failed: {e}")
        return {}


def _extract_holdings(filing) -> dict:
    """從 13F filing 提取持股 dict {symbol: shares}"""
    if not filing:
        return {}
    try:
        obj = filing.obj()
        if not hasattr(obj, "infotable"):
            return {}
        holdings = {}
        for row in obj.infotable:
            sym = getattr(row, "issuer", "") or getattr(row, "symbol", "")
            shares = float(getattr(row, "shares", 0) or 0)
            value = float(getattr(row, "value", 0) or 0)
            if sym:
                if sym not in holdings:
                    holdings[sym] = {"shares": 0, "value": 0}
                holdings[sym]["shares"] += shares
                holdings[sym]["value"] += value
        return holdings
    except Exception as e:
        logger.debug(f"_extract_holdings failed: {e}")
        return {}


def _calc_changes(latest: dict, previous: dict) -> dict:
    """比較兩季變化"""
    changes = {}
    all_syms = set(latest.keys()) | set(previous.keys())
    for sym in all_syms:
        l = latest.get(sym, {"shares": 0})["shares"]
        p = previous.get(sym, {"shares": 0})["shares"]
        if p == 0 and l > 0:
            changes[sym] = "NEW"
        elif l == 0 and p > 0:
            changes[sym] = "EXITED"
        elif l > p * 1.1:
            changes[sym] = "INCREASED"
        elif l < p * 0.9:
            changes[sym] = "DECREASED"
        else:
            changes[sym] = "HELD"
    return changes


def scan_all_institutions(target_symbols: list = None) -> dict:
    """掃描全部 12 家機構,聚合對白名單股票的動向"""
    aggregate = defaultdict(lambda: {"NEW": [], "INCREASED": [],
                                       "DECREASED": [], "EXITED": [], "HELD": []})

    for inst in INSTITUTIONS_TO_TRACK:
        data = fetch_13f(inst["cik"])
        if not data:
            continue
        for sym, change in data.get("changes", {}).items():
            if target_symbols and sym not in target_symbols:
                continue
            aggregate[sym][change].append(inst["name"])
    return dict(aggregate)
```

### 5.10 src/data/earnings_calendar.py

```python
"""財報日曆(yfinance.calendar)"""

from datetime import datetime, timedelta
import yfinance as yf
from loguru import logger

from src.storage.state_manager import write_json, read_json
from src.config.settings import TIMEZONE_US_MARKET

EARNINGS_FILE = "earnings_calendar.json"


def fetch_earnings_date(symbol: str) -> dict:
    """抓單一標的下次財報日"""
    try:
        ticker = yf.Ticker(symbol)
        cal = ticker.calendar
        if cal is None:
            return {}

        # yfinance.calendar 回傳格式可能是 dict 或 DataFrame
        if isinstance(cal, dict):
            earnings_date = cal.get("Earnings Date")
        else:
            try:
                earnings_date = cal.loc["Earnings Date"].iloc[0] if "Earnings Date" in cal.index else None
            except Exception:
                earnings_date = None

        if earnings_date:
            if isinstance(earnings_date, list) and earnings_date:
                earnings_date = earnings_date[0]
            try:
                return {
                    "symbol": symbol,
                    "earnings_date": str(earnings_date),
                    "fetched_at": datetime.now(TIMEZONE_US_MARKET).isoformat(),
                }
            except Exception:
                pass
        return {"symbol": symbol, "earnings_date": None}
    except Exception as e:
        logger.error(f"fetch_earnings_date({symbol}) failed: {e}")
        return {"symbol": symbol, "earnings_date": None}


def update_calendar(symbols: list) -> dict:
    """更新整個白名單的財報日曆"""
    calendar = {}
    for s in symbols:
        info = fetch_earnings_date(s)
        if info.get("earnings_date"):
            calendar[s] = info
    write_json(EARNINGS_FILE, calendar)
    logger.info(f"Updated earnings calendar for {len(calendar)} symbols")
    return calendar


def days_until_earnings(symbol: str) -> int:
    """讀快取,回傳距下次財報的天數;無資料回 999"""
    cal = read_json(EARNINGS_FILE, default={})
    if symbol not in cal:
        return 999
    try:
        ed_str = cal[symbol]["earnings_date"]
        # 解析多種可能格式
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"]:
            try:
                ed = datetime.strptime(ed_str.split("+")[0].strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return 999
        delta = (ed.date() - datetime.now().date()).days
        return max(delta, 0)
    except Exception as e:
        logger.error(f"days_until_earnings({symbol}) parse failed: {e}")
        return 999


def is_earnings_within_days(symbol: str, n_days: int = 7) -> bool:
    return days_until_earnings(symbol) <= n_days
```

### 5.11 src/data/fundamentals.py

```python
"""基本面儀表板(yfinance)"""

import yfinance as yf
from loguru import logger


def fetch_fundamentals(symbol: str) -> dict:
    """單一標的基本面快照"""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        return {
            "symbol": symbol,
            "pe_trailing": info.get("trailingPE"),
            "pe_forward": info.get("forwardPE"),
            "peg": info.get("pegRatio"),
            "pb": info.get("priceToBook"),
            "ps": info.get("priceToSalesTrailing12Months"),
            "fcf_yield": _calc_fcf_yield(info),
            "roe": info.get("returnOnEquity"),
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "rev_growth_yoy": info.get("revenueGrowth"),
            "earnings_growth_yoy": info.get("earningsGrowth"),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }
    except Exception as e:
        logger.error(f"fetch_fundamentals({symbol}) failed: {e}")
        return {"symbol": symbol}


def _calc_fcf_yield(info: dict) -> float:
    """FCF Yield = Free Cash Flow / Market Cap"""
    fcf = info.get("freeCashflow")
    mcap = info.get("marketCap")
    if fcf and mcap and mcap > 0:
        return fcf / mcap
    return None


def fetch_eps_history(symbol: str, n_quarters: int = 4) -> list:
    """過去 N 季 EPS(用於偵測 EPS miss)"""
    try:
        ticker = yf.Ticker(symbol)
        earnings = ticker.quarterly_earnings  # DataFrame
        if earnings is None or earnings.empty:
            return []
        df = earnings.head(n_quarters)
        return [
            {"quarter": str(idx), "eps": float(row.get("Earnings", 0))}
            for idx, row in df.iterrows()
        ]
    except Exception as e:
        logger.error(f"fetch_eps_history({symbol}) failed: {e}")
        return []


def detect_consecutive_eps_miss(symbol: str, n_quarters: int = 2) -> bool:
    """連續 N 季 EPS 衰退(用於 LEAPS 否決)"""
    history = fetch_eps_history(symbol, n_quarters + 1)
    if len(history) < n_quarters + 1:
        return False
    # 比較最近 N 季是否都比前一季低
    for i in range(n_quarters):
        if history[i]["eps"] >= history[i + 1]["eps"]:
            return False
    return True
```

### 5.12 src/data/analyst_actions.py

```python
"""分析師動向(yfinance.upgrades_downgrades)"""

from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
from loguru import logger

from src.config.settings import TIMEZONE_US_MARKET


def fetch_analyst_actions(symbol: str, lookback_days: int = 7) -> dict:
    """抓某檔過去 N 天的分析師動作"""
    try:
        ticker = yf.Ticker(symbol)
        ud = ticker.upgrades_downgrades  # DataFrame
        if ud is None or ud.empty:
            return {"symbol": symbol, "upgrades": 0, "downgrades": 0, "actions": []}

        cutoff = datetime.now(TIMEZONE_US_MARKET) - timedelta(days=lookback_days)
        if ud.index.tz is None:
            ud.index = ud.index.tz_localize("UTC").tz_convert(TIMEZONE_US_MARKET)
        else:
            ud.index = ud.index.tz_convert(TIMEZONE_US_MARKET)

        recent = ud[ud.index >= cutoff]
        actions = []
        upgrades = 0
        downgrades = 0
        for idx, row in recent.iterrows():
            grade = str(row.get("ToGrade", "")).lower()
            from_grade = str(row.get("FromGrade", "")).lower()
            action = str(row.get("Action", "")).lower()
            firm = row.get("Firm", "")

            is_up = (
                "buy" in grade or "outperform" in grade or "overweight" in grade
                or action in ["upgraded", "init", "main"]
            )
            is_down = (
                "sell" in grade or "underperform" in grade
                or action == "downgraded"
            )
            if is_up and not is_down:
                upgrades += 1
                actions.append({"date": str(idx), "firm": firm,
                                "to": grade, "type": "upgrade"})
            elif is_down:
                downgrades += 1
                actions.append({"date": str(idx), "firm": firm,
                                "to": grade, "type": "downgrade"})

        return {
            "symbol": symbol,
            "upgrades": upgrades,
            "downgrades": downgrades,
            "actions": actions,
            "lookback_days": lookback_days,
        }
    except Exception as e:
        logger.error(f"fetch_analyst_actions({symbol}) failed: {e}")
        return {"symbol": symbol, "upgrades": 0, "downgrades": 0, "actions": []}


def has_recent_upgrades(symbol: str, n_min: int = 2, lookback_days: int = 7) -> bool:
    return fetch_analyst_actions(symbol, lookback_days)["upgrades"] >= n_min


def has_recent_downgrades(symbol: str, n_min: int = 2, lookback_days: int = 7) -> bool:
    return fetch_analyst_actions(symbol, lookback_days)["downgrades"] >= n_min
```

### 5.13 src/data/fred_api.py

```python
"""FRED API - 殖利率 / 信用利差 / DXY / GDP / CPI"""

import os
from datetime import datetime, timedelta
from fredapi import Fred
from loguru import logger

FRED_API_KEY = os.getenv("FRED_API_KEY", "")

# FRED Series ID 對照
FRED_SERIES = {
    "treasury_10y": "DGS10",
    "treasury_2y": "DGS2",
    "treasury_3m": "DGS3MO",
    "hy_oas": "BAMLH0A0HYM2",       # ICE BofA US High Yield OAS
    "ig_oas": "BAMLC0A0CM",          # IG OAS
    "dxy": "DTWEXBGS",               # 廣義貿易加權美元指數
    "vix_fred": "VIXCLS",
    "cpi": "CPIAUCSL",
    "gdp": "GDP",
    "unrate": "UNRATE",
    "fed_funds": "FEDFUNDS",
}


def get_fred_client():
    if not FRED_API_KEY:
        raise ValueError("FRED_API_KEY not set in env")
    return Fred(api_key=FRED_API_KEY)


def fetch_series(series_id: str, lookback_days: int = 60) -> list:
    """抓單一 FRED series 的近期觀測值"""
    try:
        fred = get_fred_client()
        end = datetime.now()
        start = end - timedelta(days=lookback_days)
        data = fred.get_series(series_id, start, end)
        return [(str(idx.date()), float(val))
                for idx, val in data.items() if not _is_nan(val)]
    except Exception as e:
        logger.error(f"FRED fetch_series({series_id}) failed: {e}")
        return []


def _is_nan(v):
    try:
        import math
        return math.isnan(v)
    except Exception:
        return v is None


def get_yield_curve_spread() -> float:
    """10Y-2Y 殖利率差(bps)"""
    y10 = fetch_series(FRED_SERIES["treasury_10y"], lookback_days=10)
    y2 = fetch_series(FRED_SERIES["treasury_2y"], lookback_days=10)
    if not y10 or not y2:
        return None
    return (y10[-1][1] - y2[-1][1]) * 100  # 轉 bps


def get_hy_credit_spread() -> float:
    """HY 信用利差(bps)"""
    data = fetch_series(FRED_SERIES["hy_oas"], lookback_days=10)
    return data[-1][1] * 100 if data else None


def get_dxy() -> float:
    """DXY 美元指數"""
    data = fetch_series(FRED_SERIES["dxy"], lookback_days=10)
    return data[-1][1] if data else None


def get_macro_snapshot() -> dict:
    """完整宏觀快照"""
    return {
        "yield_curve_spread_bps": get_yield_curve_spread(),
        "hy_oas_bps": get_hy_credit_spread(),
        "dxy": get_dxy(),
        "fetched_at": datetime.utcnow().isoformat(),
    }
```

### 5.14 src/data/breadth_data.py

```python
"""市場廣度 - StockCharts scraping"""

import httpx
from selectolax.parser import HTMLParser
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential


HEADERS = {"User-Agent": "Mozilla/5.0"}


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, max=8))
def fetch_breadth_indicator(symbol: str) -> float:
    """抓 StockCharts 的廣度指標(例如 $NYHL, $SPXA50R, $SPXA200R)"""
    url = f"https://stockcharts.com/h-sc/ui?s={symbol}"
    try:
        with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            tree = HTMLParser(r.text)
            # StockCharts 的最新值通常在 .last-quote 或類似 class
            for sel in [".last-quote", ".price", "span.quote"]:
                node = tree.css_first(sel)
                if node:
                    try:
                        return float(node.text(strip=True).replace(",", ""))
                    except ValueError:
                        continue
        return None
    except Exception as e:
        logger.error(f"fetch_breadth_indicator({symbol}) failed: {e}")
        return None


def get_breadth_snapshot() -> dict:
    """完整廣度快照"""
    return {
        "spx_above_50ma_pct": fetch_breadth_indicator("$SPXA50R"),
        "spx_above_200ma_pct": fetch_breadth_indicator("$SPXA200R"),
        "nyse_new_highs": fetch_breadth_indicator("$NYHL"),
        "advance_decline_line": fetch_breadth_indicator("$NYAD"),
    }
```

### 5.15 src/data/bubble_indicators.py

```python
"""泡沫偵測指標 - currentmarketvaluation.com / multpl.com / AAII"""

import httpx
import re
from selectolax.parser import HTMLParser
from loguru import logger


HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_buffett_indicator() -> float:
    """Buffett Indicator(US Total Market Cap / GDP)
    來源:currentmarketvaluation.com
    """
    try:
        url = "https://www.currentmarketvaluation.com/models/buffett-indicator.php"
        with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            tree = HTMLParser(r.text)
            text = tree.text()
            # 用 regex 抓「current ratio」附近的數字
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
            if m:
                return float(m.group(1)) / 100
        return None
    except Exception as e:
        logger.error(f"fetch_buffett_indicator failed: {e}")
        return None


def fetch_shiller_cape() -> float:
    """Shiller CAPE(multpl.com)"""
    try:
        url = "https://www.multpl.com/shiller-pe"
        with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            tree = HTMLParser(r.text)
            node = tree.css_first("#current")
            if node:
                m = re.search(r"(\d+\.\d+)", node.text())
                if m:
                    return float(m.group(1))
        return None
    except Exception as e:
        logger.error(f"fetch_shiller_cape failed: {e}")
        return None


def fetch_sp500_top10_concentration() -> float:
    """SPX Top 10 集中度(slickcharts 或 SPY 持股)"""
    try:
        url = "https://www.slickcharts.com/sp500"
        with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            tree = HTMLParser(r.text)
            rows = tree.css("table tbody tr")[:10]
            total = 0.0
            for row in rows:
                cells = row.css("td")
                if len(cells) >= 4:
                    try:
                        weight = float(cells[3].text(strip=True).replace("%", ""))
                        total += weight
                    except ValueError:
                        continue
            return total / 100 if total else None
    except Exception as e:
        logger.error(f"fetch_sp500_top10_concentration failed: {e}")
        return None


def fetch_margin_debt_yoy() -> float:
    """Margin Debt YoY(FINRA / advisorperspectives)"""
    # 簡化:此資料更新月度,可以 placeholder
    # 階段 2 可先回傳 None,階段 3 補完
    return None


def get_bubble_snapshot() -> dict:
    return {
        "buffett_indicator": fetch_buffett_indicator(),
        "shiller_cape": fetch_shiller_cape(),
        "sp500_top10_concentration": fetch_sp500_top10_concentration(),
        "margin_debt_yoy": fetch_margin_debt_yoy(),
    }
```

### 5.16 src/data/put_call_ratio.py

```python
"""Put/Call Ratio - CBOE 主、yfinance ^CPC 備"""

from datetime import datetime, timedelta
import httpx
import yfinance as yf
from loguru import logger


HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_pcr_from_cboe() -> float:
    """從 CBOE 抓 daily total PCR(可能需要 scraping HTML)"""
    try:
        # CBOE 的 PCR 頁面結構不穩定;嘗試先從 yfinance ^CPC
        return None  # 暫保留,直接走 fallback
    except Exception as e:
        logger.error(f"fetch_pcr_from_cboe failed: {e}")
        return None


def fetch_pcr_from_yfinance() -> float:
    """fallback - yfinance ^CPC(部分時期可能無資料)"""
    try:
        ticker = yf.Ticker("^CPC")
        df = ticker.history(period="5d")
        if df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception as e:
        logger.error(f"fetch_pcr_from_yfinance failed: {e}")
        return None


def get_put_call_ratio() -> dict:
    """主備雙重來源"""
    pcr = fetch_pcr_from_cboe()
    source = "cboe"
    if pcr is None:
        pcr = fetch_pcr_from_yfinance()
        source = "yfinance"
    return {
        "pcr": pcr,
        "source": source,
        "fetched_at": datetime.utcnow().isoformat(),
    }
```

### 5.17 src/data/vix_structure.py

```python
"""VIX 期貨結構 - VIX / VIX9D / VIX3M"""

import yfinance as yf
from loguru import logger


def fetch_vix_term_structure() -> dict:
    """VIX 短中長期結構"""
    out = {}
    for label, sym in [("vix", "^VIX"), ("vix9d", "^VIX9D"), ("vix3m", "^VIX3M")]:
        try:
            ticker = yf.Ticker(sym)
            df = ticker.history(period="5d")
            if not df.empty:
                out[label] = float(df["Close"].iloc[-1])
            else:
                out[label] = None
        except Exception as e:
            logger.error(f"fetch_vix({sym}) failed: {e}")
            out[label] = None

    # 倒掛標記
    if out.get("vix") and out.get("vix9d"):
        out["vix9d_inverted"] = out["vix9d"] > out["vix"]
    if out.get("vix") and out.get("vix3m"):
        out["vix3m_inverted"] = out["vix"] > out["vix3m"]
    return out


def is_vix_consecutive_above(threshold: float = 30, n_days: int = 3) -> bool:
    """檢查 VIX 是否連續 N 天 > threshold(用於學習鎖第 4 條)"""
    try:
        ticker = yf.Ticker("^VIX")
        df = ticker.history(period=f"{n_days + 5}d")
        if df.empty or len(df) < n_days:
            return False
        recent = df["Close"].iloc[-n_days:]
        return all(v > threshold for v in recent)
    except Exception as e:
        logger.error(f"is_vix_consecutive_above failed: {e}")
        return False
```

### 5.18 src/data/tsmc_revenue.py

```python
"""TSMC 月營收 - 公開資訊觀測站(MOPS)"""

import httpx
import re
from datetime import datetime
from selectolax.parser import HTMLParser
from loguru import logger


HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_tsmc_monthly_revenue() -> dict:
    """從 MOPS 抓台積電(2330)最新月營收"""
    url = "https://mops.twse.com.tw/nas/t21/sii/t21sc03_2330_0.html"
    try:
        with httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            r.encoding = "big5"
            tree = HTMLParser(r.text)
            tables = tree.css("table")
            for tbl in tables:
                rows = tbl.css("tr")
                for row in rows:
                    cells = [c.text(strip=True) for c in row.css("td")]
                    if len(cells) >= 6 and re.match(r"\d{3,4}/\d{1,2}", cells[0]):
                        # 格式: 民國年/月, 當月營收, 去年同月, YoY%, 累計, 累計YoY
                        try:
                            yoy_pct = float(cells[3].replace("%", "").replace(",", "")) / 100
                            return {
                                "year_month": cells[0],
                                "current_revenue": cells[1],
                                "prev_year_revenue": cells[2],
                                "yoy_pct": yoy_pct,
                                "ytd_revenue": cells[4],
                                "ytd_yoy_pct": float(cells[5].replace("%", "").replace(",", "")) / 100,
                                "fetched_at": datetime.utcnow().isoformat(),
                            }
                        except (ValueError, IndexError) as e:
                            logger.debug(f"Parse row failed: {e}")
                            continue
        return {}
    except Exception as e:
        logger.error(f"fetch_tsmc_monthly_revenue failed: {e}")
        return {}
```

### 5.19 src/data/etf_flows.py

```python
"""ETF 資金流 - SMH / QQQ / SPY(etf.com 或 etfdb scraping)"""

import httpx
from datetime import datetime
from selectolax.parser import HTMLParser
from loguru import logger


HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_etf_flow(symbol: str, lookback_days: int = 5) -> dict:
    """嘗試從 etfdb 抓資金流(此資料源不穩,失敗回 None)"""
    try:
        url = f"https://etfdb.com/etf/{symbol}/#flows"
        with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            tree = HTMLParser(r.text)
            # 此頁面結構複雜,簡化版本只抓總 AUM 變化
            # 階段 2 暫返 placeholder,階段 3 補完
            return {
                "symbol": symbol,
                "lookback_days": lookback_days,
                "estimated_net_flow_usd": None,
                "data_quality": "placeholder",
            }
    except Exception as e:
        logger.error(f"fetch_etf_flow({symbol}) failed: {e}")
        return {"symbol": symbol, "estimated_net_flow_usd": None}


def get_smh_qqq_flows() -> dict:
    return {
        "SMH": fetch_etf_flow("SMH", 5),
        "QQQ": fetch_etf_flow("QQQ", 5),
        "SPY": fetch_etf_flow("SPY", 5),
    }
```

### 5.20 src/data/twstock_data.py

```python
"""台股資料 - twstock 套件 + yfinance .TW 後綴雙來源"""

import yfinance as yf
from datetime import datetime, timedelta
from loguru import logger


def fetch_tw_history(symbol: str, period: str = "1y") -> "pd.DataFrame":
    """台股歷史價(yfinance .TW)"""
    try:
        # 確保 .TW 後綴
        if not symbol.endswith(".TW") and not symbol.endswith(".TWO"):
            symbol = f"{symbol}.TW"
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        return df
    except Exception as e:
        logger.error(f"fetch_tw_history({symbol}) failed: {e}")
        import pandas as pd
        return pd.DataFrame()


def get_tw_latest_price(symbol: str) -> float:
    df = fetch_tw_history(symbol, period="5d")
    if df.empty:
        return None
    return float(df["Close"].iloc[-1])


def get_tw_52w_metrics(symbol: str) -> dict:
    df = fetch_tw_history(symbol, period="1y")
    if df.empty:
        return {}
    high = float(df["High"].max())
    low = float(df["Low"].min())
    current = float(df["Close"].iloc[-1])
    return {
        "high": high,
        "low": low,
        "current": current,
        "pct_from_high": (current - high) / high,
        "pct_from_low": (current - low) / low,
    }
```

### 5.21 src/data/twstock_active_etf.py

```python
"""台股主動 ETF 持股 - 從證交所 ETF 專區抓"""

import httpx
import json
from datetime import datetime, timedelta
from collections import defaultdict
from loguru import logger

from src.config.universe import TWSTOCK_ACTIVE_ETFS
from src.storage.state_manager import read_json, write_json

ACTIVE_ETF_HOLDINGS_FILE = "active_etf_holdings.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_etf_holdings(etf_symbol: str) -> list:
    """抓單檔主動 ETF 持股(去 .TW 後綴)
    證交所開放資料: https://www.twse.com.tw/zh/page/ETF/list.html
    Note: 部分主動 ETF 持股可能要從投信公司網站抓
    """
    code = etf_symbol.replace(".TW", "").replace(".TWO", "")
    try:
        # 嘗試證交所 OpenAPI
        url = f"https://openapi.twse.com.tw/v1/opendata/t187ap47_L"
        with httpx.Client(timeout=20.0, headers=HEADERS) as c:
            r = c.get(url)
            r.raise_for_status()
            data = r.json()
            holdings = [item for item in data
                        if item.get("基金統一編號") == code
                        or item.get("基金代號") == code]
            return [{
                "symbol": h.get("持股代號", ""),
                "name": h.get("持股名稱", ""),
                "weight_pct": float(h.get("持股比例", 0) or 0),
                "shares": int(float(h.get("持股股數", 0) or 0)),
            } for h in holdings]
    except Exception as e:
        logger.warning(f"fetch_etf_holdings({etf_symbol}) failed via TWSE OpenAPI: {e}")
        return []


def update_all_active_etf_holdings() -> dict:
    """更新全部 6 檔主動 ETF 持股快取"""
    today = datetime.now().strftime("%Y-%m-%d")
    history = read_json(ACTIVE_ETF_HOLDINGS_FILE, default={})

    for etf in TWSTOCK_ACTIVE_ETFS:
        holdings = fetch_etf_holdings(etf["symbol"])
        if not holdings:
            continue
        if etf["symbol"] not in history:
            history[etf["symbol"]] = {}
        history[etf["symbol"]][today] = holdings

        # 保留最近 60 天
        if len(history[etf["symbol"]]) > 60:
            keys = sorted(history[etf["symbol"]].keys())
            for k in keys[:-60]:
                del history[etf["symbol"]][k]

    write_json(ACTIVE_ETF_HOLDINGS_FILE, history)
    logger.info(f"Updated {len(history)} ETFs holdings")
    return history


def get_holdings_change(
    etf_symbol: str, lookback_days: int = 7
) -> dict:
    """比較某檔主動 ETF 過去 N 天的持股變化"""
    history = read_json(ACTIVE_ETF_HOLDINGS_FILE, default={})
    if etf_symbol not in history:
        return {}
    dates = sorted(history[etf_symbol].keys())
    if len(dates) < 2:
        return {}

    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    old_dates = [d for d in dates if d <= cutoff]
    if not old_dates:
        return {}

    old_date = old_dates[-1]
    new_date = dates[-1]
    old_h = {h["symbol"]: h["weight_pct"] for h in history[etf_symbol][old_date]}
    new_h = {h["symbol"]: h["weight_pct"] for h in history[etf_symbol][new_date]}

    changes = {}
    for sym in set(old_h.keys()) | set(new_h.keys()):
        old_w = old_h.get(sym, 0)
        new_w = new_h.get(sym, 0)
        diff = new_w - old_w
        if abs(diff) >= 0.5:  # 變化 ≥0.5%
            changes[sym] = {"old": old_w, "new": new_w, "diff_pct": diff}
    return changes


def aggregate_cross_etf_signals(lookback_days: int = 7) -> dict:
    """聚合跨主動 ETF 訊號(三級訊號用)"""
    aggregate = defaultdict(lambda: {"increased_etfs": [], "decreased_etfs": []})

    for etf in TWSTOCK_ACTIVE_ETFS:
        changes = get_holdings_change(etf["symbol"], lookback_days)
        for sym, ch in changes.items():
            if ch["diff_pct"] > 0:
                aggregate[sym]["increased_etfs"].append({
                    "etf": etf["symbol"],
                    "etf_name": etf["name"],
                    "diff_pct": ch["diff_pct"],
                })
            else:
                aggregate[sym]["decreased_etfs"].append({
                    "etf": etf["symbol"],
                    "etf_name": etf["name"],
                    "diff_pct": ch["diff_pct"],
                })
    return dict(aggregate)
```

---

## 6. src/indicators/ 技術指標

### 6.1 src/indicators/__init__.py

```python
# 空檔
```

### 6.2 src/indicators/basic.py

```python
"""基礎技術指標 - RSI / Bollinger Bands / MA / ADX
注意:使用 pandas_ta_classic(不是 pandas_ta)
"""

import pandas as pd
import pandas_ta_classic as ta
from loguru import logger


def add_rsi(df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
    """加入 RSI 欄位"""
    df = df.copy()
    df.ta.rsi(length=length, append=True)  # 產生 RSI_14 欄
    return df


def get_rsi_latest(df: pd.DataFrame, length: int = 14) -> float:
    """取最新 RSI 值"""
    df = add_rsi(df, length)
    col = f"RSI_{length}"
    if col not in df.columns or df[col].isna().all():
        return None
    return float(df[col].dropna().iloc[-1])


def add_bbands(df: pd.DataFrame, length: int = 20, std: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands"""
    df = df.copy()
    df.ta.bbands(length=length, std=std, append=True)
    return df


def get_bbands_position(df: pd.DataFrame, length: int = 20, std: float = 2.0) -> dict:
    """回傳 BB 位置: pct(0=下軌,1=上軌)、是否觸碰"""
    df = add_bbands(df, length, std)
    upper_col = f"BBU_{length}_{std}"
    lower_col = f"BBL_{length}_{std}"
    if upper_col not in df.columns:
        return {}
    upper = df[upper_col].dropna().iloc[-1]
    lower = df[lower_col].dropna().iloc[-1]
    close = df["Close"].iloc[-1]
    width = upper - lower
    pct = (close - lower) / width if width else 0.5
    return {
        "upper": float(upper),
        "lower": float(lower),
        "close": float(close),
        "pct": float(pct),
        "touch_upper": close >= upper * 0.995,
        "touch_lower": close <= lower * 1.005,
    }


def add_ma(df: pd.DataFrame, lengths: list = None) -> pd.DataFrame:
    """加入多條 MA"""
    df = df.copy()
    lengths = lengths or [20, 50, 100, 200]
    for n in lengths:
        df[f"SMA_{n}"] = df["Close"].rolling(n).mean()
    return df


def get_ma_position(df: pd.DataFrame) -> dict:
    """價格相對 MA 的位置"""
    df = add_ma(df)
    close = df["Close"].iloc[-1]
    out = {"close": float(close)}
    for n in [20, 50, 100, 200]:
        col = f"SMA_{n}"
        if col in df.columns and not df[col].isna().all():
            ma_val = df[col].dropna().iloc[-1]
            out[f"sma_{n}"] = float(ma_val)
            out[f"pct_from_sma_{n}"] = (close - ma_val) / ma_val
            out[f"above_sma_{n}"] = close > ma_val
    return out


def add_adx(df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
    """ADX(趨勢強度)"""
    df = df.copy()
    df.ta.adx(length=length, append=True)
    return df


def get_adx_latest(df: pd.DataFrame, length: int = 14) -> float:
    df = add_adx(df, length)
    col = f"ADX_{length}"
    if col not in df.columns or df[col].isna().all():
        return None
    return float(df[col].dropna().iloc[-1])


def get_consecutive_up_days(df: pd.DataFrame) -> int:
    """連續上漲天數"""
    if df.empty or "Close" not in df.columns:
        return 0
    closes = df["Close"].values
    count = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            count += 1
        else:
            break
    return count
```

### 6.3 src/indicators/volume.py

```python
"""成交量指標"""

import pandas as pd
from loguru import logger


def get_volume_avg(df: pd.DataFrame, length: int = 20) -> float:
    """平均成交量"""
    if df.empty or "Volume" not in df.columns:
        return None
    return float(df["Volume"].rolling(length).mean().iloc[-1])


def get_volume_ratio(df: pd.DataFrame, length: int = 20) -> float:
    """當日成交量 / 均量"""
    avg = get_volume_avg(df, length)
    if not avg:
        return None
    return float(df["Volume"].iloc[-1] / avg)


def detect_volume_surge(df: pd.DataFrame, multiplier: float = 1.5) -> bool:
    """量爆(>均量 N 倍)"""
    ratio = get_volume_ratio(df)
    return ratio is not None and ratio >= multiplier


def detect_volume_price_divergence(df: pd.DataFrame, lookback: int = 5) -> dict:
    """量價背離 - 價漲量縮 / 價跌量增"""
    if df.empty or len(df) < lookback + 1:
        return {"divergence": False}
    recent = df.iloc[-lookback:]
    price_change = (recent["Close"].iloc[-1] - recent["Close"].iloc[0]) / recent["Close"].iloc[0]
    vol_change = (recent["Volume"].mean() - df["Volume"].iloc[-lookback*2:-lookback].mean()) / \
                 df["Volume"].iloc[-lookback*2:-lookback].mean()

    bearish_div = price_change > 0.02 and vol_change < -0.2  # 漲超 2% 但量縮 20%+
    bullish_div = price_change < -0.02 and vol_change < -0.2  # 跌但量縮(賣壓減弱)

    return {
        "divergence": bearish_div or bullish_div,
        "type": "bearish" if bearish_div else ("bullish" if bullish_div else None),
        "price_change_pct": price_change,
        "volume_change_pct": vol_change,
    }
```

### 6.4 src/indicators/pattern.py

```python
"""形態識別 - 阻力/支撐區、52W 高低距離"""

import pandas as pd
from loguru import logger


def find_support_resistance(df: pd.DataFrame, lookback: int = 60,
                             tolerance: float = 0.02) -> dict:
    """簡化版支撐/阻力 - 用近期高低點"""
    if df.empty or len(df) < lookback:
        return {}
    recent = df.iloc[-lookback:]
    highs = recent["High"].values
    lows = recent["Low"].values
    close = df["Close"].iloc[-1]

    # 阻力 = 近 N 日內接近的高點(>= close × 1.01)
    resistance_levels = sorted(set(round(h, 2) for h in highs if h > close * 1.005))
    support_levels = sorted(set(round(l, 2) for l in lows if l < close * 0.995), reverse=True)

    return {
        "current": float(close),
        "nearest_resistance": resistance_levels[0] if resistance_levels else None,
        "nearest_support": support_levels[0] if support_levels else None,
        "near_resistance": (
            resistance_levels[0] - close
        ) / close < tolerance if resistance_levels else False,
        "near_support": (
            close - support_levels[0]
        ) / close < tolerance if support_levels else False,
    }


def detect_resistance_rejection(df: pd.DataFrame, lookback: int = 5) -> bool:
    """阻力區拒絕 - 近 N 日有 wick 上影線且收回"""
    if df.empty or len(df) < lookback:
        return False
    recent = df.iloc[-lookback:]
    for _, row in recent.iterrows():
        upper_wick = row["High"] - max(row["Open"], row["Close"])
        body = abs(row["Close"] - row["Open"])
        if body > 0 and upper_wick > body * 2:
            return True
    return False
```

### 6.5 src/indicators/distribution_days.py

```python
"""IBD Distribution Days 演算法
規則:25 個交易日內,SPY (或 QQQ) 收盤跌 ≥0.2% 且當日量 > 前一日量
"""

import pandas as pd
from datetime import datetime, timedelta
from loguru import logger

from src.data.price_data import fetch_history
from src.config.thresholds import DISTRIBUTION_DAYS_RULE
from src.storage.state_manager import write_json


def detect_distribution_days(symbol: str = "SPY",
                              lookback: int = 25) -> dict:
    """偵測過去 25 個交易日內的派發日"""
    df = fetch_history(symbol, period="2mo", interval="1d")
    if df.empty or len(df) < lookback + 1:
        return {"count": 0, "days": [], "level": "unknown"}

    df = df.iloc[-(lookback + 1):]
    distribution_days = []

    for i in range(1, len(df)):
        today = df.iloc[i]
        yesterday = df.iloc[i - 1]
        price_drop_pct = (today["Close"] - yesterday["Close"]) / yesterday["Close"]
        vol_increased = today["Volume"] > yesterday["Volume"]

        if price_drop_pct <= -DISTRIBUTION_DAYS_RULE["min_drop_pct"] and vol_increased:
            distribution_days.append({
                "date": str(today.name.date()),
                "drop_pct": float(price_drop_pct),
                "volume": int(today["Volume"]),
                "prev_volume": int(yesterday["Volume"]),
            })

    count = len(distribution_days)
    thresholds = DISTRIBUTION_DAYS_RULE["thresholds"]
    if count <= thresholds["healthy"]:
        level = "healthy"
    elif count <= thresholds["pressure"]:
        level = "pressure"
    else:
        level = "distribution"

    result = {
        "symbol": symbol,
        "lookback": lookback,
        "count": count,
        "days": distribution_days,
        "level": level,
        "fetched_at": datetime.utcnow().isoformat(),
    }

    write_json("distribution_days_log.json", result)
    return result
```

---

## 7. src/layers/ Layer 0 / 0+ / F

### 7.1 src/layers/__init__.py

```python
# 空檔
```

### 7.2 src/layers/macro_regime.py

```python
"""Layer 0.1 - Macro Regime Score
五子指標各佔 20%:
  10Y-2Y / HY OAS / DXY / VIX / Copper-Gold ratio
"""

import yfinance as yf
from loguru import logger

from src.data.fred_api import get_yield_curve_spread, get_hy_credit_spread, get_dxy
from src.data.vix_structure import fetch_vix_term_structure
from src.config.thresholds import LAYER0_SUBMODIFIER_RANGES


def get_copper_gold_ratio() -> float:
    """Copper / Gold 比率(用 ETF 替代:CPER / GLD)"""
    try:
        copper = yf.Ticker("CPER").history(period="5d")["Close"].iloc[-1]
        gold = yf.Ticker("GLD").history(period="5d")["Close"].iloc[-1]
        return copper / gold
    except Exception as e:
        logger.error(f"copper_gold_ratio failed: {e}")
        return None


def classify_macro_regime() -> dict:
    """五子指標分類 + 整體評分"""
    indicators = {}

    # 10Y-2Y(bps)
    spread = get_yield_curve_spread()
    indicators["yield_curve"] = {
        "value": spread,
        "regime": (
            "risk_on" if spread is not None and spread > 0 else
            "risk_off" if spread is not None and spread < -50 else
            "neutral"
        ),
    }

    # HY OAS(bps)
    hy = get_hy_credit_spread()
    indicators["hy_oas"] = {
        "value": hy,
        "regime": (
            "risk_on" if hy is not None and hy < 300 else
            "risk_off" if hy is not None and hy > 500 else
            "neutral"
        ),
    }

    # DXY
    dxy = get_dxy()
    indicators["dxy"] = {
        "value": dxy,
        "regime": (
            "risk_on" if dxy is not None and dxy < 100 else
            "risk_off" if dxy is not None and dxy > 105 else
            "neutral"
        ),
    }

    # VIX
    vix_data = fetch_vix_term_structure()
    vix = vix_data.get("vix")
    indicators["vix"] = {
        "value": vix,
        "regime": (
            "risk_on" if vix is not None and vix < 18 else
            "risk_off" if vix is not None and vix > 25 else
            "neutral"
        ),
    }

    # Copper/Gold
    cg = get_copper_gold_ratio()
    indicators["copper_gold"] = {"value": cg, "regime": "neutral"}  # 趨勢需時間序列

    # 計算 risk_on / risk_off 比例
    risk_on_count = sum(1 for v in indicators.values() if v["regime"] == "risk_on")
    risk_off_count = sum(1 for v in indicators.values() if v["regime"] == "risk_off")

    # Modifier: -15 ~ +10
    min_mod, max_mod = LAYER0_SUBMODIFIER_RANGES["macro_regime"]
    if risk_off_count >= 3:
        modifier = min_mod
    elif risk_off_count == 2:
        modifier = min_mod / 2
    elif risk_on_count >= 3:
        modifier = max_mod
    elif risk_on_count == 2:
        modifier = max_mod / 2
    else:
        modifier = 0

    return {
        "indicators": indicators,
        "risk_on_count": risk_on_count,
        "risk_off_count": risk_off_count,
        "modifier": int(modifier),
        "regime": (
            "risk_off" if risk_off_count >= 3 else
            "risk_on" if risk_on_count >= 3 else
            "neutral"
        ),
    }
```

### 7.3 src/layers/breadth.py

```python
"""Layer 0.2 - Market Breadth"""

from src.data.breadth_data import get_breadth_snapshot
from src.config.thresholds import LAYER0_SUBMODIFIER_RANGES


def classify_breadth() -> dict:
    snap = get_breadth_snapshot()
    above_50 = snap.get("spx_above_50ma_pct")
    above_200 = snap.get("spx_above_200ma_pct")

    min_mod, max_mod = LAYER0_SUBMODIFIER_RANGES["breadth"]

    if above_50 is None or above_200 is None:
        return {"snapshot": snap, "modifier": 0, "regime": "unknown"}

    # 雙弱(<40%)= -10
    if above_50 < 40 and above_200 < 50:
        modifier = min_mod
        regime = "weak"
    elif above_50 > 70 and above_200 > 65:
        modifier = max_mod
        regime = "strong"
    elif above_50 < 50 or above_200 < 55:
        modifier = min_mod / 2
        regime = "soft"
    else:
        modifier = 0
        regime = "normal"

    return {
        "snapshot": snap,
        "modifier": int(modifier),
        "regime": regime,
    }
```

### 7.4 src/layers/distribution.py

```python
"""Layer 0.3 - Distribution Days"""

from src.indicators.distribution_days import detect_distribution_days
from src.config.thresholds import LAYER0_SUBMODIFIER_RANGES


def classify_distribution() -> dict:
    """SPY + QQQ 各跑一次,取較壞者"""
    spy_dd = detect_distribution_days("SPY")
    qqq_dd = detect_distribution_days("QQQ")
    worst = max((spy_dd, qqq_dd), key=lambda x: x["count"])

    min_mod, _ = LAYER0_SUBMODIFIER_RANGES["distribution_days"]
    if worst["level"] == "distribution":
        # 派發級(6+ 天):LEAPS -20、賣 PUT -15、賣 CALL +5
        modifier_for_leaps = min_mod
        modifier_for_sell_put = -15
        modifier_for_sell_call = +5
    elif worst["level"] == "pressure":
        # 承壓(4-5 天):LEAPS -10、賣 PUT -5
        modifier_for_leaps = -10
        modifier_for_sell_put = -5
        modifier_for_sell_call = 0
    else:
        modifier_for_leaps = 0
        modifier_for_sell_put = 0
        modifier_for_sell_call = 0

    return {
        "spy": spy_dd,
        "qqq": qqq_dd,
        "level": worst["level"],
        "modifiers": {
            "leaps_entry": modifier_for_leaps,
            "sell_put": modifier_for_sell_put,
            "sell_call": modifier_for_sell_call,
        },
    }
```

### 7.5 src/layers/bubble.py

```python
"""Layer 0.4 - Bubble Detector"""

from src.data.bubble_indicators import get_bubble_snapshot
from src.config.thresholds import BUBBLE_INDICATORS_THRESHOLDS, LAYER0_SUBMODIFIER_RANGES


def calc_bubble_score() -> dict:
    """5 個指標各佔 20 分,合 100"""
    snap = get_bubble_snapshot()
    score = 0
    breakdown = {}

    # Buffett Indicator
    buffett = snap.get("buffett_indicator")
    if buffett:
        thr = BUBBLE_INDICATORS_THRESHOLDS["buffett_indicator"]
        if buffett > thr["bubble"]:
            s = 20
        elif buffett > thr["warning"]:
            s = 12
        elif buffett > thr["normal"]:
            s = 5
        else:
            s = 0
        score += s
        breakdown["buffett"] = {"value": buffett, "score": s}

    # Shiller CAPE
    cape = snap.get("shiller_cape")
    if cape:
        thr = BUBBLE_INDICATORS_THRESHOLDS["shiller_cape"]
        if cape > thr["bubble"]:
            s = 20
        elif cape > thr["warning"]:
            s = 12
        elif cape > thr["normal"]:
            s = 5
        else:
            s = 0
        score += s
        breakdown["shiller_cape"] = {"value": cape, "score": s}

    # SP500 Top 10 集中度
    conc = snap.get("sp500_top10_concentration")
    if conc:
        thr = BUBBLE_INDICATORS_THRESHOLDS["sp500_top10_concentration"]
        if conc > thr["bubble"]:
            s = 20
        elif conc > thr["warning"]:
            s = 12
        else:
            s = 0
        score += s
        breakdown["concentration"] = {"value": conc, "score": s}

    # Margin Debt YoY(可能 None)
    md = snap.get("margin_debt_yoy")
    if md:
        thr = BUBBLE_INDICATORS_THRESHOLDS["margin_debt_yoy"]
        if md > thr["bubble"]:
            s = 20
        elif md > thr["warning"]:
            s = 12
        else:
            s = 0
        score += s
        breakdown["margin_debt"] = {"value": md, "score": s}

    # AAII bull-bear spread(由 aaii_sentiment.py 提供,此處跳過)

    # 對應 modifier
    min_mod, _ = LAYER0_SUBMODIFIER_RANGES["bubble"]
    if score > 80:
        modifier = min_mod  # -15
        stage = "high_alert"
    elif score > 60:
        modifier = -10
        stage = "late"
    elif score > 30:
        modifier = -5  # 主要影響 Tier C
        stage = "mid_late"
    else:
        modifier = 0
        stage = "normal"

    return {
        "score": score,
        "stage": stage,
        "modifier": modifier,
        "breakdown": breakdown,
        "snapshot": snap,
    }
```

### 7.6 src/layers/put_call.py

```python
"""Layer 0.5 - Put/Call Ratio"""

from src.data.put_call_ratio import get_put_call_ratio
from src.config.thresholds import PUT_CALL_RATIO_THRESHOLDS


def classify_put_call() -> dict:
    pcr_data = get_put_call_ratio()
    pcr = pcr_data.get("pcr")
    if pcr is None:
        return {"pcr": None, "regime": "unknown",
                "modifiers": {"sell_put": 0, "sell_call": 0, "leaps_entry": 0}}

    thr = PUT_CALL_RATIO_THRESHOLDS
    if pcr > thr["extreme_fear"]:
        return {
            "pcr": pcr, "source": pcr_data.get("source"),
            "regime": "extreme_fear",
            "modifiers": {"sell_put": +10, "leaps_entry": +10, "sell_call": 0},
        }
    if pcr < thr["extreme_greed"]:
        return {
            "pcr": pcr, "source": pcr_data.get("source"),
            "regime": "extreme_greed",
            "modifiers": {"sell_put": 0, "leaps_entry": 0, "sell_call": +10},
        }
    return {
        "pcr": pcr, "source": pcr_data.get("source"),
        "regime": "neutral",
        "modifiers": {"sell_put": 0, "leaps_entry": 0, "sell_call": 0},
    }
```

### 7.7 src/layers/vix_structure_layer.py

```python
"""Layer 0.6 - VIX 期貨結構"""

from src.data.vix_structure import fetch_vix_term_structure
from src.config.thresholds import VIX_STRUCTURE_RULES


def classify_vix_structure() -> dict:
    data = fetch_vix_term_structure()
    vix = data.get("vix")
    vix9d = data.get("vix9d")
    vix3m = data.get("vix3m")

    if vix is None or vix9d is None:
        return {"snapshot": data, "modifiers": {}}

    modifiers = {"sell_put": 0, "leaps_entry": 0, "sell_call": 0}

    if data.get("vix9d_inverted"):
        # VIX9D > VIX:短期極恐慌但中期穩 → 賣 PUT/LEAPS +15
        modifiers["sell_put"] = VIX_STRUCTURE_RULES["vix9d_inversion_modifier"]
        modifiers["leaps_entry"] = VIX_STRUCTURE_RULES["vix9d_inversion_modifier"]

    if data.get("vix3m_inverted"):
        # VIX > VIX3M:整體恐慌持續 → 暫停新建 long premium(在 veto 處理)
        modifiers["leaps_entry_veto"] = True

    return {"snapshot": data, "modifiers": modifiers}
```

### 7.8 src/layers/aaii_sentiment.py

```python
"""Layer 0.7 - AAII 情緒(週四更新)"""

import httpx
import re
from datetime import datetime
from selectolax.parser import HTMLParser
from loguru import logger

from src.config.thresholds import LAYER0_SUBMODIFIER_RANGES
from src.storage.state_manager import write_json


HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_aaii_latest() -> dict:
    """從 AAII 網站抓最新一週情緒調查"""
    url = "https://www.aaii.com/sentimentsurvey/sent_results"
    try:
        with httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            tree = HTMLParser(r.text)
            text = tree.text()
            # 用 regex 抓 Bullish/Neutral/Bearish 百分比
            m_bull = re.search(r"Bullish[\s\S]{0,80}?(\d+\.\d+)%", text)
            m_neu = re.search(r"Neutral[\s\S]{0,80}?(\d+\.\d+)%", text)
            m_bear = re.search(r"Bearish[\s\S]{0,80}?(\d+\.\d+)%", text)

            if m_bull and m_bear:
                bull = float(m_bull.group(1))
                bear = float(m_bear.group(1))
                neu = float(m_neu.group(1)) if m_neu else (100 - bull - bear)
                return {
                    "bullish": bull,
                    "bearish": bear,
                    "neutral": neu,
                    "spread": bull - bear,
                    "fetched_at": datetime.utcnow().isoformat(),
                }
        return {}
    except Exception as e:
        logger.error(f"fetch_aaii_latest failed: {e}")
        return {}


def classify_aaii() -> dict:
    data = fetch_aaii_latest()
    if not data:
        return {"data": {}, "modifier": 0}

    spread = data.get("spread", 0)
    min_mod, max_mod = LAYER0_SUBMODIFIER_RANGES["aaii_sentiment"]

    if spread > 30:  # 極端樂觀(反向)
        modifier = min_mod  # -5
    elif spread < -20:  # 極端悲觀(反向 = 買進機會)
        modifier = max_mod  # +5
    else:
        modifier = 0

    write_json("aaii_history.json", data)
    return {"data": data, "modifier": modifier}
```

### 7.9 src/layers/trump_classifier.py

```python
"""Layer 0+.1 - Trump Truth Social 三級分類"""

from datetime import datetime
from loguru import logger

from src.data.trump_truth import fetch_recent_posts, filter_new_posts, extract_text
from src.config.keywords import classify_post, get_matched_keywords
from src.config.position_mapping import map_event_to_positions


def scan_and_classify() -> list:
    """抓新貼文 + 分類 + 映射部位
    回傳 list of {tier, text, matched_keywords, events, post_meta}
    """
    posts = fetch_recent_posts()
    new_posts = filter_new_posts(posts)

    classified = []
    for p in new_posts:
        text = extract_text(p)
        if not text:
            continue
        tier = classify_post(text)
        if tier == "tier3":
            continue  # 入庫不推

        matched = get_matched_keywords(text)
        events = map_event_to_positions(matched)

        classified.append({
            "post_id": str(p.get("id", "")),
            "tier": tier,
            "text": text[:500],  # 截斷防超長
            "created_at": p.get("created_at", ""),
            "matched_keywords": matched,
            "events": events,
            "scan_time": datetime.utcnow().isoformat(),
        })
    return classified
```

### 7.10 src/layers/news_classifier.py

```python
"""Layer 0+.2 - RSS 新聞分類"""

from src.data.rss_feeds import fetch_all_feeds, filter_by_keywords


def scan_recent_news(lookback_minutes: int = 15) -> list:
    """抓最近 RSS 並過濾"""
    items = fetch_all_feeds(lookback_minutes)
    return filter_by_keywords(items)
```

### 7.11 src/layers/fundamentals_dashboard.py

```python
"""Layer F.1 - 基本面儀表板"""

from src.data.fundamentals import fetch_fundamentals


def build_fundamentals_dashboard(symbols: list) -> dict:
    """為白名單建立基本面快照"""
    return {s: fetch_fundamentals(s) for s in symbols}
```

### 7.12 src/layers/analyst_dashboard.py

```python
"""Layer F.2 - 分析師動向"""

from src.data.analyst_actions import fetch_analyst_actions


def build_analyst_dashboard(symbols: list, lookback_days: int = 7) -> dict:
    return {s: fetch_analyst_actions(s, lookback_days) for s in symbols}


def get_analyst_modifier(symbol: str) -> dict:
    """LEAPS 訊號加成 / 賣 CALL 否決參考"""
    data = fetch_analyst_actions(symbol, 7)
    upgrades = data["upgrades"]
    downgrades = data["downgrades"]

    modifier = 0
    if upgrades >= 2:
        modifier += 5  # LEAPS +5
    if downgrades >= 2:
        modifier -= 5

    return {
        "data": data,
        "leaps_modifier": modifier,
        "sell_call_veto": upgrades >= 2,  # 賣 CALL 否決條件
    }
```

### 7.13 src/layers/institutional_dashboard.py

```python
"""Layer F.3 - 13F 機構動向"""

from src.data.institutional_holdings import scan_all_institutions


def build_institutional_dashboard(target_symbols: list) -> dict:
    return scan_all_institutions(target_symbols)


def detect_divergence(symbol: str, analyst_data: dict, inst_data: dict) -> bool:
    """偵測「分析師上調 vs 13F 減倉」背離"""
    syms_decreased = inst_data.get(symbol, {}).get("DECREASED", [])
    analyst_upgrades = analyst_data.get(symbol, {}).get("upgrades", 0)
    return analyst_upgrades >= 2 and len(syms_decreased) >= 2
```

### 7.14 src/layers/insider_signals.py

```python
"""Layer F.4 - Insider Cluster Buying"""

from src.data.form4_insider import detect_cluster_buying, detect_ceo_cfo_buy
from src.config.thresholds import INSIDER_BUYING_RULES


def get_insider_modifier(symbol: str) -> dict:
    """根據 Cluster + CEO/CFO 大買加成"""
    cluster = detect_cluster_buying(
        symbol,
        lookback_days=INSIDER_BUYING_RULES["tier3_cluster"]["lookback_days"],
        min_insiders=INSIDER_BUYING_RULES["tier3_cluster"]["min_insiders"],
        min_total_usd=INSIDER_BUYING_RULES["tier3_cluster"]["min_total_usd"],
    )
    ceo_buys = detect_ceo_cfo_buy(
        symbol,
        lookback_days=7,
        min_usd=INSIDER_BUYING_RULES["tier2_ceo_cfo_min_usd"],
    )

    leaps_mod = 0
    sell_put_mod = 0
    tier = "none"

    if cluster["is_cluster"]:
        leaps_mod = INSIDER_BUYING_RULES["tier3_signal_boost"]["leaps_entry"]
        sell_put_mod = INSIDER_BUYING_RULES["tier3_signal_boost"]["sell_put"]
        tier = "tier3_cluster"
    elif ceo_buys:
        leaps_mod = INSIDER_BUYING_RULES["tier2_signal_boost"]["leaps_entry"]
        tier = "tier2_ceo_cfo"

    return {
        "tier": tier,
        "cluster_data": cluster,
        "ceo_cfo_buys": ceo_buys,
        "modifiers": {"leaps_entry": leaps_mod, "sell_put": sell_put_mod},
    }
```

### 7.15 src/layers/modifier_aggregator.py

```python
"""統一彙整所有 Layer 0 / F → 給 signals/ 使用"""

from datetime import datetime
from loguru import logger

from src.layers.macro_regime import classify_macro_regime
from src.layers.breadth import classify_breadth
from src.layers.distribution import classify_distribution
from src.layers.bubble import calc_bubble_score
from src.layers.put_call import classify_put_call
from src.layers.vix_structure_layer import classify_vix_structure
from src.layers.aaii_sentiment import classify_aaii
from src.config.thresholds import LAYER0_MODIFIER_MIN, LAYER0_MODIFIER_MAX
from src.storage.state_manager import write_json


def aggregate_layer0() -> dict:
    """跑全部 7 個 Layer 0 子模組,回傳彙整 dict"""
    out = {
        "scan_time": datetime.utcnow().isoformat(),
        "submodules": {},
    }

    try:
        out["submodules"]["macro_regime"] = classify_macro_regime()
    except Exception as e:
        logger.error(f"macro_regime failed: {e}")
        out["submodules"]["macro_regime"] = {"modifier": 0}

    try:
        out["submodules"]["breadth"] = classify_breadth()
    except Exception as e:
        logger.error(f"breadth failed: {e}")
        out["submodules"]["breadth"] = {"modifier": 0}

    try:
        out["submodules"]["distribution"] = classify_distribution()
    except Exception as e:
        logger.error(f"distribution failed: {e}")
        out["submodules"]["distribution"] = {"modifiers": {}}

    try:
        out["submodules"]["bubble"] = calc_bubble_score()
    except Exception as e:
        logger.error(f"bubble failed: {e}")
        out["submodules"]["bubble"] = {"modifier": 0}

    try:
        out["submodules"]["put_call"] = classify_put_call()
    except Exception as e:
        logger.error(f"put_call failed: {e}")
        out["submodules"]["put_call"] = {"modifiers": {}}

    try:
        out["submodules"]["vix_structure"] = classify_vix_structure()
    except Exception as e:
        logger.error(f"vix_structure failed: {e}")
        out["submodules"]["vix_structure"] = {"modifiers": {}}

    try:
        out["submodules"]["aaii"] = classify_aaii()
    except Exception as e:
        logger.error(f"aaii failed: {e}")
        out["submodules"]["aaii"] = {"modifier": 0}

    # 統一 modifier(分訊號類型)
    out["aggregate_modifiers"] = _aggregate_per_signal_type(out["submodules"])

    write_json("layer0_history.json", out)
    return out


def _aggregate_per_signal_type(submodules: dict) -> dict:
    """根據三大訊號類型,加總對應的 modifiers"""
    sell_call_mod = 0
    sell_put_mod = 0
    leaps_entry_mod = 0
    leaps_entry_veto = False

    # macro_regime / breadth / bubble / aaii 通用對「進場類訊號」(sell_put + leaps)有負面影響
    macro_mod = submodules.get("macro_regime", {}).get("modifier", 0)
    breadth_mod = submodules.get("breadth", {}).get("modifier", 0)
    bubble_mod = submodules.get("bubble", {}).get("modifier", 0)
    aaii_mod = submodules.get("aaii", {}).get("modifier", 0)

    sell_put_mod += macro_mod + breadth_mod + bubble_mod + aaii_mod
    leaps_entry_mod += macro_mod + breadth_mod + bubble_mod + aaii_mod
    sell_call_mod += -macro_mod * 0.3  # 負相關較弱

    # distribution
    dist = submodules.get("distribution", {}).get("modifiers", {})
    sell_call_mod += dist.get("sell_call", 0)
    sell_put_mod += dist.get("sell_put", 0)
    leaps_entry_mod += dist.get("leaps_entry", 0)

    # put_call
    pcr = submodules.get("put_call", {}).get("modifiers", {})
    sell_call_mod += pcr.get("sell_call", 0)
    sell_put_mod += pcr.get("sell_put", 0)
    leaps_entry_mod += pcr.get("leaps_entry", 0)

    # vix_structure
    vix = submodules.get("vix_structure", {}).get("modifiers", {})
    sell_call_mod += vix.get("sell_call", 0)
    sell_put_mod += vix.get("sell_put", 0)
    leaps_entry_mod += vix.get("leaps_entry", 0)
    leaps_entry_veto = vix.get("leaps_entry_veto", False)

    # 上下限 clip
    return {
        "sell_call": int(max(LAYER0_MODIFIER_MIN, min(LAYER0_MODIFIER_MAX, sell_call_mod))),
        "sell_put": int(max(LAYER0_MODIFIER_MIN, min(LAYER0_MODIFIER_MAX, sell_put_mod))),
        "leaps_entry": int(max(LAYER0_MODIFIER_MIN, min(LAYER0_MODIFIER_MAX, leaps_entry_mod))),
        "leaps_entry_veto": leaps_entry_veto,
    }
```

---

## 8. src/signals/ 三大核心訊號評分系統

### 8.1 src/signals/__init__.py

```python
# 空檔
```

### 8.2 src/signals/base_scorer.py

```python
"""共用評分基底"""

from typing import Optional


def normalize_to_100(score: float, max_score: float) -> float:
    """將原始分數縮放至 0-100"""
    if max_score <= 0:
        return 0
    return min(100, max(0, score / max_score * 100))


def score_with_threshold(value: float, thresholds: list, scores: list) -> float:
    """根據閾值階梯給分
    e.g. score_with_threshold(rsi, [30, 50, 70], [40, 20, 5]) =
         rsi<=30 → 40, rsi<=50 → 20, rsi<=70 → 5, else 0
    """
    for thr, s in zip(thresholds, scores):
        if value <= thr:
            return s
    return 0
```

### 8.3 src/signals/sell_call_scorer.py

```python
"""系統 #1 - 賣 CALL 評分(Covered/Diagonal/Naked 對 2x ETF)"""

from loguru import logger

from src.data.price_data import fetch_history, get_52w_high_low
from src.data.iv_rank import calc_iv_rank, get_atm_iv
from src.data.earnings_calendar import is_earnings_within_days
from src.indicators.basic import (
    get_rsi_latest, get_bbands_position, get_ma_position,
    get_adx_latest, get_consecutive_up_days,
)
from src.indicators.volume import detect_volume_surge
from src.indicators.pattern import detect_resistance_rejection
from src.layers.analyst_dashboard import get_analyst_modifier
from src.config.thresholds import (
    SELL_CALL_WEIGHTS, SELL_CALL_VETO, IVR_THRESHOLDS, IVR_2X_ETF_THRESHOLD,
)
from src.config.universe import ETF_LEVERAGED_SINGLE_STOCK


def score_sell_call(symbol: str, layer0_mod: int = 0) -> dict:
    """單一標的賣 CALL 評分"""
    df = fetch_history(symbol, period="6mo", interval="1d")
    if df.empty:
        return {"symbol": symbol, "score": 0, "skip_reason": "no_data"}

    is_2x_etf = symbol in ETF_LEVERAGED_SINGLE_STOCK
    ivr_threshold = IVR_2X_ETF_THRESHOLD if is_2x_etf else IVR_THRESHOLDS["min_for_short_premium"]

    # ---- 否決條件先檢查 ----
    veto_reasons = []

    # 1. 7 天內財報
    if is_earnings_within_days(symbol, SELL_CALL_VETO["earnings_within_days"]):
        veto_reasons.append("earnings_within_7_days")

    # 2. 創 52W 新高且放量
    high_data = get_52w_high_low(symbol)
    if (high_data["pct_from_high"] is not None
            and high_data["pct_from_high"] > -(1 - SELL_CALL_VETO["near_52w_high_pct"])
            and detect_volume_surge(df, SELL_CALL_VETO["volume_surge_multiplier"])):
        veto_reasons.append("near_52w_high_with_volume_surge")

    # 3. ADX > 25(強趨勢)
    adx = get_adx_latest(df, 14)
    if adx and adx > SELL_CALL_VETO["adx_strong_trend"]:
        veto_reasons.append("strong_trend_adx_above_25")

    # 4. ≥2 家分析師上調
    analyst = get_analyst_modifier(symbol)
    if analyst.get("sell_call_veto"):
        veto_reasons.append("analyst_upgrades_2plus")

    # 5. IVR < 門檻(學習鎖第 2 條)
    ivr_data = calc_iv_rank(symbol)
    ivr = ivr_data.get("ivr")
    if ivr is not None and ivr < ivr_threshold:
        veto_reasons.append(f"ivr_below_{ivr_threshold}")

    if veto_reasons:
        return {
            "symbol": symbol, "score": 0,
            "veto_reasons": veto_reasons,
            "skip_reason": "veto_triggered",
        }

    # ---- 正向評分 ----
    weights = SELL_CALL_WEIGHTS
    score_components = {}

    # 權利金面(40分):IVR + IV/HV + ATM Premium 月化率
    iv_score = 0
    if ivr is not None:
        iv_score = (ivr / 100) * 25  # IVR 越高越多分
    atm_iv = get_atm_iv(symbol) or 0
    iv_score += min(15, atm_iv * 50)  # IV 0.3 ≈ 15 分
    score_components["premium"] = min(weights["premium"], iv_score)

    # 價格面(40分)
    rsi = get_rsi_latest(df, 14) or 50
    bb_pos = get_bbands_position(df)
    ma_pos = get_ma_position(df)
    consecutive = get_consecutive_up_days(df)

    price_score = 0
    if rsi > 70:
        price_score += 15
    elif rsi > 60:
        price_score += 8

    if ma_pos.get("pct_from_sma_20", 0) > 0.05:
        price_score += 10  # 距 20MA 上方 5%+

    if consecutive >= 4:
        price_score += 8

    if bb_pos.get("touch_upper"):
        price_score += 7

    score_components["price"] = min(weights["price"], price_score)

    # 形態確認(20分)
    pattern_score = 0
    if detect_resistance_rejection(df):
        pattern_score += 12
    from src.indicators.volume import detect_volume_price_divergence
    div = detect_volume_price_divergence(df)
    if div.get("type") == "bearish":
        pattern_score += 8
    score_components["pattern"] = min(weights["pattern"], pattern_score)

    # 加總底層(0-100)
    base_score = sum(score_components.values())

    # Layer 0 加成(限 max_layer0)
    layer0_capped = max(-weights["max_layer0"], min(weights["max_layer0"], layer0_mod))
    final = base_score + layer0_capped

    return {
        "symbol": symbol,
        "signal_type": "sell_call",
        "score": int(final),
        "base_score": int(base_score),
        "layer0_modifier": layer0_capped,
        "components": score_components,
        "indicators": {
            "rsi": rsi,
            "ivr": ivr,
            "atm_iv": atm_iv,
            "adx": adx,
            "pct_from_52w_high": high_data["pct_from_high"],
            "consecutive_up": consecutive,
            "bb_pos_pct": bb_pos.get("pct"),
        },
    }
```

### 8.4 src/signals/sell_put_scorer.py

```python
"""系統 #2 - 賣 PUT (Wheel Strategy)"""

from loguru import logger

from src.data.price_data import fetch_history, get_52w_high_low
from src.data.iv_rank import calc_iv_rank, get_atm_iv
from src.data.earnings_calendar import is_earnings_within_days
from src.data.vix_structure import fetch_vix_term_structure
from src.indicators.basic import (
    get_rsi_latest, get_bbands_position, get_ma_position,
)
from src.indicators.pattern import find_support_resistance
from src.layers.insider_signals import get_insider_modifier
from src.config.thresholds import (
    SELL_PUT_WEIGHTS, SELL_PUT_VETO, IVR_THRESHOLDS,
)
from src.config.universe import SELL_PUT_WHITELIST


def score_sell_put(symbol: str, layer0_mod: int = 0,
                    layerf_mod_extra: int = 0) -> dict:
    """單一標的賣 PUT 評分"""

    # ---- 第一道閘門:白名單 ----
    if symbol not in SELL_PUT_WHITELIST:
        return {
            "symbol": symbol, "score": 0,
            "skip_reason": "not_in_whitelist",
        }

    df = fetch_history(symbol, period="6mo", interval="1d")
    if df.empty:
        return {"symbol": symbol, "score": 0, "skip_reason": "no_data"}

    # ---- 否決條件 ----
    veto_reasons = []

    if is_earnings_within_days(symbol, SELL_PUT_VETO["earnings_within_days"]):
        veto_reasons.append("earnings_within_7_days")

    vix_data = fetch_vix_term_structure()
    vix = vix_data.get("vix")
    if vix and vix > SELL_PUT_VETO["vix_extreme"]:
        veto_reasons.append(f"vix_above_{SELL_PUT_VETO['vix_extreme']}")

    ivr_data = calc_iv_rank(symbol)
    ivr = ivr_data.get("ivr")
    if ivr is not None and ivr < IVR_THRESHOLDS["min_for_short_premium"]:
        veto_reasons.append("ivr_below_30")

    if veto_reasons:
        return {
            "symbol": symbol, "score": 0,
            "veto_reasons": veto_reasons, "skip_reason": "veto_triggered",
        }

    # ---- 正向評分 ----
    weights = SELL_PUT_WEIGHTS
    components = {}

    # 權利金面(35分)
    iv_score = 0
    if ivr is not None:
        iv_score = (ivr / 100) * 20
    atm_iv = get_atm_iv(symbol) or 0
    iv_score += min(15, atm_iv * 50)
    components["premium"] = min(weights["premium"], iv_score)

    # 進場品質(45分)
    rsi = get_rsi_latest(df, 14) or 50
    high_data = get_52w_high_low(symbol)
    bb_pos = get_bbands_position(df)
    sr = find_support_resistance(df)

    entry_score = 0
    if rsi < 30:
        entry_score += 18
    elif rsi < 40:
        entry_score += 10

    pct_from_high = high_data["pct_from_high"] or 0
    if pct_from_high < -0.20:
        entry_score += 12
    elif pct_from_high < -0.10:
        entry_score += 6

    if bb_pos.get("touch_lower"):
        entry_score += 8

    if sr.get("near_support"):
        entry_score += 7

    components["entry_quality"] = min(weights["entry_quality"], entry_score)

    # 形態確認(20分)
    pattern_score = 0
    # 簡化:有 RSI < 35 + 觸 BB 下軌即視為「支撐區反彈」
    if rsi < 35 and bb_pos.get("touch_lower"):
        pattern_score += 12
    components["pattern"] = min(weights["pattern"], pattern_score)

    base_score = sum(components.values())

    # Layer 0 + Layer F 加成
    layer0_capped = max(-weights["max_layer0"], min(weights["max_layer0"], layer0_mod))
    layerf_capped = max(0, min(weights["max_layerf"], layerf_mod_extra))

    final = base_score + layer0_capped + layerf_capped

    return {
        "symbol": symbol,
        "signal_type": "sell_put",
        "score": int(final),
        "base_score": int(base_score),
        "layer0_modifier": layer0_capped,
        "layerf_modifier": layerf_capped,
        "components": components,
        "indicators": {
            "rsi": rsi,
            "ivr": ivr,
            "atm_iv": atm_iv,
            "pct_from_52w_high": pct_from_high,
            "near_support": sr.get("near_support"),
        },
    }
```

### 8.5 src/signals/leaps_entry_scorer.py

```python
"""系統 #3 - LEAPS 進場評分"""

import json
from pathlib import Path
from loguru import logger

from src.data.price_data import fetch_history, get_52w_high_low
from src.data.iv_rank import calc_iv_rank
from src.data.earnings_calendar import is_earnings_within_days
from src.data.vix_structure import is_vix_consecutive_above
from src.data.fundamentals import fetch_fundamentals, detect_consecutive_eps_miss
from src.indicators.basic import get_rsi_latest, get_bbands_position, get_ma_position
from src.layers.insider_signals import get_insider_modifier
from src.config.thresholds import (
    LEAPS_ENTRY_WEIGHTS, LEAPS_ENTRY_VETO, IVR_THRESHOLDS, HARD_RULES,
)
from src.config.universe import ETF_LEVERAGED_SINGLE_STOCK
from src.storage.state_manager import DATA_STORE_DIR

UNIVERSE_THESIS_PATH = DATA_STORE_DIR / "universe_with_thesis.json"


def get_value_thesis(symbol: str) -> str:
    """讀 universe_with_thesis.json 取得標的的 value_thesis"""
    if not UNIVERSE_THESIS_PATH.exists():
        return "fair_value"
    with open(UNIVERSE_THESIS_PATH) as f:
        data = json.load(f)
    return data.get("tickers", {}).get(symbol, {}).get(
        "value_thesis", {}
    ).get("rating", "fair_value")


def score_leaps_entry(symbol: str, layer0_mod: int = 0,
                      layerf_mod_extra: int = 0,
                      layer0_veto: bool = False) -> dict:
    """單一標的 LEAPS 進場評分"""

    # ---- 學習鎖第 6 條:單股 2x ETF 不出 LEAPS ----
    if symbol in ETF_LEVERAGED_SINGLE_STOCK:
        return {"symbol": symbol, "score": 0, "skip_reason": "single_stock_2x_etf_no_leaps"}

    df = fetch_history(symbol, period="6mo", interval="1d")
    if df.empty:
        return {"symbol": symbol, "score": 0, "skip_reason": "no_data"}

    # ---- 否決條件 ----
    veto_reasons = []

    if is_earnings_within_days(symbol, LEAPS_ENTRY_VETO["earnings_within_days"]):
        veto_reasons.append("earnings_within_7_days")

    if is_vix_consecutive_above(30, LEAPS_ENTRY_VETO["vix_extreme_consecutive_days"]):
        veto_reasons.append("vix_consecutive_above_30")

    if detect_consecutive_eps_miss(symbol, 2):
        veto_reasons.append("consecutive_2q_eps_miss")

    if layer0_veto:
        veto_reasons.append("layer0_vix_term_inverted")

    thesis = get_value_thesis(symbol)
    if thesis in ["review", "exit"]:
        veto_reasons.append(f"value_thesis_{thesis}")

    if veto_reasons:
        return {
            "symbol": symbol, "score": 0,
            "veto_reasons": veto_reasons, "skip_reason": "veto_triggered",
        }

    # ---- 正向評分 ----
    weights = LEAPS_ENTRY_WEIGHTS
    components = {}

    rsi = get_rsi_latest(df, 14) or 50
    high_data = get_52w_high_low(symbol)
    bb_pos = get_bbands_position(df)
    ma_pos = get_ma_position(df)

    # 進場品質(60分)
    entry_score = 0
    if rsi < 30:
        entry_score += 22
    elif rsi < 40:
        entry_score += 12

    if bb_pos.get("touch_lower"):
        entry_score += 12

    pct_from_50ma = ma_pos.get("pct_from_sma_50", 0)
    if pct_from_50ma < -0.05:
        entry_score += 12  # 跌破 50MA

    pct_from_high = high_data["pct_from_high"] or 0
    if pct_from_high < -0.25:
        entry_score += 14  # 距高點 -25% 以下
    elif pct_from_high < -0.15:
        entry_score += 7
    components["entry_quality"] = min(weights["entry_quality"], entry_score)

    # 估值面(20分)
    fund = fetch_fundamentals(symbol)
    val_score = 0
    pe_fwd = fund.get("pe_forward")
    if pe_fwd and pe_fwd > 0 and pe_fwd < 20:
        val_score += 8
    fcf_y = fund.get("fcf_yield")
    if fcf_y and fcf_y > 0.04:
        val_score += 7
    peg = fund.get("peg")
    if peg and 0 < peg < 1.5:
        val_score += 5
    components["valuation"] = min(weights["valuation"], val_score)

    # 波動面(20分)
    ivr_data = calc_iv_rank(symbol)
    ivr = ivr_data.get("ivr")
    vol_score = 0
    if ivr is not None and 30 <= ivr <= 70:
        vol_score = 20  # IVR 正中段
    elif ivr is not None and ivr > 70:
        vol_score = 12
    elif ivr is not None and ivr < 30:
        vol_score = 8
    components["volatility"] = min(weights["volatility"], vol_score)

    base_score = sum(components.values())

    # Layer 0 + Layer F 加成
    layer0_capped = max(-30, min(20, layer0_mod))
    layerf_capped = max(0, min(weights["max_layerf"], layerf_mod_extra))

    final = base_score + layer0_capped + layerf_capped

    return {
        "symbol": symbol,
        "signal_type": "leaps_entry",
        "score": int(final),
        "base_score": int(base_score),
        "layer0_modifier": layer0_capped,
        "layerf_modifier": layerf_capped,
        "components": components,
        "value_thesis": thesis,
        "indicators": {
            "rsi": rsi,
            "ivr": ivr,
            "pct_from_52w_high": pct_from_high,
            "pct_from_50ma": pct_from_50ma,
            "pe_forward": pe_fwd,
            "fcf_yield": fcf_y,
        },
    }
```

### 8.6 src/signals/veto_checker.py

```python
"""跨訊號通用否決檢查"""

from loguru import logger

from src.data.earnings_calendar import is_earnings_within_days
from src.data.vix_structure import is_vix_consecutive_above
from src.config.thresholds import HARD_RULES


def check_hard_rules(symbol: str, signal_type: str, dte_days: int = None) -> list:
    """檢查所有學習鎖 - 回傳被觸發的規則 list(空 = 全通過)"""
    triggered = []

    # 規則 1:Long Call DTE < 365 → 否決
    if signal_type == "leaps_entry" and dte_days is not None:
        if dte_days < HARD_RULES["min_long_call_dte_days"]:
            triggered.append("rule1_dte_below_365")

    # 規則 3:財報前 7 天不 short premium
    if signal_type in ["sell_call", "sell_put"]:
        if is_earnings_within_days(
            symbol, HARD_RULES["no_short_premium_within_earnings_days"]
        ):
            triggered.append("rule3_earnings_within_7_days")

    # 規則 4:連 3 天 VIX > 30 不 long premium
    if signal_type == "leaps_entry":
        if is_vix_consecutive_above(30, HARD_RULES["no_long_premium_after_vix_high_days"]):
            triggered.append("rule4_vix_consecutive_above_30")

    # 規則 5:Tier C 不賣 PUT
    if signal_type == "sell_put" and symbol in HARD_RULES["tier_c_no_sell_put"]:
        triggered.append("rule5_tier_c_no_sell_put")

    return triggered
```

### 8.7 src/signals/final_scorer.py

```python
"""整合 base + modifier + veto + Trump 標籤 → 最終分數"""

from datetime import datetime
from loguru import logger

from src.signals.sell_call_scorer import score_sell_call
from src.signals.sell_put_scorer import score_sell_put
from src.signals.leaps_entry_scorer import score_leaps_entry
from src.signals.veto_checker import check_hard_rules
from src.layers.modifier_aggregator import aggregate_layer0
from src.layers.insider_signals import get_insider_modifier
from src.config.universe import (
    ALL_US_STOCKS, SELL_PUT_WHITELIST, ETF_LEVERAGED_SINGLE_STOCK,
    get_priority,
)
from src.config.thresholds import (
    PRIORITY_PUSH_THRESHOLD, PUSH_THRESHOLD_GREEN, PUSH_THRESHOLD_YELLOW,
)


def scan_all_signals(current_holdings: list = None) -> dict:
    """完整掃描三大訊號"""
    layer0 = aggregate_layer0()
    mods = layer0["aggregate_modifiers"]

    out = {
        "scan_time": datetime.utcnow().isoformat(),
        "layer0_summary": {
            k: v.get("modifier") or v.get("modifiers") or {}
            for k, v in layer0["submodules"].items()
        },
        "sell_call": [],
        "sell_put": [],
        "leaps_entry": [],
    }

    # 1. Sell CALL - 全 universe + 單股 2x ETF
    sc_universe = ALL_US_STOCKS + list(ETF_LEVERAGED_SINGLE_STOCK.keys())
    for sym in sc_universe:
        try:
            r = score_sell_call(sym, layer0_mod=mods["sell_call"])
            if r.get("score", 0) > 0:
                # 學習鎖檢查
                hard = check_hard_rules(sym, "sell_call")
                if hard:
                    r["score"] = 0
                    r["hard_rule_violations"] = hard
                _attach_priority_and_push(r, current_holdings)
                out["sell_call"].append(r)
        except Exception as e:
            logger.error(f"score_sell_call({sym}) failed: {e}")

    # 2. Sell PUT - 僅白名單
    for sym in SELL_PUT_WHITELIST:
        try:
            insider = get_insider_modifier(sym)
            r = score_sell_put(
                sym,
                layer0_mod=mods["sell_put"],
                layerf_mod_extra=insider["modifiers"]["sell_put"],
            )
            if r.get("score", 0) > 0:
                hard = check_hard_rules(sym, "sell_put")
                if hard:
                    r["score"] = 0
                    r["hard_rule_violations"] = hard
                r["insider_signal"] = insider["tier"]
                _attach_priority_and_push(r, current_holdings)
                out["sell_put"].append(r)
        except Exception as e:
            logger.error(f"score_sell_put({sym}) failed: {e}")

    # 3. LEAPS Entry - 排除單股 2x ETF
    for sym in ALL_US_STOCKS:
        if sym in ETF_LEVERAGED_SINGLE_STOCK:
            continue
        try:
            insider = get_insider_modifier(sym)
            r = score_leaps_entry(
                sym,
                layer0_mod=mods["leaps_entry"],
                layerf_mod_extra=insider["modifiers"]["leaps_entry"],
                layer0_veto=mods["leaps_entry_veto"],
            )
            if r.get("score", 0) > 0:
                # LEAPS DTE 假設 540(理想範圍中點),會觸發學習鎖第 1 條
                hard = check_hard_rules(sym, "leaps_entry", dte_days=540)
                if hard:
                    r["score"] = 0
                    r["hard_rule_violations"] = hard
                r["insider_signal"] = insider["tier"]
                _attach_priority_and_push(r, current_holdings)
                out["leaps_entry"].append(r)
        except Exception as e:
            logger.error(f"score_leaps_entry({sym}) failed: {e}")

    # 排序(分數高 → 低)
    for k in ["sell_call", "sell_put", "leaps_entry"]:
        out[k].sort(key=lambda x: x.get("score", 0), reverse=True)

    return out


def _attach_priority_and_push(result: dict, current_holdings: list = None):
    """附加 P0/P1/P2/P3 優先級與是否達推播門檻"""
    sym = result["symbol"]
    priority = get_priority(sym, current_holdings or [])
    threshold = PRIORITY_PUSH_THRESHOLD.get(priority)

    result["priority"] = priority
    result["push_threshold"] = threshold
    result["should_push"] = (
        threshold is not None
        and result["score"] >= threshold
    )
    if PUSH_THRESHOLD_YELLOW <= result["score"] < (threshold or PUSH_THRESHOLD_GREEN):
        result["alert_level"] = "yellow"  # 進日報
    elif result["score"] >= (threshold or PUSH_THRESHOLD_GREEN):
        result["alert_level"] = "green"   # 推播
    else:
        result["alert_level"] = "white"
```

### 8.8 src/signals/exit_rules.py

```python
"""5 大出場規則 + value_thesis 例外"""

from datetime import datetime
from loguru import logger

from src.data.price_data import fetch_history, get_52w_high_low
from src.data.fundamentals import detect_consecutive_eps_miss
from src.data.analyst_actions import has_recent_downgrades
from src.indicators.basic import get_rsi_latest, get_bbands_position, get_ma_position
from src.signals.leaps_entry_scorer import get_value_thesis
from src.config.thresholds import SEASONAL_EXIT_RULES


def rule_a_technical_exit(symbol: str) -> dict:
    """規則 A:進場理由消失"""
    df = fetch_history(symbol, period="3mo")
    if df.empty:
        return {"trigger": False}

    rsi = get_rsi_latest(df) or 50
    bb = get_bbands_position(df)
    ma = get_ma_position(df)
    high = get_52w_high_low(symbol)

    triggers = []
    if rsi > 75:
        triggers.append("rsi_above_75")
    if bb.get("touch_upper") or (bb.get("pct", 0.5) > 0.95):
        triggers.append("bb_upper_break")
    if ma.get("pct_from_sma_50", 0) > 0.10:
        triggers.append("above_50ma_10pct")
    if high.get("pct_from_high", -1) > -0.03:
        triggers.append("near_52w_high_3pct")

    thesis = get_value_thesis(symbol)
    note = ("value_thesis=deep_value → 改出戰術賣 short call,不出場"
            if thesis == "deep_value" else None)

    return {
        "rule": "A_technical_exit",
        "trigger": len(triggers) >= 2,
        "triggers": triggers,
        "value_thesis": thesis,
        "note": note,
    }


def rule_b_fundamental_breakdown(symbol: str) -> dict:
    """規則 B:基本面破裂"""
    eps_miss = detect_consecutive_eps_miss(symbol, 2)
    downgrades = has_recent_downgrades(symbol, n_min=3, lookback_days=30)
    return {
        "rule": "B_fundamental_breakdown",
        "trigger": eps_miss or downgrades,
        "eps_miss": eps_miss,
        "downgrades": downgrades,
        "action": "value_thesis 重新評估" if (eps_miss or downgrades) else None,
    }


def rule_c_seasonal_year_end(symbol: str, dte: int = 90) -> dict:
    """規則 C:LEAPS 季節性最佳化(11-12 月、DTE 60-120、距高點 < 5%)"""
    rules = SEASONAL_EXIT_RULES["leaps_year_end_peak"]
    now = datetime.now()

    in_window = now.month in rules["trigger_months"]
    dte_ok = rules["dte_range_days"][0] <= dte <= rules["dte_range_days"][1]

    high_data = get_52w_high_low(symbol)
    near_high = (
        high_data["pct_from_high"] is not None
        and high_data["pct_from_high"] > -rules["near_high_pct"]
    )

    triggered = in_window and dte_ok and near_high
    thesis = get_value_thesis(symbol)
    note = ("value_thesis=deep_value → 降為 roll out 建議"
            if thesis == "deep_value" and triggered else None)

    return {
        "rule": "C_seasonal_year_end",
        "trigger": triggered,
        "in_window": in_window,
        "dte_ok": dte_ok,
        "near_high": near_high,
        "value_thesis": thesis,
        "note": note,
    }


def rule_e_september_slump(symbol: str) -> dict:
    """規則 E:September Slump 防禦(7 月底-8 月中、週 RSI > 70、距高點 < 3%)"""
    rules = SEASONAL_EXIT_RULES["september_slump_defense"]
    now = datetime.now()
    in_window = now.month in rules["trigger_months"]

    df = fetch_history(symbol, period="3mo", interval="1wk")
    if df.empty:
        return {"trigger": False}

    weekly_rsi = get_rsi_latest(df, 14) or 50
    high_data = get_52w_high_low(symbol)

    triggered = (
        in_window
        and weekly_rsi >= rules["weekly_rsi_min"]
        and high_data.get("pct_from_high", -1) > -rules["near_high_pct"]
    )

    thesis = get_value_thesis(symbol)
    if triggered and thesis == "deep_value":
        return {"rule": "E_september_slump", "trigger": False,
                "note": "value_thesis=deep_value 跳過"}

    return {
        "rule": "E_september_slump",
        "trigger": triggered,
        "weekly_rsi": weekly_rsi,
        "in_window": in_window,
        "action": f"建議減碼 {rules['reduce_position_pct']:.0%}" if triggered else None,
    }


def evaluate_all_exit_rules(symbol: str, leaps_dte: int = None) -> list:
    """跑完整 5 條規則,回傳被觸發者"""
    rules = []
    for fn in [rule_a_technical_exit, rule_b_fundamental_breakdown, rule_e_september_slump]:
        try:
            r = fn(symbol)
            if r.get("trigger"):
                rules.append(r)
        except Exception as e:
            logger.error(f"{fn.__name__}({symbol}) failed: {e}")

    if leaps_dte is not None:
        try:
            r = rule_c_seasonal_year_end(symbol, leaps_dte)
            if r.get("trigger"):
                rules.append(r)
        except Exception as e:
            logger.error(f"rule_c({symbol}) failed: {e}")

    return rules
```

---

## 9. src/management/ 部位管理

### 9.1 src/management/__init__.py

```python
# 空檔
```

### 9.2 src/management/current_positions.py

```python
"""positions.json 載入 + 三模式判斷"""

from src.storage.state_manager import read_json
from src.config.settings import POSITION_MODE


def load_positions() -> dict:
    """載入目前部位"""
    return read_json("positions.json", default={"stocks": [], "options": []})


def get_holdings_symbols() -> list:
    """目前持倉的 symbols list(用於 P0 優先級)"""
    if POSITION_MODE == "mode_3":
        return []
    pos = load_positions()
    syms = set()
    for s in pos.get("stocks", []):
        if not s.get("_example"):
            syms.add(s["symbol"])
    for o in pos.get("options", []):
        if not o.get("_example"):
            syms.add(o["symbol"])
    return list(syms)


def get_long_options() -> list:
    """所有 long_call / long_put"""
    if POSITION_MODE == "mode_3":
        return []
    pos = load_positions()
    return [
        o for o in pos.get("options", [])
        if not o.get("_example") and o.get("type", "").startswith("long_")
    ]


def get_short_options() -> list:
    """所有 short_call / short_put"""
    if POSITION_MODE == "mode_3":
        return []
    pos = load_positions()
    return [
        o for o in pos.get("options", [])
        if not o.get("_example") and o.get("type", "").startswith("short_")
    ]
```

### 9.3 src/management/leaps_pnl_tracker.py

```python
"""LEAPS 損益觸發 - +50 / +100 / -30 / -40"""

from datetime import datetime
from loguru import logger

from src.data.price_data import get_latest_price
from src.data.greeks_calculator import calc_delta
from src.data.iv_rank import get_atm_iv
from src.management.current_positions import get_long_options
from src.config.thresholds import LEAPS_MANAGEMENT_TRIGGERS


def calc_option_pnl(option: dict) -> dict:
    """計算單一 LEAPS 損益(粗估,以當前 ATM IV 估)"""
    sym = option["symbol"]
    underlying = get_latest_price(sym)
    if underlying is None:
        return {}

    iv = get_atm_iv(sym) or 0.3
    expiry = datetime.strptime(option["expiry"], "%Y-%m-%d")
    dte = (expiry.date() - datetime.now().date()).days
    if dte <= 0:
        return {"option_id": option["id"], "expired": True}

    # 簡化估值:用 Black-Scholes
    from scipy.stats import norm
    import math

    K = option["strike"]
    T = dte / 365
    r = 0.045

    d1 = (math.log(underlying / K) + (r + 0.5 * iv**2) * T) / (iv * math.sqrt(T))
    d2 = d1 - iv * math.sqrt(T)

    if option["type"] == "long_call":
        current_price = underlying * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:  # long_put
        current_price = K * math.exp(-r * T) * norm.cdf(-d2) - underlying * norm.cdf(-d1)

    cost = option["cost_per_contract"]
    pnl_pct = (current_price - cost) / cost

    return {
        "option_id": option["id"],
        "underlying": underlying,
        "current_price_per_contract": round(current_price, 2),
        "cost_per_contract": cost,
        "pnl_pct": round(pnl_pct, 4),
        "dte": dte,
    }


def check_leaps_triggers() -> list:
    """檢查所有 LEAPS 是否觸發管理規則"""
    triggers = []
    options = get_long_options()
    rules = LEAPS_MANAGEMENT_TRIGGERS

    for opt in options:
        try:
            pnl = calc_option_pnl(opt)
            if not pnl or pnl.get("expired"):
                continue
            pct = pnl["pnl_pct"]
            dte = pnl["dte"]

            if pct >= rules["profit_take_partial_pct"]:
                triggers.append({"option_id": opt["id"], "level": "+100",
                                 "action": "賣 1/3 鎖利", "pnl": pnl})
            elif pct >= rules["profit_protect_pct"]:
                triggers.append({"option_id": opt["id"], "level": "+50",
                                 "action": "考慮變 diagonal", "pnl": pnl})
            elif pct <= rules["loss_force_decision_pct"]:
                triggers.append({"option_id": opt["id"], "level": "-40",
                                 "action": "強制決策:roll/平/diagonal", "pnl": pnl})
            elif pct <= rules["loss_warning_pct"]:
                triggers.append({"option_id": opt["id"], "level": "-30",
                                 "action": "警告,評估", "pnl": pnl})

            if dte < rules["dte_roll_threshold_days"]:
                triggers.append({"option_id": opt["id"], "level": "DTE_low",
                                 "action": "評估 roll out 至 18+ 月", "dte": dte})
        except Exception as e:
            logger.error(f"check_leaps_triggers({opt.get('id')}) failed: {e}")
    return triggers
```

### 9.4 src/management/short_delta_monitor.py

```python
"""Short Option Delta 監測 - |Delta| > 0.35 警報"""

from datetime import datetime
from loguru import logger

from src.data.price_data import get_latest_price
from src.data.greeks_calculator import calc_delta
from src.data.iv_rank import get_atm_iv
from src.management.current_positions import get_short_options
from src.config.thresholds import SHORT_OPTION_DEFENSE


def check_short_deltas() -> list:
    """檢查 short option Delta 是否超標"""
    alerts = []
    threshold = SHORT_OPTION_DEFENSE["delta_warning_threshold"]

    for opt in get_short_options():
        try:
            sym = opt["symbol"]
            underlying = get_latest_price(sym)
            if underlying is None:
                continue
            iv = get_atm_iv(sym) or 0.3
            expiry = datetime.strptime(opt["expiry"], "%Y-%m-%d")
            dte = (expiry.date() - datetime.now().date()).days
            if dte <= 0:
                continue

            opt_type = "call" if "call" in opt["type"] else "put"
            delta = calc_delta(
                S=underlying, K=opt["strike"],
                T=dte / 365, r=0.045, sigma=iv,
                option_type=opt_type,
            )

            if abs(delta) > threshold:
                alerts.append({
                    "option_id": opt.get("id", f"{sym}_{opt['strike']}"),
                    "symbol": sym, "delta": delta,
                    "underlying": underlying, "strike": opt["strike"],
                    "dte": dte,
                    "action": "考慮 roll up/down 或平倉",
                })
        except Exception as e:
            logger.error(f"check_short_deltas({opt}) failed: {e}")
    return alerts
```

### 9.5 src/management/hedge_dte_tracker.py

```python
"""對沖部位 DTE < 45 天提醒"""

from datetime import datetime
from loguru import logger

from src.management.current_positions import get_long_options
from src.config.thresholds import HEDGE_DTE_THRESHOLD_DAYS
from src.config.universe import ETF_HEDGE


def check_hedge_dte() -> list:
    """檢查對沖部位(long put/長期 hedge)DTE"""
    alerts = []
    for opt in get_long_options():
        if opt["symbol"] not in ETF_HEDGE and opt["type"] != "long_put":
            continue
        try:
            expiry = datetime.strptime(opt["expiry"], "%Y-%m-%d")
            dte = (expiry.date() - datetime.now().date()).days
            if 0 < dte < HEDGE_DTE_THRESHOLD_DAYS:
                alerts.append({
                    "option_id": opt.get("id"),
                    "symbol": opt["symbol"], "dte": dte,
                    "action": "對沖即將進入加速耗損期,建議換倉",
                })
        except Exception as e:
            logger.error(f"check_hedge_dte({opt}) failed: {e}")
    return alerts
```

### 9.6 src/management/account_drawdown.py

```python
"""帳戶回撤防線 -10 / -20 / -30"""

from datetime import datetime
from loguru import logger

from src.storage.state_manager import read_json, write_json
from src.config.thresholds import ACCOUNT_DRAWDOWN_LEVELS

DRAWDOWN_FILE = "drawdown_history.json"


def update_account_value(current_value: float) -> dict:
    """更新帳戶高點與當前回撤"""
    history = read_json(DRAWDOWN_FILE, default={"peak": 0, "current": 0})
    if current_value > history.get("peak", 0):
        history["peak"] = current_value
    history["current"] = current_value
    history["last_updated"] = datetime.utcnow().isoformat()

    drawdown = (current_value - history["peak"]) / history["peak"] if history["peak"] else 0
    history["drawdown_pct"] = drawdown

    # 觸發等級
    if drawdown <= ACCOUNT_DRAWDOWN_LEVELS["level_3"]:
        history["alert_level"] = "level_3"
        history["action"] = "防守模式:平所有 short premium"
    elif drawdown <= ACCOUNT_DRAWDOWN_LEVELS["level_2"]:
        history["alert_level"] = "level_2"
        history["action"] = "強制檢視 LEAPS,-30% 以上者考慮減半"
    elif drawdown <= ACCOUNT_DRAWDOWN_LEVELS["level_1"]:
        history["alert_level"] = "level_1"
        history["action"] = "暫停加碼,全面檢視"
    else:
        history["alert_level"] = "normal"
        history["action"] = None

    write_json(DRAWDOWN_FILE, history)
    return history
```

---

## 第 10 節:src/twstock/ — 台股訊號模組

### 10.1 src/twstock/twstock_signals.py

```python
"""台股核心訊號:00631L (台灣 50 正 2) + 2330 (台積電) 三級加碼"""

from datetime import datetime
import pytz
from loguru import logger

from src.data.twstock_data import fetch_twstock_price, fetch_twstock_history
from src.indicators.basic import calculate_rsi, calculate_bollinger_bands, calculate_ma
from src.config.thresholds import TWSTOCK_THRESHOLDS

TW_TZ = pytz.timezone("Asia/Taipei")


def evaluate_00631l_signal() -> dict:
    """
    00631L 三級加碼訊號:
    - Tier A:RSI(14) <= 30 + 跌破 BB 下軌  → 重壓加碼
    - Tier B:RSI(14) <= 40 + 接近 BB 下軌 + MA20 > MA60  → 中度加碼
    - Tier C:跌破 MA20 + 大盤多頭  → 輕度加碼
    """
    try:
        df = fetch_twstock_history("00631L", period="6mo")
        if df is None or len(df) < 60:
            return {"symbol": "00631L", "signal": "no_data"}

        rsi = calculate_rsi(df["Close"], length=14).iloc[-1]
        bb = calculate_bollinger_bands(df["Close"], length=20, std=2)
        bb_lower = bb["BBL"].iloc[-1]
        ma20 = calculate_ma(df["Close"], length=20).iloc[-1]
        ma60 = calculate_ma(df["Close"], length=60).iloc[-1]
        last_close = df["Close"].iloc[-1]

        signal = {
            "symbol": "00631L",
            "name": "元大台灣 50 正 2",
            "timestamp": datetime.now(TW_TZ).isoformat(),
            "price": float(last_close),
            "rsi14": float(rsi),
            "bb_lower": float(bb_lower),
            "ma20": float(ma20),
            "ma60": float(ma60),
        }

        thr = TWSTOCK_THRESHOLDS["00631L"]
        if rsi <= thr["tier_a_rsi"] and last_close <= bb_lower:
            signal.update({"tier": "A", "action": "重壓加碼", "alert_level": "green"})
        elif rsi <= thr["tier_b_rsi"] and last_close <= bb_lower * 1.02 and ma20 > ma60:
            signal.update({"tier": "B", "action": "中度加碼", "alert_level": "yellow"})
        elif last_close < ma20 and ma20 > ma60:
            signal.update({"tier": "C", "action": "輕度加碼", "alert_level": "white"})
        else:
            signal.update({"tier": None, "action": "觀望", "alert_level": "none"})

        return signal
    except Exception as e:
        logger.error(f"evaluate_00631l_signal failed: {e}")
        return {"symbol": "00631L", "signal": "error", "error": str(e)}


def evaluate_2330_signal() -> dict:
    """
    2330 台積電 三級加碼訊號(配合 TSMC 月營收)
    """
    try:
        df = fetch_twstock_history("2330", period="1y")
        if df is None or len(df) < 60:
            return {"symbol": "2330", "signal": "no_data"}

        rsi = calculate_rsi(df["Close"], length=14).iloc[-1]
        bb = calculate_bollinger_bands(df["Close"], length=20, std=2)
        ma60 = calculate_ma(df["Close"], length=60).iloc[-1]
        ma200 = calculate_ma(df["Close"], length=200).iloc[-1] if len(df) >= 200 else None
        last_close = df["Close"].iloc[-1]

        signal = {
            "symbol": "2330",
            "name": "台積電",
            "timestamp": datetime.now(TW_TZ).isoformat(),
            "price": float(last_close),
            "rsi14": float(rsi),
            "ma60": float(ma60),
            "ma200": float(ma200) if ma200 else None,
        }

        thr = TWSTOCK_THRESHOLDS["2330"]
        if rsi <= thr["tier_a_rsi"] and (ma200 is None or last_close > ma200):
            signal.update({"tier": "A", "action": "重壓加碼", "alert_level": "green"})
        elif rsi <= thr["tier_b_rsi"] and last_close > ma60:
            signal.update({"tier": "B", "action": "中度加碼", "alert_level": "yellow"})
        elif last_close < ma60 and ma200 and last_close > ma200:
            signal.update({"tier": "C", "action": "輕度加碼", "alert_level": "white"})
        else:
            signal.update({"tier": None, "action": "觀望", "alert_level": "none"})

        return signal
    except Exception as e:
        logger.error(f"evaluate_2330_signal failed: {e}")
        return {"symbol": "2330", "signal": "error", "error": str(e)}


def scan_twstock_core() -> list:
    """掃描台股核心標的"""
    return [evaluate_00631l_signal(), evaluate_2330_signal()]
```

### 10.2 src/twstock/active_etf_signals.py

```python
"""主動 ETF 三級訊號:00982A / 00981A / 00978A 等(依 universe)"""

from datetime import datetime
import pytz
from loguru import logger

from src.data.twstock_active_etf import fetch_active_etf_data
from src.indicators.basic import calculate_rsi, calculate_ma
from src.config.universe import TW_ACTIVE_ETF_LIST
from src.config.thresholds import ACTIVE_ETF_THRESHOLDS

TW_TZ = pytz.timezone("Asia/Taipei")


def evaluate_active_etf(symbol: str) -> dict:
    """
    主動 ETF 三級訊號:
    - Tier 1:折價 > 1% + RSI(14) <= 35  → 重壓
    - Tier 2:折價 > 0.5% + RSI(14) <= 45  → 中度
    - Tier 3:接近 NAV + 跌破 MA20  → 輕度
    """
    try:
        data = fetch_active_etf_data(symbol)
        if not data or "history" not in data:
            return {"symbol": symbol, "signal": "no_data"}

        df = data["history"]
        nav = data.get("nav")
        market_price = data.get("market_price", df["Close"].iloc[-1])
        premium_discount = (market_price - nav) / nav if nav else 0

        rsi = calculate_rsi(df["Close"], length=14).iloc[-1]
        ma20 = calculate_ma(df["Close"], length=20).iloc[-1]

        signal = {
            "symbol": symbol,
            "timestamp": datetime.now(TW_TZ).isoformat(),
            "market_price": float(market_price),
            "nav": float(nav) if nav else None,
            "premium_discount_pct": float(premium_discount * 100),
            "rsi14": float(rsi),
            "ma20": float(ma20),
        }

        thr = ACTIVE_ETF_THRESHOLDS
        if premium_discount <= -thr["tier_1_discount"] and rsi <= thr["tier_1_rsi"]:
            signal.update({"tier": 1, "action": "重壓加碼", "alert_level": "green"})
        elif premium_discount <= -thr["tier_2_discount"] and rsi <= thr["tier_2_rsi"]:
            signal.update({"tier": 2, "action": "中度加碼", "alert_level": "yellow"})
        elif abs(premium_discount) < thr["tier_3_band"] and market_price < ma20:
            signal.update({"tier": 3, "action": "輕度加碼", "alert_level": "white"})
        else:
            signal.update({"tier": None, "action": "觀望", "alert_level": "none"})

        return signal
    except Exception as e:
        logger.error(f"evaluate_active_etf({symbol}) failed: {e}")
        return {"symbol": symbol, "signal": "error", "error": str(e)}


def scan_all_active_etfs() -> list:
    """掃描所有主動 ETF"""
    return [evaluate_active_etf(s) for s in TW_ACTIVE_ETF_LIST]
```

### 10.3 src/twstock/twstock_alerts.py

```python
"""台股訊號統一格式化(送 Telegram 前)"""

from src.twstock.twstock_signals import scan_twstock_core
from src.twstock.active_etf_signals import scan_all_active_etfs


def format_twstock_alert(signal: dict) -> str:
    """格式化單一台股訊號為 Telegram HTML"""
    if signal.get("tier") is None:
        return None

    emoji = {"green": "🟢", "yellow": "🟡", "white": "⚪"}.get(signal.get("alert_level"), "⚫")
    name = signal.get("name", signal["symbol"])

    msg = (
        f"{emoji} <b>[台股] {name} ({signal['symbol']})</b>\n"
        f"Tier: {signal['tier']} - {signal['action']}\n"
        f"Price: {signal.get('price', signal.get('market_price', '-')):.2f}\n"
        f"RSI(14): {signal.get('rsi14', 0):.1f}\n"
    )
    if "premium_discount_pct" in signal:
        msg += f"折溢價: {signal['premium_discount_pct']:+.2f}%\n"
    return msg


def collect_twstock_alerts() -> list:
    """收集所有台股訊號(供 runner 調用)"""
    alerts = []
    for sig in scan_twstock_core() + scan_all_active_etfs():
        formatted = format_twstock_alert(sig)
        if formatted:
            alerts.append({"signal": sig, "message": formatted})
    return alerts
```

---

## 第 11 節:src/alerts/ — 通知格式化與路由

### 11.1 src/alerts/alert_formatter.py

```python
"""統一格式化各類訊號為 Telegram HTML 格式"""

from datetime import datetime


def format_signal_alert(signal: dict) -> str:
    """格式化美股 Sell Call / Sell Put / LEAPS 訊號"""
    sig_type = signal.get("signal_type", "unknown")
    symbol = signal.get("symbol", "?")
    score = signal.get("final_score", 0)
    level = signal.get("alert_level", "none")
    emoji = {"green": "🟢", "yellow": "🟡", "white": "⚪"}.get(level, "⚫")

    type_label = {
        "sell_call": "賣 CALL",
        "sell_put": "賣 PUT",
        "leaps_entry": "LEAPS 進場",
    }.get(sig_type, sig_type)

    msg = (
        f"{emoji} <b>[{type_label}] {symbol}</b>  Score: {score:.1f}\n"
        f"Price: ${signal.get('price', 0):.2f}\n"
    )

    if "iv_rank" in signal:
        msg += f"IV Rank: {signal['iv_rank']:.0f}\n"
    if "rsi14" in signal:
        msg += f"RSI(14): {signal['rsi14']:.1f}\n"
    if "value_thesis" in signal:
        msg += f"Value Thesis: {'✅' if signal['value_thesis'] else '❌'}\n"
    if signal.get("vetoes"):
        msg += f"⚠ Veto: {', '.join(signal['vetoes'])}\n"
    if signal.get("tags"):
        msg += f"Tags: {' '.join(signal['tags'])}\n"

    return msg


def format_position_alert(alert: dict) -> str:
    """格式化部位管理訊號(LEAPS PnL / Short Delta / Hedge DTE)"""
    kind = alert.get("kind", "position")
    emoji_map = {
        "leaps_pnl": "📈",
        "short_delta": "⚠",
        "hedge_dte": "⏰",
        "drawdown": "🛑",
    }
    emoji = emoji_map.get(kind, "📌")
    return f"{emoji} <b>[部位管理]</b> {alert.get('message', str(alert))}"


def format_news_alert(news: dict) -> str:
    """格式化新聞 / Trump / SEC 訊號"""
    src = news.get("source", "news")
    tier = news.get("tier", news.get("classification", "?"))
    emoji = "🚨" if tier == 1 else ("⚠" if tier == 2 else "📰")
    return (
        f"{emoji} <b>[{src}] Tier {tier}</b>\n"
        f"{news.get('title', news.get('content', ''))[:200]}\n"
        f"{news.get('url', '')}"
    )
```

### 11.2 src/alerts/alert_router.py

```python
"""訊號路由:依 P0/P1/P2/P3 priority 與頻率限制決定是否推送"""

from datetime import datetime, timedelta
from loguru import logger

from src.storage.state_manager import read_json, write_json
from src.alerts.deduplication import is_duplicate, mark_sent
from src.notifications.telegram_sender import send_telegram

ROUTING_FILE = "alert_routing_state.json"

# 頻率限制(每類訊號的最小間隔分鐘)
FREQUENCY_LIMITS = {
    "P0": 0,      # 立即(Trump Tier 1, SEC 8-K, 重大訊號)
    "P1": 5,      # 5 分鐘(Sell Call/Put green)
    "P2": 30,     # 30 分鐘(yellow tier)
    "P3": 240,    # 4 小時(white tier、台股輕度)
}


def determine_priority(alert: dict) -> str:
    """依 alert_level + signal_type 判 P0/P1/P2/P3"""
    level = alert.get("alert_level", "none")
    src = alert.get("source", "")

    if alert.get("kind") == "drawdown" and alert.get("level") in ("level_2", "level_3"):
        return "P0"
    if "trump" in src.lower() and alert.get("tier") == 1:
        return "P0"
    if "sec" in src.lower() and alert.get("form_type") in ("8-K", "10-K"):
        return "P0"

    if level == "green":
        return "P1"
    elif level == "yellow":
        return "P2"
    elif level == "white":
        return "P3"
    return "P3"


def should_send(alert: dict, priority: str) -> bool:
    """檢查頻率限制"""
    state = read_json(ROUTING_FILE, default={})
    last_sent_str = state.get(priority)
    if not last_sent_str:
        return True
    last_sent = datetime.fromisoformat(last_sent_str)
    elapsed_min = (datetime.utcnow() - last_sent).total_seconds() / 60
    return elapsed_min >= FREQUENCY_LIMITS[priority]


def route_alert(alert: dict) -> bool:
    """主路由:dedup → priority → frequency → send"""
    try:
        if is_duplicate(alert):
            logger.info(f"Skip duplicate: {alert.get('symbol', '?')}/{alert.get('signal_type', '?')}")
            return False

        priority = determine_priority(alert)
        if not should_send(alert, priority):
            logger.info(f"Frequency limit hit for {priority}, skip")
            return False

        message = alert.get("message") or str(alert)
        ok = send_telegram(message)
        if ok:
            mark_sent(alert)
            state = read_json(ROUTING_FILE, default={})
            state[priority] = datetime.utcnow().isoformat()
            write_json(ROUTING_FILE, state)
        return ok
    except Exception as e:
        logger.error(f"route_alert failed: {e}")
        return False
```

### 11.3 src/alerts/deduplication.py

```python
"""24 小時去重:依 symbol + signal_type"""

from datetime import datetime, timedelta
from loguru import logger

from src.storage.state_manager import read_json, write_json

DEDUP_FILE = "alert_dedup.json"
DEDUP_WINDOW_HOURS = 24


def _key(alert: dict) -> str:
    sym = alert.get("symbol", alert.get("source", "unknown"))
    typ = alert.get("signal_type", alert.get("kind", "unknown"))
    return f"{sym}::{typ}"


def is_duplicate(alert: dict) -> bool:
    state = read_json(DEDUP_FILE, default={})
    key = _key(alert)
    last_str = state.get(key)
    if not last_str:
        return False
    last_time = datetime.fromisoformat(last_str)
    return (datetime.utcnow() - last_time) < timedelta(hours=DEDUP_WINDOW_HOURS)


def mark_sent(alert: dict):
    state = read_json(DEDUP_FILE, default={})
    state[_key(alert)] = datetime.utcnow().isoformat()
    # 清掉超過 7 天的舊紀錄
    cutoff = datetime.utcnow() - timedelta(days=7)
    state = {k: v for k, v in state.items() if datetime.fromisoformat(v) > cutoff}
    write_json(DEDUP_FILE, state)
```

### 11.4 src/alerts/tag_attacher.py

```python
"""標籤附加器:60 分鐘內若有 Trump Tier 1 → 對所有美股訊號加 ⚠ 標籤"""

from datetime import datetime, timedelta
from loguru import logger

from src.storage.state_manager import read_json

TRUMP_STATE_FILE = "trump_classifier_state.json"
TAG_WINDOW_MINUTES = 60


def has_recent_trump_tier1() -> bool:
    """檢查 60 分鐘內是否有 Trump Tier 1"""
    try:
        state = read_json(TRUMP_STATE_FILE, default={})
        last_tier1 = state.get("last_tier1_at")
        if not last_tier1:
            return False
        last_time = datetime.fromisoformat(last_tier1)
        return (datetime.utcnow() - last_time) < timedelta(minutes=TAG_WINDOW_MINUTES)
    except Exception as e:
        logger.error(f"has_recent_trump_tier1 failed: {e}")
        return False


def attach_context_tags(alert: dict) -> dict:
    """為訊號附加 context 標籤"""
    tags = alert.get("tags", [])
    if has_recent_trump_tier1() and alert.get("signal_type") in ("sell_call", "sell_put", "leaps_entry"):
        if "⚠Trump60min" not in tags:
            tags.append("⚠Trump60min")
    alert["tags"] = tags
    return alert
```

---

## 第 12 節:src/runners/ — 任務 Runner

每個 runner 為 GitHub Actions cron 進入點,負責「載入資料 → 執行邏輯 → 路由通知」。

### 12.1 src/runners/run_trump_monitor.py

```python
"""Trump 貼文監控 (5 分鐘)"""

from loguru import logger
from src.data.trump_truth import fetch_latest_trump_posts
from src.layers.trump_classifier import classify_trump_post, save_tier1_timestamp
from src.alerts.alert_formatter import format_news_alert
from src.alerts.alert_router import route_alert


def main():
    logger.info("=== run_trump_monitor start ===")
    posts = fetch_latest_trump_posts(limit=20)
    if not posts:
        logger.warning("No Trump posts fetched")
        return
    for post in posts:
        result = classify_trump_post(post)
        if result.get("is_new") and result.get("tier") in (1, 2):
            if result["tier"] == 1:
                save_tier1_timestamp()
            alert = {
                "source": "Trump",
                "tier": result["tier"],
                "title": post.get("text", "")[:200],
                "url": post.get("url", ""),
                "alert_level": "green" if result["tier"] == 1 else "yellow",
                "kind": "news",
            }
            alert["message"] = format_news_alert(alert)
            route_alert(alert)
    logger.info("=== run_trump_monitor done ===")


if __name__ == "__main__":
    main()
```

### 12.2 src/runners/run_news_monitor.py

```python
"""RSS 新聞監控 (10 分鐘)"""

from loguru import logger
from src.data.rss_feeds import fetch_all_rss
from src.layers.news_classifier import classify_news
from src.alerts.alert_formatter import format_news_alert
from src.alerts.alert_router import route_alert


def main():
    logger.info("=== run_news_monitor start ===")
    items = fetch_all_rss()
    for item in items:
        result = classify_news(item)
        if result.get("is_new") and result.get("tier") in (1, 2):
            alert = {
                "source": item.get("source", "RSS"),
                "tier": result["tier"],
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "alert_level": "green" if result["tier"] == 1 else "yellow",
                "kind": "news",
            }
            alert["message"] = format_news_alert(alert)
            route_alert(alert)
    logger.info("=== run_news_monitor done ===")


if __name__ == "__main__":
    main()
```

### 12.3 src/runners/run_sec_monitor.py

```python
"""SEC EDGAR 監控 (1 小時)"""

from loguru import logger
from src.data.sec_edgar import fetch_recent_filings
from src.config.universe import US_UNIVERSE
from src.alerts.alert_formatter import format_news_alert
from src.alerts.alert_router import route_alert


def main():
    logger.info("=== run_sec_monitor start ===")
    for symbol in US_UNIVERSE:
        try:
            filings = fetch_recent_filings(symbol, forms=["8-K", "10-Q", "10-K"])
            for f in filings:
                if f.get("is_new"):
                    alert = {
                        "source": f"SEC/{symbol}",
                        "form_type": f.get("form_type"),
                        "title": f.get("title", ""),
                        "url": f.get("url", ""),
                        "tier": 1 if f.get("form_type") in ("8-K", "10-K") else 2,
                        "alert_level": "green" if f.get("form_type") in ("8-K", "10-K") else "yellow",
                        "kind": "news",
                    }
                    alert["message"] = format_news_alert(alert)
                    route_alert(alert)
        except Exception as e:
            logger.error(f"sec_monitor({symbol}) failed: {e}")
    logger.info("=== run_sec_monitor done ===")


if __name__ == "__main__":
    main()
```

### 12.4 src/runners/run_signal_scan_intraday.py

```python
"""盤中訊號掃描 (15 分鐘,僅美股交易時段)"""

from loguru import logger
from src.signals.final_scorer import scan_all_signals
from src.alerts.alert_formatter import format_signal_alert
from src.alerts.tag_attacher import attach_context_tags
from src.alerts.alert_router import route_alert


def main():
    logger.info("=== run_signal_scan_intraday start ===")
    alerts = scan_all_signals(mode="intraday")
    for alert in alerts:
        alert = attach_context_tags(alert)
        if alert.get("alert_level") in ("green", "yellow"):
            alert["message"] = format_signal_alert(alert)
            route_alert(alert)
    logger.info(f"=== run_signal_scan_intraday done ({len(alerts)} signals) ===")


if __name__ == "__main__":
    main()
```

### 12.5 src/runners/run_signal_scan_eod.py

```python
"""盤後訊號掃描 (美股收盤後)"""

from loguru import logger
from src.signals.final_scorer import scan_all_signals
from src.signals.exit_rules import evaluate_all_exit_rules
from src.alerts.alert_formatter import format_signal_alert, format_position_alert
from src.alerts.tag_attacher import attach_context_tags
from src.alerts.alert_router import route_alert


def main():
    logger.info("=== run_signal_scan_eod start ===")
    # 進場掃描(white 也在 EOD 推送)
    alerts = scan_all_signals(mode="eod")
    for alert in alerts:
        alert = attach_context_tags(alert)
        if alert.get("alert_level") != "none":
            alert["message"] = format_signal_alert(alert)
            route_alert(alert)

    # 出場規則
    exit_alerts = evaluate_all_exit_rules()
    for ea in exit_alerts:
        ea["message"] = format_position_alert(ea)
        route_alert(ea)
    logger.info("=== run_signal_scan_eod done ===")


if __name__ == "__main__":
    main()
```

### 12.6 src/runners/run_macro_layer.py

```python
"""每日宏觀層更新 (Layer 0 / 0+ / F)"""

from loguru import logger
from src.layers.macro_regime import update_macro_regime
from src.layers.breadth import update_breadth
from src.layers.distribution import update_distribution
from src.layers.bubble import update_bubble_score
from src.layers.put_call import update_put_call
from src.layers.vix_structure_layer import update_vix_structure
from src.layers.fundamentals_dashboard import refresh_universe_fundamentals
from src.layers.modifier_aggregator import build_modifier_dashboard


def main():
    logger.info("=== run_macro_layer start ===")
    update_macro_regime()
    update_breadth()
    update_distribution()
    update_bubble_score()
    update_put_call()
    update_vix_structure()
    refresh_universe_fundamentals()
    dashboard = build_modifier_dashboard()
    logger.info(f"Macro dashboard: {dashboard.get('summary', {})}")
    logger.info("=== run_macro_layer done ===")


if __name__ == "__main__":
    main()
```

### 12.7 src/runners/run_institutional_scan.py

```python
"""每日 13F + Form 4 內部人交易掃描"""

from loguru import logger
from src.layers.institutional_dashboard import update_institutional_dashboard
from src.layers.insider_signals import scan_all_insider_signals
from src.alerts.alert_formatter import format_news_alert
from src.alerts.alert_router import route_alert


def main():
    logger.info("=== run_institutional_scan start ===")
    update_institutional_dashboard()
    insider_alerts = scan_all_insider_signals()
    for alert in insider_alerts:
        if alert.get("tier") in (2, 3):
            alert["message"] = format_news_alert(alert)
            alert["alert_level"] = "green" if alert["tier"] == 3 else "yellow"
            route_alert(alert)
    logger.info("=== run_institutional_scan done ===")


if __name__ == "__main__":
    main()
```

### 12.8 src/runners/run_earnings_update.py

```python
"""每日財報行事曆更新"""

from loguru import logger
from src.data.earnings_calendar import refresh_earnings_calendar


def main():
    logger.info("=== run_earnings_update start ===")
    refresh_earnings_calendar()
    logger.info("=== run_earnings_update done ===")


if __name__ == "__main__":
    main()
```

### 12.9 src/runners/run_tsmc_revenue.py

```python
"""TSMC 月營收更新 (每月 10 號台北時間 16:00)"""

from loguru import logger
from src.data.tsmc_revenue import fetch_tsmc_monthly_revenue
from src.alerts.alert_formatter import format_news_alert
from src.alerts.alert_router import route_alert


def main():
    logger.info("=== run_tsmc_revenue start ===")
    result = fetch_tsmc_monthly_revenue()
    if result and result.get("is_new"):
        yoy = result.get("yoy_pct", 0)
        mom = result.get("mom_pct", 0)
        tier = 1 if abs(yoy) >= 20 else (2 if abs(yoy) >= 10 else 3)
        alert = {
            "source": "TSMC 月營收",
            "tier": tier,
            "title": f"TSMC {result.get('month')} 營收 YoY {yoy:+.1f}% / MoM {mom:+.1f}%",
            "alert_level": "green" if tier == 1 else "yellow",
            "kind": "news",
        }
        alert["message"] = format_news_alert(alert)
        route_alert(alert)
    logger.info("=== run_tsmc_revenue done ===")


if __name__ == "__main__":
    main()
```

### 12.10 src/runners/run_aaii_update.py

```python
"""AAII 散戶情緒週更新 (每週四)"""

from loguru import logger
from src.layers.aaii_sentiment import update_aaii_sentiment


def main():
    logger.info("=== run_aaii_update start ===")
    result = update_aaii_sentiment()
    logger.info(f"AAII updated: {result}")
    logger.info("=== run_aaii_update done ===")


if __name__ == "__main__":
    main()
```

### 12.11 src/runners/run_twstock_signal.py

```python
"""台股訊號掃描 (台股盤後)"""

from loguru import logger
from src.twstock.twstock_alerts import collect_twstock_alerts
from src.alerts.alert_router import route_alert


def main():
    logger.info("=== run_twstock_signal start ===")
    alerts = collect_twstock_alerts()
    for a in alerts:
        signal = a["signal"]
        signal["message"] = a["message"]
        signal["kind"] = "twstock"
        signal["source"] = "TW"
        route_alert(signal)
    logger.info(f"=== run_twstock_signal done ({len(alerts)} alerts) ===")


if __name__ == "__main__":
    main()
```

### 12.12 src/runners/run_position_check.py

```python
"""部位管理檢查 (每日:LEAPS PnL / Short Delta / Hedge DTE / Drawdown)"""

from loguru import logger
from src.management.leaps_pnl_tracker import scan_all_leaps
from src.management.short_delta_monitor import scan_all_shorts
from src.management.hedge_dte_tracker import scan_all_hedges
from src.management.account_drawdown import update_account_value
from src.management.current_positions import get_account_snapshot
from src.alerts.alert_formatter import format_position_alert
from src.alerts.alert_router import route_alert


def main():
    logger.info("=== run_position_check start ===")
    leaps_alerts = scan_all_leaps()
    short_alerts = scan_all_shorts()
    hedge_alerts = scan_all_hedges()

    snapshot = get_account_snapshot()
    if snapshot and snapshot.get("total_value"):
        dd = update_account_value(snapshot["total_value"])
        if dd.get("alert_level") != "normal":
            dd_alert = {
                "kind": "drawdown",
                "level": dd["alert_level"],
                "message": f"回撤 {dd['drawdown_pct']*100:.1f}% — {dd['action']}",
                "alert_level": "green",
            }
            route_alert(dd_alert)

    for alert in leaps_alerts + short_alerts + hedge_alerts:
        alert["message"] = format_position_alert(alert)
        alert["alert_level"] = alert.get("alert_level", "yellow")
        route_alert(alert)
    logger.info("=== run_position_check done ===")


if __name__ == "__main__":
    main()
```

---

## 第 13 節:.github/workflows/ — Cron 排程

所有 workflow 共用 base setup(checkout → setup-python → install requirements → run runner)。
時間皆為 UTC,需考量美股(EST/EDT)與台股(CST = UTC+8)時差。

### 13.1 .github/workflows/trump_monitor.yml

```yaml
name: Trump Monitor

on:
  schedule:
    - cron: '*/5 * * * *'  # 每 5 分鐘
  workflow_dispatch:

jobs:
  monitor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - name: Run Trump monitor
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python -m src.runners.run_trump_monitor
      - name: Commit state
        if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data_store/ || true
          git diff --quiet && git diff --staged --quiet || git commit -m "state: trump monitor [skip ci]"
          git push || true
```

### 13.2 .github/workflows/news_monitor.yml

```yaml
name: News Monitor

on:
  schedule:
    - cron: '*/10 * * * *'  # 每 10 分鐘
  workflow_dispatch:

jobs:
  monitor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - name: Run news monitor
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python -m src.runners.run_news_monitor
      - name: Commit state
        if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data_store/ || true
          git diff --quiet && git diff --staged --quiet || git commit -m "state: news monitor [skip ci]"
          git push || true
```

### 13.3 .github/workflows/sec_monitor.yml

```yaml
name: SEC EDGAR Monitor

on:
  schedule:
    - cron: '15 * * * *'  # 每小時 15 分
  workflow_dispatch:

jobs:
  monitor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          SEC_EDGAR_USER_AGENT: ${{ secrets.SEC_EDGAR_USER_AGENT }}
        run: python -m src.runners.run_sec_monitor
      - if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data_store/ || true
          git diff --quiet && git diff --staged --quiet || git commit -m "state: sec monitor [skip ci]"
          git push || true
```

### 13.4 .github/workflows/signal_scan_intraday.yml

```yaml
name: Signal Scan Intraday

on:
  schedule:
    # 美股交易時段 14:30 - 21:00 UTC (夏令) / 15:30 - 22:00 UTC (冬令)
    # 為簡化,涵蓋 13:30 - 22:00 UTC,每 15 分鐘
    - cron: '*/15 13-22 * * 1-5'
  workflow_dispatch:

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
        run: python -m src.runners.run_signal_scan_intraday
      - if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data_store/ || true
          git diff --quiet && git diff --staged --quiet || git commit -m "state: intraday scan [skip ci]"
          git push || true
```

### 13.5 .github/workflows/signal_scan_eod.yml

```yaml
name: Signal Scan EOD

on:
  schedule:
    - cron: '15 21 * * 1-5'  # 美股收盤後 (夏令時 21:15 UTC)
  workflow_dispatch:

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
        run: python -m src.runners.run_signal_scan_eod
      - if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data_store/ || true
          git diff --quiet && git diff --staged --quiet || git commit -m "state: eod scan [skip ci]"
          git push || true
```

### 13.6 .github/workflows/macro_layer.yml

```yaml
name: Macro Layer Update

on:
  schedule:
    - cron: '30 22 * * 1-5'  # 美股收盤後 22:30 UTC
  workflow_dispatch:

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - env:
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
        run: python -m src.runners.run_macro_layer
      - if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data_store/ || true
          git diff --quiet && git diff --staged --quiet || git commit -m "state: macro layer [skip ci]"
          git push || true
```

### 13.7 .github/workflows/institutional_scan.yml

```yaml
name: Institutional & Insider Scan

on:
  schedule:
    - cron: '0 23 * * 1-5'  # 美股收盤後 23:00 UTC
  workflow_dispatch:

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          SEC_EDGAR_USER_AGENT: ${{ secrets.SEC_EDGAR_USER_AGENT }}
        run: python -m src.runners.run_institutional_scan
      - if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data_store/ || true
          git diff --quiet && git diff --staged --quiet || git commit -m "state: institutional [skip ci]"
          git push || true
```

### 13.8 .github/workflows/earnings_update.yml

```yaml
name: Earnings Calendar Update

on:
  schedule:
    - cron: '0 12 * * *'  # 每日 12:00 UTC
  workflow_dispatch:

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - run: python -m src.runners.run_earnings_update
      - if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data_store/ || true
          git diff --quiet && git diff --staged --quiet || git commit -m "state: earnings [skip ci]"
          git push || true
```

### 13.9 .github/workflows/tsmc_revenue.yml

```yaml
name: TSMC Monthly Revenue

on:
  schedule:
    - cron: '0 8 10 * *'  # 每月 10 號 08:00 UTC (台北 16:00)
  workflow_dispatch:

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python -m src.runners.run_tsmc_revenue
      - if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data_store/ || true
          git diff --quiet && git diff --staged --quiet || git commit -m "state: tsmc revenue [skip ci]"
          git push || true
```

### 13.10 .github/workflows/aaii_update.yml

```yaml
name: AAII Sentiment Update

on:
  schedule:
    - cron: '0 22 * * 4'  # 每週四 22:00 UTC
  workflow_dispatch:

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - run: python -m src.runners.run_aaii_update
      - if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data_store/ || true
          git diff --quiet && git diff --staged --quiet || git commit -m "state: aaii [skip ci]"
          git push || true
```

### 13.11 .github/workflows/twstock_signal.yml

```yaml
name: Taiwan Stock Signal Scan

on:
  schedule:
    - cron: '30 6 * * 1-5'  # 台股收盤後 06:30 UTC (台北 14:30)
  workflow_dispatch:

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python -m src.runners.run_twstock_signal
      - if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data_store/ || true
          git diff --quiet && git diff --staged --quiet || git commit -m "state: twstock [skip ci]"
          git push || true
```

### 13.12 .github/workflows/position_check.yml

```yaml
name: Position Management Check

on:
  schedule:
    - cron: '0 22 * * 1-5'  # 美股收盤後 22:00 UTC
  workflow_dispatch:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python -m src.runners.run_position_check
      - if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data_store/ || true
          git diff --quiet && git diff --staged --quiet || git commit -m "state: position check [skip ci]"
          git push || true
```

---

## 第 14 節:Phase 3 交接提示詞

完成 Phase 2 後,將以下提示詞貼給下一個 Claude Code 對話以啟動 Phase 3:

```text
Kevin Trading Monitor 階段 2 已完成,所有 runner / workflow 皆可在 GitHub Actions 跑通。
請讀取 Project 內的 PHASE_1_FOUNDATION.md 與 PHASE_2_STRATEGY_AND_DATA.md,
撰寫 PHASE_3_BACKTEST_AND_EV.md,涵蓋:
- src/backtest/* (vectorbt 引擎、20 年歷史回測、滾動視窗驗證)
- src/ev/* (Expected Value 追蹤、訊號實戰績效統計、weight 自動微調)
- src/optimizer/* (參數網格搜尋、Walk-forward optimization)
- src/reports/* (週報 / 月報 PDF 自動產出)
- 對應的 src/runners/run_backtest.py、run_ev_update.py、run_weekly_report.py
- .github/workflows/backtest.yml (週末跑) / ev_update.yml (每日) / weekly_report.yml (週日)
注意 Phase 2 留下的擴充點:
1. final_scorer 需暴露 weight dict 供 EV optimizer 寫入
2. 所有訊號需保留 raw_score 與 final_score 雙欄位以便回測
3. exit_rules 需支援回測模式(批次餵歷史價格)
4. requirements.txt 需新增 vectorbt、weasyprint(PDF 報表)
```

---

## 第 15 節:完成檢查清單

實作完成後,逐項勾選:

### 程式碼層
- [ ] requirements.txt 使用 `pandas-ta-classic`,所有 import 為 `import pandas_ta_classic as ta`
- [ ] src/data/ 全部 20 個模組可獨立 import 不報錯
- [ ] src/indicators/ 4 個模組通過 unit test(可用合成資料)
- [ ] src/layers/ 14 個模組產生的 modifier 皆 clip 在 [-30, +30]
- [ ] src/signals/ 三大評分系統皆走 veto_checker → score → tier 流程
- [ ] src/management/ 5 個模組皆能讀寫 data_store/
- [ ] src/twstock/ 三模組皆獨立可跑

### Workflow 層
- [ ] 12 個 workflow yml 皆通過 `actionlint` 語法檢查
- [ ] 所有 cron 皆使用 UTC,時差換算註解清楚
- [ ] 所有 workflow 皆有 `git commit data_store/ [skip ci]` 步驟
- [ ] 所有需要 secret 的 step 皆透過 `${{ secrets.XXX }}` 注入

### 通知層
- [ ] alert_router 的 P0/P1/P2/P3 頻率限制可實際運作
- [ ] deduplication 24 小時視窗可阻擋重複訊號
- [ ] tag_attacher 在 Trump Tier 1 後 60 分鐘內附加 ⚠ 標籤

### 學習鎖
- [ ] 學習鎖 1:賣 PUT 僅限 whitelist(在 sell_put_scorer 強制)
- [ ] 學習鎖 2:嚴禁裸賣 CALL(在 veto_checker 強制)
- [ ] 學習鎖 3:嚴禁 2x 槓桿 ETF 買 LEAPS(在 leaps_entry_scorer 強制)
- [ ] 學習鎖 4:財報前 7 天禁開新短倉(在 veto_checker 強制)
- [ ] 學習鎖 5:對沖 DTE < 45 天強制提醒(hedge_dte_tracker)
- [ ] 學習鎖 6:回撤 -20% 強制檢視 LEAPS(account_drawdown level_2)

### Phase 1 對齊
- [ ] 所有 runner 皆使用 Phase 1 的 `src.notifications.telegram_sender.send_telegram`
- [ ] 所有狀態檔皆透過 Phase 1 的 `src.storage.state_manager.read_json/write_json`
- [ ] 所有 logger 皆使用 Phase 1 的 loguru 設定

---

