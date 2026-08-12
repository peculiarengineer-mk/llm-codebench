"""Tests for reasoning-effort model variants (config fan-out + wire param)."""

import asyncio
import json

import httpx
import pytest

from bench.config import build_run_config, expand_targets
from bench.cost import estimate_run
from bench.openrouter import ModelPricing, OpenRouterClient, OpenRouterError
from bench.runner import run_benchmark
from bench.types import (
    Attempt,
    ExecResult,
    Language,
    ModelSpec,
    Problem,
    RunConfig,
    target_label,
)


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
    # API failures are structurally flagged, not silently bucketed as "no code".
    assert all(a.error is not None for a in pr.attempts)


def test_fatal_402_aborts_run_early_instead_of_hammering():
    """A billing 402 halts the whole run; queued attempts short-circuit."""
    calls = {"n": 0}

    class Fatal402Client:
        async def complete(self, *a, **kw):
            calls["n"] += 1
            raise OpenRouterError("HTTP 402: out of credits", status_code=402)

    # 3 problems x k=3 = 9 attempts if it hammered; abort should cut it far short.
    problems = [_problem(), _problem(), _problem()]
    targets = expand_targets([ModelSpec(id="m")])
    cfg = RunConfig(
        models=["m"], k=3, temperature=0.7, timeout=10.0, max_spend_usd=5.0,
        dry_run=False, prompt_style="strict", targets=targets,
    )
    run = asyncio.run(run_benchmark(cfg, problems, Fatal402Client(), concurrency=1))
    assert run.aborted_reason is not None
    assert "402" in run.aborted_reason
    # With concurrency=1 the abort trips on attempt 1, so the remaining 8 are
    # skipped — far fewer than the 9 a non-aborting run would have made.
    assert calls["n"] == 1


def test_api_error_classified_distinctly_from_no_code():
    from bench.report import _classify
    from bench.types import ExecResult

    fail_ex = ExecResult(passed=False, stdout="", stderr="x", exit_code=-1,
                         duration_ms=0.0, timed_out=False)
    api = Attempt(code=None, latency_ms=0.0, ttft_ms=None, prompt_tokens=0,
                  completion_tokens=0, cost_usd=0.0, price_source="api",
                  raw_response="", error="HTTP 402")
    no_code = api.model_copy(update={"error": None})
    assert _classify(api, fail_ex) == "api_error"
    assert _classify(no_code, fail_ex) == "no_code"


def test_content_filter_classified_as_filtered_not_no_code():
    """A provider safety-filter block (empty 200) is 'filtered', not 'no code'."""
    from bench.report import _classify
    from bench.types import ExecResult

    fail_ex = ExecResult(passed=False, stdout="", stderr="x", exit_code=-1,
                         duration_ms=0.0, timed_out=False)
    # Empty content + finish_reason=content_filter, no api-layer error.
    filtered = Attempt(code=None, latency_ms=1.0, ttft_ms=None, prompt_tokens=5,
                       completion_tokens=1, cost_usd=0.0, price_source="api",
                       raw_response="", error=None, finish_reason="content_filter")
    assert _classify(filtered, fail_ex) == "filtered"
    # Same empty reply but a normal stop reason stays 'no code'.
    plain = filtered.model_copy(update={"finish_reason": "stop"})
    assert _classify(plain, fail_ex) == "no_code"


def test_filter_trip_with_usable_code_scores_normally():
    """Regression guard (finding #1): a filter trip that still streamed a full
    code fence is a genuine sample — classify on execution, not the flag."""
    from bench.report import _classify
    from bench.types import ExecResult

    ok_ex = ExecResult(passed=True, stdout="", stderr="", exit_code=0,
                       duration_ms=1.0, timed_out=False)
    att = Attempt(code="print('hi')", latency_ms=1.0, ttft_ms=1.0,
                  prompt_tokens=5, completion_tokens=10, cost_usd=0.0,
                  price_source="api", raw_response="```python\nprint('hi')\n```",
                  error=None, finish_reason="content_filter")
    # Pre-narrowing `filtered` was finish_reason alone, so a filtered attempt
    # carrying passing code was excluded from pass@k: the first two assertions
    # fail under that contract.
    assert not att.filtered
    assert att.sampled
    assert _classify(att, ok_ex) == "pass"


@pytest.mark.asyncio
async def test_stream_captures_content_filter_finish_reason():
    """The client records finish_reason so a filtered reply is diagnosable."""
    captured = {}

    body = _sse(
        '{"choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}',
        '{"choices":[{"delta":{},"finish_reason":"content_filter"}]}',
        '{"choices":[{"delta":{}}],"usage":{"prompt_tokens":5,"completion_tokens":1}}',
        "[DONE]",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, content=body)

    client = OpenRouterClient("k")
    client._client = httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(handler),
    )
    client._price_overrides = {}
    client._pricing_cache = {"m": ModelPricing(0.0, 0.0, "api")}
    async with client:
        attempt = await client.complete("m", "p", 0.0, effort="medium")
    assert attempt.finish_reason == "content_filter"
    assert attempt.raw_response == ""  # blocked: no content


def test_errored_attempts_excluded_so_one_real_pass_counts(monkeypatch):
    """One real passing attempt among 402s => problem solved (errors ignored)."""
    from bench import runner as R

    calls = {"n": 0}

    class MixedClient:
        async def complete(self, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:  # first attempt reaches the model and answers
                return Attempt(
                    code=None, latency_ms=1.0, ttft_ms=1.0, prompt_tokens=1,
                    completion_tokens=1, cost_usd=0.0, price_source="api",
                    raw_response="ok",
                )
            raise OpenRouterError("HTTP 402 from OpenRouter")  # rest run out of credit

    async def fake_sandbox(*a, **kw):
        return ExecResult(passed=True, stdout="", stderr="", exit_code=0,
                         duration_ms=1.0, timed_out=False)

    monkeypatch.setattr(R, "extract_code", lambda raw, lang: "code")
    monkeypatch.setattr(R, "run_in_sandbox", fake_sandbox)

    cfg = RunConfig(
        models=["m"], k=3, temperature=0.7, timeout=10.0, max_spend_usd=5.0,
        dry_run=False, prompt_style="strict",
        targets=expand_targets([ModelSpec(id="m")]),
    )
    run = asyncio.run(run_benchmark(cfg, [_problem()], MixedClient()))
    pr = run.results[0]
    assert pr.pass_at_k == 1.0  # single real sample passed; the two 402s ignored
    assert sum(1 for a in pr.attempts if a.error is not None) == 2


def test_filtered_attempt_excluded_from_passk_and_stderr_wired(monkeypatch):
    """End-to-end: a filter block with no code is excluded from pass@k, and the
    runner writes the finish_reason=content_filter stderr for the drill-down."""
    from bench import runner as R

    calls = {"n": 0}

    class PartlyFilteredClient:
        async def complete(self, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:  # provider blocks the first reply outright
                return Attempt(
                    code=None, latency_ms=1.0, ttft_ms=None, prompt_tokens=5,
                    completion_tokens=1, cost_usd=0.0, price_source="api",
                    raw_response="", finish_reason="content_filter",
                )
            # the remaining attempts reach the model — one right, one wrong
            return Attempt(
                code=None, latency_ms=1.0, ttft_ms=1.0, prompt_tokens=5,
                completion_tokens=5, cost_usd=0.0, price_source="api",
                raw_response="pass" if calls["n"] == 2 else "fail",
            )

    async def fake_sandbox(*a, **kw):
        passed = a[1] == "pass"  # a[1] is the extracted code
        return ExecResult(passed=passed, stdout="", stderr="",
                          exit_code=0 if passed else 1,
                          duration_ms=1.0, timed_out=False)

    monkeypatch.setattr(R, "extract_code", lambda raw, lang: raw or None)
    monkeypatch.setattr(R, "run_in_sandbox", fake_sandbox)

    cfg = RunConfig(
        models=["m"], k=3, temperature=0.7, timeout=10.0, max_spend_usd=5.0,
        dry_run=False, prompt_style="strict",
        targets=expand_targets([ModelSpec(id="m")]),
    )
    run = asyncio.run(run_benchmark(cfg, [_problem()], PartlyFilteredClient()))
    pr = run.results[0]
    # The block is not a sample: scoring runs over the 2 genuine samples, so
    # pass@1 is 1/2 — it would be 1/3 if the filtered attempt were counted.
    assert [a.sampled for a in pr.attempts] == [False, True, True]
    assert pr.attempts[0].filtered
    assert pr.pass_at_1 == 0.5
    assert pr.pass_at_k == 1.0
    # And the drill-down stderr says why the first attempt produced no code.
    assert "finish_reason=content_filter" in pr.exec_results[0].stderr


def test_effort_labels_round_trip_across_the_full_ladder():
    """target_label/parse_effort agree on all five levels.

    `xhigh` ends with the string `high`, so a suffix matcher could mis-parse
    "m (xhigh)" as effort "high" and file it under the wrong leaderboard board.
    The leading space in " (high)" is what prevents that — pin it.
    """
    from bench.types import VALID_EFFORTS, parse_effort, target_label

    for effort in VALID_EFFORTS:
        label = target_label("anthropic/claude-opus-5", effort)
        assert parse_effort(label) == effort, label
    assert parse_effort(target_label("m", None)) is None
    assert parse_effort("vendor/m (2025)") is None


def test_expand_targets_supports_deep_effort_levels():
    """A roster entry may sweep xhigh/max, and each becomes its own target."""
    from bench.types import ModelSpec

    targets = expand_targets([ModelSpec(id="m", efforts=["high", "xhigh", "max"])])
    assert [t.label for t in targets] == ["m (high)", "m (xhigh)", "m (max)"]
    assert [t.effort for t in targets] == ["high", "xhigh", "max"]


def test_roster_entries_only_declare_efforts_their_model_supports():
    """The shipped roster must not configure a level the provider rejects.

    OpenRouter publishes `reasoning.supported_efforts` per model; these three
    entries have gapped ladders (kimi-k3 has no medium/xhigh, qwen3.8-max has no
    max), and a level outside them passes local validation then fails at the
    provider mid-run.
    """
    from bench.config import load_model_specs

    supported = {
        "anthropic/claude-opus-5": {"low", "medium", "high", "xhigh", "max"},
        "moonshotai/kimi-k3": {"low", "high", "max"},
        "qwen/qwen3.8-max": {"low", "medium", "high", "xhigh", "minimal"},
    }
    by_id = {s.id: s for s in load_model_specs()}
    for model_id, allowed in supported.items():
        spec = by_id.get(model_id)
        assert spec is not None, f"{model_id} missing from config/models.yaml"
        assert set(spec.efforts or []) <= allowed, model_id
