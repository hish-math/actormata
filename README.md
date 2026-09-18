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

---

## Setup

### 1. Install Python 3.11+

**Windows**

The easiest option is the official installer from [python.org/downloads](https://www.python.org/downloads/).
During installation, tick **"Add python.exe to PATH"**.

After installing, verify with:
```powershell
py --version        # Windows Python Launcher (preferred)
# or
python --version
```

If neither works, open **Settings → Apps → Advanced app settings → App execution
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
.venv\Scripts\Activate.ps1
py -m pip install -e ".[dev]"
```

> If you see `cannot be loaded because running scripts is disabled`, run:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

**Linux / macOS**

```bash
cd /path/to/actormata
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

### 3. Verify the install

```bash
pytest tests/ -v
```

All tests should pass with no LLM key required (the stub adapter is used by default).

---

## Usage

```bash
# Create an entity and run through the full project-management lifecycle
python -m frontend.cli new proj-001
python -m frontend.cli run proj-001

# Step through manually
python -m frontend.cli advance proj-001
python -m frontend.cli history proj-001

# Override to any stage
python -m frontend.cli override proj-001 deferred --reason "deprioritised in Q3"
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
