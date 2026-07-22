"""Fail-closed, identity-bound, non-terminal-protecting rolling archive.

The archive is the authoritative payload store for retry/pending recovery, so it
must never mis-identify a payload (key == id), never silently drop a still-owed
post's payload when pruning, and fail closed (not green) on overflow of protected
rows.
"""

from __future__ import annotations

import json

import pytest

from src.data import trump_truth
from src.data.trump_truth import (
    ArchiveError,
    archive_posts,
    get_archived_posts,
    validate_archive_content,
)
from src.storage import state_manager


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(trump_truth, "DATA_STORE_DIR", tmp_path)
    monkeypatch.setattr(state_manager, "DATA_STORE_DIR", tmp_path)


def _post(post_id, *, created="2026-07-21T00:00:00+00:00"):
    return {"id": post_id, "created_at": created, "text": f"post {post_id}"}


# --- key == id binding ------------------------------------------------------


def test_validate_archive_rejects_key_id_mismatch():
    with pytest.raises(ArchiveError):
        validate_archive_content({"X": {"id": "Y"}})
    with pytest.raises(ArchiveError):
        validate_archive_content({"X": 123})  # not an object
    # Correct binding passes.
    assert validate_archive_content({"X": {"id": "X"}}) == {"X": {"id": "X"}}


def test_read_archive_fails_closed_on_key_id_mismatch(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    (tmp_path / trump_truth.ARCHIVE_FILE).write_text(
        json.dumps({"X": {"id": "Y"}}), encoding="utf-8"
    )
    with pytest.raises(ArchiveError):
        get_archived_posts(["X"])


def test_archive_roundtrip_and_lookup(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    archive_posts([_post("a"), _post("b")])
    found = get_archived_posts(["a", "b", "missing"])
    assert set(found) == {"a", "b"}
    assert found["a"]["id"] == "a"


# --- protected, state-aware pruning -----------------------------------------


def test_prune_protects_non_terminal_ids(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    monkeypatch.setattr(trump_truth, "MAX_ARCHIVE", 3)
    # 'old_protected' is the oldest row but is referenced by a non-terminal
    # ledger record, so it must survive while newer unprotected rows are evicted.
    archive_posts([_post("old_protected", created="2020-01-01T00:00:00+00:00")])
    archive_posts(
        [_post(f"n{i}", created=f"2026-07-2{i}T00:00:00+00:00") for i in range(5)],
        protected_ids={"old_protected"},
    )
    archive = get_archived_posts(
        ["old_protected", "n0", "n1", "n2", "n3", "n4"]
    )
    assert "old_protected" in archive  # protected payload never dropped
    assert len(archive) <= 3


def test_overflow_of_protected_rows_fails_closed(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    monkeypatch.setattr(trump_truth, "MAX_ARCHIVE", 2)
    protected = {"a", "b", "c"}
    # Three protected rows but a bound of 2: rather than delete a still-owed
    # payload, archiving fails closed with a loud overflow signal.
    with pytest.raises(ArchiveError):
        archive_posts(
            [_post("a"), _post("b"), _post("c")], protected_ids=protected
        )
    # And every protected payload was still persisted (evidence not deleted).
    assert set(get_archived_posts(["a", "b", "c"])) == {"a", "b", "c"}
