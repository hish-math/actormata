# Contributing to actormata

Thank you for your interest!  Here's what you need to know.

---

## The contribution surface

The primary contribution surface is **`schemas/`**.

> **Schema is declarative, not code.**
> A schema file is a JSON document describing stages, transitions, and WIP
> limits.  It is not a place to embed logic.  If you find yourself wanting to
> add `if` statements or callbacks inside a schema, that's a sign the engine
> needs a new primitive — open an issue to discuss it first.

Adding a new domain schema:
1. Copy `schemas/project_management.json` as a starting point.
2. Define your stages, outbound edges, questions, and WIP limits.
3. Add a test in `tests/` that runs a stub entity through the full lifecycle.
4. Open a PR — schema PRs are welcomed with minimal review friction.

---

## What we ask you not to do

- **Do not bypass the engine** by writing logic directly in a schema.
- **Do not modify `engine/` or `agents/` to accommodate a specific schema.**
  If the engine can't express something your schema needs, open an issue.
- **Do not add free-text LLM parsing.**  All LLM output must go through
  structured output (function calling / tool use).  This is the single most
  important safety rule in the codebase.

---

## Engine and agent changes

`engine/` and `agents/` are treated as separate installable modules.  PRs that
touch them need:

- A clear explanation of why the schema layer cannot solve the problem.
- Unit tests for the new behaviour.
- No breaking changes to the `EntityActor.send()` or `Router.dispatch()` interfaces
  without a version bump and migration notes.

---

## Development setup

```bash
git clone https://github.com/hish-math/actormata.git
cd actormata
pip install -e ".[dev]"
pytest tests/ -v
```

---

## Code style

- Python 3.11+
- Type annotations on all public functions.
- Docstrings on all public classes and methods.
- `pytest` for tests; `pytest-asyncio` for async tests.

---

## Licence

By contributing you agree that your contributions will be licensed under the
Apache 2.0 licence that covers this project.
