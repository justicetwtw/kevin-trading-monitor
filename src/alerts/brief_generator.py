"""Phase 2.5.2 — 每日 4 次 market brief 共用組裝邏輯(InvestorView 版)。

dispatch by brief_type:
  us_eod        台北 08:30 — 美股盤後
  tw_eod        台北 13:30 — 台股盤後
  us_premarket  台北 21:00 — 美股盤前
  us_midday     台北 06:00 — 美股盤中(起床看)

設計:
- 每段 try/except 內回 fallback 字串("資料抓取失敗"),整支 brief 不死
- 不走 alert_router(brief 是被動推送,不需 dedup/quota/cooldown)
- HTML escape 所有外部來源欄位(防注入)
- InvestorView 三段候選(Sell PUT / Sell CALL / LEAPS)
  conditions_total 動態(IVR / VIX n/a 不計入分母)
- 結論句根據 fully_met / partial_met / none_met 動態
- 部位健康度段:positions 空 / 全 _example → 整段(連標題)不顯示
- Sell CALL 段:同上(沒持倉沒得賣)
"""

from collections import Counter
from html import escape

from loguru import logger

from src.alerts.investor_view import InvestorView, classify_market_regime
from src.config.thresholds import TWSTOCK_TIER_RULES
from src.data.earnings_calendar import get_upcoming_earnings
from src.data.price_data import fetch_history
from src.management.account_drawdown import get_current_drawdown
from src.management.current_positions import _is_positions_empty, load_positions
from src.management.hedge_dte_tracker import scan_all_hedges
from src.management.leaps_pnl_tracker import scan_all_leaps
from src.management.short_delta_monitor import scan_all_shorts
from src.storage.state_manager import read_json
from src.twstock.active_etf_signals import scan_all_active_etfs
from src.twstock.twstock_signals import scan_twstock_core


VALID_BRIEF_TYPES = (
    "us_eod",
    "tw_eod",
    "us_premarket",
    "us_midday",
    # Phase 2.5.6 DST/timing 變體
    "us_premarket_to_intraday",
    "us_midday_to_afterhours",
)

_BRIEF_TITLE = {
    "us_eod": "📊 美股盤後 brief",
    "tw_eod": "🇹🇼 台股盤後 brief",
    "us_premarket": "🌎 美股盤前 brief",
    "us_midday": "🌃 美股盤中 brief",
    "us_premarket_to_intraday": "🌎 美股開盤即時 brief",
    "us_midday_to_afterhours": "🌃 美股盤後早晨 brief",
}

_NEXT_BRIEF_LABEL = {
    "us_eod": "台股盤後 (台北 13:30)",
    "tw_eod": "美股盤前 (台北 21:00)",
    "us_premarket": "美股盤中 (隔日 台北 06:00,間隔 9 小時)",
    "us_midday": "美股盤後 (台北 08:30)",
    "us_premarket_to_intraday": "美股盤中 (隔日 台北 06:00,間隔 9 小時)",
    "us_midday_to_afterhours": "美股盤後 (台北 08:30)",
}

# 給結論句的「段別中文名稱」
_SEGMENT_LABEL = {
    "sell_put": "Sell PUT",
    "sell_call": "Sell CALL",
    "leaps": "LEAPS",
}

# unmet_code → 「等什麼」中文(每段邏輯不同)
_WAIT_LABELS = {
    "rsi_too_high": "等 RSI 過低(短線 oversold)",
    "rsi_too_low": "等 RSI 過高(短線 overbought)",
    "distance_not_enough": "等股價深度回檔",
    "distance_too_far": "等股價接近高點",
    "ivr_too_low": "等 IV 上來",
    "vix_out_of_sweet": "等 VIX 進 20-30 sweet spot",
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


def _summarize_wait(partial_met: list) -> str:
    """統計 partial_met 多數標的「最常缺哪個條件」→ 翻成「等 X」文字。

    多數一致 → 用對應 wait label
    不一致(沒有單一條件占 ≥ 半數)→ "等多重條件成熟"
    """
    if not partial_met:
        return "等條件成熟"
    counter: Counter = Counter()
    for c in partial_met:
        counter.update(c.get("unmet_codes", []))
    if not counter:
        return "等條件成熟"
    top_code, top_count = counter.most_common(1)[0]
    if top_count >= len(partial_met):
        return _WAIT_LABELS.get(top_code, "等多重條件成熟")
    return "等多重條件成熟"


def _build_conclusion(candidates: list, segment_key: str) -> str:
    """三段共用結論句 logic。

    fully_met → 強烈候選(列 symbols)
    partial_met → "接近接貨區,等 X"(根據多數缺啥)
                  若 IVR 全 n/a → 加 IV history 提示
                  若 leaps 段 VIX 全 n/a → 加 VIX 提示
    全 none_met → 等市場回檔
    candidates 為空 → 「無候選資料」
    """
    if not candidates:
        return "<i>→ 結論:無候選資料</i>"

    fully_met = [c for c in candidates if c["conditions_met"] == c["conditions_total"]
                 and c["conditions_total"] > 0]
    partial_met = [c for c in candidates if 0 < c["conditions_met"] < c["conditions_total"]]

    label = _SEGMENT_LABEL.get(segment_key, segment_key)

    if fully_met:
        symbols = ", ".join(escape(c["symbol"]) for c in fully_met[:3])
        return f"<b>→ 結論</b>:{symbols} 條件齊備,強烈候選"

    if partial_met:
        symbols = ", ".join(escape(c["symbol"]) for c in partial_met[:3])
        wait = _summarize_wait(partial_met)
        base = f"<b>→ 結論</b>:{symbols} 接近接貨區,{wait}"
        # IVR 全 n/a → 加提示(sell_put / sell_call 段適用)
        if segment_key in ("sell_put", "sell_call") and all(
            c.get("ivr") is None for c in candidates
        ):
            base += "\n   ⚠ IVR 歷史資料不足,建議啟動 IV 累積(Phase 3 待辦)"
        # leaps 段 VIX n/a 提示
        if segment_key == "leaps" and all(c.get("vix") is None for c in candidates):
            base += "\n   ⚠ VIX 資料不足,結論未納入波動條件"
        return base

    return f"<b>→ 結論</b>:全 {label} universe 距條件仍遠,等市場回檔"


def _format_candidate_block(c: dict) -> str:
    """單筆候選的多行 markdown(含 details)。"""
    sym = escape(str(c.get("symbol", "?")))
    price = _fmt_price(c.get("price"))
    met = c["conditions_met"]
    total = c["conditions_total"]
    status = escape(c["status_text"])
    lines = [f"  • <b>{sym}</b> {price}  ({met}/{total} 達)  {status}"]
    for d in c.get("details", []):
        lines.append(f"      - {escape(str(d))}")
    return "\n".join(lines)


class BriefGenerator:
    def __init__(self, brief_type: str):
        self.brief_type = brief_type
        # 共用 InvestorView instance(同一輪 brief 內 SELL_PUT / LEAPS 13 檔資料 cache)
        self._view = InvestorView()

    # ---- public ----

    def generate(self) -> str:
        if self.brief_type not in VALID_BRIEF_TYPES:
            raise ValueError(f"Invalid brief_type: {self.brief_type}")

        builders = {
            "us_eod": self._build_us_eod,
            "tw_eod": self._build_tw_eod,
            "us_premarket": self._build_us_premarket,
            "us_midday": self._build_us_midday,
            "us_premarket_to_intraday": self._build_us_premarket_to_intraday,
            "us_midday_to_afterhours": self._build_us_midday_to_afterhours,
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
        parts.append(_safe("整體環境", self._format_market_regime))
        parts.append(_safe("Sell PUT 機會", self._format_sell_put_section))
        sell_call = _safe("Sell CALL 機會", self._format_sell_call_section)
        if sell_call:
            parts.append(sell_call)
        parts.append(_safe("LEAPS 進場", self._format_leaps_section))
        health = _safe("部位健康度", self._format_position_health)
        if health:
            parts.append(health)
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
        parts.append(_safe("整體環境", self._format_market_regime))
        parts.append(_safe("Pre-market 異動", self._format_premarket_movers))
        parts.append(_safe("Sell PUT 機會", self._format_sell_put_section))
        parts.append(_safe("LEAPS 進場", self._format_leaps_section))
        parts.append(_safe("今日事件", self._format_events_today))
        return "\n\n".join(p for p in parts if p)

    def _build_us_midday(self) -> str:
        # 整體環境段已含 SPY/QQQ/VIX,不重複放「美股當日」
        parts = []
        parts.append(_safe("整體環境", self._format_market_regime))
        parts.append(_safe("Sell PUT 機會", self._format_sell_put_section))
        sell_call = _safe("Sell CALL 機會", self._format_sell_call_section)
        if sell_call:
            parts.append(sell_call)
        parts.append(_safe("LEAPS 進場", self._format_leaps_section))
        return "\n\n".join(p for p in parts if p)

    # ---- new shared formatters (InvestorView-based) ----

    def _format_market_regime(self) -> str:
        """整體環境:大盤 + VIX 區間 + Layer 0 三維 modifier(白話)。"""
        lines = ["<b>🌡️ 整體環境</b>"]
        # 大盤
        for sym, name in (("SPY", "SPY"), ("QQQ", "QQQ"), ("^VIX", "VIX")):
            price, chg = _day_change(sym)
            lines.append(f"  {escape(name)}: {_fmt_price(price)} ({_fmt_pct(chg)})")

        # VIX regime
        vix = self._view._vix()
        regime = classify_market_regime(vix)
        if vix is not None:
            lines.append(f"  VIX 環境: {regime}")
        else:
            lines.append(f"  VIX 環境: <i>{escape(regime)}</i>")

        # Layer 0 modifier(白話化)
        layer0 = read_json("layer0_history.json", default={})
        if isinstance(layer0, dict) and layer0:
            agg = layer0.get("aggregate_modifiers", {}) or {}
            sc = agg.get("sell_call", 0)
            sp = agg.get("sell_put", 0)
            le = agg.get("leaps_entry", 0)
            veto = " (VETO)" if agg.get("leaps_entry_veto") else ""
            lines.append(
                f"  Layer 0: sell_call {sc:+d} {self._interpret_modifier(sc)} / "
                f"sell_put {sp:+d} {self._interpret_modifier(sp)} / "
                f"leaps {le:+d} {self._interpret_modifier(le)}{veto}"
            )
        else:
            lines.append("  Layer 0: <i>n/a (no data)</i>")
        return "\n".join(lines)

    @staticmethod
    def _interpret_modifier(val: int) -> str:
        if val >= 10:
            return "(強烈偏好)"
        if val >= 5:
            return "(略偏好)"
        if val >= -5:
            return "(中性)"
        if val >= -10:
            return "(略偏不利)"
        return "(不利)"

    def _format_sell_put_section(self) -> str:
        candidates = self._view.get_sell_put_candidates(top_n=3)
        lines = ["<b>💼 Sell PUT 機會檢視</b> (top 3 / 13 白名單)"]
        if not candidates:
            lines.append("  <i>無候選</i>")
            return "\n".join(lines)
        for c in candidates:
            lines.append(_format_candidate_block(c))
        lines.append(_build_conclusion(candidates, "sell_put"))
        return "\n".join(lines)

    def _format_sell_call_section(self) -> str:
        """持倉空時整段不顯示(回空字串,builder 會 filter 掉)。"""
        pos = load_positions()
        if _is_positions_empty(pos):
            return ""
        candidates = self._view.get_sell_call_candidates(top_n=3)
        lines = ["<b>💼 Sell CALL 機會檢視</b> (對持倉)"]
        if not candidates:
            lines.append("  <i>持倉但無候選</i>")
            return "\n".join(lines)
        for c in candidates:
            lines.append(_format_candidate_block(c))
        lines.append(_build_conclusion(candidates, "sell_call"))
        return "\n".join(lines)

    def _format_leaps_section(self) -> str:
        candidates = self._view.get_leaps_candidates(top_n=3)
        lines = ["<b>🚀 LEAPS 進場檢視</b> (top 3 / 13 白名單)"]
        if not candidates:
            lines.append("  <i>無候選</i>")
            return "\n".join(lines)
        for c in candidates:
            lines.append(_format_candidate_block(c))
        lines.append(_build_conclusion(candidates, "leaps"))
        return "\n".join(lines)

    def _format_position_health(self) -> str:
        """positions 空 / 全 _example → 整段(連標題)不顯示。"""
        pos = load_positions()
        if _is_positions_empty(pos):
            return ""
        lines = ["<b>📊 部位健康度</b>"]

        # LEAPS 觸發
        leaps_triggers = scan_all_leaps() or []
        if leaps_triggers:
            lines.append(f"  LEAPS 觸發: {len(leaps_triggers)} 筆")
            for t in leaps_triggers[:5]:
                opt_id = escape(str(t.get("option_id") or "?"))
                lvl = escape(str(t.get("level", "?")))
                action = escape(str(t.get("action", "?")))
                lines.append(f"    • {opt_id} [{lvl}] {action}")
        else:
            lines.append("  LEAPS 觸發: <i>無</i>")

        # Short Delta 警報
        shorts = scan_all_shorts() or []
        if shorts:
            lines.append(f"  Short Delta 警報: {len(shorts)} 筆")
            for s in shorts[:5]:
                opt_id = escape(str(s.get("option_id") or s.get("symbol", "?")))
                delta = s.get("delta")
                delta_str = f"{delta:+.2f}" if delta is not None else "n/a"
                lines.append(f"    • {opt_id} Δ={delta_str}")
        else:
            lines.append("  Short Delta: <i>正常 (|Δ| ≤ 0.35)</i>")

        # Hedge DTE
        hedges = scan_all_hedges() or []
        if hedges:
            lines.append(f"  Hedge DTE 警報: {len(hedges)} 筆")
            for h in hedges[:5]:
                opt_id = escape(str(h.get("option_id") or h.get("symbol", "?")))
                lines.append(f"    • {opt_id} DTE={h.get('dte', '?')}")
        else:
            lines.append("  Hedge DTE: <i>正常 (≥ 45 天)</i>")

        # 帳戶回撤
        dd = get_current_drawdown() or {}
        dd_pct = dd.get("drawdown_pct")
        lvl = dd.get("alert_level", "normal")
        if dd_pct is None:
            lines.append("  帳戶回撤: <i>n/a (無歷史)</i>")
        else:
            lines.append(
                f"  帳戶回撤: {dd_pct * 100:+.1f}% [{escape(str(lvl))}]"
            )
        return "\n".join(lines)

    def _format_events_today(self) -> str:
        upcoming = get_upcoming_earnings(within_days=1) or []
        lines = ["<b>⏰ 今日事件</b>"]
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
        lines = ["<b>🇹🇼 台股當日</b>"]
        for sym, name in (("00631L.TW", "00631L"), ("2330.TW", "台積電")):
            price, chg = _day_change(sym)
            lines.append(f"  {escape(name)}: {_fmt_price(price)} ({_fmt_pct(chg)})")
        return "\n".join(lines)

    def _format_twstock_signals(self) -> str:
        """🎯 加碼條件檢視 — 顯示距 52W 高 / 週 RSI / A 級門檻 / 狀態。

        scan_twstock_core 已回 pct_from_52w_high / rsi14_weekly / tier。
        門檻從 TWSTOCK_TIER_RULES 讀(A: 距高 ≤ -10% AND 週 RSI < 40)。
        """
        sigs = scan_twstock_core() or []
        lines = ["<b>🎯 加碼條件檢視</b>"]
        if not sigs:
            lines.append("  <i>無</i>")
            return "\n".join(lines)

        a_dd = TWSTOCK_TIER_RULES["A"]["drawdown_pct"]       # -0.10
        a_rsi = TWSTOCK_TIER_RULES["A"]["weekly_rsi_max"]    # 40

        for s in sigs:
            sym = escape(str(s.get("symbol", "?")))
            name = escape(str(s.get("name", "")))
            price = s.get("price")
            d2h = s.get("pct_from_52w_high")
            wrsi = s.get("rsi14_weekly")
            tier = s.get("tier")

            header = f"  • <b>{sym}</b>"
            if name:
                header += f" ({name})"
            if price is not None:
                header += f": {_fmt_price(price)}"
            lines.append(header)

            # 距高
            if d2h is None:
                lines.append("      - 距 52W 高 n/a (價格資料缺)")
            else:
                d_pct = d2h * 100
                need_pct = a_dd * 100
                if d2h <= a_dd:
                    lines.append(
                        f"      - 距 52W 高 {d_pct:+.1f}% (A 級需 ≤ {need_pct:.0f}%) ✓"
                    )
                else:
                    gap = (a_dd - d2h) * 100  # 負數,代表還要再跌
                    lines.append(
                        f"      - 距 52W 高 {d_pct:+.1f}% "
                        f"(A 級需 ≤ {need_pct:.0f}%, 還需跌 {abs(gap):.1f}%)"
                    )

            # 週 RSI
            if wrsi is None:
                lines.append("      - 週 RSI(14) n/a")
            elif wrsi < a_rsi:
                lines.append(
                    f"      - 週 RSI(14) {wrsi:.0f} (A 級需 &lt; {a_rsi}) ✓"
                )
            else:
                gap = wrsi - a_rsi
                lines.append(
                    f"      - 週 RSI(14) {wrsi:.0f} (A 級需 &lt; {a_rsi}, 還差 {gap:.0f})"
                )

            # 狀態
            if tier in ("A", "B", "C"):
                action = escape(str(s.get("action", "")))
                lines.append(f"      - 狀態:符合 {tier} 級 — {action}")
            else:
                # 接近 A 級 = 距高 ≤ -10% + 5%(放寬 5pp)或 RSI < 40 + 10
                near = (
                    (d2h is not None and d2h <= a_dd + 0.05)
                    or (wrsi is not None and wrsi < a_rsi + 10)
                )
                if near:
                    lines.append("      - 狀態:接近 A 級門檻")
                else:
                    lines.append("      - 狀態:不符合,觀望")
        return "\n".join(lines)

    def _format_active_etfs(self) -> str:
        etfs = scan_all_active_etfs() or []
        active = [e for e in etfs if e.get("tier") is not None]
        lines = ["<b>📊 主動 ETF 動向</b>"]
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
        """🌎 美股盤前展望 — ES futures 漲跌 + TSM ADR 漲跌 → 推估 2330 隔日。

        推估邏輯:2330 預期漲跌 ≈ TSM ADR 漲跌 × 0.7~1.0
        (台股對美股反應有折扣,折扣係數 0.7~1.0)
        """
        lines = ["<b>🌎 美股盤前展望</b>"]
        # ES futures 漲跌(no day_change for futures? try 1d)
        es_price, es_chg = _day_change("ES=F")
        lines.append(
            f"  ES futures: {_fmt_price(es_price)} ({_fmt_pct(es_chg)})"
        )

        # TSM ADR(對應 2330)
        tsm_price, tsm_chg = _day_change("TSM")
        lines.append(
            f"  TSM ADR: {_fmt_price(tsm_price)} ({_fmt_pct(tsm_chg)})"
        )

        # 推估 2330 隔日(只在 TSM 漲跌可拿時推)
        if tsm_chg is not None:
            low = tsm_chg * 0.7 * 100
            high = tsm_chg * 1.0 * 100
            # 若漲幅,low 較小 → 顯示 low~high;若跌幅,高低反過來
            lo, hi = (low, high) if low <= high else (high, low)
            lines.append(
                f"  → 預期 2330 隔日 {lo:+.2f}% ~ {hi:+.2f}% "
                f"(TSM × 0.7~1.0)"
            )
        return "\n".join(lines)

    # ---- DST / timing 變體 builders (Phase 2.5.6) ----

    def _build_us_premarket_to_intraday(self) -> str:
        """夏令時間 + 延後觸發,推送時美股已開盤。

        內容:整體環境 + 開盤即時異動 + Sell PUT/LEAPS + 今日事件
        + 結尾標明「美股已開盤(夏令時間)」。
        """
        parts = []
        parts.append(_safe("整體環境", self._format_market_regime))
        parts.append(_safe("開盤即時異動", self._format_intraday_movers))
        parts.append(_safe("Sell PUT 機會", self._format_sell_put_section))
        parts.append(_safe("LEAPS 進場", self._format_leaps_section))
        parts.append(_safe("今日事件", self._format_events_today))
        parts.append(
            "<i>⚠ 美股已開盤(推送時超過 09:30 ET);夏令時間下台北 21:00 = 09:00 ET,"
            "如延後觸發或備援 cron 觸發,可能落入盤中。</i>"
        )
        return "\n\n".join(p for p in parts if p)

    def _build_us_midday_to_afterhours(self) -> str:
        """夏令/冬令時間下,06:00 台北推送時美股皆已收盤。

        內容:整體環境 + 美股當日完整收盤 + Sell PUT/LEAPS
        + 結尾標明「美股已收盤」。
        """
        parts = []
        parts.append(_safe("整體環境", self._format_market_regime))
        parts.append(_safe("美股當日完整收盤", self._format_us_close_summary))
        parts.append(_safe("Sell PUT 機會", self._format_sell_put_section))
        sell_call = _safe("Sell CALL 機會", self._format_sell_call_section)
        if sell_call:
            parts.append(sell_call)
        parts.append(_safe("LEAPS 進場", self._format_leaps_section))
        parts.append(
            "<i>⚠ 美股已收盤(推送時超過 16:00 ET);"
            "夏令時間台北 06:00 = 18:00 ET、冬令時間 = 17:00 ET,屬盤後早晨 brief。</i>"
        )
        return "\n\n".join(p for p in parts if p)

    def _format_intraday_movers(self) -> str:
        """開盤即時異動:跟 pre-market movers 同 watchlist,但標題改盤中。"""
        watch = ["NVDA", "AAPL", "MSFT", "TSLA", "META", "GOOGL", "AMZN"]
        movers = []
        for s in watch:
            try:
                price, chg = _day_change(s)
                if chg is not None and abs(chg) >= 0.02:
                    movers.append((s, price, chg))
            except Exception as e:
                logger.warning(f"intraday {s} failed: {e}")
        lines = ["<b>📈 開盤即時異動 (&gt;2%)</b>"]
        if not movers:
            lines.append("  <i>無顯著異動</i>")
            return "\n".join(lines)
        for s, p, c in movers:
            lines.append(f"  • {escape(s)}: {_fmt_price(p)} ({_fmt_pct(c)})")
        return "\n".join(lines)

    def _format_us_close_summary(self) -> str:
        """美股當日完整收盤:SPY/QQQ/VIX 收盤價 + 漲跌(資料源同 _day_change)。"""
        lines = ["<b>📈 美股當日完整收盤</b>"]
        for sym, name in (("SPY", "SPY"), ("QQQ", "QQQ"), ("DIA", "DIA"), ("^VIX", "VIX")):
            price, chg = _day_change(sym)
            lines.append(f"  {escape(name)} 收盤: {_fmt_price(price)} ({_fmt_pct(chg)})")
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
        lines = ["<b>📈 Pre-market 異動 (&gt;2%)</b>"]
        if not movers:
            lines.append("  <i>無顯著異動</i>")
            return "\n".join(lines)
        for s, p, c in movers:
            lines.append(f"  • {escape(s)}: {_fmt_price(p)} ({_fmt_pct(c)})")
        return "\n".join(lines)

    # ---- next brief time ----

    def _next_brief_time(self) -> str:
        return _NEXT_BRIEF_LABEL.get(self.brief_type, "下次排程")
