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
        payload["term_inversion"] = bool(term.get("vix9d_inverted"))
        # 真實 as-of / freshness:VIX bar 日期 vs reference_date。stale/missing 可見。
        try:
            as_of = fetch_vix_asof()
        except Exception:
            as_of = None
        payload["as_of"] = as_of
        payload["freshness"] = freshness(as_of, reference_date, MAX_VOL_AGE_DAYS)
        payload["limitations"] = ["VVIX and COR1M require a source not yet connected"]
        return payload
