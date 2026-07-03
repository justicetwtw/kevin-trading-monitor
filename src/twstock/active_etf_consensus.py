"""主動式 ETF 持股抓取 + 跨經理人共識(獨立 digest 功能,純加法)。

職責:
  1. 每日抓全清單主動 ETF 持股 → 存 90 天快照(自有狀態檔,不動既有台股 TG 流程)。
  2. 純函式:從快照算「跨經理人共識」——每標的被幾位經理人同向加/減碼、淨權重變化。

資料源(measure-first):
  - 台股:重用 src.data.twstock_active_etf.fetch_etf_holdings(TWSE OpenAPI),不重寫。
  - 海外:待 scripts/probe_active_etf_sources.py 在開放網路實證真實格式後才接;
    在此之前 _fetch_overseas 安全回 [](不猜格式、不假造,踩雷筆記 §1/§2)。

共識/排行為純函式(吃 history dict),全程可 mock 單測。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from loguru import logger

from src.config import active_etf_config as cfg
from src.config.settings import TIMEZONE_TW_MARKET
from src.storage.state_manager import read_json, write_json


# ============================================================
# 抓取 + 快照儲存
# ============================================================

def _fetch_tw(fund_symbol: str) -> list[dict]:
    """台股持股:重用既有 TWSE OpenAPI 抓取(回 [{symbol,name,weight_pct,shares}, ...])。"""
    try:
        from src.data.twstock_active_etf import fetch_etf_holdings
        return fetch_etf_holdings(fund_symbol) or []
    except Exception as e:
        logger.warning(f"_fetch_tw({fund_symbol}) failed: {e}")
        return []


def _fetch_overseas(fund: dict) -> list[dict]:
    """海外持股:資料源待探針實證,先安全回 []。

    TODO(探針確認後實作):依 scripts/probe_active_etf_sources.py 輸出的真實格式,
    對接 TWSE OpenAPI(若涵蓋海外成分)或 per-投信 PCF / 公會 / 第三方,
    回 [{symbol,name,weight_pct,shares}, ...](美股代號)。
    """
    logger.info(
        f"_fetch_overseas({fund.get('symbol')}): 海外資料源待探針實證,暫回空"
    )
    return []


def fetch_fund_holdings(fund: dict) -> list[dict]:
    """抓單一基金持股,逐持股標 market,依 symbol 去重。失敗回 []。"""
    market = fund.get("market", "tw")
    raw: list[dict] = []
    if market in ("tw", "mixed"):
        raw += _fetch_tw(fund["symbol"])
    if market in ("overseas", "mixed"):
        raw += _fetch_overseas(fund)

    out: dict[str, dict] = {}
    for h in raw:
        sym = str(h.get("symbol", "")).strip()
        if not sym:
            continue
        out[sym] = {
            "symbol": sym,
            "name": h.get("name", ""),
            "weight_pct": float(h.get("weight_pct", 0) or 0),
            "shares": int(float(h.get("shares", 0) or 0)),
            "market": cfg.classify_holding_market(sym),
        }
    return list(out.values())


def update_holdings(funds: list[dict] | None = None) -> dict:
    """抓全清單持股 → 當日快照寫入狀態檔,保留最近 N 天。回傳更新後 history。

    單檔失敗只跳過該檔(容錯紅線),不炸整個 run。
    """
    funds = funds if funds is not None else cfg.ACTIVE_ETF_FUNDS
    today = datetime.now(TIMEZONE_TW_MARKET).strftime("%Y-%m-%d")
    history = read_json(cfg.DIGEST_HOLDINGS_FILE, default={})
    if not isinstance(history, dict):
        history = {}

    for fund in funds:
        sym = fund["symbol"]
        try:
            holdings = fetch_fund_holdings(fund)
        except Exception as e:
            logger.warning(f"update_holdings skip {sym}: {e}")
            continue
        if not holdings:
            continue
        history.setdefault(sym, {})[today] = holdings
        # 保留最近 N 天
        if len(history[sym]) > cfg.HOLDINGS_HISTORY_DAYS:
            for d in sorted(history[sym].keys())[:-cfg.HOLDINGS_HISTORY_DAYS]:
                del history[sym][d]

    write_json(cfg.DIGEST_HOLDINGS_FILE, history)
    logger.info(f"active_etf digest holdings updated: {len(history)} funds")
    return history


# ============================================================
# 共識計算(純函式)
# ============================================================

def _pick_baseline_date(dates: list[str], new_date: str, lookback_days: int) -> str | None:
    """挑出與最新日相距 ≥ lookback_days 的最近一個基準日;不足則回 None。"""
    try:
        new_dt = datetime.strptime(new_date, "%Y-%m-%d")
    except ValueError:
        return None
    cutoff = (new_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    older = [d for d in dates if d <= cutoff]
    return older[-1] if older else None


def fund_holding_changes(
    fund_history: dict,
    lookback_days: int,
    min_delta_pp: float,
) -> dict[str, dict]:
    """單一基金:最新日 vs lookback 基準日的逐持股權重變化(|Δ| ≥ 門檻)。純函式。

    fund_history: {"YYYY-MM-DD": [{symbol,name,weight_pct,market}, ...]}
    回 {symbol: {old, new, delta_pp, name, market}}。
    """
    dates = sorted(fund_history.keys())
    if len(dates) < 2:
        return {}
    new_date = dates[-1]
    base_date = _pick_baseline_date(dates, new_date, lookback_days)
    if not base_date or base_date == new_date:
        return {}

    old = {h["symbol"]: h for h in fund_history[base_date]}
    new = {h["symbol"]: h for h in fund_history[new_date]}

    changes: dict[str, dict] = {}
    for sym in set(old) | set(new):
        old_w = float(old.get(sym, {}).get("weight_pct", 0) or 0)
        new_w = float(new.get(sym, {}).get("weight_pct", 0) or 0)
        delta = new_w - old_w
        if abs(delta) >= min_delta_pp:
            meta = new.get(sym) or old.get(sym) or {}
            changes[sym] = {
                "old": old_w,
                "new": new_w,
                "delta_pp": delta,
                "name": meta.get("name", ""),
                "market": meta.get("market", cfg.classify_holding_market(sym)),
            }
    return changes


def build_consensus(
    history: dict,
    funds: list[dict] | None = None,
    lookback_days: int | None = None,
    min_delta_pp: float | None = None,
) -> dict[str, dict]:
    """跨基金聚合:每標的被幾位經理人同向加/減碼 + 淨權重變化。純函式。

    回 {symbol: {name, market, n_increased, n_decreased, net_delta_pp,
                 funds_increased: [{fund,name,delta_pp}], funds_decreased: [...]}}
    """
    funds = funds if funds is not None else cfg.ACTIVE_ETF_FUNDS
    lookback_days = lookback_days if lookback_days is not None else cfg.SHORT_WINDOW_DAYS
    min_delta_pp = min_delta_pp if min_delta_pp is not None else cfg.MIN_WEIGHT_DELTA_PP

    agg: dict[str, dict] = defaultdict(
        lambda: {
            "name": "",
            "market": "unknown",
            "n_increased": 0,
            "n_decreased": 0,
            "net_delta_pp": 0.0,
            "funds_increased": [],
            "funds_decreased": [],
        }
    )

    fund_meta = {f["symbol"]: f for f in funds}
    for fund_symbol, fhist in history.items():
        if fund_symbol not in fund_meta:
            continue  # 只看設定清單內的基金
        changes = fund_holding_changes(fhist, lookback_days, min_delta_pp)
        fname = fund_meta[fund_symbol].get("name", fund_symbol)
        for sym, ch in changes.items():
            entry = agg[sym]
            entry["name"] = entry["name"] or ch["name"]
            entry["market"] = ch["market"]
            entry["net_delta_pp"] += ch["delta_pp"]
            rec = {"fund": fund_symbol, "fund_name": fname, "delta_pp": ch["delta_pp"]}
            if ch["delta_pp"] > 0:
                entry["n_increased"] += 1
                entry["funds_increased"].append(rec)
            else:
                entry["n_decreased"] += 1
                entry["funds_decreased"].append(rec)

    return dict(agg)


def rank_consensus(consensus: dict, top_n: int | None = None) -> dict:
    """排行:加碼榜(共識買)/ 減碼榜(共識賣),依 (同向經理人數, |淨權重變化|) 排序。

    回 {"top_buys": [...], "top_sells": [...]},各 item 是 consensus value + symbol。
    """
    top_n = top_n if top_n is not None else cfg.DIGEST_TOP_N
    items = [{"symbol": s, **v} for s, v in consensus.items()]

    buys = [i for i in items if i["n_increased"] > 0]
    sells = [i for i in items if i["n_decreased"] > 0]
    buys.sort(key=lambda i: (i["n_increased"], i["net_delta_pp"]), reverse=True)
    sells.sort(key=lambda i: (i["n_decreased"], -i["net_delta_pp"]), reverse=True)

    return {"top_buys": buys[:top_n], "top_sells": sells[:top_n]}
