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

# Phase 2.5.7 — 多 chat_id 支援:逗號分隔(e.g. "123,456")
_raw_chat_ids = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_CHAT_IDS = [
    chat_id.strip()
    for chat_id in _raw_chat_ids.split(",")
    if chat_id.strip()
]
# 單數版本相容性:取第一個(用於外部仍取單值的場景)
TELEGRAM_CHAT_ID = TELEGRAM_CHAT_IDS[0] if TELEGRAM_CHAT_IDS else ""

# FRED(St. Louis Fed)API key — fred_api.py 會在 client init 時驗證,
# 未設不允許 fallback,直接 raise(避免靜默退回假資料)
FRED_API_KEY = os.getenv("FRED_API_KEY", "")

# SEC EDGAR User-Agent — sec_edgar / form4_insider / institutional_holdings 共用
# SEC 要求格式:"Sample Company Name AdminContact@example.com"
# 未設一律 raise(避免無 identity 觸發 SEC IP ban)
SEC_EDGAR_USER_AGENT = os.getenv("SEC_EDGAR_USER_AGENT", "")

# ============================================
# 股癌 Podcast Digest(gooaye-digest,獨立功能,從 GitHub Secrets 讀取)
# ============================================
# 缺值不 raise:gooaye pipeline 自行 try/except + log,單集失敗不阻塞交易監控。

# Gemini API(音檔→逐字稿 / 逐字稿→摘要)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# 模型 ID:gemini-2.5-flash 為已查證免費層、支援音訊輸入的安全預設;
# 免費層若釋出更新音訊模型(如 gemini-3-flash)只需改 GEMINI_MODEL secret,不動程式。
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Gmail SMTP 寄信(摘要 HTML 內文 + 逐字稿 .md 附檔)
GMAIL_SENDER = os.getenv("GMAIL_SENDER", "")
# 16 碼 app password;貼上時可能含空格,使用端一律去空格。
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
# 收件人(支援逗號分隔多收件,沿用 TELEGRAM_CHAT_ID 慣例;v1 預設只寄 Kevin)
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "")

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


def is_us_dst_active() -> bool:
    """判斷美東當下是否為夏令時間(EDT, UTC-4)。

    Sprint 2.5.9:給 market_brief workflow + run_market_brief 用,
    決定要使用哪一組 cron 對照表。

    冬令(EST, UTC-5)→ False
    夏令(EDT, UTC-4)→ True
    """
    now_et = datetime.now(TIMEZONE_US_MARKET)
    return now_et.dst().total_seconds() > 0
