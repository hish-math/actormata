"""
tests/test_simple_task.py — test suite for schemas/simple_task.json
"""

import json
from pathlib import Path

import pytest

from agents.adapter import StubAdapter
from engine.fsm import FSMValidator
from engine.registry import ActorRegistry
from engine.router import Router
from state.store import JsonStore


@pytest.fixture
def simple_task_schema():
    schema_path = Path(__file__).parent.parent / "schemas" / "simple_task.json"
    with schema_path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def test_simple_task_schema_structure(simple_task_schema):
    assert simple_task_schema["domain"] == "simple_task"
    assert simple_task_schema["initial_stage"] == "inbox"
    stages = simple_task_schema["stages"]
    assert "inbox" in stages
    assert "review" in stages
    assert "in_progress" in stages
    assert "done" in stages
    assert "deferred" in stages
    assert stages["in_progress"]["terminal"] is True
    assert stages["done"]["terminal"] is True
    assert stages["deferred"]["terminal"] is True


def test_simple_task_fsm_validation(simple_task_schema):
    fsm = FSMValidator(simple_task_schema)
    assert fsm.is_terminal("done") is True
    assert fsm.is_terminal("inbox") is False

    # capture_only transition from inbox -> review
    next_stage = fsm.validate_edge("inbox", "")
    assert next_stage == "review"

    # llm_choice transition from review
    next_stage = fsm.validate_edge("review", "start")
    assert next_stage == "in_progress"

    next_stage = fsm.validate_edge("review", "defer")
    assert next_stage == "deferred"


@pytest.mark.asyncio
async def test_simple_task_full_lifecycle(simple_task_schema, tmp_path):
    state_file = tmp_path / "state.json"
    store = JsonStore(state_file, initial_stage=simple_task_schema["initial_stage"])
    adapter = StubAdapter()
    registry = ActorRegistry(simple_task_schema, adapter, store)
    router = Router(registry, store)

    entity_id = "task-001"
    registry.get(entity_id)

    # Step 1: inbox -> review
    res1 = await router.dispatch({"type": "advance", "entity_id": entity_id})
    assert res1["stage"] == "review"

    # Step 2: review -> in_progress (StubAdapter picks first edge: 'start')
    res2 = await router.dispatch({"type": "advance", "entity_id": entity_id})
    assert res2["stage"] == "in_progress"

    # Step 3: in_progress is terminal, advancing is no-op
    res3 = await router.dispatch({"type": "advance", "entity_id": entity_id})
    assert res3["stage"] == "in_progress"

    # Override to done
    res4 = await router.dispatch({
        "type": "override",
        "entity_id": entity_id,
        "target_stage": "done",
        "reason": "completed task",
    })
    assert res4["stage"] == "done"

    registry.shutdown()
