"""Phase 2.5.2 — Investor 視角共用候選計算。

對應 docs/STRATEGY_PHILOSOPHY.md。brief_generator 的三大段落
(Sell PUT 機會 / Sell CALL 機會 / LEAPS 進場)都從這裡取資料。

設計原則:
- 一律「離條件還多遠」呈現,不是分數。
- 任一資料源失敗 → 該檔 candidate 用 None / "資料抓取失敗" 標示,不丟整批。
- VIX 從 macro_regime state 讀(避免 brief 自己再跑一次抓取)。
- 持倉從 positions.json 讀,mode_3 → 空 list。

候選 dict schema:
    {
        "symbol": "NVDA",
        "price": 145.20,                  # float | None
        "distance_to_high_pct": -8.2,     # float (already × 100) | None
        "rsi": 55.3,                      # float | None
        "ivr": 35.0,                      # float | None
        "vix": 17.0,                      # float | None  (只有 LEAPS 用)
        "pnl_pct": 45.0,                  # float | None  (只有 sell_call 用)
        "conditions_met": 0,              # 0..N (依該訊號條件數)
        "conditions_total": 3,
        "status_text": "全條件未達 — 等深度回檔",
        "missing": ["RSI 偏高 (55)", "IVR 偏低 (35)"],
        "passed":  ["距 52W 高 -8.2%"],
    }
"""

from __future__ import annotations

from typing import Optional

from loguru import logger

from src.config.settings import POSITION_MODE
from src.config.universe import SELL_PUT_WHITELIST
from src.data.iv_rank import calc_iv_rank
from src.data.price_data import fetch_history
from src.indicators.basic import get_rsi_latest
from src.management.current_positions import load_positions
from src.management.leaps_pnl_tracker import calc_option_pnl
from src.storage.state_manager import read_json


# ── 條件門檻(對應 STRATEGY_PHILOSOPHY.md)──
SELL_PUT_DIST_TO_HIGH_PCT = -15.0     # 距 52W 高 ≤ -15%
SELL_PUT_RSI_MAX = 35.0
SELL_PUT_IVR_MIN = 60.0               # IVR 是加分項,但條件齊備需要

SELL_CALL_DIST_TO_HIGH_PCT = -3.0     # 距 52W 高 ≥ -3%(漲到出場區)
SELL_CALL_RSI_MIN = 70.0
SELL_CALL_PNL_MIN_PCT = 50.0          # LEAPS 過保護點

LEAPS_DIST_TO_HIGH_PCT = -25.0
LEAPS_RSI_MAX = 30.0
LEAPS_VIX_MIN = 20.0
LEAPS_VIX_MAX = 30.0


# ── 共用快取結構 ──

def _quote_block(symbol: str) -> dict:
    """單檔抓「現價 / 52W 高 / RSI(14)」一次到位,降低 yfinance 呼叫次數。

    回 {"price": float|None, "high_52w": float|None, "dist_pct": float|None,
        "rsi": float|None, "error": str|None}
    """
    try:
        df = fetch_history(symbol, period="1y", interval="1d")
        if df is None or getattr(df, "empty", True):
            return {"price": None, "high_52w": None, "dist_pct": None,
                    "rsi": None, "error": "no_data"}
        price = float(df["Close"].iloc[-1])
        high_52w = float(df["High"].max())
        dist_pct = (price - high_52w) / high_52w * 100 if high_52w else None
        rsi = get_rsi_latest(df, length=14)
        return {"price": price, "high_52w": high_52w, "dist_pct": dist_pct,
                "rsi": rsi, "error": None}
    except Exception as e:
        logger.warning(f"_quote_block({symbol}) failed: {e}")
        return {"price": None, "high_52w": None, "dist_pct": None,
                "rsi": None, "error": str(e)}


def _ivr_safe(symbol: str) -> Optional[float]:
    try:
        ivr = calc_iv_rank(symbol).get("ivr")
        return float(ivr) if ivr is not None else None
    except Exception as e:
        logger.warning(f"_ivr_safe({symbol}) failed: {e}")
        return None


def _vix_from_macro_state() -> Optional[float]:
    """從 layer_macro_regime_state.json 讀 VIX(避免 brief 二次抓取)。"""
    try:
        state = read_json("layer_macro_regime_state.json", default={})
        vix = state.get("indicators", {}).get("vix", {}).get("value")
        return float(vix) if vix is not None else None
    except Exception as e:
        logger.warning(f"_vix_from_macro_state failed: {e}")
        return None


# ── Public API ──

class InvestorView:
    """組合各 candidate 計算 + 市場環境分類。"""

    # ── Sell PUT 候選 ──

    @staticmethod
    def get_sell_put_candidates(top_n: int = 5) -> list:
        """對 SELL_PUT_WHITELIST 每檔算「離接貨區還多遠」。
        排序:離接貨區最近者在前(距 52W 高越深越前面)。
        """
        out = []
        for sym in SELL_PUT_WHITELIST:
            q = _quote_block(sym)
            ivr = _ivr_safe(sym)
            cand = _build_sell_put_candidate(sym, q, ivr)
            out.append(cand)

        # 排序鍵:condition_met 高優先,其次離接貨區距離(越接近 -15% 越前面)
        def _sort_key(c):
            dist = c.get("distance_to_high_pct")
            return (
                -c.get("conditions_met", 0),
                # 已過接貨區的(dist <= -15)優先,然後越靠近越優先
                abs((dist if dist is not None else 999) - SELL_PUT_DIST_TO_HIGH_PCT),
            )
        out.sort(key=_sort_key)
        return out[:top_n]

    # ── Sell CALL 候選 ──

    @staticmethod
    def get_sell_call_candidates(top_n: int = 5) -> list:
        """從 positions 讀 long_call / 現股,對每筆算「離出場區還多遠」。

        mode_3 / 無真實持倉 → []。
        """
        if POSITION_MODE == "mode_3":
            return []

        pos = load_positions()
        # 抽 symbols(去重),保留是否為 LEAPS(long_call)以便算 pnl
        symbol_meta: dict[str, dict] = {}
        for opt in pos.get("options") or []:
            if opt.get("_example") or str(opt.get("type", "")) != "long_call":
                continue
            sym = opt.get("symbol")
            if sym:
                symbol_meta.setdefault(sym, {"option": opt, "stock": False})
        for s in pos.get("stocks") or []:
            if s.get("_example"):
                continue
            sym = s.get("symbol")
            if sym:
                meta = symbol_meta.setdefault(sym, {"option": None, "stock": True})
                meta["stock"] = True

        if not symbol_meta:
            return []

        out = []
        for sym, meta in symbol_meta.items():
            q = _quote_block(sym)
            pnl_pct = None
            if meta["option"] is not None:
                try:
                    pnl = calc_option_pnl(meta["option"]) or {}
                    raw = pnl.get("pnl_pct")
                    pnl_pct = round(raw * 100, 1) if raw is not None else None
                except Exception as e:
                    logger.warning(f"calc_option_pnl({sym}) failed: {e}")
            cand = _build_sell_call_candidate(sym, q, pnl_pct, has_leaps=meta["option"] is not None)
            out.append(cand)

        def _sort_key(c):
            dist = c.get("distance_to_high_pct")
            return (
                -c.get("conditions_met", 0),
                # 越靠近 -3%(出場區)越優先;dist 越接近 0(或正數)越好
                abs((dist if dist is not None else -999) - SELL_CALL_DIST_TO_HIGH_PCT),
            )
        out.sort(key=_sort_key)
        return out[:top_n]

    # ── LEAPS 進場候選 ──

    @staticmethod
    def get_leaps_candidates(top_n: int = 3) -> list:
        """對 SELL_PUT_WHITELIST 算「離 LEAPS 進場區還多遠」。"""
        vix = _vix_from_macro_state()
        out = []
        for sym in SELL_PUT_WHITELIST:
            q = _quote_block(sym)
            cand = _build_leaps_candidate(sym, q, vix)
            out.append(cand)

        def _sort_key(c):
            dist = c.get("distance_to_high_pct")
            return (
                -c.get("conditions_met", 0),
                abs((dist if dist is not None else 999) - LEAPS_DIST_TO_HIGH_PCT),
            )
        out.sort(key=_sort_key)
        return out[:top_n]

    # ── 市場環境 ──

    @staticmethod
    def classify_market_regime(vix: Optional[float]) -> str:
        """根據 VIX 返回市場環境描述(對應 STRATEGY_PHILOSOPHY.md)。"""
        if vix is None:
            return "資料缺失"
        if vix < 15:
            return "極低波動,賣方無利可圖,等待"
        if vix < 20:
            return "低波動,IVR 普偏低,賣方溢價不足"
        if vix < 25:
            return "中性,正常市場"
        if vix < 30:
            return "波動上升,賣 PUT 開始有溢價"
        if vix < 40:
            return "恐慌,賣 PUT 高溢價時機(接近底部反彈)"
        return "極端恐慌,等止跌訊號"

    @staticmethod
    def get_vix() -> Optional[float]:
        """暴露給 brief_generator 使用,避免重複抓檔。"""
        return _vix_from_macro_state()


# ── candidate builders(私有)──

def _fmt_num(v, suffix: str = "") -> str:
    if v is None:
        return "n/a"
    try:
        return f"{v:.1f}{suffix}"
    except (TypeError, ValueError):
        return "n/a"


def _build_sell_put_candidate(symbol: str, quote: dict, ivr: Optional[float]) -> dict:
    dist = quote.get("dist_pct")
    rsi = quote.get("rsi")

    details: list[str] = []   # 固定順序:距 52W 高 / RSI / IVR
    passed_flags = [False, False, False]

    # 條件 1:距 52W 高 ≤ -15%
    if dist is not None and dist <= SELL_PUT_DIST_TO_HIGH_PCT:
        details.append(f"距 52W 高 {dist:+.1f}% ✓")
        passed_flags[0] = True
    elif dist is None:
        details.append("距 52W 高 n/a")
    else:
        gap = abs(SELL_PUT_DIST_TO_HIGH_PCT - dist)
        details.append(f"距 52W 高 {dist:+.1f}%(需 ≤ -15%,還差 {gap:.1f}%)")

    # 條件 2:RSI < 35
    if rsi is not None and rsi < SELL_PUT_RSI_MAX:
        details.append(f"RSI(14) {rsi:.0f} ✓")
        passed_flags[1] = True
    elif rsi is None:
        details.append("RSI(14) n/a")
    else:
        details.append(f"RSI(14) {rsi:.0f}(需 < 35,還差 {rsi - SELL_PUT_RSI_MAX:.0f})")

    # 條件 3:IVR ≥ 60
    if ivr is not None and ivr >= SELL_PUT_IVR_MIN:
        details.append(f"IVR {ivr:.0f} ✓")
        passed_flags[2] = True
    elif ivr is None:
        details.append("IVR n/a(歷史不足 30 天)")
    else:
        details.append(f"IVR {ivr:.0f}(需 ≥ 60,還差 {SELL_PUT_IVR_MIN - ivr:.0f})")

    conditions_met = sum(passed_flags)
    status_text = _status_text("sell_put", conditions_met, dist)

    return {
        "symbol": symbol,
        "price": quote.get("price"),
        "distance_to_high_pct": dist,
        "rsi": rsi,
        "ivr": ivr,
        "conditions_met": conditions_met,
        "conditions_total": 3,
        "status_text": status_text,
        "details": details,
        "error": quote.get("error"),
    }


def _build_sell_call_candidate(
    symbol: str, quote: dict, pnl_pct: Optional[float], has_leaps: bool,
) -> dict:
    dist = quote.get("dist_pct")
    rsi = quote.get("rsi")

    details: list[str] = []
    passed_flags: list[bool] = []

    # 條件 1:距 52W 高 ≥ -3%(漲到出場區)
    if dist is not None and dist >= SELL_CALL_DIST_TO_HIGH_PCT:
        details.append(f"距 52W 高 {dist:+.1f}% ✓")
        passed_flags.append(True)
    elif dist is None:
        details.append("距 52W 高 n/a")
        passed_flags.append(False)
    else:
        gap = abs(SELL_CALL_DIST_TO_HIGH_PCT - dist)
        details.append(f"距 52W 高 {dist:+.1f}%(需 ≥ -3%,還差 {gap:.1f}%)")
        passed_flags.append(False)

    # 條件 2:RSI > 70
    if rsi is not None and rsi > SELL_CALL_RSI_MIN:
        details.append(f"RSI(14) {rsi:.0f} ✓")
        passed_flags.append(True)
    elif rsi is None:
        details.append("RSI(14) n/a")
        passed_flags.append(False)
    else:
        details.append(f"RSI(14) {rsi:.0f}(需 > 70,還差 {SELL_CALL_RSI_MIN - rsi:.0f})")
        passed_flags.append(False)

    # 條件 3:LEAPS pnl ≥ +50%(只在有 LEAPS 時檢視)
    if has_leaps:
        if pnl_pct is not None and pnl_pct >= SELL_CALL_PNL_MIN_PCT:
            details.append(f"持倉獲利 {pnl_pct:+.0f}% ✓(過保護點)")
            passed_flags.append(True)
        elif pnl_pct is None:
            details.append("持倉獲利 n/a")
            passed_flags.append(False)
        else:
            details.append(
                f"持倉獲利 {pnl_pct:+.0f}%(需 ≥ +50%,還差 {SELL_CALL_PNL_MIN_PCT - pnl_pct:.0f}%)"
            )
            passed_flags.append(False)
        total = 3
    else:
        total = 2

    conditions_met = sum(passed_flags)
    status_text = _status_text("sell_call", conditions_met, dist)

    return {
        "symbol": symbol,
        "price": quote.get("price"),
        "distance_to_high_pct": dist,
        "rsi": rsi,
        "pnl_pct": pnl_pct,
        "has_leaps": has_leaps,
        "conditions_met": conditions_met,
        "conditions_total": total,
        "status_text": status_text,
        "details": details,
        "error": quote.get("error"),
    }


def _build_leaps_candidate(symbol: str, quote: dict, vix: Optional[float]) -> dict:
    dist = quote.get("dist_pct")
    rsi = quote.get("rsi")

    details: list[str] = []
    passed_flags = [False, False, False]

    # 條件 1:距 52W 高 ≤ -25%
    if dist is not None and dist <= LEAPS_DIST_TO_HIGH_PCT:
        details.append(f"距 52W 高 {dist:+.1f}% ✓")
        passed_flags[0] = True
    elif dist is None:
        details.append("距 52W 高 n/a")
    else:
        gap = abs(LEAPS_DIST_TO_HIGH_PCT - dist)
        details.append(f"距 52W 高 {dist:+.1f}%(需 ≤ -25%,還差 {gap:.1f}%)")

    # 條件 2:RSI < 30
    if rsi is not None and rsi < LEAPS_RSI_MAX:
        details.append(f"RSI(14) {rsi:.0f} ✓")
        passed_flags[1] = True
    elif rsi is None:
        details.append("RSI(14) n/a")
    else:
        details.append(f"RSI(14) {rsi:.0f}(需 < 30,還差 {rsi - LEAPS_RSI_MAX:.0f})")

    # 條件 3:VIX 在 sweet spot 20~30
    if vix is not None and LEAPS_VIX_MIN <= vix <= LEAPS_VIX_MAX:
        details.append(f"VIX {vix:.1f} ✓(sweet spot)")
        passed_flags[2] = True
    elif vix is None:
        details.append("VIX n/a")
    elif vix < LEAPS_VIX_MIN:
        details.append(f"VIX {vix:.1f}(需 20-30,偏低)")
    else:
        details.append(f"VIX {vix:.1f}(需 20-30,偏高,等止跌)")

    conditions_met = sum(passed_flags)
    status_text = _status_text("leaps", conditions_met, dist)

    return {
        "symbol": symbol,
        "price": quote.get("price"),
        "distance_to_high_pct": dist,
        "rsi": rsi,
        "vix": vix,
        "conditions_met": conditions_met,
        "conditions_total": 3,
        "status_text": status_text,
        "details": details,
        "error": quote.get("error"),
    }


def _status_text(kind: str, met: int, dist: Optional[float]) -> str:
    if kind == "sell_put":
        if met == 3:
            return "三條件齊備 — 可考慮賣 PUT 接貨"
        if met == 2:
            return "兩條件齊備 — 觀察,等第三條件"
        if met == 1:
            return "僅一條件達 — 候選,不行動"
        return "全條件未達 — 等深度回檔"
    if kind == "sell_call":
        if met == 3:
            return "三條件齊備 — 可考慮賣 CALL 鎖利"
        if met == 2:
            return "兩條件齊備 — 接近出場區,觀察"
        if met == 1:
            return "僅一條件達"
        return "全條件未達 — 持有"
    # leaps
    if met == 3:
        return "三條件齊備 — 可考慮 LEAPS 進場"
    if met == 2:
        return "兩條件齊備 — 接近進場區,觀察"
    if met == 1:
        return "僅一條件達"
    return "全條件未達 — 等市場回檔"
