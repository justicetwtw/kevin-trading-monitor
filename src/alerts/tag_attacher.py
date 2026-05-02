"""context 標籤附加器:60 分鐘內若有 Trump Tier 1 → 對特定 alert 加 ⚠Trump_Tier1。

職責邊界(與 final_scorer 的 _build_trump_tags_for_symbol 不同):
- final_scorer 處理「美股訊號 alert」(已注入精細 EVENT_TO_POSITIONS tags)
- tag_attacher 處理「非 final_scorer 路徑的 alert」(部位管理 leaps_pnl/short_delta/hedge_dte、台股、外掛)
- 若 alert 已含 ⚠Trump_Tier1 → 不重複加(等冪)

哪些 kind 加 / 哪些不加:
- 加:leaps_pnl / short_delta / hedge_dte(動作建議要在事件 context 下慎重)
- 不加:drawdown(回撤是長期累積,跟即時事件無關)
- 不加:news / news source 已是 Trump 自己,不需要再 self-tag
- 美股 sell_call / sell_put / leaps_entry signal_type:final_scorer 已處理
  此模組仍可叫,僅補丟失的 ⚠Trump_Tier1(若未被 EVENT_TO_POSITIONS 命中)

來源:layer_trump_classifier_state.json 的 classified list,取最近一筆 tier=='tier1'
的 created_at(若無 created_at,fallback 用 scan_time)。
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from src.storage.state_manager import read_json

TRUMP_STATE_FILE = "layer_trump_classifier_state.json"
TAG_WINDOW_MINUTES = 60
TRUMP_TIER1_TAG = "⚠Trump_Tier1"

# kind 白名單(會加 tag)
_TAG_KINDS = {"leaps_pnl", "short_delta", "hedge_dte"}
# 訊號類型白名單(美股 scorer alert,允許補丟失的 tag)
_TAG_SIGNAL_TYPES = {"sell_call", "sell_put", "leaps_entry"}


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _latest_tier1_at(state: dict) -> Optional[datetime]:
    classified = state.get("classified") if isinstance(state, dict) else None
    if not classified:
        return None
    latest: Optional[datetime] = None
    for item in classified:
        if not isinstance(item, dict) or item.get("tier") != "tier1":
            continue
        dt = _parse_iso(item.get("created_at")) or _parse_iso(item.get("scan_time"))
        if dt is None:
            continue
        if latest is None or dt > latest:
            latest = dt
    return latest


def has_recent_trump_tier1() -> bool:
    """檢查 layer_trump_classifier_state.json 內最近一筆 tier1 是否在 60 分鐘內。"""
    try:
        state = read_json(TRUMP_STATE_FILE, default={})
        latest = _latest_tier1_at(state or {})
        if latest is None:
            return False
        return (datetime.now(timezone.utc) - latest) < timedelta(minutes=TAG_WINDOW_MINUTES)
    except Exception as e:
        logger.warning(f"has_recent_trump_tier1 failed (assume False): {e}")
        return False


def _should_tag(alert: dict) -> bool:
    """依 alert 的 kind / signal_type 決定是否該補 Trump tag。"""
    kind = alert.get("kind")
    if kind in _TAG_KINDS:
        return True
    if kind in {"drawdown", "news"}:
        return False
    sig_type = alert.get("signal_type")
    if sig_type in _TAG_SIGNAL_TYPES:
        return True
    return False


def attach_context_tags(alert: dict) -> dict:
    """為 alert 附加 context tag(等冪、不覆蓋既有 tags 欄位中的其他 tag)。

    執行條件:_should_tag(alert) 為 True AND 60 分鐘內有 Trump Tier 1。
    若 alert 已含 TRUMP_TIER1_TAG → 不重複加。
    """
    if not _should_tag(alert):
        return alert
    if not has_recent_trump_tier1():
        return alert

    tags = list(alert.get("tags") or [])
    if TRUMP_TIER1_TAG not in tags:
        tags.append(TRUMP_TIER1_TAG)
    alert["tags"] = tags
    return alert
