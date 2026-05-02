"""Phase 2.5 — 每日 4 次 market brief 共用組裝邏輯。

dispatch by brief_type:
  us_eod        台北 08:30 — 美股盤後
  tw_eod        台北 13:30 — 台股盤後
  us_premarket  台北 21:00 — 美股盤前
  us_midday     台北 06:00 — 美股盤中(起床看)

設計:
- 每段 try/except 內回 fallback 字串("資料抓取失敗"),整支 brief 不死
- 不走 alert_router(brief 是被動推送,不需 dedup/quota/cooldown)
- HTML escape 所有外部來源欄位(防注入)
- scan_all_signals 在 us_eod / us_midday 真跑(可接受 1-2 分鐘成本,4 次/天低頻)
"""

from datetime import datetime, timedelta
from html import escape

from loguru import logger

from src.config.settings import TIMEZONE_USER
from src.data.earnings_calendar import get_upcoming_earnings
from src.data.price_data import fetch_history, get_52w_high_low, get_latest_price
from src.signals.final_scorer import scan_all_signals
from src.storage.state_manager import read_json
from src.twstock.active_etf_signals import scan_all_active_etfs
from src.twstock.twstock_signals import scan_twstock_core


VALID_BRIEF_TYPES = ("us_eod", "tw_eod", "us_premarket", "us_midday")

_BRIEF_TITLE = {
    "us_eod": "📊 美股盤後 brief",
    "tw_eod": "🇹🇼 台股盤後 brief",
    "us_premarket": "🌎 美股盤前 brief",
    "us_midday": "🌃 美股盤中 brief",
}

_NEXT_BRIEF_LABEL = {
    "us_eod": "台股盤後 (台北 13:30)",
    "tw_eod": "美股盤前 (台北 21:00)",
    "us_premarket": "美股盤中 (隔日 台北 06:00,間隔 9 小時)",
    "us_midday": "美股盤後 (台北 08:30)",
}


def _safe(label: str, fn, *args, **kwargs) -> str:
    """每段資料抓取的安全包裝。失敗 → "資料抓取失敗" + 細節到 log。"""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.warning(f"brief section '{label}' failed: {e}")
        return f"<i>{escape(label)} 資料抓取失敗</i>"


def _fmt_pct(v) -> str:
    if v is None:
        return "n/a"
    try:
        return f"{v * 100:+.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_price(v) -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _day_change(symbol: str) -> tuple:
    """回 (latest_price, day_change_pct)。失敗回 (None, None)。"""
    try:
        df = fetch_history(symbol, period="5d", interval="1d")
        if df is None or getattr(df, "empty", True):
            return None, None
        if len(df) < 2:
            return float(df["Close"].iloc[-1]), None
        prev = float(df["Close"].iloc[-2])
        cur = float(df["Close"].iloc[-1])
        return cur, (cur - prev) / prev if prev else None
    except Exception as e:
        logger.warning(f"_day_change({symbol}) failed: {e}")
        return None, None


class BriefGenerator:
    def __init__(self, brief_type: str):
        self.brief_type = brief_type

    # ---- public ----

    def generate(self) -> str:
        if self.brief_type not in VALID_BRIEF_TYPES:
            raise ValueError(f"Invalid brief_type: {self.brief_type}")

        builders = {
            "us_eod": self._build_us_eod,
            "tw_eod": self._build_tw_eod,
            "us_premarket": self._build_us_premarket,
            "us_midday": self._build_us_midday,
        }
        title = _BRIEF_TITLE[self.brief_type]
        try:
            body = builders[self.brief_type]()
        except Exception as e:
            logger.error(f"brief body build crashed: {e}")
            body = f"<i>brief 組裝失敗: {escape(str(e))}</i>"
        footer = f"\n\n<i>下次 brief: {escape(self._next_brief_time())}</i>"
        return f"<b>{title}</b>\n\n{body}{footer}"

    # ---- builders per type ----

    def _build_us_eod(self) -> str:
        parts = []
        parts.append(_safe("美股當日", self._format_macro_snapshot))
        parts.append(_safe("Layer 0 modifier", self._format_layer0))
        parts.append(_safe("EOD scan top 3", self._format_top_signals, mode="eod"))
        parts.append(_safe("台股展望", self._format_tw_outlook))
        parts.append(_safe("今日事件", self._format_events_today))
        return "\n\n".join(p for p in parts if p)

    def _build_tw_eod(self) -> str:
        parts = []
        parts.append(_safe("台股當日", self._format_tw_today))
        parts.append(_safe("加碼訊號", self._format_twstock_signals))
        parts.append(_safe("主動 ETF", self._format_active_etfs))
        parts.append(_safe("美股盤前展望", self._format_us_premarket_preview))
        return "\n\n".join(p for p in parts if p)

    def _build_us_premarket(self) -> str:
        parts = []
        parts.append(_safe("Pre-market 異動", self._format_premarket_movers))
        parts.append(_safe("Macro 變化", self._format_macro_indicators))
        parts.append(_safe("今日事件", self._format_events_today))
        return "\n\n".join(p for p in parts if p)

    def _build_us_midday(self) -> str:
        parts = []
        parts.append(_safe("美股當日進度", self._format_macro_snapshot))
        parts.append(_safe("Intraday top 3", self._format_top_signals, mode="intraday"))
        parts.append(_safe("台股展望", self._format_tw_outlook))
        return "\n\n".join(p for p in parts if p)

    # ---- shared formatters ----

    def _format_macro_snapshot(self) -> str:
        lines = ["<b>美股大盤</b>"]
        for sym, name in (("SPY", "SPY"), ("QQQ", "QQQ"), ("^VIX", "VIX")):
            price, chg = _day_change(sym)
            lines.append(f"  {escape(name)}: {_fmt_price(price)} ({_fmt_pct(chg)})")
        return "\n".join(lines)

    def _interpret_modifier(self, val: int) -> str:
        if val >= 10:
            return "(強烈偏好)"
        elif val >= 5:
            return "(略偏好)"
        elif val >= -5:
            return "(中性)"
        elif val >= -10:
            return "(略偏不利)"
        else:
            return "(不利,等待回檔)"

    def _format_layer0(self) -> str:
        layer0 = read_json("layer0_history.json", default={})
        if not isinstance(layer0, dict) or not layer0:
            return "<b>Layer 0 三維 modifier</b>\n  <i>n/a (no data)</i>"
        agg = layer0.get("aggregate_modifiers", {}) or {}
        sc = agg.get("sell_call", 0)
        sp = agg.get("sell_put", 0)
        le = agg.get("leaps_entry", 0)
        veto = " (VETO)" if agg.get("leaps_entry_veto") else ""
        return (
            "<b>Layer 0 三維 modifier</b>\n"
            f"  sell_call:   {sc:+d} {self._interpret_modifier(sc)}\n"
            f"  sell_put:    {sp:+d} {self._interpret_modifier(sp)}\n"
            f"  leaps_entry: {le:+d} {self._interpret_modifier(le)}{veto}"
        )

    def _format_top_signals(self, mode: str = "eod", n: int = 3) -> str:
        try:
            results = scan_all_signals(mode=mode)
        except Exception as e:
            logger.warning(f"_format_top_signals scan failed: {e}")
            return (
                f"<b>{escape(mode.upper())} scan</b>\n"
                f"  <i>系統初始化中,等待資料累積</i>"
            )
        if results is None:
            return (
                f"<b>{escape(mode.upper())} scan</b>\n"
                f"  <i>系統初始化中,等待資料累積</i>"
            )
        if not results:
            return f"<b>{escape(mode.upper())} scan</b>\n  <i>無訊號(全 universe 評分 &lt; 50)</i>"

        pushed = sum(1 for r in results if r.get("alert_level") in ("green", "yellow"))
        vetoed = sum(1 for r in results if r.get("alert_level") == "white"
                     and r.get("final_score", 0) >= (r.get("push_threshold") or 0))
        lines = [f"<b>{escape(mode.upper())} scan</b>"]
        if pushed > 0:
            lines.append(
                f"  {len(results)} 評分 / {pushed} 已推播 / {vetoed} 被 veto"
            )
            lines.append(f"  Top {n}:")
        else:
            lines.append(
                f"  {len(results)} 評分 / 0 達 ≥70 推播門檻 / {vetoed} 被 veto"
            )
            lines.append(f"  最接近門檻 top {n}:")
        for r in results[:n]:
            sym = escape(str(r.get("symbol", "?")))
            sig = escape(str(r.get("signal_type", "?")))
            score = r.get("final_score", 0)
            thr = r.get("push_threshold", "n/a")
            lvl = escape(str(r.get("alert_level", "?")))
            lines.append(f"    • {sym} {sig} {score}/{thr} [{lvl}]")
        return "\n".join(lines)

    def _format_tw_outlook(self) -> str:
        lines = ["<b>台股展望</b>"]
        for sym, name in (("00631L.TW", "00631L"), ("2330.TW", "2330")):
            try:
                m = get_52w_high_low(sym)
                pct = m.get("pct_from_high")
                cur = m.get("current")
                lines.append(
                    f"  {escape(name)}: {_fmt_price(cur)} (距 52W 高 {_fmt_pct(pct)})"
                )
            except Exception as e:
                logger.warning(f"tw outlook {sym} failed: {e}")
                lines.append(f"  {escape(name)}: <i>n/a</i>")
        return "\n".join(lines)

    def _format_events_today(self) -> str:
        upcoming = get_upcoming_earnings(within_days=1) or []
        lines = ["<b>今日事件</b>"]
        if not upcoming:
            lines.append("  <i>無</i>")
            return "\n".join(lines)
        for e in upcoming[:10]:
            sym = escape(str(e.get("symbol", "?")))
            d = e.get("days_until")
            ed = escape(str(e.get("earnings_date", "?")))
            lines.append(f"  • {sym} earnings {ed} (T-{d})")
        return "\n".join(lines)

    # ---- tw_eod-specific ----

    def _format_tw_today(self) -> str:
        lines = ["<b>台股當日</b>"]
        for sym, name in (("00631L.TW", "00631L"), ("2330.TW", "台積電")):
            price, chg = _day_change(sym)
            lines.append(f"  {escape(name)}: {_fmt_price(price)} ({_fmt_pct(chg)})")
        return "\n".join(lines)

    def _format_twstock_signals(self) -> str:
        sigs = scan_twstock_core() or []
        lines = ["<b>核心加碼訊號</b>"]
        for s in sigs:
            sym = escape(str(s.get("symbol", "?")))
            tier = s.get("tier") or "—"
            action = escape(str(s.get("action", "—")))
            lines.append(f"  • {sym}: tier={tier} {action}")
        return "\n".join(lines) if len(lines) > 1 else "<b>核心加碼訊號</b>\n  <i>無</i>"

    def _format_active_etfs(self) -> str:
        etfs = scan_all_active_etfs() or []
        active = [e for e in etfs if e.get("tier") is not None]
        lines = ["<b>主動 ETF 動向</b>"]
        if not active:
            lines.append("  <i>無加碼動向</i>")
            return "\n".join(lines)
        for e in active[:5]:
            sym = escape(str(e.get("symbol", "?")))
            tier = e.get("tier", "—")
            n_short = e.get("n_etfs_increased_short_window", 0)
            lines.append(f"  • {sym}: tier={tier} ({n_short} 檔加碼)")
        return "\n".join(lines)

    def _format_us_premarket_preview(self) -> str:
        lines = ["<b>美股盤前展望</b>"]
        for sym, name in (("ES=F", "ES futures"), ("NVDA", "NVDA")):
            price = get_latest_price(sym)
            lines.append(f"  {escape(name)}: {_fmt_price(price)}")
        return "\n".join(lines)

    # ---- us_premarket-specific ----

    def _format_premarket_movers(self) -> str:
        # 只查少數重要 symbols(避免成本爆),完整版 Phase 3 補
        watch = ["NVDA", "AAPL", "MSFT", "TSLA", "META", "GOOGL", "AMZN"]
        movers = []
        for s in watch:
            try:
                price, chg = _day_change(s)
                if chg is not None and abs(chg) >= 0.02:
                    movers.append((s, price, chg))
            except Exception as e:
                logger.warning(f"premarket {s} failed: {e}")
        lines = ["<b>Pre-market 異動 (>2%)</b>"]
        if not movers:
            lines.append("  <i>無顯著異動</i>")
            return "\n".join(lines)
        for s, p, c in movers:
            lines.append(f"  • {escape(s)}: {_fmt_price(p)} ({_fmt_pct(c)})")
        return "\n".join(lines)

    def _format_macro_indicators(self) -> str:
        lines = ["<b>Macro 指標</b>"]
        for sym, name in (("^VIX", "VIX"), ("^TNX", "10Y yield"), ("DX-Y.NYB", "DXY")):
            price = get_latest_price(sym)
            lines.append(f"  {escape(name)}: {_fmt_price(price)}")
        return "\n".join(lines)

    # ---- next brief time ----

    def _next_brief_time(self) -> str:
        return _NEXT_BRIEF_LABEL.get(self.brief_type, "下次排程")
