"""統一格式化各類訊號為 Telegram HTML 格式。

三類:
- format_signal_alert:美股 sell_call / sell_put / leaps_entry
- format_position_alert:部位管理 leaps_pnl / short_delta / hedge_dte / drawdown
- format_news_alert:新聞 / Trump / SEC

對所有 user-controlled 字串(title / content / action)做 HTML escape,防止 Telegram parse_mode=HTML 的注入。
"""

from html import escape as _escape


_LEVEL_EMOJI = {
    "red": "🔴",
    "orange": "🟠",
    "green": "🟢",
    "yellow": "🟡",
    "white": "⚪",
}

_SIGNAL_TYPE_LABEL = {
    "sell_call": "賣 CALL",
    "sell_put": "賣 PUT",
    "leaps_entry": "LEAPS 進場",
}

_POSITION_KIND_EMOJI = {
    "leaps_pnl": "📈",
    "short_delta": "⚠",
    "hedge_dte": "⏰",
    "drawdown": "🛑",
}


def _safe(val, default: str = "") -> str:
    return _escape(str(val)) if val is not None else default


def format_signal_alert(signal: dict) -> str:
    """美股 sell_call / sell_put / leaps_entry 訊號格式化。"""
    sig_type = signal.get("signal_type", "unknown")
    symbol = _safe(signal.get("symbol", "?"))
    score = signal.get("final_score", 0) or 0
    level = signal.get("alert_level", "none")
    emoji = _LEVEL_EMOJI.get(level, "⚫")
    type_label = _SIGNAL_TYPE_LABEL.get(sig_type, sig_type)

    lines = [
        f"{emoji} <b>[{_safe(type_label)}] {symbol}</b>  Score: {float(score):.1f}",
    ]
    price = signal.get("price")
    if price is not None:
        lines.append(f"Price: ${float(price):.2f}")

    iv = signal.get("iv_rank")
    if iv is not None:
        lines.append(f"IV Rank: {float(iv):.0f}")

    rsi = signal.get("rsi14")
    if rsi is not None:
        lines.append(f"RSI(14): {float(rsi):.1f}")

    thesis = signal.get("value_thesis")
    if thesis is not None:
        ok_emoji = "✅" if thesis else "❌"
        lines.append(f"Value Thesis: {ok_emoji}")

    vetoes = signal.get("vetoes") or []
    if vetoes:
        lines.append(f"⚠ Veto: {_safe(', '.join(str(v) for v in vetoes))}")

    tags = signal.get("tags") or []
    if tags:
        lines.append(f"Tags: {_safe(' '.join(str(t) for t in tags))}")

    return "\n".join(lines)


def format_position_alert(alert: dict) -> str:
    """部位管理訊號格式化。需要 alert['kind'] ∈ {leaps_pnl, short_delta, hedge_dte, drawdown}。"""
    kind = alert.get("kind", "position")
    emoji = _POSITION_KIND_EMOJI.get(kind, "📌")
    lines = [f"{emoji} <b>[部位管理 / {_safe(kind)}]</b>"]

    if kind == "leaps_pnl":
        opt_id = _safe(alert.get("option_id", "?"))
        level = _safe(alert.get("level", "?"))
        action = _safe(alert.get("action", ""))
        lines.append(f"Option: {opt_id}  Level: {level}")
        if action:
            lines.append(f"Action: {action}")
        pnl = alert.get("pnl") or {}
        pct = pnl.get("pnl_pct")
        if pct is not None:
            lines.append(f"PnL: {float(pct) * 100:+.1f}%")
    elif kind == "short_delta":
        sym = _safe(alert.get("symbol", "?"))
        delta = alert.get("delta")
        action = _safe(alert.get("action", ""))
        lines.append(f"Symbol: {sym}")
        if delta is not None:
            lines.append(f"Delta: {float(delta):.3f}")
        if action:
            lines.append(f"Action: {action}")
    elif kind == "hedge_dte":
        sym = _safe(alert.get("symbol", "?"))
        dte = alert.get("dte")
        action = _safe(alert.get("action", ""))
        lines.append(f"Hedge: {sym}  DTE: {dte}")
        if action:
            lines.append(f"Action: {action}")
    elif kind == "drawdown":
        dd = alert.get("drawdown_pct")
        action = _safe(alert.get("action", ""))
        if dd is not None:
            lines.append(f"Drawdown: {float(dd) * 100:.1f}%")
        if action:
            lines.append(f"Action: {action}")
    else:
        lines.append(_safe(alert.get("message", str(alert))))
    return "\n".join(lines)


def format_news_alert(news: dict) -> str:
    """新聞 / Trump / SEC 格式化。"""
    src = _safe(news.get("source", "news"))
    tier = news.get("tier", news.get("classification", "?"))
    emoji = "🚨" if tier == 1 else ("⚠" if tier == 2 else "📰")
    raw_title = news.get("title", news.get("content", ""))
    title = _safe(str(raw_title)[:200])
    url = _safe(news.get("url", ""))
    lines = [f"{emoji} <b>[{src}] Tier {tier}</b>"]
    if title:
        lines.append(title)
    if url:
        lines.append(url)
    return "\n".join(lines)
