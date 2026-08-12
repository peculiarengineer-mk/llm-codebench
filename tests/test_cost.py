"""Unit tests for bench.cost estimation and the spend guard (T6)."""

import asyncio

import pytest

from bench.cost import (
    DEFAULT_COMPLETION_TOKENS,
    PROMPT_WRAPPER_TOKENS,
    SpendGuard,
    estimate_run,
)
from bench.openrouter import ModelPricing
from bench.types import Language, Problem, RunConfig


def _problem(slug: str, token_est: int) -> Problem:
    return Problem(
        slug=slug,
        language=Language.python,
        prompt="x" * (token_est * 4),
        tests="",
        solution="",
        difficulty="easy",
        prompt_token_estimate=token_est,
    )


def _config(models, k) -> RunConfig:
    return RunConfig(
        models=models, k=k, temperature=0.7, timeout=10.0,
        max_spend_usd=5.0, dry_run=True, prompt_style="strict",
    )


def test_estimate_arithmetic():
    problems = [_problem("a", 100), _problem("b", 200)]
    config = _config(["m"], k=3)
    pricing = {"m": ModelPricing(0.001, 0.002, "api")}

    est = estimate_run(config, problems, pricing)
    assert est.total_calls == 2 * 3  # 2 problems x k=3

    m = est.per_model[0]
    # prompt tokens = sum(est + wrapper) * k
    expected_prompt = (100 + PROMPT_WRAPPER_TOKENS + 200 + PROMPT_WRAPPER_TOKENS) * 3
    expected_completion = 2 * 3 * DEFAULT_COMPLETION_TOKENS
    assert m.est_prompt_tokens == expected_prompt
    assert m.est_completion_tokens == expected_completion
    expected_cost = expected_prompt * 0.001 + expected_completion * 0.002
    assert m.est_cost_usd == pytest.approx(expected_cost)
    assert m.priced is True


def test_estimate_unpriced_model():
    est = estimate_run(_config(["unknown"], k=1), [_problem("a", 10)], {})
    assert est.per_model[0].priced is False
    assert est.per_model[0].est_cost_usd == 0.0
    assert est.has_unpriced


def test_spend_guard_stops_at_cap():
    async def run():
        guard = SpendGuard(1.0)
        assert await guard.can_proceed() is True
        await guard.record(0.6)
        assert await guard.can_proceed() is True  # 0.6 < 1.0
        await guard.record(0.6)  # now 1.2 >= 1.0
        assert guard.stopped is True
        assert await guard.can_proceed() is False
        assert guard.spent == pytest.approx(1.2)

    asyncio.run(run())


def test_spend_guard_concurrent_records():
    async def run():
        guard = SpendGuard(1000.0)
        await asyncio.gather(*(guard.record(1.0) for _ in range(100)))
        assert guard.spent == pytest.approx(100.0)

    asyncio.run(run())


def test_every_valid_effort_has_a_reasoning_estimate():
    """Guard the enum↔heuristic coupling that under-priced xhigh/max.

    `estimate_run` used `REASONING_TOKENS.get(effort, 0)`, so a level present in
    VALID_EFFORTS but absent here silently estimated ZERO reasoning tokens —
    making the deepest targets look cheaper than low effort, the one direction a
    spend cap must never be wrong in. bench.cost now raises at import instead;
    this pins that the two stay in sync.
    """
    from bench.cost import REASONING_TOKENS
    from bench.types import VALID_EFFORTS

    assert set(REASONING_TOKENS) == set(VALID_EFFORTS)


def test_reasoning_estimates_increase_with_effort():
    """Deeper effort must never estimate cheaper than a shallower one."""
    from bench.cost import REASONING_TOKENS
    from bench.types import VALID_EFFORTS

    ladder = [REASONING_TOKENS[e] for e in VALID_EFFORTS]
    assert ladder == sorted(ladder)
    assert len(set(ladder)) == len(ladder)  # strictly increasing, no ties


def test_estimated_cost_rises_monotonically_across_the_ladder():
    """End-to-end through estimate_run: the priced ladder is ordered.

    This is the regression for the observed bug — a full-roster --dry-run showed
    `(xhigh)` and `(max)` pricing *below* `(low)` because both fell through to the
    no-reasoning baseline.
    """
    from bench.config import expand_targets
    from bench.types import VALID_EFFORTS, ModelSpec

    problems = [_problem("a", 100)]
    targets = expand_targets([ModelSpec(id="m", efforts=list(VALID_EFFORTS))])
    config = _config(["m"], k=1)
    config = config.model_copy(update={"targets": targets})
    est = estimate_run(config, problems, {"m": ModelPricing(0.001, 0.002, "api")})

    costs = [row.est_cost_usd for row in est.per_model]
    assert len(costs) == len(VALID_EFFORTS)
    assert costs == sorted(costs)
    # the effort-less baseline must be cheapest of all
    base = estimate_run(
        config.model_copy(update={"targets": expand_targets([ModelSpec(id="m")])}),
        problems,
        {"m": ModelPricing(0.001, 0.002, "api")},
    )
    assert base.per_model[0].est_cost_usd < costs[0]
