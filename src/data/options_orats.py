"""ORATS options provider — Phase 2 stub,尚未實作。

ORATS 是付費 options 資料的優先候選(IV rank / skew / historical options
data / near-EOD history / proprietary indicators),適合 EOD / swing / LEAPS
決策節奏。評估細節見 docs/data_api_evaluation.md。

Secret 紀律:實作前不要在 GitHub 新增 ORATS_API_KEY;實作後 key 只透過
GitHub Actions secrets 注入,不得寫入 repo 或 .env。
"""

from src.data.options_provider import OptionsProvider

_NOT_IMPLEMENTED = (
    "ORATS provider 尚未實作(Phase 2)。實作前請勿新增 ORATS_API_KEY secret;"
    "見 docs/data_api_evaluation.md。"
)


class ORATSOptionsProvider(OptionsProvider):
    provider_name = "orats"
    SECRET_NAME = "ORATS_API_KEY"

    def get_iv_metrics(self, symbol: str) -> dict:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def get_options_snapshot(self, symbol: str) -> dict:
        raise NotImplementedError(_NOT_IMPLEMENTED)
