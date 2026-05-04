"""Phase 2.5.2 — InvestorView:給 brief_generator 用的「使用者視角候選」。

跟 src/signals/*_scorer.py 不同:
  - scorer 是給「自動推播決策」用的(打分 + veto + push_threshold)
  - InvestorView 是給「人每天打開 brief 看」用的(條件達成 N/M + 結論)

候選函式回傳 list[dict],每筆:
  {
    'symbol':                'NVDA',
    'price':                 145.20 or None,
    'distance_to_high_pct':  -0.082 (= -8.2%) or None,
    'rsi':                   55.3 or None,
    'ivr':                   None or float,
    'vix':                   None or float          (僅 LEAPS 用)
    'details':               ['距 52W 高 -8.2% (需 ≤ -15%, 還差 6.8%)', ...]
    'passed_flags':          [True / False / None]  (None = 條件不適用 / 資料 n/a)
    'conditions_met':        N
    'conditions_total':      M  (動態,n/a 不計入)
    'status_text':           '部分條件達 — 候選' / ...
  }

★ 關鍵:conditions_total 動態
  IVR / VIX 拿不到 → 該條件 passed_flag=None、conditions_total -=1
  → 避免「資料沒到位的 universe 永遠湊不齊 N/N」失能。

★ 排序:conditions_met 降序、平手 distance_to_high_pct 升序(更深回檔優先)。
"""

from typing import Optional

from loguru import logger

from src.config.thresholds import IVR_THRESHOLDS
from src.config.universe import SELL_PUT_WHITELIST
from src.data.iv_rank import calc_iv_rank
from src.data.price_data import fetch_history, get_52w_high_low
from src.data.vix_structure import fetch_vix_term_structure
from src.indicators.basic import get_rsi_latest
from src.management.current_positions import (
    _is_positions_empty, load_positions, _real_options, _real_stocks,
)
from src.storage.state_manager import read_json


# ---- 條件門檻(集中管理,讓 strategy 可調)----

SELL_PUT_THRESHOLDS = {
    "distance_to_high_pct": -0.15,    # ≤ -15%
    "rsi_max": 35,                    # < 35
    "ivr_min": IVR_THRESHOLDS["min_for_short_premium"],   # 30
}

SELL_CALL_THRESHOLDS = {
    "distance_to_high_pct": -0.03,    # ≥ -3%(接近高點)
    "rsi_min": 65,                    # > 65
    "ivr_min": IVR_THRESHOLDS["min_for_short_premium"],
}

LEAPS_THRESHOLDS = {
    "distance_to_high_pct": -0.25,    # ≤ -25%
    "rsi_max": 30,                    # < 30
    "vix_sweet_low": 20,              # 20-30
    "vix_sweet_high": 30,
}


def _ratio_to_status(conditions_met: int, conditions_total: int) -> str:
    """ratio → 文字。conditions_total = 0 邏輯上不會發生(距高+RSI 永遠算)"""
    if conditions_total <= 0:
        return "資料不足"
    ratio = conditions_met / conditions_total
    if ratio >= 1.0:
        return "全條件達標 — 強烈候選"
    if ratio >= 0.5:
        return "多數條件達 — 候選"
    if ratio > 0:
        return "僅部分條件達"
    return "全條件未達"


def classify_market_regime(vix: Optional[float]) -> str:
    """VIX → 環境分類。None → 'n/a'。"""
    if vix is None:
        return "n/a"
    if vix < 12:
        return "極低波動 (vol crush)"
    if vix < 15:
        return "低波動"
    if vix < 20:
        return "正常"
    if vix < 25:
        return "略偏高"
    if vix < 30:
        return "高波動"
    return "極高波動 (panic)"


class InvestorView:
    """instance 內維護 fetch cache(同一輪 brief 內 SELL_PUT / LEAPS 共用 13 檔資料)。"""

    def __init__(self):
        self._df_cache: dict = {}
        self._high_cache: dict = {}
        self._ivr_cache: dict = {}
        self._vix_value: Optional[float] = None
        self._vix_fetched: bool = False

    # ---- 共用 fetcher with cache ----

    def _df(self, symbol: str):
        if symbol not in self._df_cache:
            try:
                self._df_cache[symbol] = fetch_history(symbol, period="6mo", interval="1d")
            except Exception as e:
                logger.warning(f"InvestorView._df({symbol}) failed: {e}")
                self._df_cache[symbol] = None
        return self._df_cache[symbol]

    def _high(self, symbol: str) -> dict:
        if symbol not in self._high_cache:
            try:
                self._high_cache[symbol] = get_52w_high_low(symbol) or {}
            except Exception as e:
                logger.warning(f"InvestorView._high({symbol}) failed: {e}")
                self._high_cache[symbol] = {}
        return self._high_cache[symbol]

    def _ivr(self, symbol: str) -> Optional[float]:
        if symbol not in self._ivr_cache:
            try:
                self._ivr_cache[symbol] = (calc_iv_rank(symbol) or {}).get("ivr")
            except Exception as e:
                logger.warning(f"InvestorView._ivr({symbol}) failed: {e}")
                self._ivr_cache[symbol] = None
        return self._ivr_cache[symbol]

    def _rsi(self, symbol: str) -> Optional[float]:
        df = self._df(symbol)
        if df is None or getattr(df, "empty", True):
            return None
        try:
            return get_rsi_latest(df, 14)
        except Exception as e:
            logger.warning(f"InvestorView._rsi({symbol}) failed: {e}")
            return None

    def _vix(self) -> Optional[float]:
        """先讀 layer0_history.json(已抓過,免重複),失敗 fallback 直接抓。"""
        if self._vix_fetched:
            return self._vix_value
        try:
            layer0 = read_json("layer0_history.json", default={})
            vix = (layer0.get("submodules", {}).get("vix_structure", {})
                   .get("snapshot", {}).get("vix"))
            if vix is not None:
                self._vix_value = float(vix)
                self._vix_fetched = True
                return self._vix_value
        except Exception as e:
            logger.warning(f"InvestorView._vix layer0 read failed: {e}")
        try:
            term = fetch_vix_term_structure() or {}
            v = term.get("vix")
            self._vix_value = float(v) if v is not None else None
        except Exception as e:
            logger.warning(f"InvestorView._vix fetch failed: {e}")
            self._vix_value = None
        self._vix_fetched = True
        return self._vix_value

    # ---- candidates ----

    def get_sell_put_candidates(self, top_n: int = 3) -> list:
        """對 SELL_PUT_WHITELIST 算 3 條件(IVR n/a → conditions_total 動態 = 2)。"""
        out = []
        for symbol in SELL_PUT_WHITELIST:
            try:
                out.append(self._evaluate_sell_put(symbol))
            except Exception as e:
                logger.warning(f"sell_put candidate {symbol} failed: {e}")
        return self._rank_top_n(out, top_n)

    def get_sell_call_candidates(self, top_n: int = 3) -> list:
        """對 positions 內持倉算。冷啟動 / 全 _example → []。

        - LEAPS (long_call): 3 條件(距高 ≥ -3% / RSI > 65 / IVR ≥ 30)
        - 現股: 2 條件(距高 / RSI),沒「+50% 鎖利」概念 → IVR 不算
        - 其餘類型(long_put / short_*): skip(不會在這段)
        """
        pos = load_positions()
        if _is_positions_empty(pos):
            return []
        symbols_seen = set()
        out = []
        # 持倉 LEAPS:long_call
        for opt in _real_options(pos):
            if str(opt.get("type", "")) != "long_call":
                continue
            sym = opt.get("symbol")
            if not sym or sym in symbols_seen:
                continue
            symbols_seen.add(sym)
            try:
                out.append(self._evaluate_sell_call(sym, is_leaps=True))
            except Exception as e:
                logger.warning(f"sell_call LEAPS {sym} failed: {e}")
        # 現股
        for stk in _real_stocks(pos):
            sym = stk.get("symbol")
            if not sym or sym in symbols_seen:
                continue
            symbols_seen.add(sym)
            try:
                out.append(self._evaluate_sell_call(sym, is_leaps=False))
            except Exception as e:
                logger.warning(f"sell_call stock {sym} failed: {e}")
        return self._rank_top_n(out, top_n)

    def get_leaps_candidates(self, top_n: int = 3) -> list:
        """對 SELL_PUT_WHITELIST 算 3 條件(VIX n/a → conditions_total 動態 = 2)。"""
        out = []
        for symbol in SELL_PUT_WHITELIST:
            try:
                out.append(self._evaluate_leaps(symbol))
            except Exception as e:
                logger.warning(f"leaps candidate {symbol} failed: {e}")
        return self._rank_top_n(out, top_n)

    # ---- per-candidate evaluation ----

    def _evaluate_sell_put(self, symbol: str) -> dict:
        thresh = SELL_PUT_THRESHOLDS
        high = self._high(symbol)
        price = high.get("current")
        d2h = high.get("pct_from_high")
        rsi = self._rsi(symbol)
        ivr = self._ivr(symbol)

        details: list = []
        passed_flags: list = []
        unmet_codes: list = []

        # 距 52W 高
        if d2h is None:
            details.append("距 52W 高 n/a (價格資料缺)")
            passed_flags.append(None)
        else:
            d_pct = d2h * 100
            need_pct = thresh["distance_to_high_pct"] * 100
            if d2h <= thresh["distance_to_high_pct"]:
                details.append(f"距 52W 高 {d_pct:+.1f}% (需 ≤ {need_pct:.0f}%) ✓")
                passed_flags.append(True)
            else:
                gap = abs(d2h - thresh["distance_to_high_pct"]) * 100
                details.append(
                    f"距 52W 高 {d_pct:+.1f}% (需 ≤ {need_pct:.0f}%, 還差 {gap:.1f}%)"
                )
                passed_flags.append(False)
                unmet_codes.append("distance_not_enough")

        # RSI
        if rsi is None:
            details.append("RSI n/a (歷史資料缺)")
            passed_flags.append(None)
        elif rsi < thresh["rsi_max"]:
            details.append(f"RSI(14) {rsi:.0f} (需 < {thresh['rsi_max']}) ✓")
            passed_flags.append(True)
        else:
            gap = rsi - thresh["rsi_max"]
            details.append(
                f"RSI(14) {rsi:.0f} (需 < {thresh['rsi_max']}, 還差 {gap:.0f})"
            )
            passed_flags.append(False)
            unmet_codes.append("rsi_too_high")

        # IVR
        if ivr is None:
            details.append("IVR n/a (歷史不足 30 天)")
            passed_flags.append(None)
        elif ivr >= thresh["ivr_min"]:
            details.append(f"IVR {ivr:.0f} (需 ≥ {thresh['ivr_min']}) ✓")
            passed_flags.append(True)
        else:
            gap = thresh["ivr_min"] - ivr
            details.append(
                f"IVR {ivr:.0f} (需 ≥ {thresh['ivr_min']}, 還差 {gap:.0f})"
            )
            passed_flags.append(False)
            unmet_codes.append("ivr_too_low")

        return self._pack(
            symbol=symbol, price=price, d2h=d2h, rsi=rsi, ivr=ivr,
            details=details, passed_flags=passed_flags,
            unmet_codes=unmet_codes,
        )

    def _evaluate_sell_call(self, symbol: str, is_leaps: bool) -> dict:
        thresh = SELL_CALL_THRESHOLDS
        high = self._high(symbol)
        price = high.get("current")
        d2h = high.get("pct_from_high")
        rsi = self._rsi(symbol)
        ivr = self._ivr(symbol) if is_leaps else None

        details: list = []
        passed_flags: list = []
        unmet_codes: list = []

        # 距 52W 高(條件:接近高點 → d2h ≥ -3%)
        if d2h is None:
            details.append("距 52W 高 n/a (價格資料缺)")
            passed_flags.append(None)
        else:
            d_pct = d2h * 100
            need_pct = thresh["distance_to_high_pct"] * 100
            if d2h >= thresh["distance_to_high_pct"]:
                details.append(f"距 52W 高 {d_pct:+.1f}% (需 ≥ {need_pct:.0f}%) ✓")
                passed_flags.append(True)
            else:
                gap = abs(d2h - thresh["distance_to_high_pct"]) * 100
                details.append(
                    f"距 52W 高 {d_pct:+.1f}% (需 ≥ {need_pct:.0f}%, 還差 {gap:.1f}%)"
                )
                passed_flags.append(False)
                unmet_codes.append("distance_too_far")

        # RSI(條件:overbought → > 65)
        if rsi is None:
            details.append("RSI n/a (歷史資料缺)")
            passed_flags.append(None)
        elif rsi > thresh["rsi_min"]:
            details.append(f"RSI(14) {rsi:.0f} (需 > {thresh['rsi_min']}) ✓")
            passed_flags.append(True)
        else:
            gap = thresh["rsi_min"] - rsi
            details.append(
                f"RSI(14) {rsi:.0f} (需 > {thresh['rsi_min']}, 還差 {gap:.0f})"
            )
            passed_flags.append(False)
            unmet_codes.append("rsi_too_low")

        # IVR(LEAPS 持倉才算)
        if is_leaps:
            if ivr is None:
                details.append("IVR n/a (歷史不足 30 天)")
                passed_flags.append(None)
            elif ivr >= thresh["ivr_min"]:
                details.append(f"IVR {ivr:.0f} (需 ≥ {thresh['ivr_min']}) ✓")
                passed_flags.append(True)
            else:
                gap = thresh["ivr_min"] - ivr
                details.append(
                    f"IVR {ivr:.0f} (需 ≥ {thresh['ivr_min']}, 還差 {gap:.0f})"
                )
                passed_flags.append(False)
                unmet_codes.append("ivr_too_low")
        # 現股不加 IVR 條件

        return self._pack(
            symbol=symbol, price=price, d2h=d2h, rsi=rsi, ivr=ivr,
            details=details, passed_flags=passed_flags,
            unmet_codes=unmet_codes,
        )

    def _evaluate_leaps(self, symbol: str) -> dict:
        thresh = LEAPS_THRESHOLDS
        high = self._high(symbol)
        price = high.get("current")
        d2h = high.get("pct_from_high")
        rsi = self._rsi(symbol)
        vix = self._vix()

        details: list = []
        passed_flags: list = []
        unmet_codes: list = []

        # 距 52W 高
        if d2h is None:
            details.append("距 52W 高 n/a (價格資料缺)")
            passed_flags.append(None)
        else:
            d_pct = d2h * 100
            need_pct = thresh["distance_to_high_pct"] * 100
            if d2h <= thresh["distance_to_high_pct"]:
                details.append(f"距 52W 高 {d_pct:+.1f}% (需 ≤ {need_pct:.0f}%) ✓")
                passed_flags.append(True)
            else:
                gap = abs(d2h - thresh["distance_to_high_pct"]) * 100
                details.append(
                    f"距 52W 高 {d_pct:+.1f}% (需 ≤ {need_pct:.0f}%, 還差 {gap:.1f}%)"
                )
                passed_flags.append(False)
                unmet_codes.append("distance_not_enough")

        # RSI
        if rsi is None:
            details.append("RSI n/a (歷史資料缺)")
            passed_flags.append(None)
        elif rsi < thresh["rsi_max"]:
            details.append(f"RSI(14) {rsi:.0f} (需 < {thresh['rsi_max']}) ✓")
            passed_flags.append(True)
        else:
            gap = rsi - thresh["rsi_max"]
            details.append(
                f"RSI(14) {rsi:.0f} (需 < {thresh['rsi_max']}, 還差 {gap:.0f})"
            )
            passed_flags.append(False)
            unmet_codes.append("rsi_too_high")

        # VIX(全市場共用,n/a 整體跳過)
        lo = thresh["vix_sweet_low"]
        hi = thresh["vix_sweet_high"]
        if vix is None:
            details.append(f"VIX n/a (需 {lo}-{hi} sweet spot)")
            passed_flags.append(None)
        elif lo <= vix <= hi:
            details.append(f"VIX {vix:.1f} (需 {lo}-{hi}) ✓")
            passed_flags.append(True)
        else:
            details.append(f"VIX {vix:.1f} (需 {lo}-{hi})")
            passed_flags.append(False)
            unmet_codes.append("vix_out_of_sweet")

        return self._pack(
            symbol=symbol, price=price, d2h=d2h, rsi=rsi, ivr=None,
            details=details, passed_flags=passed_flags, vix=vix,
            unmet_codes=unmet_codes,
        )

    # ---- pack / rank ----

    @staticmethod
    def _pack(symbol, price, d2h, rsi, ivr, details, passed_flags,
              vix=None, unmet_codes=None) -> dict:
        conditions_met = sum(1 for f in passed_flags if f is True)
        conditions_total = sum(1 for f in passed_flags if f is not None)
        return {
            "symbol": symbol,
            "price": price,
            "distance_to_high_pct": d2h,
            "rsi": rsi,
            "ivr": ivr,
            "vix": vix,
            "details": details,
            "passed_flags": passed_flags,
            "conditions_met": conditions_met,
            "conditions_total": conditions_total,
            "status_text": _ratio_to_status(conditions_met, conditions_total),
            "unmet_codes": unmet_codes or [],
        }

    @staticmethod
    def _rank_top_n(candidates: list, top_n: int) -> list:
        """按 conditions_met 降序、平手按距高升序(更深回檔優先)。"""
        def sort_key(c):
            d2h = c.get("distance_to_high_pct")
            d2h_key = d2h if d2h is not None else 0.0
            return (-c["conditions_met"], d2h_key)
        return sorted(candidates, key=sort_key)[:top_n]
