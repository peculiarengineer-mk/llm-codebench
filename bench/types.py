"""Shared, frozen data contracts for the llm-codebench harness.

Every other module (T2 loader, T4 client/extract, T5 sandbox, T6 runner,
T7 reporter, T8 CLI) builds against the Pydantic models defined here. They are
declared ``frozen=True`` so that, once constructed, an instance is an immutable
value object that can be shared across async tasks without defensive copying.

==============================================================================
PER-LANGUAGE INVOCATION ABI  (the T2/T3/T5 contract — read this before writing
a problem, a loader, or the sandbox)
==============================================================================

This section is the single source of truth for two things:

  (a) the exact filename the *model's* solution code is written to inside the
      sandbox working directory, and
  (b) how the *hidden* test file locates and calls that code (import name and
      the ``entrypoint`` symbol the solution must expose).

The sandbox (T5) writes exactly two files into the container's ``/workspace``:
the extracted model solution under the language's SOLUTION FILENAME, and the
problem's hidden tests under the language's TEST FILENAME. Nothing else is
injected. Problem authors (T3) and the loader (T2) MUST honor these names, and
tests MUST reference the solution using the import form below. ``entrypoint``
(``Problem.entrypoint``) names the symbol the solution is required to expose;
it is what the prompt instructs the model to implement and what the tests call.

------------------------------------------------------------------------------
Language.python
------------------------------------------------------------------------------
  SOLUTION FILENAME : solution.py
  TEST FILENAME     : test_solution.py
  IMPORT / CALL     : the test module does `from solution import <entrypoint>`
                      (e.g. `from solution import merge_intervals`). The
                      solution therefore defines `<entrypoint>` at module top
                      level (a function or class).
  TEST RUNNER       : pytest, invoked as `pytest -q test_solution.py`.
  PASS CRITERION    : pytest process exit code == 0.
  DEFAULT IMAGE     : llm-codebench-python  (python:3.12-slim + pytest baked in;
                      built offline so the sandbox runs with --network none).

------------------------------------------------------------------------------
Language.typescript
------------------------------------------------------------------------------
  SOLUTION FILENAME : solution.ts
  TEST FILENAME     : tests.ts
  IMPORT / CALL     : the test file does
                      `import { <entrypoint> } from "./solution";`
                      (a NAMED export). The solution therefore `export`s
                      `<entrypoint>` (e.g. `export function twoSum(...) {}`).
  TEST RUNNER       : tsx, invoked as `tsx tests.ts`. The test file performs
                      its own assertions and MUST throw / call
                      `process.exit(1)` on failure and exit 0 on success
                      (a tiny inline `assert` helper is the convention; no
                      external test framework is required or available offline).
  PASS CRITERION    : node/tsx process exit code == 0.
  DEFAULT IMAGE     : llm-codebench-typescript (node:20-slim + tsx + typescript
                      baked in; built offline so the sandbox runs with
                      --network none — no npm install at run time).

------------------------------------------------------------------------------
Language.csharp
------------------------------------------------------------------------------
  SOLUTION FILENAME : Solution.cs
  TEST FILENAME     : Tests.cs
  IMPORT / CALL     : both files are compiled together into ONE console
                      project living in the image at /app (a pre-created,
                      pre-restored .csproj). At run time the sandbox copies
                      Solution.cs and Tests.cs into that project directory and
                      builds offline. There is no cross-file `import`: C# shares
                      symbols by namespace/assembly. Both files use the shared
                      namespace `Grok` (top of file: `namespace Grok;`). The
                      solution exposes a `public` class/method named
                      `<entrypoint>` (e.g. `public static class Solver`); the
                      Program entrypoint lives in Tests.cs, references it by
                      name, runs assertions, and returns a nonzero exit code on
                      failure.
  TEST RUNNER       : `dotnet run --no-restore` (restore already done at image
                      build time; run is fully offline).
  PASS CRITERION    : dotnet process exit code == 0.
  DEFAULT IMAGE     : llm-codebench-csharp (mcr.microsoft.com/dotnet/sdk:9.0 with
                      a warm, pre-restored console project so `dotnet run` needs
                      no network; falls back per T5 if 9.0 is unavailable).

------------------------------------------------------------------------------
Language.bash
------------------------------------------------------------------------------
  SOLUTION FILENAME : solution.sh
  TEST FILENAME     : tests.sh
  IMPORT / CALL     : the test file does `source ./solution.sh` (both files are
                      copied into the same working directory, so the relative
                      path resolves) and then invokes the shell FUNCTION named
                      `<entrypoint>`, which echoes its result to stdout. Tests
                      capture it via command substitution, e.g.
                      `result="$(word_count "$input")"`. The solution therefore
                      defines `<entrypoint>` as a function (e.g.
                      `word_count() { ... echo "$total"; }`), not a standalone
                      script.
  TEST RUNNER       : bash, invoked as `bash tests.sh`.
  PASS CRITERION    : bash process exit code == 0.
  PASS-CRITERION HARDENING (REQUIRED): a bash script's exit code is that of its
                      LAST command, so a tests.sh whose final line is a
                      successful `echo` would return 0 even after an earlier
                      assertion failed — silently always-passing. Every tests.sh
                      MUST therefore begin with `set -euo pipefail` AND use an
                      assert helper that calls `exit 1` on mismatch. The
                      canonical helper (use verbatim):

                          assert_eq() {  # assert_eq <got> <want> <msg>
                            if [ "$1" != "$2" ]; then
                              echo "FAIL $3: got '$1', want '$2'" >&2
                              exit 1
                            fi
                          }

                      This mirrors the TypeScript ABI's process.exit(1)
                      convention; no external test framework is used.
  DEFAULT IMAGE     : llm-codebench-bash (debian:12-slim + bash + GNU
                      coreutils/gawk/sed/grep baked in; built offline so the
                      sandbox runs with --network none).

Any `Problem.image_tag` overrides the DEFAULT IMAGE for that single problem
(e.g. a problem needing an extra runtime dependency). The override image MUST
still satisfy the SOLUTION/TEST filename + runner contract above.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# Reasoning-effort levels accepted by OpenRouter's unified ``reasoning.effort``
# param (mapped per-provider: Anthropic thinking budget, OpenAI reasoning effort,
# etc.). ``None`` means "send no reasoning field" — the model's own default.
Effort = Literal["low", "medium", "high"]
VALID_EFFORTS: tuple[str, ...] = ("low", "medium", "high")


def target_label(model_id: str, effort: str | None) -> str:
    """Display/grouping identity for one (model, effort) benchmark target.

    Single source of truth for how a variant reads in the leaderboard, CSV, and
    HTML report, e.g. ``"anthropic/claude-opus-4.8 (high)"``. With no effort the
    label is just the model id, so non-reasoning models are unchanged.
    """
    return model_id if effort is None else f"{model_id} ({effort})"


class Language(str, Enum):
    """Languages the harness can benchmark."""

    python = "python"
    csharp = "csharp"
    typescript = "typescript"
    bash = "bash"


class _Frozen(BaseModel):
    """Base for immutable value objects."""

    model_config = {"frozen": True}


class Problem(_Frozen):
    """A single coding problem, loaded from disk by T2.

    ``entrypoint`` is the symbol (function/class name) the solution must expose
    per the INVOCATION ABI in this module's docstring. ``image_tag`` optionally
    overrides the default per-language sandbox image. ``prompt_token_estimate``
    is a cheap chars/4 heuristic used by the dry-run cost estimator so pricing
    can happen without a tokenizer.
    """

    slug: str
    language: Language
    prompt: str
    tests: str
    solution: str
    difficulty: Literal["easy", "medium", "hard"]
    timeout_override: float | None = None
    entrypoint: str | None = None
    image_tag: str | None = None
    prompt_token_estimate: int = 0


class RunTarget(_Frozen):
    """A resolved benchmark target: one OpenRouter model at one reasoning effort.

    ``label`` is the display/grouping identity used everywhere results are keyed
    (leaderboard, CSV/JSON, HTML) — see :func:`target_label`. ``model`` is the
    real OpenRouter id sent on the wire; ``effort`` is passed via OpenRouter's
    ``reasoning.effort`` (``None`` = model default, no reasoning field sent).
    ``price_override`` mirrors :class:`ModelSpec` and is keyed by ``model``.
    """

    label: str
    model: str
    effort: Effort | None = None
    price_override: float | None = None


class RunConfig(_Frozen):
    """Resolved configuration for a single benchmark run (built by T1 config).

    ``models`` is the list of target *labels* (kept for provenance/back-compat);
    ``targets`` carries the resolved (model, effort) pairs the runner and cost
    estimator iterate. When ``targets`` is empty, consumers fall back to treating
    each ``models`` entry as a plain, effort-less target.
    """

    models: list[str]
    k: int
    temperature: float
    timeout: float
    max_spend_usd: float
    dry_run: bool
    prompt_style: Literal["strict", "loose"]
    max_tokens: int | None = None  # per-request completion cap; None = model default
    targets: list[RunTarget] = Field(default_factory=list)


class Attempt(_Frozen):
    """One model generation attempt for one problem.

    ``code`` is ``None`` when extraction found no usable code block (the attempt
    is then treated as a failure rather than crashing the run). ``ttft_ms`` is
    the streaming time-to-first-token; ``price_source`` records whether cost was
    computed from live API pricing or a config override.
    """

    code: str | None
    latency_ms: float
    ttft_ms: float | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    price_source: Literal["api", "config"]
    raw_response: str
    retries: int = 0  # network retries beyond the first try (0 = first-try OK)
    # Set when the API call itself failed (e.g. HTTP 402 out-of-credit, provider
    # 5xx after retries): the model was never sampled. Such attempts are reported
    # as an "api error" — distinct from a model emitting no code — and excluded
    # from pass@k so a billing/infra failure never scores as a wrong answer.
    error: str | None = None


class ExecResult(_Frozen):
    """The outcome of running one attempt's code against hidden tests in T5."""

    passed: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float
    timed_out: bool


class ProblemResult(_Frozen):
    """Scored result for one (model, problem) pair across ``k`` attempts.

    ``attempts`` and ``exec_results`` are index-aligned: ``exec_results[i]`` is
    the sandbox outcome for ``attempts[i]``.
    """

    model: str
    problem_slug: str
    language: Language
    pass_at_1: float
    pass_at_k: float
    attempts: list[Attempt]
    exec_results: list[ExecResult]
    difficulty: Literal["easy", "medium", "hard"] | None = None


class RunResult(_Frozen):
    """Top-level aggregate for an entire run; consumed by the T7 reporter."""

    results: list[ProblemResult]
    total_cost_usd: float
    total_latency_ms: float
    models: list[str]
    problems_count: int
    k: int
    total_retries: int = 0  # sum of Attempt.retries across the whole run
    # -- run provenance (methodology header); optional so older callers/tests
    #    that build a RunResult without them keep working.
    temperature: float | None = None
    timeout: float | None = None
    prompt_style: str | None = None
    generated_at: str | None = None  # ISO-8601 UTC timestamp of the run


class ModelSpec(_Frozen):
    """One entry from config/models.yaml.

    ``price_override`` is USD per token; when set, attempts against this model
    record ``price_source="config"`` instead of ``"api"``. ``efforts`` is an
    optional fan-out list of reasoning-effort levels: one entry with
    ``efforts: [low, medium, high]`` expands into three benchmark targets sharing
    the same model id. Absent/empty ``efforts`` means a single effort-less target.
    """

    id: str
    price_override: float | None = Field(default=None)
    efforts: list[Effort] | None = Field(default=None)


__all__ = [
    "Language",
    "Effort",
    "VALID_EFFORTS",
    "target_label",
    "Problem",
    "RunConfig",
    "RunTarget",
    "Attempt",
    "ExecResult",
    "ProblemResult",
    "RunResult",
    "ModelSpec",
]
