"""Phase 2.5.2 — 每日 4 次 market brief 組裝(investor 視角)。

對應 docs/STRATEGY_PHILOSOPHY.md:
  - Sell PUT = 打折買單(離接貨區還多遠)
  - Sell CALL = 鎖利出場單(離出場區還多遠)
  - LEAPS 進場 = 深度便宜買單(離進場區還多遠)

dispatch by brief_type:
  us_eod        台北 08:30 — 美股盤後(完整檢視)
  tw_eod        台北 13:30 — 台股盤後
  us_premarket  台北 21:00 — 美股盤前(精簡)
  us_midday     台北 06:00 — 美股盤中(精簡)

設計:
- 每段 try/except 內回 fallback 字串("資料抓取失敗"),整支 brief 不死
- HTML escape 所有外部來源欄位(防注入)
- 不走 alert_router(brief 是被動推送,不需 dedup/quota/cooldown)
"""

from html import escape
from typing import Optional

from loguru import logger

from src.alerts.investor_view import InvestorView
from src.data.earnings_calendar import get_upcoming_earnings
from src.data.price_data import fetch_history, get_52w_high_low, get_latest_price
from src.management.account_drawdown import get_current_drawdown
from src.management.hedge_dte_tracker import scan_all_hedges
from src.management.leaps_pnl_tracker import scan_all_leaps
from src.management.short_delta_monitor import scan_all_shorts
from src.twstock.active_etf_signals import scan_all_active_etfs


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


# ── helpers ──

def _safe(label: str, fn, *args, **kwargs) -> str:
    """每段資料抓取的安全包裝。失敗 → "資料抓取失敗" + 細節到 log。"""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.warning(f"brief section '{label}' failed: {e}")
        return f"<i>{escape(label)} 資料抓取失敗</i>"


def _fmt_pct(v) -> str:
    """v 已是「百分比數」(例如 -8.2 表示 -8.2%)。"""
    if v is None:
        return "n/a"
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_pct_ratio(v) -> str:
    """v 是「比率」(例如 -0.082 表示 -8.2%)。"""
    if v is None:
        return "n/a"
    try:
        return f"{float(v) * 100:+.2f}%"
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
    """回 (latest_price, day_change_ratio)。失敗回 (None, None)。"""
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


# ── BriefGenerator ──

class BriefGenerator:
    def __init__(self, brief_type: str):
        self.brief_type = brief_type

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

    # ── builders ──

    def _build_us_eod(self) -> str:
        parts = [
            _safe("整體環境", self._format_market_regime),
            _safe("Sell PUT 機會檢視", self._format_sell_put, full=True),
            _safe("Sell CALL 機會檢視", self._format_sell_call, full=True),
            _safe("LEAPS 進場檢視", self._format_leaps_entry, full=True),
            _safe("部位健康度", self._format_portfolio_health),
            _safe("今日事件", self._format_events_today),
        ]
        return "\n\n".join(p for p in parts if p)

    def _build_tw_eod(self) -> str:
        parts = [
            _safe("台股當日", self._format_tw_today),
            _safe("加碼條件檢視", self._format_tw_add_check),
            _safe("主動 ETF 動向", self._format_active_etfs),
            _safe("美股盤前展望", self._format_us_premarket_preview),
        ]
        return "\n\n".join(p for p in parts if p)

    def _build_us_premarket(self) -> str:
        parts = [
            _safe("整體環境", self._format_market_regime),
            _safe("Pre-market 異動", self._format_premarket_movers),
            _safe("Macro 變化", self._format_macro_indicators),
            _safe("今日事件", self._format_events_today),
            _safe("Sell PUT 候選", self._format_sell_put, full=False, top_n=3),
            _safe("Sell CALL 候選", self._format_sell_call, full=False, top_n=3),
        ]
        return "\n\n".join(p for p in parts if p)

    def _build_us_midday(self) -> str:
        parts = [
            _safe("整體環境", self._format_market_regime),
            _safe("美股當日進度", self._format_macro_snapshot),
            _safe("今日異動 >3%", self._format_intraday_movers),
            _safe("Sell PUT 候選", self._format_sell_put, full=False, top_n=3),
            _safe("Sell CALL 候選", self._format_sell_call, full=False, top_n=3),
            _safe("台股展望", self._format_tw_outlook),
        ]
        return "\n\n".join(p for p in parts if p)

    # ── investor view sections ──

    def _format_market_regime(self) -> str:
        vix = InvestorView.get_vix()
        regime = InvestorView.classify_market_regime(vix)
        vix_str = f"{vix:.2f}" if vix is not None else "n/a"
        # 推導下一步建議
        if vix is None:
            advice = "等資料補齊"
        elif vix < 20:
            advice = "等 VIX 上升 或 個股深度回檔"
        elif vix < 30:
            advice = "正常掃個股機會"
        elif vix < 40:
            advice = "賣 PUT 高溢價時機(挑接貨區)"
        else:
            advice = "極端恐慌,等止跌訊號"
        return (
            "🌡️ <b>整體環境</b>\n"
            f"   VIX {escape(vix_str)}\n"
            f"   <i>{escape(regime)}</i>\n"
            f"   → {escape(advice)}"
        )

    def _format_sell_put(self, full: bool = True, top_n: int = 5) -> str:
        candidates = InvestorView.get_sell_put_candidates(top_n=top_n)
        header = (
            "💼 <b>Sell PUT 機會檢視</b>\n   「哪些優質股快到接貨區?」"
            if full else
            "💼 <b>Sell PUT 候選 (top 3)</b>"
        )
        if not candidates:
            return header + "\n   <i>無候選資料</i>"

        body_lines = [header]
        for i, c in enumerate(candidates, start=1):
            sym = escape(str(c["symbol"]))
            price = _fmt_price(c.get("price"))
            if c.get("error"):
                body_lines.append(f"   {i}. {sym} <i>(資料抓取失敗)</i>")
                continue
            if full:
                body_lines.append(f"   {i}. {sym} ${price}")
                for line in c.get("details", []):
                    body_lines.append(f"      {escape(str(line))}")
                body_lines.append(f"      狀態:{escape(c['status_text'])}")
            else:
                met = c.get("conditions_met", 0)
                tot = c.get("conditions_total", 3)
                body_lines.append(
                    f"   {i}. {sym} ${price} — {escape(c['status_text'])} ({met}/{tot})"
                )

        # 結論
        max_met = max((c.get("conditions_met", 0) for c in candidates), default=0)
        if max_met >= 3:
            conclusion = "今日有標的滿足三條件,可深入檢視合約鏈"
        elif max_met == 2:
            conclusion = "今日無標的同時滿足三條件,觀察接近者"
        else:
            conclusion = "今日無標的接近接貨區,等 VIX 上升 或 個股深度回檔"
        body_lines.append(f"   → 結論:{escape(conclusion)}")
        return "\n".join(body_lines)

    def _format_sell_call(self, full: bool = True, top_n: int = 5) -> str:
        candidates = InvestorView.get_sell_call_candidates(top_n=top_n)
        header = (
            "💼 <b>Sell CALL 機會檢視</b>\n   「哪些持倉到我的出場區?」"
            if full else
            "💼 <b>Sell CALL 候選 (top 3)</b>"
        )
        if not candidates:
            # mode_3 / 沒持倉
            return header + "\n   <i>未啟用部位管理或無持倉,跳過</i>"

        body_lines = [header]
        for i, c in enumerate(candidates, start=1):
            sym = escape(str(c["symbol"]))
            price = _fmt_price(c.get("price"))
            tag = "LEAPS" if c.get("has_leaps") else "現股"
            if c.get("error"):
                body_lines.append(f"   {i}. {sym} ({tag}) <i>(資料抓取失敗)</i>")
                continue
            if full:
                body_lines.append(f"   {i}. {sym} {tag} ${price}")
                for line in c.get("details", []):
                    body_lines.append(f"      {escape(str(line))}")
                body_lines.append(f"      狀態:{escape(c['status_text'])}")
            else:
                met = c.get("conditions_met", 0)
                tot = c.get("conditions_total", 3)
                body_lines.append(
                    f"   {i}. {sym} ({tag}) ${price} — {escape(c['status_text'])} ({met}/{tot})"
                )

        max_met = max((c.get("conditions_met", 0) for c in candidates), default=0)
        if max_met >= 3:
            conclusion = "今日有持倉接近出場區,可考慮賣 CALL 鎖利"
        elif max_met == 2:
            conclusion = "持倉接近出場區但條件未齊,觀察"
        else:
            conclusion = "持倉皆未到出場區,持有"
        body_lines.append(f"   → 結論:{escape(conclusion)}")
        return "\n".join(body_lines)

    def _format_leaps_entry(self, full: bool = True, top_n: int = 3) -> str:
        candidates = InvestorView.get_leaps_candidates(top_n=top_n)
        header = (
            "🚀 <b>LEAPS 進場檢視</b>\n   「哪些優質股到深度便宜區?」"
            if full else
            "🚀 <b>LEAPS 進場候選</b>"
        )
        if not candidates:
            return header + "\n   <i>無候選資料</i>"

        body_lines = [header]
        for i, c in enumerate(candidates, start=1):
            sym = escape(str(c["symbol"]))
            price = _fmt_price(c.get("price"))
            if c.get("error"):
                body_lines.append(f"   {i}. {sym} <i>(資料抓取失敗)</i>")
                continue
            if full:
                body_lines.append(f"   {i}. {sym} ${price}")
                for line in c.get("details", []):
                    body_lines.append(f"      {escape(str(line))}")
                body_lines.append(f"      狀態:{escape(c['status_text'])}")
            else:
                met = c.get("conditions_met", 0)
                tot = c.get("conditions_total", 3)
                body_lines.append(
                    f"   {i}. {sym} ${price} — {escape(c['status_text'])} ({met}/{tot})"
                )

        max_met = max((c.get("conditions_met", 0) for c in candidates), default=0)
        if max_met >= 3:
            conclusion = "今日有 LEAPS 進場機會,可深入檢視合約"
        elif max_met == 2:
            conclusion = "接近進場區但條件未齊,觀察"
        else:
            conclusion = "今日無 LEAPS 進場機會,等市場回檔"
        body_lines.append(f"   → 結論:{escape(conclusion)}")
        return "\n".join(body_lines)

    def _format_portfolio_health(self) -> str:
        lines = ["📊 <b>部位健康度</b>"]

        # LEAPS 損益
        try:
            leaps = scan_all_leaps() or []
        except Exception as e:
            logger.warning(f"scan_all_leaps failed: {e}")
            leaps = None
        if leaps is None:
            lines.append("   LEAPS 損益: <i>資料抓取失敗</i>")
        elif not leaps:
            lines.append("   LEAPS 損益: <i>無持倉或冷啟動</i>")
        else:
            lines.append("   LEAPS 損益:")
            for t in leaps[:5]:
                oid = escape(str(t.get("option_id", "?")))
                pnl = t.get("pnl") or {}
                pct = pnl.get("pnl_pct")
                pct_str = _fmt_pct_ratio(pct) if pct is not None else "n/a"
                lvl = escape(str(t.get("level", "")))
                lines.append(f"     • {oid}: {pct_str} [{lvl}]")

        # Short delta 警示
        try:
            shorts = scan_all_shorts() or []
        except Exception as e:
            logger.warning(f"scan_all_shorts failed: {e}")
            shorts = None
        if shorts is None:
            lines.append("   Short Delta 警示: <i>資料抓取失敗</i>")
        elif not shorts:
            lines.append("   Short Delta 警示:無")
        else:
            for s in shorts[:3]:
                sym = escape(str(s.get("symbol", "?")))
                d = s.get("delta")
                d_str = f"{d:.2f}" if d is not None else "n/a"
                lines.append(f"     • {sym} Δ={d_str}")

        # Hedge DTE
        try:
            hedges = scan_all_hedges() or []
        except Exception as e:
            logger.warning(f"scan_all_hedges failed: {e}")
            hedges = None
        if hedges is None:
            lines.append("   Hedge DTE: <i>資料抓取失敗</i>")
        elif not hedges:
            lines.append("   Hedge DTE:健康(無 DTE < 45 對沖)")
        else:
            for h in hedges[:3]:
                sym = escape(str(h.get("symbol", "?")))
                dte = h.get("dte", "?")
                lines.append(f"     • {sym}: DTE {dte} ⚠")

        # Drawdown
        try:
            dd = get_current_drawdown() or {}
        except Exception as e:
            logger.warning(f"get_current_drawdown failed: {e}")
            dd = None
        if dd is None:
            lines.append("   帳戶回撤: <i>資料抓取失敗</i>")
        else:
            pct = dd.get("drawdown_pct")
            level = escape(str(dd.get("alert_level", "normal")))
            lines.append(f"   帳戶回撤:{_fmt_pct_ratio(pct)} [{level}]")

        return "\n".join(lines)

    # ── pre/midday/tw 段落 ──

    def _format_premarket_movers(self) -> str:
        watch = ["NVDA", "AAPL", "MSFT", "TSLA", "META", "GOOGL", "AMZN"]
        movers = []
        for s in watch:
            try:
                price, chg = _day_change(s)
                if chg is not None and abs(chg) >= 0.02:
                    movers.append((s, price, chg))
            except Exception as e:
                logger.warning(f"premarket {s} failed: {e}")
        lines = ["📊 <b>Pre-market 異動 (>2%)</b>"]
        if not movers:
            lines.append("   <i>無顯著異動</i>")
            return "\n".join(lines)
        for s, p, c in movers:
            lines.append(f"   • {escape(s)}: {_fmt_price(p)} ({_fmt_pct_ratio(c)})")
        return "\n".join(lines)

    def _format_intraday_movers(self) -> str:
        watch = ["NVDA", "AAPL", "MSFT", "TSLA", "META", "GOOGL", "AMZN", "AVGO", "TSM"]
        movers = []
        for s in watch:
            try:
                price, chg = _day_change(s)
                if chg is not None and abs(chg) >= 0.03:
                    movers.append((s, price, chg))
            except Exception as e:
                logger.warning(f"intraday {s} failed: {e}")
        lines = ["🔥 <b>今日異動 (>3%)</b>"]
        if not movers:
            lines.append("   <i>無顯著異動</i>")
            return "\n".join(lines)
        for s, p, c in movers:
            lines.append(f"   • {escape(s)}: {_fmt_price(p)} ({_fmt_pct_ratio(c)})")
        return "\n".join(lines)

    def _format_macro_snapshot(self) -> str:
        lines = ["📊 <b>美股大盤</b>"]
        for sym, name in (("SPY", "SPY"), ("QQQ", "QQQ"), ("^VIX", "VIX")):
            price, chg = _day_change(sym)
            lines.append(f"   {escape(name)}: {_fmt_price(price)} ({_fmt_pct_ratio(chg)})")
        return "\n".join(lines)

    def _format_macro_indicators(self) -> str:
        lines = ["🌐 <b>Macro 指標</b>"]
        for sym, name in (("^VIX", "VIX"), ("^TNX", "10Y yield"), ("DX-Y.NYB", "DXY")):
            price = _safe_price(sym)
            lines.append(f"   {escape(name)}: {_fmt_price(price)}")
        return "\n".join(lines)

    def _format_events_today(self) -> str:
        upcoming = get_upcoming_earnings(within_days=1) or []
        lines = ["⏰ <b>今日事件</b>"]
        if not upcoming:
            lines.append("   <i>無</i>")
            return "\n".join(lines)
        for e in upcoming[:10]:
            sym = escape(str(e.get("symbol", "?")))
            d = e.get("days_until")
            ed = escape(str(e.get("earnings_date", "?")))
            lines.append(f"   • {sym} earnings {ed} (T-{d})")
        return "\n".join(lines)

    def _format_tw_outlook(self) -> str:
        lines = ["🇹🇼 <b>台股展望</b>"]
        for sym, name in (("00631L.TW", "00631L"), ("2330.TW", "2330")):
            try:
                m = get_52w_high_low(sym)
                pct = m.get("pct_from_high")
                cur = m.get("current")
                lines.append(
                    f"   {escape(name)}: {_fmt_price(cur)} (距 52W 高 {_fmt_pct_ratio(pct)})"
                )
            except Exception as e:
                logger.warning(f"tw outlook {sym} failed: {e}")
                lines.append(f"   {escape(name)}: <i>n/a</i>")
        return "\n".join(lines)

    # ── tw_eod sections ──

    def _format_tw_today(self) -> str:
        lines = ["📊 <b>台股當日</b>"]
        for sym, name in (("00631L.TW", "00631L"), ("2330.TW", "2330")):
            price, chg = _day_change(sym)
            lines.append(f"   {escape(name)}: {_fmt_price(price)} ({_fmt_pct_ratio(chg)})")
        return "\n".join(lines)

    def _format_tw_add_check(self) -> str:
        """台股加碼條件檢視(對應 STRATEGY 加碼三層,以「離 A 級還多遠」呈現)。

        A 級門檻(從 thresholds 讀,但 thresholds 形狀可能變,
        失敗 fallback 到 -10% / RSI 40)。
        """
        from src.indicators.basic import get_rsi_latest

        # 嘗試讀 thresholds(失敗 fallback)
        try:
            from src.config.thresholds import TWSTOCK_CORE_THRESHOLDS as _thr  # type: ignore
            a_dist = _thr.get("tier_A_dist_to_high_pct", -10.0)
            a_rsi = _thr.get("tier_A_rsi_max", 40.0)
        except Exception:
            a_dist, a_rsi = -10.0, 40.0

        lines = ["🎯 <b>加碼條件檢視</b>"]
        for sym, name in (("00631L.TW", "00631L"), ("2330.TW", "2330")):
            try:
                df = fetch_history(sym, period="1y", interval="1d")
                if df is None or getattr(df, "empty", True):
                    lines.append(f"   {escape(name)}: <i>n/a</i>")
                    continue
                price = float(df["Close"].iloc[-1])
                high = float(df["High"].max())
                dist = (price - high) / high * 100 if high else None
                rsi = get_rsi_latest(df, length=14)
                lines.append(f"   {escape(name)}:")
                if dist is None:
                    lines.append("      距 52W 高 n/a")
                elif dist <= a_dist:
                    lines.append(f"      距 52W 高 {dist:+.2f}% ✓ A 級已達")
                else:
                    gap = abs(a_dist - dist)
                    lines.append(
                        f"      距 52W 高 {dist:+.2f}%(A 級需 ≤ {a_dist}%,還差 {gap:.2f}%)"
                    )
                if rsi is None:
                    lines.append("      RSI(14) n/a")
                elif rsi <= a_rsi:
                    lines.append(f"      RSI(14) {rsi:.0f} ✓ A 級已達")
                else:
                    lines.append(
                        f"      RSI(14) {rsi:.0f}(A 級需 ≤ {a_rsi},還差 {rsi - a_rsi:.0f})"
                    )
                # 結論
                if dist is not None and rsi is not None and dist <= a_dist and rsi <= a_rsi:
                    lines.append("      狀態:符合 A 級加碼條件")
                else:
                    lines.append("      狀態:不符合加碼,觀望")
            except Exception as e:
                logger.warning(f"tw add check {sym} failed: {e}")
                lines.append(f"   {escape(name)}: <i>資料抓取失敗</i>")
        return "\n".join(lines)

    def _format_active_etfs(self) -> str:
        etfs = scan_all_active_etfs() or []
        active = [e for e in etfs if e.get("tier") is not None]
        lines = ["📈 <b>主動 ETF 動向</b>(7d lookback)"]
        if not active:
            lines.append("   <i>無加碼動向</i>")
            return "\n".join(lines)
        for e in active[:5]:
            sym = escape(str(e.get("symbol", "?")))
            tier = e.get("tier", "—")
            n_short = e.get("n_etfs_increased_short_window", 0)
            lines.append(f"   • {sym}: tier={tier} ({n_short} 檔加碼)")
        return "\n".join(lines)

    def _format_us_premarket_preview(self) -> str:
        lines = ["🌎 <b>美股盤前展望</b>"]
        # ES futures 隔夜變化
        try:
            _, chg = _day_change("ES=F")
            es_str = _fmt_pct_ratio(chg)
            lines.append(
                f"   ES futures: {es_str} "
                f"→ 預期美股{'高開' if (chg or 0) > 0 else '低開' if (chg or 0) < 0 else '平開'}"
            )
        except Exception as e:
            logger.warning(f"es futures fail: {e}")
            lines.append("   ES futures: <i>n/a</i>")
        try:
            _, chg = _day_change("TSM")
            tsm_str = _fmt_pct_ratio(chg)
            lines.append(f"   TSM ADR: {tsm_str} → 對應 2330 預期方向")
        except Exception as e:
            logger.warning(f"tsm adr fail: {e}")
            lines.append("   TSM ADR: <i>n/a</i>")
        return "\n".join(lines)

    # ── next brief time ──

    def _next_brief_time(self) -> str:
        return _NEXT_BRIEF_LABEL.get(self.brief_type, "下次排程")


def _safe_price(sym: str) -> Optional[float]:
    try:
        return get_latest_price(sym)
    except Exception as e:
        logger.warning(f"_safe_price({sym}) failed: {e}")
        return None
