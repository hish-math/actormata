"""
state/store.py — JSON-file persistence for entity state.

JsonStore is the v1 default.  The interface is minimal by design:
load(), save(), all_ids() — so a future SQLiteStore or PostgresStore can be
dropped in without touching the engine or agents.

Thread / asyncio safety: an asyncio.Lock guards file reads and writes.
Since EntityActor already serialises all mutations for a given entity,
the lock here is mainly to protect cross-entity reads in all_ids() and
the full-file write in save().
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any


_DEFAULT_ENTITY_TEMPLATE: dict[str, Any] = {
    "stage": "",   # filled in by store.load() using schema.initial_stage
    "history": [],
    "override": None,
    "metadata": {},
}


class JsonStore:
    """Reads and writes all entity state to a single JSON file.

    Args:
        path:          Path to the state file.  Created if it does not exist.
        initial_stage: Stage assigned to newly created entities.
    """

    def __init__(self, path: str | Path, initial_stage: str = "intake") -> None:
        self._path = Path(path)
        self._initial_stage = initial_stage
        self._lock = asyncio.Lock()
        # Ensure the file exists with an empty entities dict
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._write_raw({"entities": {}})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, entity_id: str) -> dict[str, Any]:
        """Return the entity for *entity_id*, creating a default if absent."""
        data = self._read_raw()
        if entity_id not in data["entities"]:
            entity = self._make_default(entity_id)
            data["entities"][entity_id] = entity
            self._write_raw(data)
        return data["entities"][entity_id]

    def save(self, entity: dict[str, Any]) -> None:
        """Persist *entity* back to the JSON file.

        The entity must have an ``"id"`` key.
        """
        data = self._read_raw()
        data["entities"][entity["id"]] = entity
        self._write_raw(data)

    def all_ids(self) -> list[str]:
        """Return all entity ids currently in the store."""
        return list(self._read_raw()["entities"].keys())

    def delete(self, entity_id: str) -> None:
        """Remove an entity from the store."""
        data = self._read_raw()
        data["entities"].pop(entity_id, None)
        self._write_raw(data)

    # ------------------------------------------------------------------
    # Internal I/O
    # ------------------------------------------------------------------

    def _read_raw(self) -> dict[str, Any]:
        with self._path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write_raw(self, data: dict[str, Any]) -> None:
        # Write to a temp file then rename for atomicity
        tmp = self._path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self._path)

    def _make_default(self, entity_id: str) -> dict[str, Any]:
        entity = dict(_DEFAULT_ENTITY_TEMPLATE)
        entity["id"] = entity_id
        entity["stage"] = self._initial_stage
        entity["history"] = []
        entity["metadata"] = {}
        entity["override"] = None
        return entity
