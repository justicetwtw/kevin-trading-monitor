"""預覽 6 種 brief 真實輸出 → 寫入 brief_previews.txt。

Sprint 2.5.9: 改成 6 種(us_eod / tw_open / tw_close / us_premarket / us_open / us_midday)。
"""

import sys
from pathlib import Path

from src.alerts.brief_generator import VALID_BRIEF_TYPES, BriefGenerator

if __name__ == "__main__":
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("brief_previews.txt")
    chunks = []
    for t in VALID_BRIEF_TYPES:
        chunks.append("=" * 60)
        chunks.append(f"  brief_type = {t}")
        chunks.append("=" * 60)
        try:
            chunks.append(BriefGenerator(t).generate())
        except Exception as e:
            chunks.append(f"[FAIL] {t}: {e}")
        chunks.append("")
    out_path.write_text("\n".join(chunks), encoding="utf-8")
    print(f"Written to {out_path} ({len(VALID_BRIEF_TYPES)} briefs)")
