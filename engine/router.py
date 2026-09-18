"""
engine/router.py — single dispatch point for all callers.

v1 only has the ``transition`` branch fully wired.
``query`` and ``external`` are stubbed; future contributors add them here
without touching the registry or actor.

Everything that wants to mutate or inspect workflow state goes through
``Router``, never directly to ``ActorRegistry``.  This indirection is what
makes a scheduler, multi-domain support, and tiered autonomy additive later.
"""

from __future__ import annotations

from typing import Any

from engine.registry import ActorRegistry


_NOT_YET_IMPLEMENTED = (
    "This handler is not yet implemented in v1. "
    "See engine/router.py for the extension point."
)


class Router:
    """Dispatch messages to the right subsystem.

    Args:
        registry: The live ``ActorRegistry``.
        store:    The store instance (used for read-only query path).
    """

    def __init__(self, registry: ActorRegistry, store: Any) -> None:
        self._registry = registry
        self._store = store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def dispatch(self, message: dict[str, Any]) -> Any:
        """Route *message* to the appropriate handler and return its result.

        Raises:
            NotImplementedError: for ``query`` and ``external`` message kinds.
            ValueError:          for unknown message kinds.
        """
        route = self._route(message)

        if route == "transition":
            return await self._handle_transition(message)

        if route == "query":
            return self._handle_query(message)

        if route == "external":
            return self._handle_external(message)

        raise ValueError(f"Unknown route: {route!r}")

    # ------------------------------------------------------------------
    # Routing logic — swap this to a classifier agent in a future version
    # ------------------------------------------------------------------

    def _route(self, message: dict[str, Any]) -> str:
        """v1: keyword-based routing.

        Returns one of: ``"transition"``, ``"query"``, ``"external"``.
        """
        msg_type = message.get("type")
        if msg_type in ("advance", "override"):
            return "transition"
        if message.get("is_question"):
            return "query"
        return "external"

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_transition(self, message: dict[str, Any]) -> dict[str, Any]:
        """Forward advance/override messages to the correct actor."""
        entity_id = message["entity_id"]
        actor = self._registry.get(entity_id)
        # Strip routing metadata before forwarding to the actor
        actor_message = {k: v for k, v in message.items() if k != "entity_id"}
        return await actor.send(actor_message)

    def _handle_query(self, message: dict[str, Any]) -> Any:  # noqa: ARG002
        """Read-only search over state — never touches the FSM.

        v1 stub — implement with ``store.search()`` when ready.
        """
        raise NotImplementedError(_NOT_YET_IMPLEMENTED)

    def _handle_external(self, message: dict[str, Any]) -> Any:  # noqa: ARG002
        """Tool-calling agent path with human-confirmed saves.

        v1 stub — implement when tiered autonomy is needed.
        """
        raise NotImplementedError(_NOT_YET_IMPLEMENTED)
