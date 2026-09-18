"""
engine/fsm.py — stateless FSM transition validator.

Called by EntityActor before committing any transition so that the actor
itself stays free of schema-parsing logic.
"""

from __future__ import annotations

from typing import Any


class WIPLimitError(Exception):
    """Raised when advancing into a stage would exceed its WIP limit."""


class InvalidTransitionError(Exception):
    """Raised when the proposed next stage is not a valid edge on the node."""


class FSMValidator:
    """Validates proposed transitions against a loaded schema dict.

    The validator is stateless — it holds only the schema and a reference to
    a callable that returns current stage population counts so WIP limits can
    be checked.  Pass ``get_stage_counts`` as ``None`` to skip WIP checks
    (useful in tests).

    Args:
        schema:            The parsed schema dict (e.g. from schemas/*.json).
        get_stage_counts:  Optional callable ``() -> dict[str, int]`` that
                           returns the current number of entities in each stage.
    """

    def __init__(
        self,
        schema: dict[str, Any],
        get_stage_counts: Any = None,
    ) -> None:
        self._schema = schema
        self._get_stage_counts = get_stage_counts

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def current_node(self, stage: str) -> dict[str, Any]:
        """Return the schema node for *stage*, raising KeyError if missing."""
        try:
            return self._schema["stages"][stage]
        except KeyError:
            raise InvalidTransitionError(
                f"Stage {stage!r} is not defined in the schema."
            )

    def validate_edge(self, current_stage: str, answer_key: str) -> str:
        """Return the next stage for *answer_key* on *current_stage*.

        Raises:
            InvalidTransitionError: if *answer_key* is not an outbound edge.
            WIPLimitError:          if the target stage is at its WIP limit.
        """
        node = self.current_node(current_stage)

        # capture_only nodes use `on_trigger`, not an LLM key
        if node.get("transition") == "capture_only":
            next_stage = node["on_trigger"]
        else:
            if answer_key not in node:
                valid = self._outbound_keys(node)
                raise InvalidTransitionError(
                    f"Key {answer_key!r} is not a valid outbound edge from "
                    f"{current_stage!r}. Valid keys: {valid}"
                )
            next_stage = node[answer_key]

        self._check_wip(next_stage)
        return next_stage

    def validate_override(self, target_stage: str) -> None:
        """Ensure *target_stage* exists in the schema.

        Raises:
            InvalidTransitionError: if the stage is unknown.
        """
        if target_stage not in self._schema["stages"]:
            raise InvalidTransitionError(
                f"Override target {target_stage!r} is not a known stage."
            )

    def is_terminal(self, stage: str) -> bool:
        """Return True if *stage* is a terminal (resting) node."""
        return bool(self.current_node(stage).get("terminal", False))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _outbound_keys(self, node: dict[str, Any]) -> list[str]:
        """Return the valid answer-key names on *node* (excludes metadata keys)."""
        _meta = {
            "label", "description", "transition", "question",
            "on_trigger", "terminal",
        }
        return [k for k in node if k not in _meta]

    def _check_wip(self, stage: str) -> None:
        wip_limits: dict[str, int] = self._schema.get("wip_limits", {})
        limit = wip_limits.get(stage)
        if limit is None or self._get_stage_counts is None:
            return
        counts = self._get_stage_counts()
        current = counts.get(stage, 0)
        if current >= limit:
            raise WIPLimitError(
                f"Stage {stage!r} is at its WIP limit ({limit}). "
                "Cannot advance more entities into it right now."
            )
