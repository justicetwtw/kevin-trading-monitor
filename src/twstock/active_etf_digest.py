"""主動式 ETF 經理人共識 — 每日盤後 email 趨勢摘要(渲染 + 寄送 + 串接)。

投遞:獨立 email(重用 gooaye 的 markdown_to_html + 同一組 Gmail secrets),
不走交易 TG(保持訊號流乾淨)。
"""

from __future__ import annotations

import smtplib
from datetime import datetime
from email.message import EmailMessage

from loguru import logger

from src.config import active_etf_config as cfg
from src.config.settings import (
    EMAIL_RECIPIENT,
    GMAIL_APP_PASSWORD,
    GMAIL_SENDER,
    TIMEZONE_TW_MARKET,
)
from src.gooaye.emailer import markdown_to_html  # 純函式,重用不重寫
from src.storage.state_manager import read_json
from src.twstock.active_etf_consensus import (
    build_consensus,
    rank_consensus,
    update_holdings,
)

SMTP_HOST = "smtp.gmail.com"
SMTP_SSL_PORT = 465


# ============================================================
# 渲染
# ============================================================

def _fmt_line(item: dict, direction: str) -> str:
    """單一標的一行:代號 名稱 — N 位同向 (淨 ±X.XX pp):基金清單。"""
    if direction == "buy":
        n = item["n_increased"]
        funds = item["funds_increased"]
        verb = "加碼"
    else:
        n = item["n_decreased"]
        funds = item["funds_decreased"]
        verb = "減碼"
    fund_names = "、".join(f["fund_name"] for f in funds)
    name = item.get("name") or ""
    return (
        f"- **{item['symbol']}** {name} — {n} 位經理人{verb} "
        f"(淨 {item['net_delta_pp']:+.2f} pp):{fund_names}"
    )


def _section(title: str, items: list[dict], direction: str) -> list[str]:
    if not items:
        return []
    return [f"## {title}", *[_fmt_line(i, direction) for i in items], ""]


def _consensus_highlights(consensus: dict, min_funds: int) -> dict:
    """挑出『被 ≥ min_funds 位經理人同向』的重點標的。"""
    buys, sells = [], []
    for sym, v in consensus.items():
        item = {"symbol": sym, **v}
        if v["n_increased"] >= min_funds:
            buys.append(item)
        if v["n_decreased"] >= min_funds:
            sells.append(item)
    buys.sort(key=lambda i: (i["n_increased"], i["net_delta_pp"]), reverse=True)
    sells.sort(key=lambda i: (i["n_decreased"], -i["net_delta_pp"]), reverse=True)
    return {"buys": buys, "sells": sells}


def render_digest_markdown(
    consensus_short: dict,
    consensus_long: dict,
    date_str: str,
) -> str:
    """組每日摘要 Markdown。空資料時回空字串(由 run() 判斷不寄)。"""
    rank_short = rank_consensus(consensus_short)
    by_market = {"tw": {"buy": [], "sell": []}, "overseas": {"buy": [], "sell": []}}
    for item in rank_short["top_buys"]:
        by_market.get(item["market"], by_market["tw"])["buy"].append(item)
    for item in rank_short["top_sells"]:
        by_market.get(item["market"], by_market["tw"])["sell"].append(item)

    hl_short = _consensus_highlights(consensus_short, cfg.CONSENSUS_MIN_FUNDS)
    hl_long = _consensus_highlights(consensus_long, cfg.CONSENSUS_MIN_FUNDS)

    if not (rank_short["top_buys"] or rank_short["top_sells"]):
        return ""

    lines: list[str] = [
        f"# 主動 ETF 經理人共識 — {date_str}",
        "",
        f"涵蓋 {len(cfg.ACTIVE_ETF_FUNDS)} 檔主動式 ETF(台股 + 海外),"
        f"短窗 {cfg.SHORT_WINDOW_DAYS} 日 / 長窗 {cfg.LONG_WINDOW_DAYS} 日。",
        "",
    ]

    # 重點共識(被多位經理人同向)
    if hl_short["buys"] or hl_short["sells"]:
        lines.append(f"## 🔥 短期共識（≥{cfg.CONSENSUS_MIN_FUNDS} 位經理人，{cfg.SHORT_WINDOW_DAYS} 日）")
        lines += [_fmt_line(i, "buy") for i in hl_short["buys"]]
        lines += [_fmt_line(i, "sell") for i in hl_short["sells"]]
        lines.append("")
    if hl_long["buys"] or hl_long["sells"]:
        lines.append(f"## 📈 中期共識（≥{cfg.CONSENSUS_MIN_FUNDS} 位經理人，{cfg.LONG_WINDOW_DAYS} 日）")
        lines += [_fmt_line(i, "buy") for i in hl_long["buys"]]
        lines += [_fmt_line(i, "sell") for i in hl_long["sells"]]
        lines.append("")

    # 台股 / 海外 加減碼榜
    lines += _section("🇹🇼 台股加碼榜", by_market["tw"]["buy"], "buy")
    lines += _section("🇹🇼 台股減碼榜", by_market["tw"]["sell"], "sell")
    lines += _section("🌎 海外加碼榜", by_market["overseas"]["buy"], "buy")
    lines += _section("🌎 海外減碼榜", by_market["overseas"]["sell"], "sell")

    lines.append("---")
    lines.append("_資料來源:各主動式 ETF 每日持股公告(法定揭露)。權重變化為跨基金加總,僅供參考。_")
    return "\n".join(lines)


# ============================================================
# 寄送
# ============================================================

def _recipients() -> list[str]:
    return [r.strip() for r in (EMAIL_RECIPIENT or "").split(",") if r.strip()]


def send_digest_email(markdown_body: str, date_str: str) -> bool:
    """寄出 digest;設定缺失或失敗回 False(不拋例外)。"""
    sender = (GMAIL_SENDER or "").strip()
    app_password = (GMAIL_APP_PASSWORD or "").replace(" ", "")
    recipients = _recipients()
    if not sender or not app_password:
        logger.error("GMAIL_SENDER / GMAIL_APP_PASSWORD 未設定,跳過寄信")
        return False
    if not recipients:
        logger.error("EMAIL_RECIPIENT 未設定,跳過寄信")
        return False

    try:
        msg = EmailMessage()
        msg["Subject"] = f"{cfg.EMAIL_SUBJECT_PREFIX} {date_str} 經理人共識"
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)
        msg.set_content(markdown_body)
        msg.add_alternative(
            "<html><body style=\"font-family:-apple-system,Segoe UI,'Noto Sans TC',"
            "sans-serif;line-height:1.6;\">" + markdown_to_html(markdown_body)
            + "</body></html>",
            subtype="html",
        )
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_SSL_PORT, timeout=60) as server:
            server.login(sender, app_password)
            server.send_message(msg)
        logger.info(f"active_etf digest email sent → {recipients}")
        return True
    except Exception as e:
        logger.error(f"active_etf digest email failed: {e}")
        return False


# ============================================================
# 串接
# ============================================================

def run() -> int:
    """跑完整 digest:抓持股 → 建共識 → 渲染 → 寄信。回 0 成功/no-op,1 有錯。"""
    logger.info("=== run_active_etf_digest start ===")
    try:
        update_holdings()
        history = read_json(cfg.DIGEST_HOLDINGS_FILE, default={})
        if not isinstance(history, dict) or not history:
            logger.warning("active_etf: 無持股快照(no-op,可能首跑或資料源待實證)")
            return 0

        consensus_short = build_consensus(history, lookback_days=cfg.SHORT_WINDOW_DAYS)
        consensus_long = build_consensus(history, lookback_days=cfg.LONG_WINDOW_DAYS)

        date_str = datetime.now(TIMEZONE_TW_MARKET).strftime("%Y-%m-%d")
        markdown = render_digest_markdown(consensus_short, consensus_long, date_str)
        if not markdown:
            logger.info("active_etf: 今日無達門檻的持股變化(no-op,不寄信)")
            return 0

        ok = send_digest_email(markdown, date_str)
        logger.info(f"=== run_active_etf_digest done (sent={ok}) ===")
        return 0 if ok else 1
    except Exception as e:
        logger.error(f"run_active_etf_digest crashed: {e}")
        return 1
