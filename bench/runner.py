"""Runner: compose client + sandbox + scoring into a RunResult (T6, part 2).

Orchestrates model × problem × k attempts with bounded concurrency, extracts
code, executes it in the sandbox, scores pass@k with the unbiased estimator, and
aggregates latency/tokens/cost — all under the :class:`SpendGuard` cap.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from math import comb

from bench.cost import CostEstimate, SpendGuard, estimate_run
from bench.extract import extract_code
from bench.openrouter import (
    FATAL_STATUS,
    ModelPricing,
    OpenRouterClient,
    OpenRouterError,
)
from bench.problems import render_prompt
from bench.sandbox import run_in_sandbox
from bench.types import (
    Attempt,
    ExecResult,
    Problem,
    ProblemResult,
    RunConfig,
    RunResult,
    RunTarget,
)


def resolve_targets(config: RunConfig) -> list[RunTarget]:
    """The benchmark targets for a run, back-compatible with older callers.

    Uses ``config.targets`` when present; otherwise treats each ``config.models``
    entry as a plain, effort-less target so configs built before reasoning-effort
    variants existed still run unchanged.
    """
    if config.targets:
        return list(config.targets)
    return [RunTarget(label=m, model=m) for m in config.models]


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k estimator (Chen et al., 2021).

    ``n`` total samples, ``c`` correct, ``k`` the k in pass@k::

        pass@k = 1 - C(n - c, k) / C(n, k)

    ``k`` is clamped to ``n`` (you cannot ask about more picks than samples).
    Returns 0.0 when nothing passed, 1.0 when every remaining pick must contain
    a correct sample.
    """
    if n <= 0:
        return 0.0
    k = min(k, n)
    if c <= 0:
        return 0.0
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


async def _run_one_attempt(
    client: OpenRouterClient,
    target: RunTarget,
    problem: Problem,
    config: RunConfig,
    guard: SpendGuard,
) -> tuple[Attempt, ExecResult]:
    """One generation + sandbox execution for a (target, problem)."""
    prompt = render_prompt(problem, config.prompt_style)
    try:
        attempt = await client.complete(
            target.model,
            prompt,
            config.temperature,
            effort=target.effort,
            max_tokens=config.max_tokens,
        )
    except OpenRouterError as exc:
        # A per-attempt API failure (e.g. provider 5xx after retries) must not
        # abort the whole multi-model run: record it as a failed attempt and let
        # every other (target, problem) proceed. But an auth/billing failure
        # (401/402/403) won't fix itself, so signal a run-wide abort — the rest
        # of the queued attempts then short-circuit instead of hammering the API.
        if exc.status_code in FATAL_STATUS:
            guard.abort(
                f"Run aborted — OpenRouter returned HTTP {exc.status_code} "
                f"(auth/billing). Top up or check the key; no further calls made."
            )
        attempt = Attempt(
            code=None,
            latency_ms=0.0,
            ttft_ms=None,
            prompt_tokens=0,
            completion_tokens=0,
            cost_usd=0.0,
            price_source="api",
            raw_response="",
            error=str(exc),
        )
        exec_result = ExecResult(
            passed=False,
            stdout="",
            stderr=f"API error (no attempt made): {exc}",
            exit_code=-1,
            duration_ms=0.0,
            timed_out=False,
        )
        return attempt, exec_result
    await guard.record(attempt.cost_usd)

    code = extract_code(attempt.raw_response, problem.language)
    attempt = attempt.model_copy(update={"code": code})

    if code is None:
        exec_result = ExecResult(
            passed=False,
            stdout="",
            stderr="no extractable code block in model response",
            exit_code=-1,
            duration_ms=0.0,
            timed_out=False,
        )
        return attempt, exec_result

    timeout = problem.timeout_override or config.timeout
    exec_result = await run_in_sandbox(
        problem.language,
        code,
        problem.tests,
        timeout=timeout,
        image_tag=problem.image_tag,
    )
    return attempt, exec_result


async def _run_problem_for_model(
    client: OpenRouterClient,
    target: RunTarget,
    problem: Problem,
    config: RunConfig,
    guard: SpendGuard,
    sem: asyncio.Semaphore,
) -> ProblemResult:
    """Run all ``k`` attempts for one (target, problem) and score them."""
    attempts: list[Attempt] = []
    exec_results: list[ExecResult] = []

    for _ in range(config.k):
        if not await guard.can_proceed():
            break
        async with sem:
            # Re-check after acquiring a slot: an abort (fatal API error) or the
            # spend cap may have tripped while this attempt was queued behind the
            # semaphore, so don't fire a call that's already known to be futile.
            if not await guard.can_proceed():
                break
            attempt, exec_result = await _run_one_attempt(
                client, target, problem, config, guard
            )
        attempts.append(attempt)
        exec_results.append(exec_result)

    # Score only attempts that actually reached the model. An attempt that failed
    # at the API layer (e.g. HTTP 402) never sampled it, so counting it toward
    # pass@k would penalize the model for a billing/infra failure.
    scored = [(a, e) for a, e in zip(attempts, exec_results) if a.error is None]
    n = len(scored)
    c = sum(1 for _, e in scored if e.passed)
    return ProblemResult(
        model=target.label,
        problem_slug=problem.slug,
        language=problem.language,
        pass_at_1=pass_at_k(n, c, 1) if n else 0.0,
        pass_at_k=pass_at_k(n, c, config.k) if n else 0.0,
        attempts=attempts,
        exec_results=exec_results,
        difficulty=problem.difficulty,
    )


async def run_benchmark(
    config: RunConfig,
    problems: list[Problem],
    client: OpenRouterClient,
    *,
    concurrency: int = 4,
    guard: SpendGuard | None = None,
) -> RunResult:
    """Execute the full benchmark and return an aggregated :class:`RunResult`.

    Runs every (model, problem) pair concurrently up to ``concurrency`` in-flight
    API calls, honoring the spend cap via ``guard`` (created from
    ``config.max_spend_usd`` if not supplied).
    """
    guard = guard or SpendGuard(config.max_spend_usd)
    sem = asyncio.Semaphore(concurrency)
    targets = resolve_targets(config)

    tasks = [
        _run_problem_for_model(client, target, problem, config, guard, sem)
        for target in targets
        for problem in problems
    ]
    wall_start = time.perf_counter()
    results: list[ProblemResult] = await asyncio.gather(*tasks)
    wall_time_ms = (time.perf_counter() - wall_start) * 1000.0

    total_cost = sum(a.cost_usd for r in results for a in r.attempts)
    # Cumulative per-attempt latency (compute time). NOT wall-clock: attempts run
    # concurrently, so this sums overlapping requests — wall_time_ms is the real
    # elapsed duration of the run.
    total_latency = sum(a.latency_ms for r in results for a in r.attempts)
    total_retries = sum(a.retries for r in results for a in r.attempts)

    return RunResult(
        results=results,
        total_cost_usd=total_cost,
        total_latency_ms=total_latency,
        models=[t.label for t in targets],
        problems_count=len(problems),
        k=config.k,
        total_retries=total_retries,
        temperature=config.temperature,
        timeout=config.timeout,
        prompt_style=config.prompt_style,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        aborted_reason=guard.abort_reason,
        wall_time_ms=wall_time_ms,
    )


def dry_run_estimate(
    config: RunConfig,
    problems: list[Problem],
    pricing: dict[str, ModelPricing],
) -> CostEstimate:
    """Convenience wrapper around :func:`bench.cost.estimate_run` for the CLI."""
    return estimate_run(config, problems, pricing)


__all__ = ["run_benchmark", "pass_at_k", "dry_run_estimate", "resolve_targets"]
