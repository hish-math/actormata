# actormata

**Agent-driven workflow engine using the actor model for safe concurrency.**

Move entities (projects, tickets, requests, anything) through a declarative
finite-state machine. At each step an LLM agent decides the transition; the
engine enforces it.  Multiple agents and users can hit the same entity
concurrently — the actor mailbox serialises writes so there are no race
conditions.

---

## The three-file mental model

| File | Role |
|---|---|
| `schemas/*.json` | **Rules** — stages, questions, WIP limits |
| `state.json` | **Data** — current stage + full transition history per entity |
| `agents.json` | **LLM binding** — which model/template handles each stage |

Engine and agents are separate installable modules.  You can swap the LLM
adapter without touching the FSM, and you can add a new domain schema without
touching the engine.

> Copy `agents.example.json` to `agents.json` to get started with LLM configuration.

---

## How it works

```
  ┌──────────────────────────────────────────────┐
  │                 Your code / CLI               │
  └─────────────────────┬────────────────────────┘
                        │ router.dispatch(message)
  ┌─────────────────────▼────────────────────────┐
  │    Router   ->   ActorRegistry                │
  │                      │                        │
  │              EntityActor (one per entity)      │
  │           ┌──────────┴──────────┐             │
  │      mailbox queue          FSMValidator       │
  │     (serial writes)     (transition rules)     │
  └─────────────────────┬────────────────────────┘
                        │ LLM call (structured output only)
  ┌─────────────────────▼────────────────────────┐
  │  AgentAdapter  (OpenAI / Anthropic)  or        │
  │  StubAdapter   (deterministic, no key)         │
  └─────────────────────┬────────────────────────┘
                        │ persist
  ┌─────────────────────▼────────────────────────┐
  │              JsonStore -> state.json           │
  └──────────────────────────────────────────────┘
```

**Key design decisions:**
- **No free-text LLM parsing.** All LLM output goes through structured output (function calling / tool use). The engine never parses prose.
- **Mailbox = no locks.** Each entity has exactly one actor. All mutations are enqueued and processed one at a time — concurrent callers are safe automatically.
- **Schema is declarative, not code.** Add a new domain in one JSON file. No Python changes required.

---

## Setup

### 1. Install Python 3.11+

**Windows**

The easiest option is the official installer from [python.org/downloads](https://www.python.org/downloads/).
During installation, tick **"Add python.exe to PATH"**.

After installing, verify:
```powershell
py --version
```

If this fails, open **Settings → Apps → Advanced app settings → App execution
aliases** and disable the Store alias for Python, then re-open your terminal.

**Linux / macOS**

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install python3.11 python3.11-venv python3-pip

# macOS (via Homebrew)
brew install python@3.11

# Verify
python3 --version
```

---

### 2. Create a virtual environment and install

**Windows (PowerShell)**

```powershell
cd "c:\path\to\actormata"
py -m venv .venv

# If Activate.ps1 is blocked by execution policy, run this first:
# Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

.venv\Scripts\pip install -e ".[dev]"
```

**Linux / macOS**

```bash
cd /path/to/actormata
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

### 3. Verify the install

**Windows**
```powershell
.venv\Scripts\pytest tests/ -v
```

**Linux / macOS**
```bash
pytest tests/ -v
```

All 38 tests pass with no LLM key required — the `StubAdapter` is used by default.

---

## Quickstart: CLI

```bash
# Windows -- prefix commands with .venv\Scripts\python -m
# Linux/macOS -- activate venv first, then use python -m

# 1. Create an entity and run it through the full lifecycle
python -m frontend.cli new proj-001
python -m frontend.cli run proj-001

# 2. Step through manually
python -m frontend.cli advance proj-001
python -m frontend.cli history proj-001

# 3. Force any stage directly (human override)
python -m frontend.cli override proj-001 deferred --reason "deprioritised in Q3"

# 4. List all entities
python -m frontend.cli list
```

By default the CLI uses `StubAdapter` (deterministic, no API key required).
To use a real LLM, export your key before running:

```bash
# OpenAI
export OPENAI_API_KEY=sk-...          # Linux/macOS
$env:OPENAI_API_KEY = "sk-..."        # Windows PowerShell

# Anthropic
export ANTHROPIC_API_KEY=sk-ant-...   # Linux/macOS
$env:ANTHROPIC_API_KEY = "sk-ant-..." # Windows PowerShell

python -m frontend.cli run proj-001
```

### Using a custom schema or state file

```bash
python -m frontend.cli new task-001 \
  --schema schemas/simple_task.json \
  --state-file my_tasks.json

python -m frontend.cli run task-001 \
  --schema schemas/simple_task.json \
  --state-file my_tasks.json
```

---

## Quickstart: Python library

You can drive actormata from any Python script or web framework:

```python
import asyncio
import json
from pathlib import Path

from agents.adapter import StubAdapter
from engine.registry import ActorRegistry
from engine.router import Router
from state.store import JsonStore


async def main() -> None:
    # Load a schema
    schema = json.loads(Path("schemas/simple_task.json").read_text())

    # Wire up the components (StubAdapter needs no API key)
    store    = JsonStore("my_state.json", initial_stage=schema["initial_stage"])
    adapter  = StubAdapter()
    registry = ActorRegistry(schema, adapter, store)
    router   = Router(registry, store)

    # Create an entity and advance it through the FSM
    registry.get("task-42")  # lazy-create

    result = await router.dispatch({"type": "advance", "entity_id": "task-42"})
    print(f"Stage: {result['stage']}")          # -> in_progress

    history = result["history"]
    for step in history:
        print(f"  {step['from']} -> {step['to']}: {step['reasoning']}")

    registry.shutdown()


asyncio.run(main())
```

To use a real LLM instead of `StubAdapter`, swap it out:

```python
from agents.adapter import AgentAdapter
import json

agents_config = json.loads(Path("agents.json").read_text())
adapter = AgentAdapter(agents_config)   # picks OpenAI or Anthropic from env
```

---

## Schema reference

Schemas live in `schemas/*.json`.  Each file describes one domain (project management, task queue, hiring pipeline, etc.).

### Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `domain` | string | yes | Unique name for this workflow (used in logging) |
| `version` | string | yes | Schema version string |
| `initial_stage` | string | yes | The stage assigned to every newly created entity |
| `stages` | object | yes | Map of stage name -> stage node (see below) |
| `wip_limits` | object | no | Map of stage name -> max entities allowed in that stage |

### Stage node fields

| Field | Type | Description |
|---|---|---|
| `label` | string | Human-readable name shown in the CLI |
| `description` | string | Explains the purpose of this stage |
| `transition` | `"capture_only"` / `"llm_choice"` / `null` | Controls how the next stage is chosen (see below) |
| `terminal` | boolean | If `true`, the entity rests here; `advance` is a no-op |
| `on_trigger` | string | *(capture_only only)* The stage to jump to automatically |
| `question` | string | *(llm_choice only)* The prompt sent to the LLM |
| *`<key>`* | string | *(llm_choice only)* Outbound edge: LLM answer key -> next stage name |

### Transition types

| Value | Behaviour |
|---|---|
| `"capture_only"` | Entity is automatically advanced to `on_trigger` with no LLM call. Use for intake/capture stages. |
| `"llm_choice"` | The LLM is called with `question`. It returns one of the outbound keys (e.g. `"viable"`, `"rejected"`). That key maps to the next stage name in the node. |
| `null` | Stage is terminal — no transitions. |

### Example node (llm_choice)

```json
"assessment": {
  "label": "Assessment",
  "description": "Evaluate feasibility and risk.",
  "transition": "llm_choice",
  "question": "Is this item viable or should it be rejected? Answer: viable or rejected.",
  "viable":   "prioritization",
  "rejected": "rejected",
  "terminal": false
}
```

---

## Creating your own workflow

> **Goal:** a simple personal task tracker in under 5 minutes.

### Step 1 — Copy the minimal template

```bash
cp schemas/simple_task.json schemas/my_workflow.json
```

Open `schemas/simple_task.json` as a reference.  Its lifecycle is:

```
inbox  ->  review  ->  in_progress
                   \-> deferred
```

### Step 2 — Define your stages

Edit `my_workflow.json`.  Rules:
- Every `llm_choice` node must have a `question` and at least one outbound key.
- Every outbound key value must be a stage name defined elsewhere in `stages`.
- Every path through the graph must eventually reach a stage where `"terminal": true`.

### Step 3 — (Optional) Add WIP limits

Add `"wip_limits": { "in_progress": 3 }` at the top level to cap how many entities can be in that stage simultaneously. actormata enforces this automatically and raises a `WIPLimitError` instead of allowing the advance.

### Step 4 — (Optional) Add a prompt template

Create `agents/prompts/<stage_name>.j2`.  Use `agents/prompts/assess.j2` as a reference — it shows how to access `entity`, `node`, and `entity.metadata` fields in Jinja2.

### Step 5 — Run it

```bash
python -m frontend.cli new my-task-001 --schema schemas/my_workflow.json --state-file tasks.json
python -m frontend.cli run  my-task-001 --schema schemas/my_workflow.json --state-file tasks.json
python -m frontend.cli history my-task-001 --schema schemas/my_workflow.json --state-file tasks.json
```

---

## Repo layout

```
actormata/
├── schemas/
│   └── project_management.json   # example FSM schema (contribute more here)
├── engine/
│   ├── actor.py                  # EntityActor — mailbox + advance/override
│   ├── fsm.py                    # FSMValidator — stateless transition checker
│   ├── registry.py               # ActorRegistry — lazy spawn + cache
│   └── router.py                 # Router — single dispatch point
├── agents/
│   ├── adapter.py                # StubAdapter + AgentAdapter (OpenAI / Anthropic)
│   └── prompts/                  # Jinja2 prompt templates per stage
├── state/
│   └── store.py                  # JsonStore (v1); swap in SQLiteStore later
├── frontend/
│   └── cli.py                    # actormata CLI
└── tests/
```

---

## Example schema

See [`schemas/project_management.json`](schemas/project_management.json) for a
full example.  The lifecycle is:

```
intake → data_collection → assessment → prioritization → active
                                     ↘                 ↘
                                      rejected          deferred
```

A stage node looks like:

```json
"assessment": {
  "label": "Assessment",
  "transition": "llm_choice",
  "question": "Assess this item. viable or rejected?",
  "viable": "prioritization",
  "rejected": "rejected",
  "terminal": false
}
```

---

## Running tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
