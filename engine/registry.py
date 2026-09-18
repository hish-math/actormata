"""
engine/registry.py — lazy actor registry.

Spawns and caches one EntityActor per entity id.  All access goes through
Router, never directly from external callers.
"""

from __future__ import annotations

from typing import Any

from engine.actor import EntityActor
from engine.fsm import FSMValidator


class ActorRegistry:
    """Spawns EntityActor instances on first access and caches them in memory.

    Args:
        schema:        Parsed schema dict (from schemas/*.json).
        agent_adapter: Adapter passed through to each actor.
        store:         ``state.store.JsonStore`` (or any compatible store).
    """

    def __init__(
        self,
        schema: dict[str, Any],
        agent_adapter: Any,
        store: Any,
    ) -> None:
        self._schema = schema
        self._agent = agent_adapter
        self._store = store
        self._actors: dict[str, EntityActor] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, entity_id: str) -> EntityActor:
        """Return (or lazily create) the actor for *entity_id*."""
        if entity_id not in self._actors:
            entity = self._store.load(entity_id)
            fsm = FSMValidator(
                self._schema,
                get_stage_counts=self._stage_counts,
            )
            self._actors[entity_id] = EntityActor(
                entity, fsm, self._agent, self._store.save
            )
        return self._actors[entity_id]

    def all_entity_ids(self) -> list[str]:
        """Return ids of all entities known to the store."""
        return self._store.all_ids()

    def shutdown(self) -> None:
        """Cancel all running actor tasks (call on process exit)."""
        for actor in self._actors.values():
            actor.cancel()
        self._actors.clear()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _stage_counts(self) -> dict[str, int]:
        """Count entities per stage across the store (for WIP limit checks)."""
        counts: dict[str, int] = {}
        for eid in self._store.all_ids():
            entity = self._store.load(eid)
            stage = entity.get("stage", "")
            counts[stage] = counts.get(stage, 0) + 1
        return counts
