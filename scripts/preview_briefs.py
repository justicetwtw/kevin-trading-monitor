"""Preview all market briefs with canonical Asia/Taipei market-time copy."""

import sys
from pathlib import Path

from src.alerts.brief_generator import VALID_BRIEF_TYPES, BriefGenerator
from src.config.market_clock import normalize_market_brief_copy


if __name__ == "__main__":
    out_path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path("brief_previews.txt")
    )
    chunks = []
    for brief_type in VALID_BRIEF_TYPES:
        chunks.append("=" * 60)
        chunks.append(f"  brief_type = {brief_type}")
        chunks.append("=" * 60)
        try:
            legacy = BriefGenerator(brief_type).generate()
            chunks.append(
                normalize_market_brief_copy(legacy, brief_type)
            )
        except Exception as exc:
            chunks.append(f"[FAIL] {brief_type}: {exc}")
        chunks.append("")
    out_path.write_text("\n".join(chunks), encoding="utf-8")
    print(f"Written to {out_path} ({len(VALID_BRIEF_TYPES)} briefs)")
