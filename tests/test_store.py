"""
tests/test_store.py — unit tests for state.store.JsonStore
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from state.store import JsonStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_store(tmp_path):
    """A fresh JsonStore backed by a temp file."""
    return JsonStore(tmp_path / "state.json", initial_stage="intake")


# ---------------------------------------------------------------------------
# Creation and defaults
# ---------------------------------------------------------------------------


def test_file_created_on_init(tmp_path):
    path = tmp_path / "state.json"
    assert not path.exists()
    JsonStore(path)
    assert path.exists()


def test_load_missing_entity_returns_default(tmp_store):
    entity = tmp_store.load("proj-001")
    assert entity["id"] == "proj-001"
    assert entity["stage"] == "intake"
    assert entity["history"] == []
    assert entity["override"] is None


def test_load_missing_entity_persists_to_file(tmp_store):
    tmp_store.load("proj-002")
    # Re-read raw file to confirm persistence
    data = json.loads(tmp_store._path.read_text())
    assert "proj-002" in data["entities"]


# ---------------------------------------------------------------------------
# Save and round-trip
# ---------------------------------------------------------------------------


def test_save_and_reload(tmp_store):
    entity = tmp_store.load("proj-003")
    entity["stage"] = "assessment"
    entity["history"].append({"from": "intake", "to": "assessment", "reasoning": "test"})
    tmp_store.save(entity)

    reloaded = tmp_store.load("proj-003")
    assert reloaded["stage"] == "assessment"
    assert len(reloaded["history"]) == 1


def test_save_does_not_corrupt_other_entities(tmp_store):
    e1 = tmp_store.load("a")
    e2 = tmp_store.load("b")

    e1["stage"] = "done"
    tmp_store.save(e1)

    # e2 should be unchanged
    e2_reloaded = tmp_store.load("b")
    assert e2_reloaded["stage"] == "intake"


# ---------------------------------------------------------------------------
# all_ids
# ---------------------------------------------------------------------------


def test_all_ids_empty(tmp_store):
    assert tmp_store.all_ids() == []


def test_all_ids_after_load(tmp_store):
    tmp_store.load("x")
    tmp_store.load("y")
    ids = tmp_store.all_ids()
    assert set(ids) == {"x", "y"}


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_removes_entity(tmp_store):
    tmp_store.load("to-delete")
    tmp_store.delete("to-delete")
    assert "to-delete" not in tmp_store.all_ids()


def test_delete_nonexistent_is_safe(tmp_store):
    # Should not raise
    tmp_store.delete("ghost")


# ---------------------------------------------------------------------------
# Atomicity (temp-file write)
# ---------------------------------------------------------------------------


def test_write_is_atomic(tmp_store, tmp_path):
    """After save, no .tmp file should remain."""
    entity = tmp_store.load("atomic-test")
    tmp_store.save(entity)
    tmp_file = tmp_path / "state.tmp"
    assert not tmp_file.exists()
