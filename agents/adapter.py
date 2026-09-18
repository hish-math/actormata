"""
agents/adapter.py — LLM adapter with structured output enforcement.

Two concrete adapters ship with v1:

StubAdapter
    Deterministic fake.  Always returns the first outbound edge on the current
    node.  Use for tests and when no API key is configured.  Zero external deps.

AgentAdapter
    Production adapter.  Reads per-stage config from agents.json, calls the LLM
    via function-calling / tool-use (structured output only — never free-text
    parsing), and validates the returned key is a legal edge on the node.

    Provider is selected by the presence of an env var or explicit argument:
        OPENAI_API_KEY   → OpenAI function calling (default if both are set)
        ANTHROPIC_API_KEY → Anthropic tool use

    The adapter intentionally never parses free text.  If the LLM returns a
    malformed response, ``InvalidLLMResponseError`` is raised — catch it at the
    call site and decide whether to retry, fall back to StubAdapter, or surface
    to the user.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class InvalidLLMResponseError(Exception):
    """Raised when the LLM response is missing required structured fields."""


# ---------------------------------------------------------------------------
# StubAdapter — deterministic, dependency-free
# ---------------------------------------------------------------------------

_META_KEYS = {
    "label", "description", "transition", "question",
    "on_trigger", "terminal",
}


class StubAdapter:
    """Always picks the first outbound edge on the current node.

    Useful for:
    - Unit tests that don't need an LLM
    - Smoke-testing the full lifecycle without API credentials
    - Local development with ACTORMATA_STUB=1

    Args:
        fixed_key: If provided, always return this key instead of the first
                   outbound edge.  Convenient for targeted tests.
    """

    def __init__(self, fixed_key: str | None = None) -> None:
        self._fixed_key = fixed_key

    async def call(self, entity: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
        if self._fixed_key:
            key = self._fixed_key
        else:
            outbound = [k for k in node if k not in _META_KEYS]
            if not outbound:
                raise InvalidLLMResponseError(
                    f"Stage {entity.get('stage')!r} has no outbound edges; "
                    "cannot stub a transition."
                )
            key = outbound[0]
        return {
            "key": key,
            "reasoning": f"[stub] auto-selected first edge: {key!r}",
        }


# ---------------------------------------------------------------------------
# AgentAdapter — production LLM adapter
# ---------------------------------------------------------------------------


class AgentAdapter:
    """Calls an LLM with structured output (function calling / tool use).

    Args:
        agents_config:  Dict loaded from agents.json (per-stage config).
        api_key:        Override the API key (defaults to env vars).
        provider:       ``"openai"`` or ``"anthropic"``.  Auto-detected from
                        env vars when not specified.
        prompts_dir:    Path to the Jinja2 prompt templates directory.
    """

    def __init__(
        self,
        agents_config: dict[str, Any],
        api_key: str | None = None,
        provider: str | None = None,
        prompts_dir: Path | str | None = None,
    ) -> None:
        self._config = agents_config
        self._provider = provider or self._detect_provider()
        self._api_key = api_key or self._env_key()

        prompts_path = Path(prompts_dir or Path(__file__).parent / "prompts")
        self._jinja = Environment(
            loader=FileSystemLoader(str(prompts_path)),
            autoescape=False,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def call(self, entity: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
        """Call the LLM and return ``{"key": str, "reasoning": str}``.

        Raises:
            InvalidLLMResponseError: if the LLM response is malformed or
                                     missing the ``key`` field.
        """
        stage = entity["stage"]
        stage_cfg = self._config.get(stage, {})

        prompt = self._render_prompt(stage, entity, node, stage_cfg)
        output_schema = stage_cfg.get("output_schema", self._default_schema(node))

        if self._provider == "openai":
            raw = await self._call_openai(prompt, output_schema)
        else:
            raw = await self._call_anthropic(prompt, output_schema)

        return self._validate_response(raw, node)

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    async def _call_openai(
        self, prompt: str, output_schema: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            from openai import AsyncOpenAI  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "openai package is not installed. Run: pip install actormata[openai]"
            ) from exc

        client = AsyncOpenAI(api_key=self._api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "transition_decision",
                        "description": "Return the workflow transition decision.",
                        "parameters": output_schema,
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": "transition_decision"}},
        )
        tool_call = response.choices[0].message.tool_calls[0]
        return json.loads(tool_call.function.arguments)

    async def _call_anthropic(
        self, prompt: str, output_schema: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            import anthropic  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "anthropic package is not installed. Run: pip install actormata[anthropic]"
            ) from exc

        client = anthropic.AsyncAnthropic(api_key=self._api_key)
        response = await client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=256,
            tools=[
                {
                    "name": "transition_decision",
                    "description": "Return the workflow transition decision.",
                    "input_schema": output_schema,
                }
            ],
            tool_choice={"type": "tool", "name": "transition_decision"},
            messages=[{"role": "user", "content": prompt}],
        )
        tool_use = next(b for b in response.content if b.type == "tool_use")
        return tool_use.input

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _render_prompt(
        self,
        stage: str,
        entity: dict[str, Any],
        node: dict[str, Any],
        stage_cfg: dict[str, Any],
    ) -> str:
        template_name = stage_cfg.get("template", f"{stage}.j2")
        try:
            template = self._jinja.get_template(template_name)
            return template.render(entity=entity, node=node)
        except Exception:  # noqa: BLE001 — fall back to inline question
            return (
                f"Entity context:\n{json.dumps(entity, indent=2)}\n\n"
                f"Task: {node.get('question', 'Decide the next step.')}"
            )

    def _default_schema(self, node: dict[str, Any]) -> dict[str, Any]:
        """Build a minimal JSON Schema for the transition decision."""
        outbound = [k for k in node if k not in _META_KEYS]
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "enum": outbound,
                    "description": "The transition key to follow.",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Brief explanation of the decision.",
                },
            },
            "required": ["key", "reasoning"],
        }

    def _validate_response(
        self, raw: dict[str, Any], node: dict[str, Any]
    ) -> dict[str, Any]:
        if "key" not in raw:
            raise InvalidLLMResponseError(
                f"LLM response missing 'key' field: {raw!r}"
            )
        outbound = [k for k in node if k not in _META_KEYS]
        if raw["key"] not in outbound:
            raise InvalidLLMResponseError(
                f"LLM returned key {raw['key']!r} which is not a valid edge. "
                f"Valid keys: {outbound}"
            )
        return raw

    def _detect_provider(self) -> str:
        if os.getenv("OPENAI_API_KEY"):
            return "openai"
        if os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic"
        raise RuntimeError(
            "No LLM provider detected. Set OPENAI_API_KEY or ANTHROPIC_API_KEY, "
            "or use StubAdapter for development."
        )

    def _env_key(self) -> str:
        key = os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("API key not found in environment.")
        return key


# ---------------------------------------------------------------------------
# Factory — pick the right adapter automatically
# ---------------------------------------------------------------------------


def make_adapter(agents_config: dict[str, Any]) -> "StubAdapter | AgentAdapter":
    """Return ``StubAdapter`` if ACTORMATA_STUB=1 or no API keys are set,
    otherwise return a configured ``AgentAdapter``."""
    if os.getenv("ACTORMATA_STUB") == "1":
        return StubAdapter()
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
    if not has_openai and not has_anthropic:
        return StubAdapter()
    return AgentAdapter(agents_config)
