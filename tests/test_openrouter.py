"""Unit tests for bench.openrouter SSE parsing, costing, and retry (T4)."""

import httpx
import pytest

from bench.openrouter import ModelPricing, OpenRouterClient, OpenRouterError


def _sse(*chunks: str) -> bytes:
    return "".join(f"data: {c}\n\n" for c in chunks).encode()


def _make_client(handler, **kw) -> OpenRouterClient:
    client = OpenRouterClient("test-key", **kw)
    client._client = httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(handler),
    )
    return client


@pytest.mark.asyncio
async def test_stream_parsing_and_costing():
    body = _sse(
        '{"choices":[{"delta":{"content":"def "}}]}',
        '{"choices":[{"delta":{"content":"f(): return 1"}}]}',
        '{"choices":[{"delta":{}}],"usage":{"prompt_tokens":10,"completion_tokens":20}}',
        "[DONE]",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, content=body)

    client = _make_client(
        handler, price_overrides={"m": 0.0}  # override -> source "config"
    )
    # Override price 0.0 both sides -> cost 0 but source config; test API pricing instead:
    client._price_overrides = {}
    client._pricing_cache = {"m": ModelPricing(0.001, 0.002, "api")}
    async with client:
        attempt = await client.complete("m", "prompt", 0.7)

    assert attempt.raw_response == "def f(): return 1"
    assert attempt.prompt_tokens == 10
    assert attempt.completion_tokens == 20
    assert attempt.ttft_ms is not None and attempt.ttft_ms >= 0
    # 10*0.001 + 20*0.002 = 0.05
    assert attempt.cost_usd == pytest.approx(0.05)
    assert attempt.price_source == "api"
    assert attempt.code is None  # extraction happens in the runner
    assert attempt.retries == 0  # succeeded on the first try


@pytest.mark.asyncio
async def test_config_price_override_source():
    body = _sse(
        '{"choices":[{"delta":{"content":"x"}}]}',
        '{"choices":[{"delta":{}}],"usage":{"prompt_tokens":5,"completion_tokens":5}}',
        "[DONE]",
    )
    client = _make_client(
        lambda r: httpx.Response(200, content=body),
        price_overrides={"m": 0.01},
    )
    async with client:
        attempt = await client.complete("m", "p", 0.0)
    assert attempt.price_source == "config"
    assert attempt.cost_usd == pytest.approx((5 + 5) * 0.01)


@pytest.mark.asyncio
async def test_retry_then_success():
    calls = {"n": 0}
    good = _sse(
        '{"choices":[{"delta":{"content":"ok"}}]}',
        '{"choices":[{"delta":{}}],"usage":{"prompt_tokens":1,"completion_tokens":1}}',
        "[DONE]",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, content=b"try later")
        return httpx.Response(200, content=good)

    client = _make_client(handler, base_delay=0.0, max_delay=0.0)
    client._price_overrides = {}
    client._pricing_cache = {"m": ModelPricing(0.0, 0.0, "api")}
    async with client:
        attempt = await client.complete("m", "p", 0.0)
    assert calls["n"] == 2
    assert attempt.raw_response == "ok"
    assert attempt.retries == 1  # one transient 5xx before success


@pytest.mark.asyncio
async def test_retry_exhausted_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"boom")

    client = _make_client(handler, max_retries=2, base_delay=0.0, max_delay=0.0)
    client._price_overrides = {}
    client._pricing_cache = {"m": ModelPricing(0.0, 0.0, "api")}
    async with client:
        with pytest.raises(OpenRouterError):
            await client.complete("m", "p", 0.0)


@pytest.mark.asyncio
async def test_non_retryable_4xx_raises_immediately():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, content=b"bad request")

    client = _make_client(handler, base_delay=0.0, max_delay=0.0)
    client._price_overrides = {}
    client._pricing_cache = {"m": ModelPricing(0.0, 0.0, "api")}
    async with client:
        with pytest.raises(OpenRouterError):
            await client.complete("m", "p", 0.0)
    assert calls["n"] == 1  # no retries on 400
