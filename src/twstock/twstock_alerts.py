"""台股訊號統一格式化(送 Telegram 前)。

Batch 9 不直接送 Telegram(由 Batch 11 runner 負責),
這裡只負責 (a) HTML 格式化、(b) 過濾 tier=None 的雜訊。
"""

from src.twstock.twstock_signals import scan_twstock_core
from src.twstock.active_etf_signals import scan_all_active_etfs


_LEVEL_EMOJI = {
    "green": "🟢",
    "yellow": "🟡",
    "orange": "🟠",
    "red": "🔴",
    "white": "⚪",
}


def _format_core(sig: dict) -> str:
    name = sig.get("name", sig["symbol"])
    emoji = _LEVEL_EMOJI.get(sig.get("alert_level"), "⚫")
    lines = [
        f"{emoji} <b>[台股核心] {name} ({sig['symbol']})</b>",
        f"Tier: {sig['tier']} - {sig.get('action', '')}",
    ]
    if sig.get("price") is not None:
        lines.append(f"Price: {sig['price']:.2f}")
    pct = sig.get("pct_from_52w_high")
    if pct is not None:
        lines.append(f"距 52W 高: {pct * 100:+.1f}%")
    rsi = sig.get("rsi14_weekly")
    if rsi is not None:
        lines.append(f"週 RSI(14): {rsi:.1f}")
    vix = sig.get("vix")
    if vix is not None:
        lines.append(f"VIX: {vix:.1f}")
    deploy = sig.get("deploy_pct")
    if deploy is not None:
        lines.append(f"建議子彈: {deploy * 100:.0f}% 加碼")
    if sig.get("cooldown"):
        lines.append(f"⏳ 冷卻中,還需 {sig.get('cooldown_days_remaining', '?')} 天")
    return "\n".join(lines)


def _format_active_etf(sig: dict) -> str:
    emoji = _LEVEL_EMOJI.get(sig.get("alert_level"), "⚫")
    lines = [
        f"{emoji} <b>[主動 ETF 跟單] {sig['symbol']}</b>",
        f"Tier: {sig['tier']} - {sig.get('action', '')}",
    ]
    n_short = sig.get("n_etfs_increased_short_window", 0)
    n_long = sig.get("n_etfs_increased_long_window", 0)
    lines.append(f"7 日加碼: {n_short} 檔 / 30 日加碼: {n_long} 檔")
    max_diff = sig.get("max_diff_pp_short_window")
    if max_diff is not None:
        lines.append(f"最大單檔加碼幅度: {max_diff:+.2f} pp")
    return "\n".join(lines)


def format_twstock_alert(sig: dict) -> str | None:
    """格式化單一台股訊號為 Telegram HTML。tier=None → 回 None(不推播)。"""
    if sig is None or sig.get("tier") is None:
        return None
    # 區分核心(symbol 帶 .TW)vs 主動 ETF(個股代號無後綴)
    if "name" in sig and "rsi14_weekly" in sig:
        return _format_core(sig)
    if "n_etfs_increased_short_window" in sig:
        return _format_active_etf(sig)
    # fallback
    emoji = _LEVEL_EMOJI.get(sig.get("alert_level"), "⚫")
    return f"{emoji} <b>{sig.get('symbol', '?')}</b> Tier {sig['tier']} - {sig.get('action', '')}"


def collect_twstock_alerts() -> list:
    """收集所有台股訊號(供 runner 調用)。過濾 tier=None。"""
    alerts = []
    for sig in scan_twstock_core() + scan_all_active_etfs():
        msg = format_twstock_alert(sig)
        if msg is not None:
            alerts.append({"signal": sig, "message": msg})
    return alerts
