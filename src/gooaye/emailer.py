"""組信 + Gmail SMTP 寄送(stdlib smtplib + email,不裝額外套件)。

設計(§7.4):
- 摘要 → HTML 內文(易讀、Gmail 直接顯示)。
- 逐字稿 → {safe_title}.md 附檔(Gmail 內文 >102KB 會截斷,50 分鐘中文逐字稿易逼近)。
- 認證:GMAIL_SENDER + GMAIL_APP_PASSWORD(16 碼去空格);收件 EMAIL_RECIPIENT(可逗號分隔)。
- SMTP:smtp.gmail.com:465 SSL。
- 失敗 try/except 回 False,不拋例外(紅線 §4)。
"""

from __future__ import annotations

import html
import re
import smtplib
from email.message import EmailMessage

from loguru import logger

from src.config.settings import (
    EMAIL_RECIPIENT,
    GMAIL_APP_PASSWORD,
    GMAIL_SENDER,
)

SMTP_HOST = "smtp.gmail.com"
SMTP_SSL_PORT = 465


def _safe_filename(title: str) -> str:
    """把集名清成安全檔名(去路徑符號 / 控制字元),保留中英數。"""
    name = (title or "transcript").strip()
    # 移除檔名不合法字元
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name)
    name = name.strip(". ")
    if not name:
        name = "transcript"
    # 避免過長檔名
    return name[:120]


def _parse_recipients(raw: str) -> list[str]:
    """EMAIL_RECIPIENT 支援逗號分隔多收件(沿用 TELEGRAM_CHAT_ID 慣例)。"""
    return [r.strip() for r in (raw or "").split(",") if r.strip()]


def markdown_to_html(md: str) -> str:
    """輕量 Markdown → HTML(只處理摘要會用到的語法:## 標題 / - 條列 / **粗體**)。

    不引第三方套件;先 escape 再套標籤,避免 HTML injection。
    """
    lines = (md or "").splitlines()
    html_parts: list[str] = []
    in_list = False

    def _close_list() -> None:
        nonlocal in_list
        if in_list:
            html_parts.append("</ul>")
            in_list = False

    def _inline(text: str) -> str:
        esc = html.escape(text)
        # **粗體**
        esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
        return esc

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            _close_list()
            continue
        if stripped.startswith("### "):
            _close_list()
            html_parts.append(f"<h3>{_inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            _close_list()
            html_parts.append(f"<h2>{_inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            _close_list()
            html_parts.append(f"<h1>{_inline(stripped[2:])}</h1>")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{_inline(stripped[2:])}</li>")
        else:
            _close_list()
            html_parts.append(f"<p>{_inline(stripped)}</p>")

    _close_list()
    return "\n".join(html_parts)


def compose_message(
    title: str,
    summary_md: str,
    transcript_md: str,
    published: str,
    sender: str,
    recipients: list[str],
) -> EmailMessage:
    """組好 EmailMessage(純函式,可單測):HTML 摘要內文 + 純文字 fallback + .md 附檔。"""
    msg = EmailMessage()
    msg["Subject"] = f"[股癌] {title}".strip()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    header = f"# {title}\n\n發布時間:{published}\n\n" if published else f"# {title}\n\n"
    plain_body = header + (summary_md or "")
    html_body = (
        "<html><body style=\"font-family:-apple-system,Segoe UI,Roboto,"
        "'Noto Sans TC',sans-serif;line-height:1.6;\">"
        f"<h1>{html.escape(title)}</h1>"
        + (f"<p style=\"color:#888\">發布時間:{html.escape(published)}</p>"
           if published else "")
        + markdown_to_html(summary_md or "")
        + "<hr><p style=\"color:#888\">完整逐字稿見附檔。</p>"
        "</body></html>"
    )

    # plain-text fallback + HTML alternative
    msg.set_content(plain_body)
    msg.add_alternative(html_body, subtype="html")

    # 逐字稿附檔(.md):傳 str 讓 email 套件以 UTF-8 編(傳 bytes 會掉 charset → 亂碼)
    filename = f"{_safe_filename(title)}.md"
    msg.add_attachment(
        transcript_md or "",
        subtype="markdown",
        filename=filename,
    )
    return msg


def send_digest(
    title: str,
    summary_md: str,
    transcript_md: str,
    published: str = "",
) -> bool:
    """寄送 digest;回傳成功與否。任何錯誤 try/except 回 False(不阻塞 pipeline)。"""
    sender = (GMAIL_SENDER or "").strip()
    app_password = (GMAIL_APP_PASSWORD or "").replace(" ", "")
    recipients = _parse_recipients(EMAIL_RECIPIENT)

    if not sender or not app_password:
        logger.error("GMAIL_SENDER / GMAIL_APP_PASSWORD 未設定,跳過寄信")
        return False
    if not recipients:
        logger.error("EMAIL_RECIPIENT 未設定,跳過寄信")
        return False

    try:
        msg = compose_message(
            title=title,
            summary_md=summary_md,
            transcript_md=transcript_md,
            published=published,
            sender=sender,
            recipients=recipients,
        )
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_SSL_PORT, timeout=60) as server:
            server.login(sender, app_password)
            server.send_message(msg)
        logger.info(f"Gooaye email sent: {title} → {recipients}")
        return True
    except Exception as e:
        logger.error(f"Gooaye email failed: {e}")
        return False
