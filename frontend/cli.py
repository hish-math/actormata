"""
frontend/cli.py -- minimal command-line interface for actormata.

Commands
--------
    actormata new <entity_id>                  Create entity at initial stage
    actormata list                             List all entities and their stages
    actormata advance <entity_id>              Advance entity one step
    actormata run <entity_id>                  Advance until terminal
    actormata override <entity_id> <stage>     Force a stage (with optional --reason)
    actormata history <entity_id>              Show full transition history

The CLI picks the adapter automatically:
    - ACTORMATA_STUB=1   -> StubAdapter (no LLM)
    - OPENAI_API_KEY     -> AgentAdapter (OpenAI)
    - ANTHROPIC_API_KEY  -> AgentAdapter (Anthropic)
    - (nothing set)      -> StubAdapter with a warning

State is persisted to state.json in the current directory by default.
Override with --state-file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Windows-safe Unicode output
# On Windows the default console encoding is often cp1252, which cannot
# encode characters like the right-arrow (\u2192).  Reconfiguring stdout
# and stderr to UTF-8 here fixes UnicodeEncodeError for all downstream
# print() calls without requiring users to set PYTHONIOENCODING manually.
# ---------------------------------------------------------------------------
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except AttributeError:
        pass  # Python < 3.7 or non-TextIOWrapper stdout; best effort


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Best-effort: walk up from cwd until we find pyproject.toml."""
    here = Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return here


def _load_json(path: Path) -> dict:
    # utf-8-sig strips a UTF-8 BOM if present (common from Windows editors)
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def _build_components(args: argparse.Namespace):
    """Instantiate store, adapter, registry, and router from CLI args."""
    from agents.adapter import make_adapter
    from engine.registry import ActorRegistry
    from engine.router import Router
    from state.store import JsonStore

    root = _repo_root()

    schema_path = Path(args.schema) if hasattr(args, "schema") and args.schema else (
        root / "schemas" / "project_management.json"
    )
    if not schema_path.exists():
        _die(f"Schema not found: {schema_path}")

    schema = _load_json(schema_path)
    initial_stage = schema.get("initial_stage", "intake")

    agents_path = Path(args.agents_file) if hasattr(args, "agents_file") and args.agents_file else (
        root / "agents.json"
    )
    agents_config = _load_json(agents_path) if agents_path.exists() else {}

    state_path = Path(args.state_file) if hasattr(args, "state_file") and args.state_file else (
        Path("state.json")
    )

    store = JsonStore(state_path, initial_stage=initial_stage)
    adapter = make_adapter(agents_config)

    if isinstance(adapter, __import__("agents.adapter", fromlist=["StubAdapter"]).StubAdapter):
        _warn("No LLM API key detected — using StubAdapter (deterministic transitions).")

    registry = ActorRegistry(schema, adapter, store)
    router = Router(registry, store)
    return registry, router, store


def _die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def _warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def _fmt_entity(entity: dict) -> str:
    stage = entity.get("stage", "?")
    eid = entity.get("id", "?")
    return f"  {eid:<30}  stage={stage}"


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def cmd_new(args: argparse.Namespace) -> None:
    registry, _router, store = _build_components(args)
    entity_id = args.entity_id
    existing = store.all_ids()
    if entity_id in existing:
        _die(f"Entity {entity_id!r} already exists.")
    # Calling get() triggers lazy creation via store.load()
    actor = registry.get(entity_id)
    entity = actor.entity
    print(f"Created entity {entity_id!r} at stage {entity['stage']!r}.")
    registry.shutdown()


async def cmd_list(args: argparse.Namespace) -> None:
    registry, _router, store = _build_components(args)
    ids = store.all_ids()
    if not ids:
        print("No entities found.")
        registry.shutdown()
        return
    print(f"{'ID':<30}  STAGE")
    print("-" * 50)
    for eid in ids:
        entity = store.load(eid)
        print(_fmt_entity(entity))
    registry.shutdown()


async def cmd_advance(args: argparse.Namespace) -> None:
    registry, router, _store = _build_components(args)
    entity_id = args.entity_id
    try:
        result = await router.dispatch({"type": "advance", "entity_id": entity_id})
    except Exception as exc:  # noqa: BLE001
        _die(str(exc))
        return
    print(f"Advanced {entity_id!r} -> stage={result['stage']!r}")
    if result.get("history"):
        last = result["history"][-1]
        print(f"  reasoning: {last.get('reasoning', '')}")
    registry.shutdown()


async def cmd_run(args: argparse.Namespace) -> None:
    """Advance an entity repeatedly until it reaches a terminal stage."""
    from engine.fsm import FSMValidator

    registry, router, store = _build_components(args)
    entity_id = args.entity_id

    # Load schema separately just to inspect terminal states
    root = _repo_root()
    schema_path = Path(args.schema) if hasattr(args, "schema") and args.schema else (
        root / "schemas" / "project_management.json"
    )
    schema = _load_json(schema_path)
    fsm = FSMValidator(schema)

    steps = 0
    max_steps = 20  # safety ceiling
    while steps < max_steps:
        entity = store.load(entity_id)
        if fsm.is_terminal(entity["stage"]):
            print(f"{entity_id!r} reached terminal stage {entity['stage']!r} after {steps} step(s).")
            break
        result = await router.dispatch({"type": "advance", "entity_id": entity_id})
        steps += 1
        last = result["history"][-1] if result.get("history") else {}
        print(
            f"  step {steps}: {last.get('from', '?')} -> {last.get('to', '?')}"
            f"  [{last.get('reasoning', '')}]"
        )
    else:
        _warn(f"Reached max steps ({max_steps}) without hitting a terminal stage.")

    registry.shutdown()


async def cmd_override(args: argparse.Namespace) -> None:
    registry, router, _store = _build_components(args)
    entity_id = args.entity_id
    target = args.target_stage
    reason = args.reason or "manual override via CLI"
    try:
        result = await router.dispatch({
            "type": "override",
            "entity_id": entity_id,
            "target_stage": target,
            "reasoning": reason,
        })
    except Exception as exc:  # noqa: BLE001
        _die(str(exc))
        return
    print(f"Overrode {entity_id!r} → stage={result['stage']!r}")
    registry.shutdown()


async def cmd_history(args: argparse.Namespace) -> None:
    _registry, _router, store = _build_components(args)
    entity_id = args.entity_id
    if entity_id not in store.all_ids():
        _die(f"Entity {entity_id!r} not found.")
    entity = store.load(entity_id)
    history = entity.get("history", [])
    if not history:
        print(f"{entity_id!r} has no transition history.")
        return
    print(f"History for {entity_id!r} (current stage: {entity['stage']!r}):")
    print()
    for i, entry in enumerate(history, 1):
        ts = entry.get("timestamp", "")
        print(f"  {i:>3}. [{ts}] {entry.get('from', '?')} -> {entry.get('to', '?')}")
        print(f"       {entry.get('reasoning', '')}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--state-file",
        default=argparse.SUPPRESS,
        metavar="PATH",
        help="Path to the JSON state file (default: state.json)",
    )
    common.add_argument(
        "--schema",
        default=argparse.SUPPRESS,
        metavar="PATH",
        help="Path to the schema JSON (default: schemas/project_management.json)",
    )
    common.add_argument(
        "--agents-file",
        default=argparse.SUPPRESS,
        metavar="PATH",
        help="Path to agents.json (default: agents.json if present)",
    )

    parser = argparse.ArgumentParser(
        prog="actormata",
        description="Agent-driven workflow engine CLI",
        parents=[common],
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # new
    p_new = sub.add_parser("new", parents=[common], help="Create a new entity")
    p_new.add_argument("entity_id", help="Unique entity identifier")

    # list
    sub.add_parser("list", parents=[common], help="List all entities and their current stages")

    # advance
    p_adv = sub.add_parser("advance", parents=[common], help="Advance an entity one step")
    p_adv.add_argument("entity_id")

    # run
    p_run = sub.add_parser("run", parents=[common], help="Advance an entity until it reaches a terminal stage")
    p_run.add_argument("entity_id")

    # override
    p_over = sub.add_parser("override", parents=[common], help="Manually force an entity to a target stage")
    p_over.add_argument("entity_id")
    p_over.add_argument("target_stage")
    p_over.add_argument("--reason", default=None, help="Reason for override")

    # history
    p_hist = sub.add_parser("history", parents=[common], help="Show transition history for an entity")
    p_hist.add_argument("entity_id")

    return parser


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def entry_point() -> None:
    """Installed console script entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    # Populate defaults if not passed either globally or on subcommand
    if not hasattr(args, "state_file"):
        args.state_file = "state.json"
    if not hasattr(args, "schema"):
        args.schema = None
    if not hasattr(args, "agents_file"):
        args.agents_file = None

    handlers = {
        "new": cmd_new,
        "list": cmd_list,
        "advance": cmd_advance,
        "run": cmd_run,
        "override": cmd_override,
        "history": cmd_history,
    }

    handler = handlers.get(args.command)
    if handler is None:
        _die(f"Unknown command: {args.command!r}")

    asyncio.run(handler(args))


if __name__ == "__main__":
    entry_point()
