"""positions.json 載入 + 三模式判斷 + account snapshot。

三模式行為(從 settings.POSITION_MODE):
- mode_1 必填:positions 為空時 logger.warning + 寫 mode1_warned.flag(防重複) + 推 Telegram 一次
- mode_2 選填(預設):positions 為空時靜默回空集合
- mode_3 不填:全部 getter 直接回 [] / total=None,不讀檔
"""

from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from src.config.settings import POSITION_MODE
from src.storage.state_manager import read_json, write_json, DATA_STORE_DIR

POSITIONS_FILE = "positions.json"
MODE1_WARN_FLAG = "mode1_warned.flag"


def load_positions() -> dict:
    """載入目前部位。冷啟動回 {"stocks": [], "options": []}。"""
    return read_json(POSITIONS_FILE, default={"stocks": [], "options": []})


def _is_real(item: dict) -> bool:
    """過濾 _example 範本項目。"""
    return isinstance(item, dict) and not item.get("_example")


def _real_stocks(pos: dict) -> list:
    return [s for s in (pos.get("stocks") or []) if _is_real(s)]


def _real_options(pos: dict) -> list:
    return [o for o in (pos.get("options") or []) if _is_real(o)]


def _is_positions_empty(pos: dict) -> bool:
    return not _real_stocks(pos) and not _real_options(pos)


def _maybe_warn_mode1(pos: dict) -> None:
    """mode_1 + 部位空 → 第一次 logger.warning + Telegram + 寫 flag(冪等)。"""
    if POSITION_MODE != "mode_1":
        return
    if not _is_positions_empty(pos):
        return
    flag_path = DATA_STORE_DIR / MODE1_WARN_FLAG
    if flag_path.exists():
        return
    msg = (
        "POSITION_MODE=mode_1 但 positions.json 為空(或全為 _example 範本)。"
        "請依 docs/positions_schema.md 填入真實部位。系統繼續以空部位運行。"
    )
    logger.warning(msg)
    try:
        from src.alerts.telegram_bot import send_telegram
        send_telegram(f"[mode_1 提醒] {msg}")
    except Exception as e:
        logger.warning(f"mode_1 Telegram 推送失敗(忽略): {e}")
    try:
        flag_path.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    except Exception as e:
        logger.warning(f"mode_1 flag 寫入失敗(下次仍會警告): {e}")


def get_holdings_symbols() -> list:
    """目前持倉的 symbols list(用於 P0 優先級)。mode_3 → []。"""
    if POSITION_MODE == "mode_3":
        return []
    pos = load_positions()
    _maybe_warn_mode1(pos)
    syms = set()
    for s in _real_stocks(pos):
        if "symbol" in s:
            syms.add(s["symbol"])
    for o in _real_options(pos):
        if "symbol" in o:
            syms.add(o["symbol"])
    return list(syms)


def get_long_options() -> list:
    """所有 long_call / long_put。mode_3 → []。"""
    if POSITION_MODE == "mode_3":
        return []
    pos = load_positions()
    _maybe_warn_mode1(pos)
    return [o for o in _real_options(pos) if str(o.get("type", "")).startswith("long_")]


def get_short_options() -> list:
    """所有 short_call / short_put。mode_3 → []。"""
    if POSITION_MODE == "mode_3":
        return []
    pos = load_positions()
    _maybe_warn_mode1(pos)
    return [o for o in _real_options(pos) if str(o.get("type", "")).startswith("short_")]


def _estimate_option_value(opt: dict) -> Optional[float]:
    """單口 long/short option 當前 BS 估值(per contract = price * 100)。
    任何 price/IV/expiry 拿不到 → 回 None,呼叫端跳過該筆。"""
    try:
        from src.data.price_data import get_latest_price
        from src.data.iv_rank import get_atm_iv
        from src.data.greeks_calculator import calc_bs_price

        sym = opt.get("symbol")
        strike = opt.get("strike")
        expiry = opt.get("expiry")
        opt_type_raw = str(opt.get("type", ""))
        if not sym or strike is None or not expiry or not opt_type_raw:
            return None

        S = get_latest_price(sym)
        if S is None:
            return None
        iv = get_atm_iv(sym)
        if iv is None:
            return None

        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        today = datetime.now(timezone.utc)
        dte = (expiry_dt.date() - today.date()).days
        if dte <= 0:
            return 0.0

        bs_type = "call" if "call" in opt_type_raw else "put"
        per_share = calc_bs_price(
            S=float(S), K=float(strike), T=dte / 365, r=0.045,
            sigma=float(iv), option_type=bs_type,
        )
        contracts = int(opt.get("contracts", 1))
        return per_share * 100 * contracts
    except Exception as e:
        logger.warning(f"_estimate_option_value({opt.get('symbol')}) failed: {e}")
        return None


def _estimate_stock_value(stock: dict) -> Optional[float]:
    try:
        from src.data.price_data import get_latest_price
        sym = stock.get("symbol")
        shares = stock.get("shares")
        if not sym or shares is None:
            return None
        price = get_latest_price(sym)
        if price is None:
            return None
        return float(price) * float(shares)
    except Exception as e:
        logger.warning(f"_estimate_stock_value({stock.get('symbol')}) failed: {e}")
        return None


def get_account_snapshot() -> dict:
    """完整帳戶快照(給 Batch 11 runner / drawdown 餵真實值用)。

    冷啟動 / mode_3 → total_estimated_value=None / 0,不崩。
    任何單筆估值失敗 → 跳過該筆,total 仍計其他筆。
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    if POSITION_MODE == "mode_3":
        return {
            "mode": "mode_3",
            "stocks": [],
            "options": [],
            "total_estimated_value": None,
            "n_long_options": 0,
            "n_short_options": 0,
            "snapshot_at": now_iso,
        }

    pos = load_positions()
    _maybe_warn_mode1(pos)
    stocks = _real_stocks(pos)
    options = _real_options(pos)
    longs = [o for o in options if str(o.get("type", "")).startswith("long_")]
    shorts = [o for o in options if str(o.get("type", "")).startswith("short_")]

    if not stocks and not options:
        total: Optional[float] = 0.0
    else:
        total = 0.0
        for s in stocks:
            v = _estimate_stock_value(s)
            if v is not None:
                total += v
        for o in longs:
            v = _estimate_option_value(o)
            if v is not None:
                total += v
        for o in shorts:
            v = _estimate_option_value(o)
            if v is not None:
                total -= v

    return {
        "mode": POSITION_MODE,
        "stocks": stocks,
        "options": options,
        "total_estimated_value": total,
        "n_long_options": len(longs),
        "n_short_options": len(shorts),
        "snapshot_at": now_iso,
    }
