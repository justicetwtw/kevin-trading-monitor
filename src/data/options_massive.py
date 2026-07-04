"""Massive(前 Polygon.io)options provider — Phase 2 stub,尚未實作。

第二候選:options chain snapshot / trades / quotes / greeks / IV / OI,
偏 intraday 工程整合,適合未來的盤中 flow dashboard。
評估細節見 docs/data_api_evaluation.md。

Secret 紀律:實作前不要在 GitHub 新增 POLYGON_API_KEY(沿用
docs/codex_environment.md 預留命名);key 只透過 GitHub Actions secrets 注入。
"""

from src.data.options_provider import OptionsProvider

_NOT_IMPLEMENTED = (
    "Massive/Polygon provider 尚未實作(Phase 2)。實作前請勿新增 "
    "POLYGON_API_KEY secret;見 docs/data_api_evaluation.md。"
)


class MassiveOptionsProvider(OptionsProvider):
    provider_name = "massive"
    SECRET_NAME = "POLYGON_API_KEY"

    def get_iv_metrics(self, symbol: str) -> dict:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def get_options_snapshot(self, symbol: str) -> dict:
        raise NotImplementedError(_NOT_IMPLEMENTED)
