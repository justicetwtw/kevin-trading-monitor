"""Focus Trading Engine v1 feature flags(shadow / display-only rollout)。

Rollout contract(docs/focus_trading_engine_v1.md §13):
- 預設 OFF;啟用需要明確的環境變數 opt-in。
- v1 只有 shadow / display_only 兩種模式,沒有 alert 模式。
- 關閉 flag 後回到既有 Decision Engine,不得破壞原 state files。
"""

from __future__ import annotations

import os

FOCUS_ENGINE_MODES = ("shadow", "display_only")

#: 下降 50DMA 下方的逆勢價值加碼只允許 shadow/backtest 研究;
#: production 永遠 disabled,且刻意不提供環境變數覆寫。
CONTRARIAN_ADD_BELOW_DECLINING_50DMA_PRODUCTION = False


def focus_engine_enabled() -> bool:
    """讀取 feature flag;任何非 "1" 的值都視為關閉(fail closed)。"""
    return os.getenv("FOCUS_ENGINE_ENABLED", "0") == "1"


def focus_engine_mode() -> str:
    """回傳 rollout 模式;未知值一律退回最保守的 shadow。"""
    mode = os.getenv("FOCUS_ENGINE_MODE", "shadow").strip().lower()
    return mode if mode in FOCUS_ENGINE_MODES else "shadow"
