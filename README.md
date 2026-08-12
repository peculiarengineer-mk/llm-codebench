# llm-codebench

A Python harness that benchmarks LLM coding ability across **Python, C#,
TypeScript, and Bash** — plus **speed** and **cost** — by driving models through
[OpenRouter](https://openrouter.ai), executing the returned code **sandboxed in
Docker** against hidden tests, and scoring **pass@k**.

## How it works

For each configured model × problem, the harness:

1. Sends the problem prompt to the model via OpenRouter (streaming, so it can
   measure time-to-first-token).
2. Extracts the code block from the reply.
3. Runs that code against hidden tests **inside a locked-down Docker container**.
4. Scores `pass@1` / `pass@k` and aggregates latency, tokens, and USD cost.
5. Renders a leaderboard (CLI + self-contained HTML) and exports raw JSON/CSV.

### What the report contains

Both the terminal output and the HTML report (identical metrics, so a run is
readable at a glance and shareable on a blog) surface:

- **Methodology header** — `k`, temperature, timeout, prompt-style, and the run
  timestamp, so any run is reproducible and citable.
- **Leaderboard** — `pass@1`, `pass@k`, `tok/s`, avg time-to-first-token, total
  cost, and **`$/correct`** (cost per problem actually solved).
- **Sample-size honesty** — each model's `solved/total` alongside a **95% Wilson
  confidence interval** on `pass@k`, so a lucky 10-problem run doesn't read as a
  fact.
- **pass@k by difficulty** — an easy/medium/hard split, which is where models
  actually separate.
- **Failure modes** — every attempt bucketed into *pass* / *wrong answer* /
  *timeout* / *no code emitted*, as counts and share, so you can see *how* a
  model fails, not just that it did.
- **Cost vs. quality** — a self-contained inline-SVG scatter of `$/correct`
  against `pass@k` (the value frontier).
- **Per-problem drill-down** — which models solved each problem, plus a
  representative failing `stderr` for the ones that didn't.
- **retries** — transient network retries the OpenRouter client needed (per
  model and run-level total), so a flaky provider is visible rather than hidden
  inside the backoff loop.
- **Config-price flag** — any cost derived from a `price_override` rather than
  live API pricing is asterisked.

The HTML tables are click-to-sort (vanilla JS, no external requests) and the
page is fully self-contained — inline CSS/JS/SVG, light/dark aware — so it can
be pasted directly into a blog post.

Raw `results.json` and `results.csv` (now including `difficulty`, `timeouts`,
`no_code`, and `filtered` columns) are exported for any downstream analysis.

A `--dry-run` mode prices the whole run (model × problem × k API calls) and
enforces a per-run spend cap **before any paid API call is made**.

## Quickstart

```bash
# 1. Create the virtualenv and install (Python 3.12+ required)
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Configure secrets
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY

# 3. Edit the model roster if you like
$EDITOR config/models.yaml

# 4. Estimate cost first (no paid calls)
llm-codebench --dry-run

# 5. Run the benchmark
llm-codebench --langs python,typescript --k 3 --max-spend 2.00 --out results/
```

Common flags: `--models`, `--efforts`, `--langs`, `--k`, `--temp`, `--timeout`,
`--max-spend`, `--max-tokens`, `--dry-run`, `--prompt-style {strict,loose}`,
`--out`.

> **`HTTP 402 … requires more credits`?** OpenRouter reserves credits up front
> for a request's *maximum* possible completion — which for some models is their
> full 64k context — so a low-balance key can be rejected before generating a
> single token. Pass `--max-tokens` (e.g. `--max-tokens 8000`) to cap that
> reservation, or top up the key. A single model failing this way no longer
> aborts the run: it's recorded as a failed attempt (with the error in the
> per-problem drill-down) and every other model still completes.

### Reasoning-effort variants

The same model can be benchmarked across reasoning-effort levels to trace its
cost-vs-quality curve. Each level becomes its own leaderboard row, labelled
`<model> (<effort>)`, and effort is sent via OpenRouter's unified
`reasoning.effort` param (mapped per provider; non-reasoning models ignore it).
The report then **splits the leaderboard into one section per level** — *low*,
*medium*, *high*, *xhigh* and *max* boards (plus a *default* board for any
effort-less model), so the levels read as comparable tables rather than one
interleaved list. A level no target used is skipped, so a `low,high` run renders
two boards, not five.

**Not every model supports every level.** The five names above are the harness
vocabulary; OpenRouter publishes each model's real list as
`reasoning.supported_efforts` on `/api/v1/models`, and the per-entry `efforts:`
lists in `config/models.yaml` are set from it. Kimi K3, for instance, has no
`medium` and no `xhigh`; Qwen 3.8 has no `max`. A level the model doesn't
support passes local validation and then fails at the provider — check
OpenRouter before adding one to an entry.

By default each model runs the levels its `config/models.yaml` entry lists —
most reasoning-capable entries are swept across low/medium/high, and Claude
Opus 5 across all five (`xhigh` is the level Anthropic documents as best for
coding, so capping it at `high` would measure it below its intended setting).
The GPT-5.6 tiers
are the deliberate exception: luna/terra/sol are reasoning-capable but carry no
sweep, since the serving tiers already are the 5.6 cost/quality frontier (see
the note in `config/models.yaml`).

`--efforts` is an override, not a subset selector: a non-empty value replaces
the per-entry lists for *every* selected model. So `--efforts high` also
converts the unswept luna/terra/sol entries into `(high)` targets — the very
serving-tier × reasoning-effort conflation the yaml note avoids. Omit the flag
to run each model's configured levels:

```bash
llm-codebench --efforts high            # every selected model at high effort
llm-codebench --efforts low,high        # every selected model at low and high
llm-codebench                           # each model's configured levels (default)
```

Pin levels per model in `config/models.yaml` with an `efforts:` fan-out:

```yaml
- id: anthropic/claude-opus-4.8
  efforts: [low, medium, high]   # → three targets, three leaderboard rows
```

**Mind the estimate when sweeping — the default roster no longer fits under the
default cap.** `--dry-run` prices the full sweep at **30 targets / 1710 calls /
≈$310** at the prices documented in `config/models.yaml`, against a
`--max-spend` default of $150: a full swept run is halted partway by the spend
guard. That is the cap doing its job, not a bug — narrow the run with
`--models`/`--efforts`/`--filter`, or raise `--max-spend` deliberately.

Deep levels dominate that total. One model across its ladder, from the same
dry run:

| `anthropic/claude-opus-5` | low | medium | high | xhigh | max |
|---|---|---|---|---|---|
| est. cost | $3.20 | $7.48 | $16.03 | $30.28 | $58.78 |

So `max` costs ~18× `low` on the same 19 problems. Every figure here comes from
the `REASONING_TOKENS` heuristic in `bench/cost.py` — a rough estimate, not a
measurement — but the ordering is the point: sweeping the top of the ladder is
where the money goes.

## Configuration

- **`.env`** — holds `OPENROUTER_API_KEY` (git-ignored; copy from
  `.env.example`).
- **`config/models.yaml`** — the roster of OpenRouter model ids to benchmark,
  with optional per-model `price_override`.

## Safety: untrusted code execution

The harness runs **code generated by LLMs**, which is untrusted. All execution
happens inside Docker containers hardened as follows:

- `--network none` — no network access; images are pre-built **offline** with
  every language toolchain baked in, so C#/TypeScript never need to hit
  npm/NuGet at run time. Each language has its own offline image
  (`llm-codebench-python`, `llm-codebench-typescript`, `llm-codebench-csharp`, and
  `llm-codebench-bash` — Debian slim + bash + GNU coreutils/gawk/sed/grep).
- `--read-only` root filesystem with a small `--tmpfs /tmp`.
- `--memory 256m`, `--cpus 1`, `--pids-limit 512` resource caps.
- `--cap-drop ALL`, `--security-opt no-new-privileges`, non-root user.
- A wall-clock timeout that **kills** the container if it overruns.

Docker is a required dependency for actually executing solutions. `--dry-run`
(cost estimation) works without it.

**Do not run this harness outside a machine you're comfortable executing
arbitrary generated code on**, even with the sandbox in place.

## Project layout

```
bench/        harness package (types, config, client, sandbox, runner, report, cli)
config/       models.yaml roster
problems/     the benchmark problem suite (per language / difficulty)
results/      run output (git-ignored)
```

## Invocation ABI

The exact filenames a model's solution is written to and how hidden tests call
it (per language) are documented authoritatively in the module docstring of
[`bench/types.py`](bench/types.py). Problem authors and the sandbox both build
against that contract.
