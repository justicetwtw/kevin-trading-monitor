"""GitHub Actions 進入點:產生靜態 dashboard(HTML + JSON)。

純讀 data_store/,不打外部 API、不需要 secret、不推 Telegram。
輸出:public/dashboard/index.html + public/dashboard/data/*.json
"""

from loguru import logger

from src.dashboard.build_dashboard import DEFAULT_OUTPUT, build_all


def main() -> None:
    payloads = build_all(DEFAULT_OUTPUT)
    logger.info(
        "dashboard build done: "
        + ", ".join(f"{k}" for k in payloads)
        + f" -> {DEFAULT_OUTPUT}"
    )


if __name__ == "__main__":
    main()
