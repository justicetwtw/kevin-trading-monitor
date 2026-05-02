"""Short Option Delta 監測 - |Delta| > 0.35 警報。

主名:scan_all_shorts()
別名:check_short_deltas = scan_all_shorts
"""

from datetime import datetime, timezone

from loguru import logger

from src.config.thresholds import SHORT_OPTION_DEFENSE
from src.data.greeks_calculator import calc_delta
from src.data.iv_rank import get_atm_iv
from src.data.price_data import get_latest_price
from src.management.current_positions import get_short_options


def scan_all_shorts() -> list:
    """檢查 short option Delta 是否超標。冷啟動無部位 → []。"""
    alerts = []
    threshold = SHORT_OPTION_DEFENSE["delta_warning_threshold"]
    today = datetime.now(timezone.utc).date()

    for opt in get_short_options():
        try:
            sym = opt["symbol"]
            underlying = get_latest_price(sym)
            if underlying is None:
                continue
            iv = get_atm_iv(sym) or 0.30
            expiry = datetime.strptime(opt["expiry"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            dte = (expiry.date() - today).days
            if dte <= 0:
                continue

            opt_type = "call" if "call" in str(opt["type"]) else "put"
            delta = calc_delta(
                S=float(underlying), K=float(opt["strike"]),
                T=dte / 365, r=0.045, sigma=float(iv),
                option_type=opt_type,
            )

            if abs(delta) > threshold:
                alerts.append({
                    "option_id": opt.get("id", f"{sym}_{opt['strike']}"),
                    "symbol": sym, "delta": delta,
                    "underlying": float(underlying), "strike": float(opt["strike"]),
                    "dte": dte,
                    "action": "考慮 roll up/down 或平倉",
                })
        except Exception as e:
            logger.error(f"scan_all_shorts({opt}) failed: {e}")
    return alerts


check_short_deltas = scan_all_shorts
