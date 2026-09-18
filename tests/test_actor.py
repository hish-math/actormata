"""
tests/test_actor.py — unit tests for engine.actor.EntityActor
"""

from __future__ import annotations

import asyncio
import pytest

from engine.actor import EntityActor
from engine.fsm import FSMValidator, InvalidTransitionError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


SCHEMA = {
    "initial_stage": "intake",
    "wip_limits": {},
    "stages": {
        "intake": {
            "label": "Intake",
            "transition": "capture_only",
            "on_trigger": "assessment",
            "terminal": False,
        },
        "assessment": {
            "label": "Assessment",
            "transition": "llm_choice",
            "question": "Assess?",
            "viable": "done",
            "rejected": "rejected",
            "terminal": False,
        },
        "done": {
            "label": "Done",
            "transition": None,
            "terminal": True,
        },
        "rejected": {
            "label": "Rejected",
            "transition": None,
            "terminal": True,
        },
    },
}


class ViableStub:
    """Always returns 'viable'."""
    async def call(self, entity, node):
        return {"key": "viable", "reasoning": "stub: always viable"}


class RejectedStub:
    """Always returns 'rejected'."""
    async def call(self, entity, node):
        return {"key": "rejected", "reasoning": "stub: always rejected"}


def make_entity(stage="intake"):
    return {
        "id": "test-001",
        "stage": stage,
        "history": [],
        "override": None,
        "metadata": {},
    }


def make_actor(entity, stub=None, persist=None):
    fsm = FSMValidator(SCHEMA, get_stage_counts=None)
    stub = stub or ViableStub()
    saved = []

    def on_persist(e):
        saved.append(dict(e))

    actor = EntityActor(entity, fsm, stub, persist or on_persist)
    return actor, saved


# ---------------------------------------------------------------------------
# Basic advance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_only_advance():
    entity = make_entity("intake")
    actor, saved = make_actor(entity)
    result = await actor.send({"type": "advance"})
    assert result["stage"] == "assessment"
    assert len(result["history"]) == 1
    assert result["history"][0]["from"] == "intake"
    assert result["history"][0]["to"] == "assessment"
    actor.cancel()


@pytest.mark.asyncio
async def test_llm_choice_advance_viable():
    entity = make_entity("assessment")
    actor, saved = make_actor(entity, stub=ViableStub())
    result = await actor.send({"type": "advance"})
    assert result["stage"] == "done"
    actor.cancel()


@pytest.mark.asyncio
async def test_llm_choice_advance_rejected():
    entity = make_entity("assessment")
    actor, saved = make_actor(entity, stub=RejectedStub())
    result = await actor.send({"type": "advance"})
    assert result["stage"] == "rejected"
    actor.cancel()


# ---------------------------------------------------------------------------
# Terminal node no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminal_advance_is_noop():
    entity = make_entity("done")
    actor, saved = make_actor(entity)
    result = await actor.send({"type": "advance"})
    assert result["stage"] == "done"
    # No new history entry
    assert len(result["history"]) == 0
    actor.cancel()


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_lifecycle():
    entity = make_entity("intake")
    actor, saved = make_actor(entity, stub=ViableStub())
    # intake → assessment
    r1 = await actor.send({"type": "advance"})
    assert r1["stage"] == "assessment"
    # assessment → done (ViableStub)
    r2 = await actor.send({"type": "advance"})
    assert r2["stage"] == "done"
    assert len(r2["history"]) == 2
    actor.cancel()


# ---------------------------------------------------------------------------
# Override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_override_valid_stage():
    entity = make_entity("intake")
    actor, saved = make_actor(entity)
    result = await actor.send({
        "type": "override",
        "target_stage": "rejected",
        "reasoning": "test override",
    })
    assert result["stage"] == "rejected"
    assert result["override"] == "rejected"
    assert result["history"][-1]["reasoning"] == "test override"
    actor.cancel()


@pytest.mark.asyncio
async def test_override_invalid_stage_raises():
    entity = make_entity("intake")
    actor, _ = make_actor(entity)
    with pytest.raises(InvalidTransitionError):
        await actor.send({"type": "override", "target_stage": "fantasy_stage"})
    actor.cancel()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_persist_called_after_advance():
    entity = make_entity("intake")
    persisted = []

    def on_persist(e):
        persisted.append(dict(e))

    fsm = FSMValidator(SCHEMA, get_stage_counts=None)
    actor = EntityActor(entity, fsm, ViableStub(), on_persist)
    await actor.send({"type": "advance"})
    assert len(persisted) == 1
    assert persisted[0]["stage"] == "assessment"
    actor.cancel()


# ---------------------------------------------------------------------------
# Concurrency — serialised mailbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_sends_are_serialised():
    """Fire 10 concurrent advance messages; the entity should end at 'done'
    (not in a corrupted intermediate state) because the mailbox is FIFO serial."""
    entity = make_entity("intake")
    actor, saved = make_actor(entity, stub=ViableStub())

    # Send 10 advance messages concurrently
    results = await asyncio.gather(*[
        actor.send({"type": "advance"}) for _ in range(10)
    ])

    # All results should be valid stages (not corrupted)
    valid_stages = set(SCHEMA["stages"].keys())
    for r in results:
        assert r["stage"] in valid_stages

    # The entity should be terminal (stuck at done after the second real advance)
    final_stage = entity["stage"]
    assert SCHEMA["stages"][final_stage]["terminal"] is True
    actor.cancel()


# ---------------------------------------------------------------------------
# Unknown message type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_message_type_raises():
    entity = make_entity("intake")
    actor, _ = make_actor(entity)
    with pytest.raises(ValueError, match="Unknown message type"):
        await actor.send({"type": "teleport"})
    actor.cancel()
