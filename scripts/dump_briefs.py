"""本機驗證:跑四種 brief, 不送 Telegram, 印 HTML 內容。"""

import io
import sys

# Windows console default cp950/gbk - 強制 utf-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.alerts.brief_generator import BriefGenerator, VALID_BRIEF_TYPES  # noqa: E402


def main():
    types = sys.argv[1:] or list(VALID_BRIEF_TYPES)
    for t in types:
        print("=" * 70)
        print(f"BRIEF_TYPE = {t}")
        print("=" * 70)
        try:
            msg = BriefGenerator(t).generate()
            print(msg)
        except Exception as e:
            print(f"[CRASHED] {e}")
        print()


if __name__ == "__main__":
    main()
