"""Tests for reasoning-effort model variants (config fan-out + wire param)."""

import asyncio
import json

import httpx
import pytest

from bench.config import build_run_config, expand_targets
from bench.cost import estimate_run
from bench.openrouter import ModelPricing, OpenRouterClient, OpenRouterError
from bench.runner import run_benchmark
from bench.types import Language, ModelSpec, Problem, RunConfig, target_label


# --------------------------------------------------------------------------- #
# Labels + target expansion
# --------------------------------------------------------------------------- #


def test_target_label_format():
    assert target_label("anthropic/claude-opus-4.8", None) == "anthropic/claude-opus-4.8"
    assert target_label("anthropic/claude-opus-4.8", "high") == "anthropic/claude-opus-4.8 (high)"


def test_expand_fans_out_efforts():
    specs = [ModelSpec(id="m", efforts=["low", "medium", "high"])]
    targets = expand_targets(specs)
    assert [t.label for t in targets] == ["m (low)", "m (medium)", "m (high)"]
    assert all(t.model == "m" for t in targets)
    assert [t.effort for t in targets] == ["low", "medium", "high"]


def test_expand_no_efforts_is_single_plain_target():
    targets = expand_targets([ModelSpec(id="m")])
    assert len(targets) == 1
    assert targets[0].label == "m"
    assert targets[0].effort is None


def test_expand_override_wins_over_entry_efforts():
    specs = [ModelSpec(id="m", efforts=["low"])]
    targets = expand_targets(specs, efforts_override=["high", "medium"])
    assert [t.effort for t in targets] == ["high", "medium"]


def test_price_override_carried_onto_each_variant():
    specs = [ModelSpec(id="m", price_override=0.001, efforts=["low", "high"])]
    targets = expand_targets(specs)
    assert all(t.price_override == 0.001 for t in targets)


# --------------------------------------------------------------------------- #
# build_run_config wiring
# --------------------------------------------------------------------------- #


def test_build_run_config_efforts_override(tmp_path):
    yaml_path = tmp_path / "models.yaml"
    yaml_path.write_text("models:\n  - id: m\n", encoding="utf-8")
    cfg = build_run_config(models=["m"], efforts=["low", "high"], models_yaml=yaml_path)
    assert cfg.models == ["m (low)", "m (high)"]
    assert [t.effort for t in cfg.targets] == ["low", "high"]


def test_build_run_config_reads_entry_efforts(tmp_path):
    yaml_path = tmp_path / "models.yaml"
    yaml_path.write_text(
        "models:\n  - id: m\n    efforts: [low, medium]\n", encoding="utf-8"
    )
    cfg = build_run_config(models_yaml=yaml_path)
    assert cfg.models == ["m (low)", "m (medium)"]


def test_invalid_effort_rejected(tmp_path):
    yaml_path = tmp_path / "models.yaml"
    yaml_path.write_text("models:\n  - id: m\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid effort"):
        build_run_config(models=["m"], efforts=["turbo"], models_yaml=yaml_path)


# --------------------------------------------------------------------------- #
# Cost estimate rows per variant
# --------------------------------------------------------------------------- #


def _problem() -> Problem:
    return Problem(
        slug="a", language=Language.python, prompt="x" * 40, tests="",
        solution="", difficulty="easy", prompt_token_estimate=10,
    )


def test_estimate_one_row_per_variant_priced_by_real_id():
    targets = expand_targets([ModelSpec(id="m", efforts=["low", "high"])])
    cfg = RunConfig(
        models=[t.label for t in targets], k=1, temperature=0.7, timeout=10.0,
        max_spend_usd=5.0, dry_run=True, prompt_style="strict", targets=targets,
    )
    pricing = {"m": ModelPricing(0.001, 0.002, "api")}  # keyed by real id, not label
    est = estimate_run(cfg, [_problem()], pricing)
    assert [r.model for r in est.per_model] == ["m (low)", "m (high)"]
    assert all(r.priced for r in est.per_model)  # both variants found pricing via "m"


def test_higher_effort_estimates_more_completion_tokens():
    from bench.cost import DEFAULT_COMPLETION_TOKENS, REASONING_TOKENS

    targets = expand_targets([ModelSpec(id="m", efforts=["low", "high"])])
    cfg = RunConfig(
        models=[t.label for t in targets], k=1, temperature=0.7, timeout=10.0,
        max_spend_usd=5.0, dry_run=True, prompt_style="strict", targets=targets,
    )
    est = estimate_run(cfg, [_problem()], {})
    low, high = est.per_model
    # one problem, k=1 -> completion == base + per-effort reasoning budget
    assert low.est_completion_tokens == DEFAULT_COMPLETION_TOKENS + REASONING_TOKENS["low"]
    assert high.est_completion_tokens == DEFAULT_COMPLETION_TOKENS + REASONING_TOKENS["high"]
    assert high.est_completion_tokens > low.est_completion_tokens


def test_effortless_target_adds_no_reasoning_tokens():
    from bench.cost import DEFAULT_COMPLETION_TOKENS

    cfg = RunConfig(
        models=["m"], k=1, temperature=0.7, timeout=10.0,
        max_spend_usd=5.0, dry_run=True, prompt_style="strict",
    )
    est = estimate_run(cfg, [_problem()], {})
    assert est.per_model[0].est_completion_tokens == DEFAULT_COMPLETION_TOKENS


# --------------------------------------------------------------------------- #
# Wire param: reasoning.effort
# --------------------------------------------------------------------------- #


def _sse(*chunks: str) -> bytes:
    return "".join(f"data: {c}\n\n" for c in chunks).encode()


_BODY = _sse(
    '{"choices":[{"delta":{"content":"ok"}}]}',
    '{"choices":[{"delta":{}}],"usage":{"prompt_tokens":1,"completion_tokens":1}}',
    "[DONE]",
)


@pytest.mark.asyncio
async def test_effort_sends_reasoning_param():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, content=_BODY)

    client = OpenRouterClient("k")
    client._client = httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(handler),
    )
    client._price_overrides = {}
    client._pricing_cache = {"m": ModelPricing(0.0, 0.0, "api")}
    async with client:
        await client.complete("m", "p", 0.0, effort="high")
    assert captured["payload"]["reasoning"] == {"effort": "high"}


@pytest.mark.asyncio
async def test_no_effort_omits_reasoning_param():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, content=_BODY)

    client = OpenRouterClient("k")
    client._client = httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(handler),
    )
    client._price_overrides = {}
    client._pricing_cache = {"m": ModelPricing(0.0, 0.0, "api")}
    async with client:
        await client.complete("m", "p", 0.0)
    assert "reasoning" not in captured["payload"]


@pytest.mark.asyncio
async def test_max_tokens_forwarded_to_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, content=_BODY)

    client = OpenRouterClient("k")
    client._client = httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(handler),
    )
    client._price_overrides = {}
    client._pricing_cache = {"m": ModelPricing(0.0, 0.0, "api")}
    async with client:
        await client.complete("m", "p", 0.0, max_tokens=4000)
    assert captured["payload"]["max_tokens"] == 4000


# --------------------------------------------------------------------------- #
# Resilience: one model's API failure must not abort the whole run
# --------------------------------------------------------------------------- #


class _FailingClient:
    """Stub OpenRouterClient whose every completion raises (e.g. HTTP 402)."""

    async def complete(self, *a, **kw):
        raise OpenRouterError("HTTP 402 from OpenRouter: out of credits")


def test_run_survives_api_failure_and_records_it():
    problems = [_problem()]
    targets = expand_targets([ModelSpec(id="m")])
    cfg = RunConfig(
        models=["m"], k=2, temperature=0.7, timeout=10.0, max_spend_usd=5.0,
        dry_run=False, prompt_style="strict", targets=targets,
    )
    run = asyncio.run(run_benchmark(cfg, problems, _FailingClient()))
    # The run completes instead of crashing; the failure is captured, not passed.
    assert len(run.results) == 1
    pr = run.results[0]
    assert pr.pass_at_k == 0.0
    assert all(e.exit_code == -1 for e in pr.exec_results)
    assert "402" in pr.exec_results[0].stderr
