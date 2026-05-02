"""全域設定"""

import os
from datetime import datetime
import pytz

# ============================================
# 基本設定
# ============================================

VERSION = "0.1.0"
PROJECT_NAME = "kevin-trading-monitor"

# 時區
TIMEZONE_USER = pytz.timezone("Asia/Taipei")
TIMEZONE_US_MARKET = pytz.timezone("America/New_York")
TIMEZONE_TW_MARKET = pytz.timezone("Asia/Taipei")

# Telegram(從 GitHub Secrets 讀取)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# FRED(St. Louis Fed)API key — fred_api.py 會在 client init 時驗證,
# 未設不允許 fallback,直接 raise(避免靜默退回假資料)
FRED_API_KEY = os.getenv("FRED_API_KEY", "")

# SEC EDGAR User-Agent — sec_edgar / form4_insider / institutional_holdings 共用
# SEC 要求格式:"Sample Company Name AdminContact@example.com"
# 未設一律 raise(避免無 identity 觸發 SEC IP ban)
SEC_EDGAR_USER_AGENT = os.getenv("SEC_EDGAR_USER_AGENT", "")

# ============================================
# Position Mode 三模式切換
# ============================================

# 可選: "mode_1" (必填) / "mode_2" (選填,預設) / "mode_3" (不填)
POSITION_MODE = os.getenv("POSITION_MODE", "mode_2")

# ============================================
# 推播語言
# ============================================

LANGUAGE = "zh_TW"

# ============================================
# 開發/正式環境切換
# ============================================

ENVIRONMENT = os.getenv("ENVIRONMENT", "production")  # "development" or "production"

# 開發模式可降低 push 門檻、減少 API 呼叫等
DEV_MODE_PUSH_THRESHOLD = 50 if ENVIRONMENT == "development" else None

# ============================================
# 美股交易時段(用於排程判斷)
# ============================================

US_MARKET_OPEN_ET = "09:30"
US_MARKET_CLOSE_ET = "16:00"

TW_MARKET_OPEN = "09:00"
TW_MARKET_CLOSE = "13:30"

# ============================================
# Logging
# ============================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}"

def is_us_market_hours() -> bool:
    """判斷現在是否為美股盤中(用於 intraday scan 判斷)"""
    now_et = datetime.now(TIMEZONE_US_MARKET)
    if now_et.weekday() >= 5:  # 週末
        return False
    market_open = now_et.replace(hour=9, minute=30, second=0)
    market_close = now_et.replace(hour=16, minute=0, second=0)
    return market_open <= now_et <= market_close
