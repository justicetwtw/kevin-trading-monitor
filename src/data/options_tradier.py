"""Tradier options provider — Phase 2 stub,尚未實作。

輕量候選:options chain + greeks,適合 broker / chain 查詢與驗價,
不是完整研究資料源。評估細節見 docs/data_api_evaluation.md。

Secret 紀律:實作前不要在 GitHub 新增 TRADIER_ACCESS_TOKEN;
token 只透過 GitHub Actions secrets 注入,不得寫入 repo 或 .env。
"""

from src.data.options_provider import OptionsProvider

_NOT_IMPLEMENTED = (
    "Tradier provider 尚未實作(Phase 2)。實作前請勿新增 "
    "TRADIER_ACCESS_TOKEN secret;見 docs/data_api_evaluation.md。"
)


class TradierOptionsProvider(OptionsProvider):
    provider_name = "tradier"
    SECRET_NAME = "TRADIER_ACCESS_TOKEN"

    def get_iv_metrics(self, symbol: str) -> dict:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def get_options_snapshot(self, symbol: str) -> dict:
        raise NotImplementedError(_NOT_IMPLEMENTED)
