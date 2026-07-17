#!/usr/bin/env python3
"""Audit official agent docs and local workflow contracts without auto-adoption.

Online mode fetches configured official pages, normalizes visible text and compares
SHA-256 fingerprints. Missing/changed baselines require human review. Offline mode
validates local contracts only and is safe for ordinary CI.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / ".github" / "agent-capability-watch.json"
USER_AGENT = "kevin-trading-monitor-agent-capability-watch/1.1"


@dataclass(frozen=True)
class Fetched:
    body: str
    final_url: str
    content_type: str


def normalize_html(value: str) -> str:
    text = re.sub(
        r"<(script|style|svg|noscript|template)\b[^>]*>[\s\S]*?</\1>",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    match = re.search(r"<main\b[^>]*>([\s\S]*?)</main>", text, re.IGNORECASE)
    if match:
        text = match.group(1)
    else:
        match = re.search(
            r"<article\b[^>]*>([\s\S]*?)</article>", text, re.IGNORECASE
        )
        if match:
            text = match.group(1)
    text = re.sub(
        r"<(br|/p|/div|/section|/article|/li|/h[1-6]|/tr)>",
        "\n",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\r", "")
    text = re.sub(r"[\t\f\v ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _host_allowed(host: str, suffixes: list[str]) -> bool:
    host = host.lower()
    return any(
        host == suffix.lower() or host.endswith(f".{suffix.lower()}")
        for suffix in suffixes
    )


def evaluate_source(
    source: dict[str, Any], fetched: Fetched, config: dict[str, Any]
) -> dict[str, Any]:
    normalized = normalize_html(fetched.body)
    observed = sha256(normalized)
    host = (urlparse(fetched.final_url).hostname or "").lower()
    validation = config.get("fetch_validation") or {}
    allowed = list(validation.get("allowed_host_suffixes") or [])
    minimum = int(
        source.get("min_normalized_chars")
        or validation.get("min_normalized_chars")
        or 500
    )
    status = "ok"
    error = None
    if allowed and not _host_allowed(host, allowed):
        status = "unexpected_redirect"
        error = f"final host {host!r} is not allowed"
    elif len(normalized) < minimum:
        status = "suspicious_content"
        error = f"normalized content has {len(normalized)} chars; minimum is {minimum}"
    elif not source.get("approved_sha256"):
        status = "baseline_missing"
    elif source.get("approved_sha256") != observed:
        status = "changed"
    return {
        "id": source.get("id"),
        "url": source.get("url"),
        "final_url": fetched.final_url,
        "content_type": fetched.content_type,
        "normalized_chars": len(normalized),
        "approved_sha256": source.get("approved_sha256") or "",
        "sha256": observed,
        "status": status,
        **({"error": error} if error else {}),
    }


def fetch_text(url: str, timeout: int = 30) -> Fetched:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,text/plain;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(  # noqa: S310 - URLs are allowlisted by config
        request, timeout=timeout
    ) as response:
        body = response.read().decode(
            response.headers.get_content_charset() or "utf-8", errors="replace"
        )
        return Fetched(
            body=body,
            final_url=response.geturl(),
            content_type=response.headers.get("content-type", ""),
        )


def audit_local(
    config: dict[str, Any], root: Path = ROOT
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for relative in config.get("required_local_files") or []:
        path = root / str(relative)
        if not path.exists():
            findings.append(
                {
                    "severity": "BLOCK",
                    "code": "missing_local_file",
                    "path": str(relative),
                }
            )
    agents = (
        (root / "AGENTS.md").read_text(encoding="utf-8")
        if (root / "AGENTS.md").exists()
        else ""
    )
    required_phrases = [
        "current remote HEAD",
        "quota",
        "authenticated delivery path",
        "agent-routing-report:v1",
        "CHANGES_REQUIRED",
        "BLOCKED_DELIVERY",
        "needs-kevin",
        "not_decision_grade",
        "Kevin",
    ]
    for phrase in required_phrases:
        if phrase not in agents:
            findings.append(
                {
                    "severity": "BLOCK",
                    "code": "missing_agent_contract",
                    "path": "AGENTS.md",
                    "detail": phrase,
                }
            )
    if (root / "CLAUDE.md").exists() and len(
        (root / "CLAUDE.md").read_bytes()
    ) > 3000:
        findings.append(
            {
                "severity": "WARN",
                "code": "claude_wrapper_too_large",
                "path": "CLAUDE.md",
            }
        )
    if (root / ".github/workflows/claude_review.yml").exists():
        findings.append(
            {
                "severity": "BLOCK",
                "code": "repo_ai_inference_workflow_present",
                "path": ".github/workflows/claude_review.yml",
            }
        )
    return findings


def days_since(value: str, today: date | None = None) -> int:
    today = today or datetime.now(timezone.utc).date()
    try:
        return (today - date.fromisoformat(value)).days
    except (TypeError, ValueError):
        return 10**9


def build_report(
    config: dict[str, Any], *, offline: bool, root: Path = ROOT
) -> dict[str, Any]:
    local_findings = audit_local(config, root)
    sources: list[dict[str, Any]] = []
    if not offline:
        for source in config.get("sources") or []:
            try:
                sources.append(
                    evaluate_source(source, fetch_text(str(source["url"])), config)
                )
            except Exception as exc:  # failures must be visible, not empty success
                sources.append(
                    {
                        "id": source.get("id"),
                        "url": source.get("url"),
                        "status": "fetch_failed",
                        "error": type(exc).__name__,
                    }
                )
    overdue = days_since(str(config.get("last_verified") or "")) >= int(
        config.get("review_interval_days") or 30
    )
    source_review = any(item.get("status") != "ok" for item in sources)
    blocked = any(item.get("severity") == "BLOCK" for item in local_findings)
    if blocked:
        overall = "blocked"
    elif not offline and (source_review or overdue):
        overall = "needs_review"
    else:
        overall = "ok"
    fingerprint = sha256(
        json.dumps(
            {"local": local_findings, "sources": sources, "overdue": overdue},
            sort_keys=True,
        )
    )
    return {
        "schema_version": 2,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "offline": offline,
        "overall_status": overall,
        "last_verified": config.get("last_verified"),
        "review_overdue": overdue,
        "fingerprint": fingerprint,
        "local_findings": local_findings,
        "sources": sources,
        "policy": "human_review_only_no_auto_baseline_routing_or_adoption",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Agent capability review required",
        "",
        f"- Overall: **{report['overall_status']}**",
        f"- Checked at: `{report['checked_at']}`",
        f"- Last human verification: `{report.get('last_verified')}`",
        f"- Review overdue: `{report.get('review_overdue')}`",
        f"- Fingerprint: `{report['fingerprint']}`",
        "",
        (
            "Watcher 只提出人工審核需求；不自動接受 baseline、修改 routing、"
            "安裝 extension、呼叫模型、merge 或 deploy。"
        ),
        "",
    ]
    if report.get("local_findings"):
        lines += ["## Local contract findings", ""] + [
            f"- `{item}`" for item in report["local_findings"]
        ] + [""]
    if report.get("sources"):
        lines += ["## Official source observations", ""] + [
            (
                f"- **{item.get('id')}**: `{item.get('status')}`; "
                f"sha256 `{item.get('sha256', 'n/a')}`; {item.get('url')}"
            )
            for item in report["sources"]
        ]
    lines += [
        "",
        f"<!-- agent-capability-watch:fingerprint={report['fingerprint']} -->",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--report")
    parser.add_argument("--markdown")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    report = build_report(config, offline=args.offline)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(output, encoding="utf-8")
    else:
        print(output)
    if args.markdown:
        Path(args.markdown).write_text(
            render_markdown(report), encoding="utf-8"
        )
    return 0 if report["overall_status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
