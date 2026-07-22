"""``state_manager.write_json`` must be atomic and fail-safe.

A concurrent reader (or a run SIGKILLed mid-write) must never observe a
truncated file that reads back as the caller's empty default. A failed write
must leave the previous file intact and drop no partial scratch file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.storage import state_manager


class _NotSerializable:
    pass


def test_write_json_is_atomic_and_valid(monkeypatch, tmp_path):
    monkeypatch.setattr(state_manager, "DATA_STORE_DIR", Path(tmp_path))
    assert state_manager.write_json("h.json", {"a": 1, "b": "中文"}) is True
    on_disk = json.loads((tmp_path / "h.json").read_text(encoding="utf-8"))
    assert on_disk == {"a": 1, "b": "中文"}
    # No scratch .tmp file survives a successful write.
    assert [n for n in os.listdir(tmp_path) if n.endswith(".tmp")] == []


def test_write_json_failure_cleans_temp_and_returns_false(monkeypatch, tmp_path):
    monkeypatch.setattr(state_manager, "DATA_STORE_DIR", Path(tmp_path))
    # A non-serializable payload raises inside json.dump; the temp file must be
    # removed and the call must report failure — never a partial target file.
    assert state_manager.write_json("bad.json", {"x": _NotSerializable()}) is False
    assert not (tmp_path / "bad.json").exists()
    assert [n for n in os.listdir(tmp_path) if n.endswith(".tmp")] == []


def test_failed_overwrite_preserves_previous_file(monkeypatch, tmp_path):
    monkeypatch.setattr(state_manager, "DATA_STORE_DIR", Path(tmp_path))
    state_manager.write_json("s.json", {"kept": True})
    # The overwrite fails after the good file exists; os.replace never runs, so
    # the reader still sees the prior content, not the empty default.
    assert state_manager.write_json("s.json", {"x": _NotSerializable()}) is False
    assert state_manager.read_json("s.json", default={}) == {"kept": True}
