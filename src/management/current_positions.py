"""Private position loading, mode handling and account snapshots.

Source priority:
1. `POSITIONS_JSON` GitHub Actions secret / environment variable.
2. Local `data_store/positions.json` for development only.

When `POSITIONS_JSON` exists but is malformed, loading fails closed to an empty
portfolio. It never falls back to the public example file.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from src.config.settings import POSITION_MODE
from src.storage.state_manager import DATA_STORE_DIR, read_json

POSITIONS_FILE = "positions.json"
POSITIONS_ENV = "POSITIONS_JSON"
MODE1_WARN_FLAG = "mode1_warned.flag"
ALLOWED_OPTION_TYPES = {"long_call", "long_put", "short_call", "short_put"}


def _empty_positions() -> dict[str, list]:
    return {"stocks": [], "options": []}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_positions(value: Any) -> dict:
    """Validate private positions without logging any secret contents."""
    if not isinstance(value, dict):
        raise ValueError("top level must be an object")

    stocks = value.get("stocks", [])
    options = value.get("options", [])
    if not isinstance(stocks, list) or not isinstance(options, list):
        raise ValueError("stocks and options must be arrays")

    for index, stock in enumerate(stocks):
        if not isinstance(stock, dict):
            raise ValueError(f"stocks[{index}] must be an object")
        if stock.get("_example"):
            continue
        if not isinstance(stock.get("symbol"), str) or not stock["symbol"].strip():
            raise ValueError(f"stocks[{index}].symbol is required")
        if not _is_number(stock.get("shares")):
            raise ValueError(f"stocks[{index}].shares must be numeric")
        if float(stock["shares"]) < 0:
            raise ValueError(f"stocks[{index}].shares cannot be negative")
        if stock.get("avg_cost") is not None and not _is_number(stock["avg_cost"]):
            raise ValueError(f"stocks[{index}].avg_cost must be numeric")

    for index, option in enumerate(options):
        if not isinstance(option, dict):
            raise ValueError(f"options[{index}] must be an object")
        if option.get("_example"):
            continue
        if not isinstance(option.get("symbol"), str) or not option["symbol"].strip():
            raise ValueError(f"options[{index}].symbol is required")
        if option.get("type") not in ALLOWED_OPTION_TYPES:
            raise ValueError(f"options[{index}].type is invalid")
        if not _is_number(option.get("strike")) or float(option["strike"]) <= 0:
            raise ValueError(f"options[{index}].strike must be positive")
        expiry = option.get("expiry")
        if not isinstance(expiry, str):
            raise ValueError(f"options[{index}].expiry is required")
        try:
            datetime.strptime(expiry, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(
                f"options[{index}].expiry must use YYYY-MM-DD"
            ) from exc
        contracts = option.get("contracts", 1)
        if not isinstance(contracts, int) or isinstance(contracts, bool) or contracts <= 0:
            raise ValueError(f"options[{index}].contracts must be a positive integer")
        if option.get("cost_per_contract") is not None and not _is_number(
            option["cost_per_contract"]
        ):
            raise ValueError(
                f"options[{index}].cost_per_contract must be numeric"
            )

    return {"stocks": stocks, "options": options}


def get_position_source() -> str:
    """Return source metadata without exposing position contents."""
    return "actions_secret" if os.getenv(POSITIONS_ENV, "").strip() else "local_file"


def load_positions() -> dict:
    """Load validated positions; malformed secret input fails closed."""
    raw = os.getenv(POSITIONS_ENV, "").strip()
    if raw:
        try:
            return _validate_positions(json.loads(raw))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(
                f"{POSITIONS_ENV} validation failed; using empty positions: {exc}"
            )
            return _empty_positions()

    file_value = read_json(POSITIONS_FILE, default=_empty_positions())
    try:
        return _validate_positions(file_value)
    except ValueError as exc:
        logger.error(f"{POSITIONS_FILE} validation failed; using empty positions: {exc}")
        return _empty_positions()


def _is_real(item: dict) -> bool:
    return isinstance(item, dict) and not item.get("_example")


def _real_stocks(pos: dict) -> list:
    return [stock for stock in (pos.get("stocks") or []) if _is_real(stock)]


def _real_options(pos: dict) -> list:
    return [option for option in (pos.get("options") or []) if _is_real(option)]


def _is_positions_empty(pos: dict) -> bool:
    return not _real_stocks(pos) and not _real_options(pos)


def _maybe_warn_mode1(pos: dict) -> None:
    """Warn once when required private positions are unavailable."""
    if POSITION_MODE != "mode_1" or not _is_positions_empty(pos):
        return
    flag_path = DATA_STORE_DIR / MODE1_WARN_FLAG
    if flag_path.exists():
        return
    msg = (
        "POSITION_MODE=mode_1 but no valid private positions were loaded. "
        "Configure the POSITIONS_JSON Actions secret or a local positions.json. "
        "The system will continue with an empty portfolio."
    )
    logger.warning(msg)
    try:
        from src.alerts.telegram_bot import send_telegram

        send_telegram(f"[mode_1 reminder] {msg}")
    except Exception as exc:
        logger.warning(f"mode_1 Telegram reminder failed: {exc}")
    try:
        flag_path.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    except Exception as exc:
        logger.warning(f"mode_1 warning flag write failed: {exc}")


def get_holdings_symbols() -> list:
    if POSITION_MODE == "mode_3":
        return []
    pos = load_positions()
    _maybe_warn_mode1(pos)
    symbols = {
        item["symbol"]
        for item in _real_stocks(pos) + _real_options(pos)
        if item.get("symbol")
    }
    return sorted(symbols)


def get_long_options() -> list:
    if POSITION_MODE == "mode_3":
        return []
    pos = load_positions()
    _maybe_warn_mode1(pos)
    return [
        option
        for option in _real_options(pos)
        if str(option.get("type", "")).startswith("long_")
    ]


def get_short_options() -> list:
    if POSITION_MODE == "mode_3":
        return []
    pos = load_positions()
    _maybe_warn_mode1(pos)
    return [
        option
        for option in _real_options(pos)
        if str(option.get("type", "")).startswith("short_")
    ]


def _estimate_option_value(option: dict) -> Optional[float]:
    """Estimate current option value per all contracts; unavailable data returns None."""
    try:
        from src.data.greeks_calculator import calc_bs_price
        from src.data.iv_rank import get_atm_iv
        from src.data.price_data import get_latest_price

        symbol = option.get("symbol")
        strike = option.get("strike")
        expiry = option.get("expiry")
        option_type = str(option.get("type", ""))
        if not symbol or strike is None or not expiry or not option_type:
            return None

        underlying = get_latest_price(symbol)
        implied_volatility = get_atm_iv(symbol)
        if underlying is None or implied_volatility is None:
            return None

        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
        dte = (expiry_dt.date() - datetime.now(timezone.utc).date()).days
        if dte <= 0:
            return 0.0

        per_share = calc_bs_price(
            S=float(underlying),
            K=float(strike),
            T=dte / 365,
            r=0.045,
            sigma=float(implied_volatility),
            option_type="call" if "call" in option_type else "put",
        )
        return per_share * 100 * int(option.get("contracts", 1))
    except Exception as exc:
        logger.warning(
            f"_estimate_option_value({option.get('symbol')}) failed: {exc}"
        )
        return None


def _estimate_stock_value(stock: dict) -> Optional[float]:
    try:
        from src.data.price_data import get_latest_price

        symbol = stock.get("symbol")
        shares = stock.get("shares")
        if not symbol or shares is None:
            return None
        price = get_latest_price(symbol)
        if price is None:
            return None
        return float(price) * float(shares)
    except Exception as exc:
        logger.warning(
            f"_estimate_stock_value({stock.get('symbol')}) failed: {exc}"
        )
        return None


def get_account_snapshot() -> dict:
    """Build an in-memory private snapshot for risk checks.

    Exact position details and total value must never be committed by callers.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    if POSITION_MODE == "mode_3":
        return {
            "mode": "mode_3",
            "position_source": "disabled",
            "stocks": [],
            "options": [],
            "total_estimated_value": None,
            "n_long_options": 0,
            "n_short_options": 0,
            "snapshot_at": now_iso,
        }

    positions = load_positions()
    _maybe_warn_mode1(positions)
    stocks = _real_stocks(positions)
    options = _real_options(positions)
    longs = [
        option
        for option in options
        if str(option.get("type", "")).startswith("long_")
    ]
    shorts = [
        option
        for option in options
        if str(option.get("type", "")).startswith("short_")
    ]

    total: Optional[float] = 0.0
    for stock in stocks:
        value = _estimate_stock_value(stock)
        if value is not None:
            total += value
    for option in longs:
        value = _estimate_option_value(option)
        if value is not None:
            total += value
    for option in shorts:
        value = _estimate_option_value(option)
        if value is not None:
            total -= value

    return {
        "mode": POSITION_MODE,
        "position_source": get_position_source(),
        "stocks": stocks,
        "options": options,
        "total_estimated_value": total,
        "n_long_options": len(longs),
        "n_short_options": len(shorts),
        "snapshot_at": now_iso,
    }
