# AGENTS.md

Shared instructions for coding agents (OpenCode, Claude Code, and any other tool
that reads `AGENTS.md`). Keep this file the single source of truth for project
conventions — do not duplicate it into tool-specific files.

## What this project is

`llm-codebench` benchmarks LLM coding ability across Python, C#, TypeScript and
Bash, plus speed and cost. It drives models through OpenRouter, extracts the
returned code, executes it sandboxed in Docker against hidden tests, and scores
`pass@k`. Output is a CLI leaderboard, a self-contained HTML report, and raw
JSON/CSV.

Python 3.12+. Dependencies: `httpx`, `pydantic`, `pyyaml`, `rich`, `jinja2`,
`python-dotenv`. Tests use `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`).

## Layout

| Path | Owns |
|---|---|
| `bench/types.py` | Core contracts — `Attempt`, `Problem`, effort parsing. Most-depended-on module. |
| `bench/runner.py` | Orchestration: model calls → extraction → sandbox → scoring. |
| `bench/openrouter.py` | Streaming API client, retries, token/cost accounting. |
| `bench/extract.py` | Pulls the code block out of a model reply. |
| `bench/sandbox.py` | Hardened `docker run` execution. Security boundary. |
| `bench/problems.py` | Loads `problems/<lang>/<slug>/` into `Problem` objects. |
| `bench/report.py` | CLI + HTML rendering, CSV/JSON export. |
| `bench/cost.py` | `SpendGuard`, pricing, dry-run estimates. |
| `bench/config.py` | Roster loading, model × effort target resolution. |
| `bench/cli.py` | Argument parsing and entry point. |
| `config/models.yaml` | Model roster and price overrides. |
| `problems/` | Benchmark problems. Never edit to make a test pass. |
| `tests/` | pytest suite. |

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate   # Python 3.12+
pip install -e ".[dev]"

python3 -m pytest -q                                 # full suite
python3 -m pytest tests/test_report.py -q            # one file
python3 -m bench.cli --dry-run                       # price a run, no API calls
```

Always run the suite before declaring work done.

## Conventions

- **Match surrounding style.** Naming, comment density, and docstring voice vary
  by module — follow the file you are in rather than importing a house style.
- **Docstrings state contracts, not restatements.** If you change what a
  property means, change its docstring in the same edit.
- **Type hints on public functions.** `from __future__ import annotations` where
  the module already uses it.
- **No new runtime dependencies** without being asked. The dependency list above
  is deliberately small.
- **Async**: the runner and sandbox are `async`; keep blocking I/O out of them.

## Hard rules

- **Never edit `problems/`** to make a test pass. The problems are the
  measurement; changing them invalidates every historical result.
- **Never weaken `bench/sandbox.py` isolation.** The `--network none`,
  `--read-only`, `--cap-drop ALL`, `--security-opt no-new-privileges` and `:ro`
  mount flags are the boundary that makes running untrusted model output safe.
  Do not remove or relax them.
- **Never commit, push, or open a PR** unless explicitly asked. Leave changes in
  the working tree for review.
- **Do not touch `.env`** or print secrets. `OPENROUTER_API_KEY` lives there.
- **No test may require a live Docker daemon or network.** Stub the boundary
  (`_run`, the HTTP client) instead. The suite must pass offline.
- **Cost claims must be reproduced, not estimated from memory.** Any figure in
  the README or a comment should come from an actual `--dry-run`.

## Scoring contracts worth knowing

`Attempt.sampled` and `Attempt.filtered` in `bench/types.py` decide what counts
toward `pass@k`. They are read by `runner.py`, `report.py` and the CSV export —
a change to either ripples through every reported number. Treat them as a
contract: if you narrow one, update every consumer in the same phase, and keep
the invariant that a filtered attempt carries no usable code.
