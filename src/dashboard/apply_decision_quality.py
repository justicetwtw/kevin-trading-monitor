"""Apply final decision-grade gates to generated Mission Control output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.dashboard import build_decision_layer as layer
from src.decision.decision_grade import apply_quality_gates
from src.storage.state_manager import read_json


def apply_decision_quality(
    output_dir: Path | str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    output = Path(output_dir)
    allocation = read_json("capital_allocation.json", default={})
    if not isinstance(allocation, dict):
        allocation = {}
    payload = apply_quality_gates(payload, allocation)

    data_path = output / "data" / "decision_engine.json"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    index_path = output / "index.html"
    index = index_path.read_text(encoding="utf-8")
    if layer.START not in index or layer.END not in index:
        raise ValueError("Decision layer markers are missing")
    before, rest = index.split(layer.START, 1)
    _, after = rest.split(layer.END, 1)
    index_path.write_text(
        before + layer.render_section(payload) + after,
        encoding="utf-8",
    )
    return payload
