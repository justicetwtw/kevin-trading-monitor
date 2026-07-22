"""全域設定"""

import os
from datetime import datetime

import pytz

# ============================================
# 基本設定
# ============================================

VERSION = "0.1.0"
PROJECT_NAME = "kevin-trading-monitor"

TIMEZONE_USER = pytz.timezone("Asia/Taipei")
TIMEZONE_US_MARKET = pytz.timezone("America/New_York")
TIMEZONE_TW_MARKET = pytz.timezone("Asia/Taipei")

# Telegram（從 GitHub Secrets 讀取）
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_raw_chat_ids = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_CHAT_IDS = [
    chat_id.strip()
    for chat_id in _raw_chat_ids.split(",")
    if chat_id.strip()
]
TELEGRAM_CHAT_ID = TELEGRAM_CHAT_IDS[0] if TELEGRAM_CHAT_IDS else ""

# FRED / SEC
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
SEC_EDGAR_USER_AGENT = os.getenv("SEC_EDGAR_USER_AGENT", "")

# Podcast digest / email
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# ``or`` (not a getenv default) so an empty GEMINI_MODEL env — e.g. a workflow
# exporting an unset secret as "" — cannot override the code default and make
# every call use an empty model.
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
GMAIL_SENDER = os.getenv("GMAIL_SENDER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "")

# ============================================
# Position management
# ============================================

# "mode_1" required / "mode_2" optional / "mode_3" disabled
POSITION_MODE = os.getenv("POSITION_MODE", "mode_2")

# The public Actions log must not reveal private position identifiers. The
# position-check workflow sets this flag; shared data helpers redact tickers in
# warning/error messages while it is active.
PRIVATE_POSITION_CONTEXT = os.getenv("PRIVATE_POSITION_CONTEXT", "0") == "1"

# ============================================
# 其他設定
# ============================================

LANGUAGE = "zh_TW"
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
DEV_MODE_PUSH_THRESHOLD = 50 if ENVIRONMENT == "development" else None

US_MARKET_OPEN_ET = "09:30"
US_MARKET_CLOSE_ET = "16:00"
TW_MARKET_OPEN = "09:00"
TW_MARKET_CLOSE = "13:30"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss} | {level} | "
    "{name}:{function}:{line} | {message}"
)


def is_us_market_hours() -> bool:
    """判斷現在是否為美股盤中（用於 intraday scan 判斷）。"""
    now_et = datetime.now(TIMEZONE_US_MARKET)
    if now_et.weekday() >= 5:
        return False
    market_open = now_et.replace(hour=9, minute=30, second=0)
    market_close = now_et.replace(hour=16, minute=0, second=0)
    return market_open <= now_et <= market_close


def is_us_dst_active() -> bool:
    """判斷美東當下是否處於夏令時間。"""
    now_et = datetime.now(TIMEZONE_US_MARKET)
    return now_et.dst().total_seconds() > 0
