"""
tests/test_fsm.py — unit tests for engine.fsm.FSMValidator
"""

from __future__ import annotations

import pytest

from engine.fsm import FSMValidator, InvalidTransitionError, WIPLimitError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


SCHEMA = {
    "initial_stage": "intake",
    "wip_limits": {
        "assessment": 2,
    },
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


@pytest.fixture
def fsm_no_wip():
    return FSMValidator(SCHEMA, get_stage_counts=None)


@pytest.fixture
def fsm_with_wip():
    # Simulate 2 entities already in assessment (at limit)
    def counts():
        return {"assessment": 2}
    return FSMValidator(SCHEMA, get_stage_counts=counts)


# ---------------------------------------------------------------------------
# current_node
# ---------------------------------------------------------------------------


def test_current_node_known_stage(fsm_no_wip):
    node = fsm_no_wip.current_node("intake")
    assert node["transition"] == "capture_only"


def test_current_node_unknown_stage_raises(fsm_no_wip):
    with pytest.raises(InvalidTransitionError, match="not defined"):
        fsm_no_wip.current_node("nonexistent")


# ---------------------------------------------------------------------------
# validate_edge — capture_only
# ---------------------------------------------------------------------------


def test_capture_only_advances_to_on_trigger(fsm_no_wip):
    next_stage = fsm_no_wip.validate_edge("intake", answer_key="")
    assert next_stage == "assessment"


# ---------------------------------------------------------------------------
# validate_edge — llm_choice
# ---------------------------------------------------------------------------


def test_valid_llm_edge(fsm_no_wip):
    next_stage = fsm_no_wip.validate_edge("assessment", "viable")
    assert next_stage == "done"


def test_invalid_llm_edge_raises(fsm_no_wip):
    with pytest.raises(InvalidTransitionError, match="not a valid outbound edge"):
        fsm_no_wip.validate_edge("assessment", "bad_key")


# ---------------------------------------------------------------------------
# WIP limit
# ---------------------------------------------------------------------------


def test_wip_limit_exceeded_raises(fsm_with_wip):
    # intake → assessment, but assessment is at its WIP limit of 2
    with pytest.raises(WIPLimitError, match="WIP limit"):
        fsm_with_wip.validate_edge("intake", answer_key="")


def test_wip_limit_not_exceeded_passes(fsm_no_wip):
    # No WIP counts supplied, so limit is never hit
    next_stage = fsm_no_wip.validate_edge("intake", answer_key="")
    assert next_stage == "assessment"


# ---------------------------------------------------------------------------
# validate_override
# ---------------------------------------------------------------------------


def test_valid_override(fsm_no_wip):
    # Should not raise
    fsm_no_wip.validate_override("rejected")


def test_invalid_override_raises(fsm_no_wip):
    with pytest.raises(InvalidTransitionError, match="not a known stage"):
        fsm_no_wip.validate_override("fantasy_stage")


# ---------------------------------------------------------------------------
# is_terminal
# ---------------------------------------------------------------------------


def test_terminal_stage(fsm_no_wip):
    assert fsm_no_wip.is_terminal("done") is True


def test_non_terminal_stage(fsm_no_wip):
    assert fsm_no_wip.is_terminal("assessment") is False
