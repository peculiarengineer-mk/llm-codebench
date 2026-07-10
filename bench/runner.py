"""Runner: compose client + sandbox + scoring into a RunResult (T6, part 2).

Orchestrates model × problem × k attempts with bounded concurrency, extracts
code, executes it in the sandbox, scores pass@k with the unbiased estimator, and
aggregates latency/tokens/cost — all under the :class:`SpendGuard` cap.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from math import comb

from bench.cost import CostEstimate, SpendGuard, estimate_run
from bench.extract import extract_code
from bench.openrouter import ModelPricing, OpenRouterClient
from bench.problems import render_prompt
from bench.sandbox import run_in_sandbox
from bench.types import (
    Attempt,
    ExecResult,
    Problem,
    ProblemResult,
    RunConfig,
    RunResult,
)


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
    model: str,
    problem: Problem,
    config: RunConfig,
    guard: SpendGuard,
) -> tuple[Attempt, ExecResult]:
    """One generation + sandbox execution for a (model, problem)."""
    prompt = render_prompt(problem, config.prompt_style)
    attempt = await client.complete(model, prompt, config.temperature)
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
    model: str,
    problem: Problem,
    config: RunConfig,
    guard: SpendGuard,
    sem: asyncio.Semaphore,
) -> ProblemResult:
    """Run all ``k`` attempts for one (model, problem) and score them."""
    attempts: list[Attempt] = []
    exec_results: list[ExecResult] = []

    for _ in range(config.k):
        if not await guard.can_proceed():
            break
        async with sem:
            attempt, exec_result = await _run_one_attempt(
                client, model, problem, config, guard
            )
        attempts.append(attempt)
        exec_results.append(exec_result)

    n = len(attempts)
    c = sum(1 for e in exec_results if e.passed)
    return ProblemResult(
        model=model,
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

    tasks = [
        _run_problem_for_model(client, model, problem, config, guard, sem)
        for model in config.models
        for problem in problems
    ]
    results: list[ProblemResult] = await asyncio.gather(*tasks)

    total_cost = sum(a.cost_usd for r in results for a in r.attempts)
    total_latency = sum(a.latency_ms for r in results for a in r.attempts)
    total_retries = sum(a.retries for r in results for a in r.attempts)

    return RunResult(
        results=results,
        total_cost_usd=total_cost,
        total_latency_ms=total_latency,
        models=list(config.models),
        problems_count=len(problems),
        k=config.k,
        total_retries=total_retries,
        temperature=config.temperature,
        timeout=config.timeout,
        prompt_style=config.prompt_style,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def dry_run_estimate(
    config: RunConfig,
    problems: list[Problem],
    pricing: dict[str, ModelPricing],
) -> CostEstimate:
    """Convenience wrapper around :func:`bench.cost.estimate_run` for the CLI."""
    return estimate_run(config, problems, pricing)


__all__ = ["run_benchmark", "pass_at_k", "dry_run_estimate"]
