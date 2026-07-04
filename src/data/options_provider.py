"""Options 資料 provider 抽象介面 + 免費預設實作(yfinance)。

目的:把「dashboard / scorer 需要什麼 options 欄位」與「資料從哪來」解耦。
Phase 1 只有免費層(yfinance + 自建 iv_history);未來接 ORATS / Massive /
Tradier 時實作對應 provider,輸出 schema 不變
(src/models/signal_schema.py 的 IV_METRICS_SPEC / OPTIONS_SNAPSHOT_SPEC)。

Secret 紀律:本模組與 stub 只宣告 secret「名稱」;在 provider 真正實作
API 呼叫之前,不要在 GitHub 新增對應 secret,也不得把實際值寫入 repo。
"""

import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from loguru import logger


class OptionsProvider(ABC):
    """所有 options 資料源的統一介面。"""

    #: provider 識別名(寫進輸出的 source 欄位)
    provider_name: str = "abstract"

    #: 需要的 GitHub Actions secret 名稱;None = 免費不需 key
    SECRET_NAME: Optional[str] = None

    def is_configured(self) -> bool:
        """需要 key 的 provider:檢查環境變數是否已注入(不讀值內容)。"""
        if self.SECRET_NAME is None:
            return True
        return bool(os.getenv(self.SECRET_NAME, ""))

    @abstractmethod
    def get_iv_metrics(self, symbol: str) -> dict:
        """回傳 IV_METRICS_SPEC 格式:
        {symbol, ivr, ivp, current_iv, samples, source, as_of}
        資料不足時對應欄位為 None,不得用中性值(如 50)硬補。
        """

    @abstractmethod
    def get_options_snapshot(self, symbol: str) -> dict:
        """回傳 OPTIONS_SNAPSHOT_SPEC 格式:
        {symbol, put_call_volume_ratio, put_skew, oi_concentration,
         unusual_activity, source, as_of}
        provider 不支援的欄位一律 None(dashboard 會標示待資料)。
        """

    # ---- 共用 helper ----

    def _base_iv_metrics(self, symbol: str) -> dict:
        return {
            "symbol": symbol,
            "ivr": None,
            "ivp": None,
            "current_iv": None,
            "samples": 0,
            "source": self.provider_name,
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

    def _base_snapshot(self, symbol: str) -> dict:
        return {
            "symbol": symbol,
            "put_call_volume_ratio": None,
            "put_skew": None,
            "oi_concentration": None,
            "unusual_activity": None,
            "source": self.provider_name,
            "as_of": datetime.now(timezone.utc).isoformat(),
        }


class YFinanceOptionsProvider(OptionsProvider):
    """免費預設實作:IV metrics 來自自建 252 日 iv_history(src/data/iv_rank.py),
    snapshot 只有 yfinance chain 能算的 put/call volume ratio;
    skew / OI concentration / UOA 需付費資料 → None。
    """

    provider_name = "yfinance"
    SECRET_NAME = None

    def get_iv_metrics(self, symbol: str) -> dict:
        from src.data.iv_rank import calc_iv_rank  # 檔案讀取,不打網路

        out = self._base_iv_metrics(symbol)
        try:
            m = calc_iv_rank(symbol) or {}
            out.update({
                "ivr": m.get("ivr"),
                "ivp": m.get("ivp"),
                "current_iv": m.get("current_iv"),
                "samples": int(m.get("samples", 0) or 0),
            })
        except Exception as e:
            logger.error(f"get_iv_metrics({symbol}) failed: {e}")
        return out

    def get_options_snapshot(self, symbol: str) -> dict:
        out = self._base_snapshot(symbol)
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            if not ticker.options:
                return out
            chain = ticker.option_chain(ticker.options[0])
            call_vol = float(chain.calls["volume"].fillna(0).sum())
            put_vol = float(chain.puts["volume"].fillna(0).sum())
            if call_vol > 0:
                out["put_call_volume_ratio"] = round(put_vol / call_vol, 3)
        except Exception as e:
            logger.error(f"get_options_snapshot({symbol}) failed: {e}")
        return out


def get_provider(name: str | None = None) -> OptionsProvider:
    """依名稱(或 OPTIONS_PROVIDER 環境變數)取得 provider;預設免費 yfinance。

    付費 provider 尚未實作,選到會在呼叫方法時 raise NotImplementedError,
    提醒先完成實作與 secret 設定,避免靜默退回假資料。
    """
    name = (name or os.getenv("OPTIONS_PROVIDER", "yfinance")).lower()
    if name in ("yfinance", "free", "default"):
        return YFinanceOptionsProvider()
    if name == "orats":
        from src.data.options_orats import ORATSOptionsProvider
        return ORATSOptionsProvider()
    if name in ("massive", "polygon"):
        from src.data.options_massive import MassiveOptionsProvider
        return MassiveOptionsProvider()
    if name == "tradier":
        from src.data.options_tradier import TradierOptionsProvider
        return TradierOptionsProvider()
    raise ValueError(f"unknown options provider: {name}")
