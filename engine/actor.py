"""
engine/actor.py — concurrency-safe per-entity actor.

Each entity is owned by exactly one EntityActor.  All mutations go through
``actor.send(message)`` which enqueues work on an asyncio mailbox processed
serially, eliminating race conditions without any explicit locks.

Message types
-------------
advance   Invoke the agent adapter (or capture_only trigger) and move the
          entity to its next stage.
override  Forcibly move the entity to an arbitrary stage (human-in-the-loop).
"""

from __future__ import annotations

import asyncio
import datetime
from datetime import UTC
from typing import Any, Callable, Coroutine

from engine.fsm import FSMValidator


class EntityActor:
    """Owns one entity dict; processes messages one at a time via a mailbox.

    Args:
        entity:        The mutable entity dict (loaded from the store).
        fsm:           An ``FSMValidator`` bound to the relevant schema.
        agent_adapter: Any object with ``async call(entity, node) -> dict``
                       that returns ``{"key": str, "reasoning": str}``.
        on_persist:    Sync or async callable invoked with the entity after
                       every state change.  Must be safe to call from the
                       actor's background task.
    """

    def __init__(
        self,
        entity: dict[str, Any],
        fsm: FSMValidator,
        agent_adapter: Any,
        on_persist: Callable[[dict[str, Any]], Any],
    ) -> None:
        self.entity = entity
        self._fsm = fsm
        self._agent = agent_adapter
        self._on_persist = on_persist
        self._mailbox: asyncio.Queue[tuple[dict, asyncio.Future]] = asyncio.Queue()
        self._task = asyncio.get_event_loop().create_task(self._run())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Enqueue *message* and await its result.

        Raises whatever ``_handle`` raises — callers should catch
        ``engine.fsm.InvalidTransitionError`` and ``engine.fsm.WIPLimitError``.
        """
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        await self._mailbox.put((message, future))
        return await future

    def cancel(self) -> None:
        """Cancel the background task.  Call when tearing down the registry."""
        self._task.cancel()

    # ------------------------------------------------------------------
    # Internal mailbox loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        while True:
            message, future = await self._mailbox.get()
            try:
                result = await self._handle(message)
                future.set_result(result)
            except Exception as exc:  # noqa: BLE001
                future.set_exception(exc)
            finally:
                self._mailbox.task_done()

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    async def _handle(self, message: dict[str, Any]) -> dict[str, Any]:
        msg_type = message.get("type")

        if msg_type == "override":
            return await self._handle_override(message)

        if msg_type == "advance":
            return await self._handle_advance()

        raise ValueError(f"Unknown message type: {msg_type!r}")

    async def _handle_override(self, message: dict[str, Any]) -> dict[str, Any]:
        target = message["target_stage"]
        self._fsm.validate_override(target)

        reasoning = message.get("reasoning", "manual override")
        self._log(self.entity["stage"], target, reasoning)
        self.entity["stage"] = target
        self.entity["override"] = target
        await self._persist()
        return dict(self.entity)

    async def _handle_advance(self) -> dict[str, Any]:
        current_stage = self.entity["stage"]
        node = self._fsm.current_node(current_stage)

        # Already at a terminal node — nothing to do
        if self._fsm.is_terminal(current_stage):
            return dict(self.entity)

        if node.get("transition") == "capture_only":
            next_stage = self._fsm.validate_edge(current_stage, answer_key="")
            reasoning = "capture_only trigger"
        else:
            answer = await self._agent.call(self.entity, node)
            key = answer["key"]
            reasoning = answer.get("reasoning", "")
            next_stage = self._fsm.validate_edge(current_stage, key)

        self._log(current_stage, next_stage, reasoning)
        self.entity["stage"] = next_stage
        await self._persist()
        return dict(self.entity)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, from_stage: str, to_stage: str, reasoning: str) -> None:
        self.entity.setdefault("history", []).append(
            {
                "from": from_stage,
                "to": to_stage,
                "reasoning": reasoning,
                "timestamp": datetime.datetime.now(UTC).isoformat(),
            }
        )

    async def _persist(self) -> None:
        result = self._on_persist(self.entity)
        # Support both sync and async on_persist callables
        if asyncio.isfuture(result) or asyncio.iscoroutine(result):
            await result
