"""Provider capability contracts(docs/focus_trading_engine_v1.md §5 Layer D, §7)。

本 PR 不購買/啟用付費 API、不新增 secret。這裡只定義 provider-neutral 契約:

  - FocusOptionsProvider     :skew / OI / gamma / GEX 能力 schema
  - EstimatesProvider        :FY1/FY2 EPS、revision、multiple
  - VolatilityIndexProvider  :VIX complex + COR1M

紅線:
  - 每個欄位有明確 capability flag;provider 不支援 → value=None(honest null),
    不得用中性值硬補。
  - dealer GEX 一律標 estimated,含 assumption + confidence,永不宣稱是實際 dealer 部位。
  - OI 不能證明客戶買/賣;單日 VIX call volume 不能直接說市場押注暴跌。
  - yfinance / public Cboe 只能做 delayed / screen-grade fallback。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

# ---- 能力欄位清單(schema 穩定,測試據此檢查) ----

OPTIONS_CAPABILITY_FIELDS = (
    "current_atm_iv",
    "iv_rank",
    "iv_percentile",
    "put_skew_25d",
    "put_skew_change_5d",
    "put_skew_change_20d",
    "iv_term_structure",
    "put_call_volume_ratio",
    "put_call_oi_ratio",
    "expected_move",
    "strike_oi_concentration",
    "oi_change_1d",
    "gamma_concentration",
    "gamma_flip_proxy",
    "estimated_dealer_gex",
)

ESTIMATES_CAPABILITY_FIELDS = (
    "revenue_actual_trend",
    "eps_actual_trend",
    "fy1_eps_estimate",
    "fy2_eps_estimate",
    "eps_revision_1m",
    "eps_revision_3m",
    "trailing_pe",
    "ntm_pe",
    "fy2_pe",
    "bear_multiple",
    "base_multiple",
    "bull_multiple",
    "fair_value_range",
)

VOLATILITY_CAPABILITY_FIELDS = (
    "vix",
    "vix9d",
    "vix3m",
    "vvix",
    "cor1m",
    "term_structure",
    "term_inversion",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


#: 「確認」下檔壓力方向所需的付費欄位(context)。此清單用於 coverage 報告。
REQUIRED_PRESSURE_FIELDS = ("put_skew_25d", "gamma_flip_proxy", "strike_oi_concentration")

#: 真正有「方向性」的欄位:gamma flip 的正負 + put skew 的「變化」(非絕對值)。
#: 要到達 worsening / confirmed_ok(任何有向判定)必須同時具備這兩類證據;缺一即 unavailable。
#: 絕對 put_skew_25d 或 strike_oi_concentration 單獨存在都「不」構成方向確認。
DIRECTIONAL_GAMMA_FIELD = "gamma_flip_proxy"
SKEW_CHANGE_FIELDS = ("put_skew_change_5d", "put_skew_change_20d")

#: Market regime → 曝險上限倍數(只限制上限,不預測隔日方向,§ Layer B)。
#: 未知/資料不足 → 0.0 fail closed(無法確認 regime 就不放行新增曝險)。
REGIME_EXPOSURE_CAPS = {"calm": 1.0, "elevated": 0.5, "stress": 0.0}
_REGIME_ORDER = ("calm", "elevated", "stress")


def regime_exposure_cap(regime: str | None) -> dict[str, Any]:
    """把 regime 轉成 auditable 的曝險上限倍數。未知 regime → 0.0(fail closed)。"""
    cap = REGIME_EXPOSURE_CAPS.get(regime or "", 0.0)
    return {
        "regime": regime,
        "max_exposure_multiplier": cap,
        "blocks_new_exposure": cap <= 0.0,
        "reduces_new_exposure": 0.0 < cap < 1.0,
        "basis": "caps exposure only; not a next-day direction forecast",
    }


def _num(value: Any) -> float | None:
    """回傳有效數值(排除 bool),否則 None。"""
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def build_options_pressure(
    capability: dict[str, Any] | None,
    reference_date: Any = None,
) -> dict[str, Any]:
    """從 options capability snapshot 導出一個「下檔壓力」adapter,三態分明:

      - unavailable :方向性證據不足(缺 gamma flip 或 skew 變化)或證據 stale → 無法確認方向。
      - worsening   :put skew 變化轉惡 / gamma flip 轉負(需付費資料才判得出)。
      - confirmed_ok:方向性證據齊備且未惡化。

    紅線(finding P1 修正):
      - missing ≠ 「壓力未惡化」;partial 也不行。只要 gamma flip 或 skew 變化任一缺,
        或必要證據 stale,一律 unavailable,不會 fall through 成 confirmed_ok。
      - 絕對 put_skew_25d、strike_oi_concentration 單獨不具方向性,不足以解鎖 add。
      - 有 as_of 時做 freshness 檢查;stale 視同 unavailable(舊資料不是確認)。
    """
    from src.focus.freshness import MAX_PRICE_AGE_DAYS, freshness

    cap = capability or {}
    gamma_flip = _num(cap.get(DIRECTIONAL_GAMMA_FIELD))
    skew_change = None
    for f in SKEW_CHANGE_FIELDS:
        skew_change = _num(cap.get(f))
        if skew_change is not None:
            break

    present = [f for f in REQUIRED_PRESSURE_FIELDS if cap.get(f) is not None]
    coverage = round(len(present) / len(REQUIRED_PRESSURE_FIELDS), 4)

    as_of = cap.get("as_of")
    fresh = freshness(as_of, reference_date, MAX_PRICE_AGE_DAYS) if as_of is not None else {"status": "unknown_age"}
    stale = fresh.get("status") in ("stale", "missing")

    have_direction = gamma_flip is not None and skew_change is not None
    if not have_direction or stale:
        missing: list[str] = []
        if gamma_flip is None:
            missing.append("gamma_flip_proxy")
        if skew_change is None:
            missing.append("put_skew_change")
        reasons = ["required_options_confirmation_unavailable"]
        if stale and as_of is not None:
            reasons.append("options_evidence_stale")
        return {
            "status": "unavailable",
            "downside_pressure_worsening": False,
            "downside_pressure_confirmed_ok": False,
            "reasons": reasons,
            "missing_fields": missing,
            "coverage": coverage,
            "source": cap.get("source"),
            "as_of": as_of,
            "freshness": fresh,
        }

    worsening = bool(skew_change > 0 or gamma_flip < 0)
    return {
        "status": "worsening" if worsening else "confirmed_ok",
        "downside_pressure_worsening": worsening,
        "downside_pressure_confirmed_ok": not worsening,
        "reasons": [],
        "missing_fields": [],
        "coverage": coverage,
        "source": cap.get("source"),
        "as_of": as_of,
        "freshness": fresh,
        "put_skew_25d": _num(cap.get("put_skew_25d")),
        "put_skew_change": skew_change,
        "gamma_flip_proxy": gamma_flip,
    }


def composite_market_regime(
    vix_regime: str | None,
    index_trend: dict[str, Any] | None,
    breadth: dict[str, Any] | None,
    *,
    vix_available: bool = True,
) -> dict[str, Any]:
    """把 VIX regime 與 QQQ/SMH/SOXX 趨勢 + breadth 併成 composite regime。

    紅線(finding P1 修正):
      - regime 不能只看 VIX。若大盤(QQQ)與半導體(SMH)雙雙跌破 200DMA、或市場
        breadth 嚴重受損,即使 VIX 偏低也要向上升級 regime(fail toward caution)。
      - 缺資料的成分(VVIX/COR1M、index trend、breadth)標為 capability gap,不假裝健康。
      - 回傳 auditable exposure_cap;non-zero cap(elevated=0.5)由下游實際縮小提案倉位。
    """
    index_trend = index_trend or {}
    breadth = breadth or {}
    gaps: list[str] = []

    base = vix_regime if vix_regime in _REGIME_ORDER else None
    if not vix_available or base is None:
        gaps.append("vix_regime_unavailable")

    def _below_200(sym: str) -> bool | None:
        node = index_trend.get(sym) or {}
        val = node.get("above_200dma")
        return (val is False) if isinstance(val, bool) else None

    qqq_below = _below_200("QQQ")
    smh_below = _below_200("SMH")
    if qqq_below is None:
        gaps.append("broad_index_trend_unavailable")
    if smh_below is None:
        gaps.append("semi_index_trend_unavailable")

    breadth_50 = breadth.get("breadth_above_50dma")
    breadth_200 = breadth.get("breadth_above_200dma")
    if breadth_50 is None:
        gaps.append("breadth_50dma_unavailable")

    escalation = 0
    drivers: list[str] = []
    # 兩大領先指標同時跌破 200DMA:結構性走弱 → 直接升到 stress 區(escalate 2)。
    if qqq_below is True and smh_below is True:
        escalation += 2
        drivers.append("broad_and_semi_below_200dma")
    elif qqq_below is True or smh_below is True:
        escalation += 1
        drivers.append("one_leader_below_200dma")
    # breadth 嚴重受損。
    if isinstance(breadth_50, (int, float)) and not isinstance(breadth_50, bool) and breadth_50 < 0.4:
        escalation += 1
        drivers.append("weak_breadth_below_50dma")

    # composite regime:以 VIX base 為起點向上(更謹慎)升級;缺 VIX base 時,
    # 若有 trend/breadth 訊號可據以定級,否則 unknown(fail closed cap=0)。
    if base is not None:
        idx = min(len(_REGIME_ORDER) - 1, _REGIME_ORDER.index(base) + escalation)
        composite = _REGIME_ORDER[idx]
    elif qqq_below is not None or smh_below is not None or isinstance(breadth_50, (int, float)):
        # 無 VIX 但有市場結構證據:從 calm 起算再升級(至少能給出保守評級)。
        idx = min(len(_REGIME_ORDER) - 1, escalation)
        composite = _REGIME_ORDER[idx] if escalation > 0 else "elevated"
        drivers.append("regime_from_trend_breadth_without_vix")
    else:
        composite = None  # 完全無證據 → unknown,cap 0.0 fail closed

    cap = regime_exposure_cap(composite)
    return {
        "regime": composite,
        "vix_regime": base,
        "exposure_cap": cap,
        "escalated_from_vix": bool(escalation) and base is not None and composite != base,
        "escalation_drivers": drivers,
        "capability_gaps": gaps,
        "components": {
            "qqq_below_200dma": qqq_below,
            "smh_below_200dma": smh_below,
            "breadth_above_50dma": breadth_50,
            "breadth_above_200dma": breadth_200,
        },
        "basis": "composite of VIX regime + broad/semi trend + breadth; caps exposure only",
    }


class CapabilityProvider(ABC):
    """共用:以 capability flags 表達「哪些欄位真的支援」。"""

    provider_name: str = "abstract"
    capability_fields: tuple[str, ...] = ()

    #: 子類覆寫:此 provider 真正支援的欄位集合。其餘欄位一律 None。
    supported_fields: frozenset[str] = frozenset()

    def capabilities(self) -> dict[str, bool]:
        return {field: field in self.supported_fields for field in self.capability_fields}

    def _null_payload(self, symbol: str, status: str = "capability_gap") -> dict[str, Any]:
        payload: dict[str, Any] = {field: None for field in self.capability_fields}
        payload.update(
            {
                "symbol": symbol,
                "source": self.provider_name,
                "as_of": _now(),
                "status": status,
                "capabilities": self.capabilities(),
                "latency": None,
            }
        )
        return payload


class FocusOptionsProvider(CapabilityProvider):
    """Options / volatility positioning 能力契約(§5 Layer D)。"""

    provider_name = "abstract_options"
    capability_fields = OPTIONS_CAPABILITY_FIELDS

    @abstractmethod
    def get_capability_snapshot(self, symbol: str) -> dict[str, Any]:
        """回傳含所有 capability 欄位的 snapshot;不支援欄位為 None。"""

    def estimate_dealer_gex(
        self,
        symbol: str,
        *,
        available: bool = False,
        value: float | None = None,
    ) -> dict[str, Any]:
        """dealer GEX 一律標 estimated + assumption + confidence(§5 Layer D)。

        沒有真實 open-interest 分層資料時 available=False → value=None、
        confidence="none",並附上「為何不能宣稱真實 dealer 部位」的 assumption。
        """
        return {
            "symbol": symbol,
            "metric": "estimated_dealer_gex",
            "estimated": True,
            "value": value if available else None,
            "confidence": "low" if available else "none",
            "assumption": (
                "Assumes all long gamma sits with dealers and OI reflects net "
                "dealer positioning; open/close and customer side are unknown. "
                "This is a proxy, never a measured dealer inventory."
            ),
            "source": self.provider_name,
            "as_of": _now(),
        }


class YFinanceFocusOptionsProvider(FocusOptionsProvider):
    """免費 fallback:current IV / IV rank / IV percentile 來自自建 iv_history,
    put/call volume ratio 來自 yfinance chain;skew / OI history / gamma / GEX
    皆為付費資料 → None + capability_gap。

    Capability/value consistency(finding P1):supported_fields 宣稱支援的欄位,
    snapshot 一定會實際呼叫底層 provider 去填(runtime 缺資料才是 None);未宣稱
    支援的欄位固定 None,不會出現 capability=true 卻永遠 None 的矛盾。
    """

    provider_name = "yfinance_delayed"
    supported_fields = frozenset(
        {"current_atm_iv", "iv_rank", "iv_percentile", "put_call_volume_ratio"}
    )

    def get_capability_snapshot(self, symbol: str, base_provider: Any = None) -> dict[str, Any]:
        payload = self._null_payload(symbol, status="screen_grade")
        if base_provider is None:
            from src.data.options_provider import YFinanceOptionsProvider

            base_provider = YFinanceOptionsProvider()
        try:
            iv = base_provider.get_iv_metrics(symbol) or {}
        except Exception:
            iv = {}
        try:
            snap = base_provider.get_options_snapshot(symbol) or {}
        except Exception:
            snap = {}
        # 只填 supported_fields;值可能仍為 None(runtime 缺資料),但一定經過取數。
        payload["current_atm_iv"] = iv.get("current_iv")
        payload["iv_rank"] = iv.get("ivr")
        payload["iv_percentile"] = iv.get("ivp")
        payload["put_call_volume_ratio"] = snap.get("put_call_volume_ratio")
        payload["populated_fields"] = sorted(self.supported_fields)
        payload["limitations"] = [
            "delayed/unofficial chain",
            "no paid skew/OI history/GEX; those fields stay None",
        ]
        return payload


class EstimatesProvider(CapabilityProvider):
    """Estimates / valuation 能力契約(§5 Layer A)。"""

    provider_name = "abstract_estimates"
    capability_fields = ESTIMATES_CAPABILITY_FIELDS

    @abstractmethod
    def get_estimates(self, symbol: str) -> dict[str, Any]:
        """回傳估值/預期 snapshot;不支援欄位 None,不得用單一 forward P/E 宣稱便宜。"""


class NullEstimatesProvider(EstimatesProvider):
    """未接付費 estimates 來源時的 honest-null provider。"""

    provider_name = "unconfigured_estimates"
    supported_fields = frozenset()

    def get_estimates(self, symbol: str) -> dict[str, Any]:
        payload = self._null_payload(symbol, status="not_connected")
        payload["approval_status"] = "unconfigured"
        payload["coverage"] = 0.0
        return payload


class VolatilityIndexProvider(CapabilityProvider):
    """VIX complex + COR1M 能力契約(§5 Layer B)。"""

    provider_name = "abstract_volatility"
    capability_fields = VOLATILITY_CAPABILITY_FIELDS

    @abstractmethod
    def get_volatility_state(self) -> dict[str, Any]:
        """回傳市場波動 snapshot;COR1M 等未接來源保持 None。"""

    def joint_state(self, vix: float | None, vvix: float | None, cor1m: float | None) -> dict[str, Any]:
        """VIX / VVIX / COR1M 聯合狀態描述(僅限制曝險上限,不預測隔日)。"""
        if vix is None:
            return {"status": "insufficient_data", "note": "vix_unavailable"}
        regime = "calm"
        if vix >= 30:
            regime = "stress"
        elif vix >= 20:
            regime = "elevated"
        return {
            "status": "ok",
            "regime": regime,
            "vix": vix,
            "vvix": vvix,
            "cor1m": cor1m,
            "note": "caps exposure only; not a next-day direction forecast",
        }


class PublicVolatilityIndexProvider(VolatilityIndexProvider):
    """免費 fallback:VIX/VIX9D/VIX3M 來自 yfinance(delayed);
    VVIX/COR1M 無穩定免費來源 → None + capability_gap。
    """

    provider_name = "yfinance_delayed_vix"
    supported_fields = frozenset({"vix", "vix9d", "vix3m", "term_structure", "term_inversion"})

    def get_volatility_state(self, reference_date=None) -> dict[str, Any]:
        from src.data.vix_structure import fetch_vix_asof, fetch_vix_term_structure
        from src.focus.freshness import MAX_VOL_AGE_DAYS, freshness

        payload = self._null_payload("MARKET", status="screen_grade")
        try:
            term = fetch_vix_term_structure() or {}
        except Exception:
            term = {}
        payload["vix"] = term.get("vix")
        payload["vix9d"] = term.get("vix9d")
        payload["vix3m"] = term.get("vix3m")
        payload["term_structure"] = {
            "vix9d_inverted": term.get("vix9d_inverted"),
            "vix3m_inverted": term.get("vix3m_inverted"),
        }
        # Preserve None for unavailable inversion evidence — do NOT coerce to False
        # ("not inverted") when the underlying VIX9D/VIX is missing.
        payload["term_inversion"] = term.get("vix9d_inverted")
        # 真實 as-of / freshness:VIX bar 日期 vs reference_date。stale/missing 可見。
        try:
            as_of = fetch_vix_asof()
        except Exception:
            as_of = None
        payload["as_of"] = as_of
        payload["freshness"] = freshness(as_of, reference_date, MAX_VOL_AGE_DAYS)
        # 真正的 regime 判定(VVIX/COR1M 未接時仍以 VIX 分級,並標其為 gap)。
        joint = self.joint_state(payload["vix"], payload.get("vvix"), payload.get("cor1m"))
        payload["regime"] = joint.get("regime")
        payload["regime_state"] = joint
        payload["exposure_cap"] = regime_exposure_cap(payload.get("regime"))
        payload["limitations"] = ["VVIX and COR1M require a source not yet connected"]
        return payload
