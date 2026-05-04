"""預覽 6 種 brief 真實輸出(含 2 種 DST 變體)→ 寫入 /tmp/brief_previews.txt。"""

import sys
from pathlib import Path

from src.alerts.brief_generator import BriefGenerator

TYPES = (
    "us_eod",
    "tw_eod",
    "us_premarket",
    "us_midday",
    "us_premarket_to_intraday",
    "us_midday_to_afterhours",
)

if __name__ == "__main__":
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("brief_previews.txt")
    chunks = []
    for t in TYPES:
        chunks.append("=" * 60)
        chunks.append(f"  brief_type = {t}")
        chunks.append("=" * 60)
        try:
            chunks.append(BriefGenerator(t).generate())
        except Exception as e:
            chunks.append(f"[FAIL] {t}: {e}")
        chunks.append("")
    out_path.write_text("\n".join(chunks), encoding="utf-8")
    print(f"Written to {out_path}")
