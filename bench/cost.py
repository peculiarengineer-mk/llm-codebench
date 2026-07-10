"""Cost estimation and the spend guardrail (T6, part 1).

``estimate_run`` prices a whole run *before* any paid call (the ``--dry-run``
surface). ``SpendGuard`` is an async-safe accumulator that stops the run once
actual spend would exceed the configured cap.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from bench.openrouter import ModelPricing
from bench.types import Problem, RunConfig, RunTarget

# Heuristic: base completion length (tokens) for one attempt's *answer* — the
# fenced solution — before any reasoning tokens. A full multi-language solution
# routinely runs 800-2000 tokens, so 1200 is a middle estimate.
DEFAULT_COMPLETION_TOKENS = 1200

# Additional billed output (thinking) tokens assumed per reasoning-effort level.
# Reasoning models emit these on top of the visible answer and OpenRouter bills
# them as completion tokens, so a high-effort variant costs materially more than
# a low-effort one. Rough, deliberately order-of-magnitude figures — tune freely.
# An effort-less target (None) adds nothing.
REASONING_TOKENS: dict[str, int] = {"low": 1000, "medium": 4000, "high": 10000}

# Fixed prompt overhead (tokens) added by the strict/loose instruction wrapper.
PROMPT_WRAPPER_TOKENS = 80


@dataclass(frozen=True)
class ModelCostEstimate:
    model: str
    calls: int
    est_prompt_tokens: int
    est_completion_tokens: int
    est_cost_usd: float
    priced: bool  # False when pricing for this model was unknown (cost=0)


@dataclass(frozen=True)
class CostEstimate:
    per_model: list[ModelCostEstimate] = field(default_factory=list)

    @property
    def total_calls(self) -> int:
        return sum(m.calls for m in self.per_model)

    @property
    def total_cost_usd(self) -> float:
        return sum(m.est_cost_usd for m in self.per_model)

    @property
    def has_unpriced(self) -> bool:
        return any(not m.priced for m in self.per_model)


def estimate_run(
    config: RunConfig,
    problems: list[Problem],
    pricing: dict[str, ModelPricing],
    *,
    completion_tokens: int = DEFAULT_COMPLETION_TOKENS,
) -> CostEstimate:
    """Estimate the cost of ``config`` over ``problems`` using ``pricing``.

    Counts model × problem × k calls, estimates prompt tokens from each
    problem's chars/4 heuristic (+ wrapper overhead) and completion tokens from a
    fixed heuristic, and prices them. Models missing from ``pricing`` are counted
    but contribute $0 and flag ``priced=False``.
    """
    per_model: list[ModelCostEstimate] = []
    prompt_tokens_total = sum(p.prompt_token_estimate + PROMPT_WRAPPER_TOKENS for p in problems)

    # Iterate resolved targets so each reasoning-effort variant is a distinct
    # priced row; fall back to plain model ids for pre-variant configs. Pricing
    # is keyed by the real model id, the row is labelled by the variant.
    targets = config.targets or [RunTarget(label=m, model=m) for m in config.models]
    for target in targets:
        calls = len(problems) * config.k
        est_prompt = prompt_tokens_total * config.k
        # Higher reasoning effort adds billed thinking tokens on top of the answer.
        per_call_completion = completion_tokens + REASONING_TOKENS.get(target.effort or "", 0)
        est_completion = len(problems) * config.k * per_call_completion
        price = pricing.get(target.model)
        if price is None:
            per_model.append(
                ModelCostEstimate(target.label, calls, est_prompt, est_completion, 0.0, False)
            )
        else:
            cost = price.cost(est_prompt, est_completion)
            per_model.append(
                ModelCostEstimate(target.label, calls, est_prompt, est_completion, cost, True)
            )
    return CostEstimate(per_model=per_model)


class SpendCapExceeded(RuntimeError):
    """Raised/flagged when the run's spend cap is hit."""


class SpendGuard:
    """Async-safe accumulator that halts a run at ``max_spend_usd``.

    Usage per attempt::

        if not await guard.can_proceed():
            break                 # cap already reached — stop launching calls
        attempt = await client.complete(...)
        await guard.record(attempt.cost_usd)

    ``can_proceed`` returns False once accumulated spend has reached the cap, so
    in-flight calls finish but no new ones start.
    """

    def __init__(self, max_spend_usd: float) -> None:
        self._cap = max_spend_usd
        self._spent = 0.0
        self._lock = asyncio.Lock()
        self.stopped = False
        self.abort_reason: str | None = None

    @property
    def spent(self) -> float:
        return self._spent

    @property
    def cap(self) -> float:
        return self._cap

    def abort(self, reason: str) -> None:
        """Halt the run for a non-spend reason (e.g. a fatal auth/billing error).

        Idempotent — the first reason wins, so the message reflects the failure
        that actually stopped the run. ``can_proceed`` returns False thereafter.

        No lock is taken: asyncio is single-threaded and this method never awaits,
        so the check-then-set runs atomically with respect to other coroutines.
        """
        if self.abort_reason is None:
            self.abort_reason = reason
        self.stopped = True

    async def can_proceed(self) -> bool:
        async with self._lock:
            if self.abort_reason is not None:
                return False
            if self._spent >= self._cap:
                self.stopped = True
                return False
            return True

    async def record(self, cost_usd: float) -> None:
        async with self._lock:
            self._spent += cost_usd
            if self._spent >= self._cap:
                self.stopped = True


__all__ = [
    "estimate_run",
    "CostEstimate",
    "ModelCostEstimate",
    "SpendGuard",
    "SpendCapExceeded",
    "DEFAULT_COMPLETION_TOKENS",
    "REASONING_TOKENS",
]
