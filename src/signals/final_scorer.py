"""scan_all_signals 編排器:layer0 + valid_tags + 三 scorer + tag 注入。

簽名:scan_all_signals(mode="intraday" or "eod") -> list[dict]
flat list,按 final_score 降冪排序,final_score >= 50 才收。
mode 只當 metadata 寫進每筆 dict,不過濾(過濾邏輯交 Batch 11 runner)。
"""

from datetime import datetime, timezone, timedelta

from loguru import logger

from src.config.position_mapping import EVENT_TO_POSITIONS
from src.config.thresholds import (
    LEAPS_SPEC, PRIORITY_PUSH_THRESHOLD,
    PUSH_THRESHOLD_GREEN, PUSH_THRESHOLD_YELLOW,
)
from src.config.universe import (
    ALL_TICKERS_SCAN, ALL_US_STOCKS, ETF_LEVERAGED_SINGLE_STOCK,
    SELL_PUT_WHITELIST, get_priority,
)
from src.layers.insider_signals import get_insider_modifier
from src.layers.modifier_aggregator import aggregate_layer0
from src.layers.trump_classifier import scan_and_classify as scan_trump
from src.signals.base_scorer import alert_level_from_score, now_iso
from src.signals.sell_call_scorer import score as score_sell_call
from src.signals.sell_put_scorer import score as score_sell_put
from src.signals.leaps_entry_scorer import score as score_leaps_entry


TRUMP_TAG_TTL_SECONDS = 3600  # 60 分鐘


def _filter_valid_trump_tags(tags: list, now: datetime) -> list:
    """從 scan_and_classify() 的 raw tag list,過濾出 created_at 在 60 分鐘內的。"""
    valid = []
    for t in tags or []:
        ca = t.get("created_at", "")
        if not ca:
            continue
        try:
            t_dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
            if t_dt.tzinfo is None:
                t_dt = t_dt.replace(tzinfo=timezone.utc)
            if (now - t_dt) <= timedelta(seconds=TRUMP_TAG_TTL_SECONDS):
                valid.append(t)
        except Exception as e:
            logger.warning(f"trump tag created_at parse failed ({ca}): {e}")
            continue
    return valid


def _resolve_event_symbols(event_name: str) -> set[str]:
    """從 EVENT_TO_POSITIONS 取受影響 symbols。
    'ALL_SLEEVE_1' / 'ALL_LEAPS' / 'ALL_*' → 視為命中所有(回 None 表 wildcard)。
    """
    spec = EVENT_TO_POSITIONS.get(event_name) or {}
    affected = spec.get("affected_symbols")
    if isinstance(affected, list):
        return set(affected)
    return set()  # wildcard ALL_* 回空 set,由 caller 用 None 判斷


def _is_wildcard_event(event_name: str) -> bool:
    spec = EVENT_TO_POSITIONS.get(event_name) or {}
    affected = spec.get("affected_symbols")
    return isinstance(affected, str) and affected.startswith("ALL_")


def _build_trump_tags_for_symbol(symbol: str, valid_tags: list) -> list[str]:
    """根據 valid_tags 與 EVENT_TO_POSITIONS,為單一 symbol 產生 tag list。"""
    out: list[str] = []
    for t in valid_tags:
        tier = t.get("tier", "")
        events = t.get("events", []) or []

        # tier1 命中影響此 symbol
        for ev in events:
            wildcard = _is_wildcard_event(ev)
            symbols = _resolve_event_symbols(ev)
            hit = wildcard or (symbol in symbols)
            if not hit:
                continue
            if tier == "tier1":
                out.append("⚠Trump_Tier1")
            if ev == "semiconductor_named":
                out.append("⚠Trump_Semi_Risk")
            if ev == "china_tariff":
                out.append("⚠Trump_China_Tariff")
            if ev == "fed_powell_conflict":
                out.append("⚠Trump_Fed")

    # 去重保序
    seen = set()
    deduped = []
    for tag in out:
        if tag not in seen:
            seen.add(tag)
            deduped.append(tag)
    return deduped


def _attach_priority_and_alert(result: dict, current_holdings: list | None,
                                 valid_tags: list, mode: str) -> dict:
    """為單筆 scorer result 附加 priority / alert_level / tags / mode。"""
    sym = result["symbol"]
    priority = get_priority(sym, current_holdings or [])
    push_threshold = PRIORITY_PUSH_THRESHOLD.get(priority)

    result["priority"] = priority
    result["push_threshold"] = push_threshold
    result["mode"] = mode
    result["alert_level"] = alert_level_from_score(
        result["final_score"], push_threshold,
        green=PUSH_THRESHOLD_GREEN, yellow=PUSH_THRESHOLD_YELLOW,
    )
    result["tags"] = _build_trump_tags_for_symbol(sym, valid_tags)
    return result


def scan_all_signals(mode: str = "intraday",
                      current_holdings: list | None = None,
                      context: dict | None = None) -> list[dict]:
    """完整掃描三大訊號,回傳 flat list[dict],按 final_score 降冪。"""
    layer0 = aggregate_layer0() or {}
    mods = (layer0.get("aggregate_modifiers") or {})
    sc_mod = mods.get("sell_call", 0)
    sp_mod = mods.get("sell_put", 0)
    leaps_mod = mods.get("leaps_entry", 0)
    leaps_veto = mods.get("leaps_entry_veto", False)

    try:
        raw_tags = scan_trump() or []
    except Exception as e:
        logger.warning(f"scan_trump failed: {e}")
        raw_tags = []
    valid_tags = _filter_valid_trump_tags(raw_tags, datetime.now(timezone.utc))

    results: list[dict] = []

    # ---- Sell CALL: ALL_TICKERS_SCAN(廣)----
    for sym in ALL_TICKERS_SCAN:
        try:
            r = score_sell_call(sym, layer0_mod=sc_mod, context=context)
            if r["final_score"] >= 50:
                _attach_priority_and_alert(r, current_holdings, valid_tags, mode)
                results.append(r)
        except Exception as e:
            logger.error(f"sell_call({sym}) crashed: {e}")

    # ---- Sell PUT: SELL_PUT_WHITELIST ----
    for sym in SELL_PUT_WHITELIST:
        try:
            try:
                ins = get_insider_modifier(sym) or {}
            except Exception as e:
                logger.warning(f"insider_modifier({sym}) failed: {e}")
                ins = {"modifiers": {"sell_put": 0, "leaps_entry": 0}}
            ins_sp = (ins.get("modifiers") or {}).get("sell_put", 0) or 0

            r = score_sell_put(
                sym, layer0_mod=sp_mod, layer_f_mod=ins_sp, context=context,
            )
            if r["final_score"] >= 50:
                _attach_priority_and_alert(r, current_holdings, valid_tags, mode)
                results.append(r)
        except Exception as e:
            logger.error(f"sell_put({sym}) crashed: {e}")

    # ---- LEAPS Entry: ALL_US_STOCKS - 2x ETF ----
    for sym in ALL_US_STOCKS:
        if sym in ETF_LEVERAGED_SINGLE_STOCK:
            continue
        try:
            try:
                ins = get_insider_modifier(sym) or {}
            except Exception as e:
                logger.warning(f"insider_modifier({sym}) failed: {e}")
                ins = {"modifiers": {"sell_put": 0, "leaps_entry": 0}}
            ins_le = (ins.get("modifiers") or {}).get("leaps_entry", 0) or 0

            r = score_leaps_entry(
                sym, layer0_mod=leaps_mod, layer_f_mod=ins_le,
                layer0_veto=leaps_veto,
                dte_days=LEAPS_SPEC["default_scan_dte"],
                context=context,
            )
            if r["final_score"] >= 50:
                _attach_priority_and_alert(r, current_holdings, valid_tags, mode)
                results.append(r)
        except Exception as e:
            logger.error(f"leaps_entry({sym}) crashed: {e}")

    results.sort(key=lambda x: x.get("final_score", 0), reverse=True)
    return results
