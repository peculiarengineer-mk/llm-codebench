"""Async OpenRouter client — the harness's only network boundary (T4).

Streams chat completions so it can measure time-to-first-token, computes USD
cost from token usage against pricing fetched once per run (with optional config
overrides), and retries transient failures with exponential backoff + jitter.
Every call returns an :class:`~bench.types.Attempt` value object.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass

import httpx

from bench.types import Attempt

_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_COMPLETIONS_PATH = "/chat/completions"
_MODELS_PATH = "/models"


@dataclass(frozen=True)
class ModelPricing:
    """Per-token USD pricing for one model (from ``/models`` or a config override)."""

    prompt: float
    completion: float
    source: str  # "api" or "config"

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return prompt_tokens * self.prompt + completion_tokens * self.completion


class OpenRouterError(RuntimeError):
    """Raised when OpenRouter fails (after retries for transient errors).

    ``status_code`` is the HTTP status when the failure was an HTTP response, or
    ``None`` for transport/timeout errors. Statuses in :data:`FATAL_STATUS` are
    run-fatal — auth/billing problems that neither a retry nor continuing the
    rest of the run will resolve.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# HTTP statuses worth retrying (rate limit + transient server errors).
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Account-wide auth/billing failures that won't resolve by retrying or by
# continuing the run: 401 (bad/expired key) and 402 (out of credits). These
# justify aborting the whole run. 403 is deliberately excluded — it is usually
# per-model (the key lacks access to one model), so it's recorded as that
# model's api-error without killing the other models.
FATAL_STATUS = {401, 402}


class OpenRouterClient:
    """Async client for OpenRouter's OpenAI-compatible chat API.

    Use as an async context manager so the underlying ``httpx.AsyncClient`` is
    closed cleanly::

        async with OpenRouterClient(api_key) as client:
            attempt = await client.complete("openai/gpt-5", "prompt", 0.7)
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        price_overrides: dict[str, float] | None = None,
        referer: str | None = None,
        title: str | None = None,
        request_timeout: float = 120.0,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._price_overrides = dict(price_overrides or {})
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if referer:
            headers["HTTP-Referer"] = referer
        if title:
            headers["X-Title"] = title

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(request_timeout),
        )
        self._pricing_cache: dict[str, ModelPricing] | None = None
        self._pricing_lock = asyncio.Lock()

    async def __aenter__(self) -> "OpenRouterClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- pricing ------------------------------------------------------------

    async def list_models(self) -> list[dict]:
        """Return the raw ``/models`` list from OpenRouter."""
        resp = await self._request_json("GET", _MODELS_PATH)
        return resp.get("data", [])

    async def get_pricing(self) -> dict[str, ModelPricing]:
        """Return ``{model_id: ModelPricing}``, fetched once and cached.

        Config overrides in ``price_overrides`` win over live API pricing and are
        recorded with ``source="config"``.
        """
        async with self._pricing_lock:
            if self._pricing_cache is None:
                cache: dict[str, ModelPricing] = {}
                for entry in await self.list_models():
                    model_id = entry.get("id")
                    pricing = entry.get("pricing") or {}
                    try:
                        prompt = float(pricing.get("prompt", 0.0) or 0.0)
                        completion = float(pricing.get("completion", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        continue
                    if model_id:
                        cache[model_id] = ModelPricing(prompt, completion, "api")
                # Apply config overrides (USD per token, applied to both sides).
                for model_id, price in self._price_overrides.items():
                    cache[model_id] = ModelPricing(price, price, "config")
                self._pricing_cache = cache
            return self._pricing_cache

    async def _pricing_for(self, model: str) -> ModelPricing:
        # Override alone is enough — no need to fetch the catalog.
        if model in self._price_overrides:
            price = self._price_overrides[model]
            return ModelPricing(price, price, "config")
        pricing = await self.get_pricing()
        return pricing.get(model, ModelPricing(0.0, 0.0, "api"))

    # -- completion ---------------------------------------------------------

    async def complete(
        self,
        model: str,
        prompt: str,
        temperature: float,
        *,
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> Attempt:
        """Stream one completion and return a fully-costed :class:`Attempt`.

        ``effort`` (``"low"``/``"medium"``/``"high"``), when set, is sent via
        OpenRouter's unified ``reasoning.effort`` param — mapped per-provider to
        the model's native reasoning control. Models without a reasoning mode
        ignore it. Network/HTTP failures are retried with exponential backoff +
        jitter up to ``max_retries``; the final failure raises
        :class:`OpenRouterError`.
        """
        pricing = await self._pricing_for(model)
        payload: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if effort is not None:
            payload["reasoning"] = {"effort": effort}

        last_exc: Exception | None = None
        attempts_made = 0
        for attempt_no in range(self._max_retries + 1):
            attempts_made += 1
            try:
                result = await self._stream_once(model, payload, pricing)
                # attempt_no is 0 on first-try success, 1 after one retry, etc.
                return result.model_copy(update={"retries": attempt_no})
            except (httpx.HTTPError, OpenRouterError) as exc:
                last_exc = exc
                if attempt_no >= self._max_retries or not _is_retryable(exc):
                    break
                await asyncio.sleep(self._backoff(attempt_no))
        tries = "try" if attempts_made == 1 else "tries"
        raise OpenRouterError(
            f"OpenRouter request for {model!r} failed after {attempts_made} "
            f"{tries}: {last_exc}",
            status_code=getattr(last_exc, "status_code", None),
        ) from last_exc

    async def _stream_once(
        self, model: str, payload: dict, pricing: ModelPricing
    ) -> Attempt:
        start = time.perf_counter()
        ttft_ms: float | None = None
        content_parts: list[str] = []
        raw_lines: list[str] = []
        usage: dict = {}
        reported_cost: float | None = None

        async with self._client.stream(
            "POST", _COMPLETIONS_PATH, json=payload
        ) as resp:
            if resp.status_code in _RETRYABLE_STATUS:
                await resp.aread()
                raise OpenRouterError(
                    f"HTTP {resp.status_code} from OpenRouter (retryable)",
                    status_code=resp.status_code,
                )
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", "replace")
                raise OpenRouterError(
                    f"HTTP {resp.status_code} from OpenRouter: {body[:500]}",
                    status_code=resp.status_code,
                )

            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                raw_lines.append(data)
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        if ttft_ms is None:
                            ttft_ms = (time.perf_counter() - start) * 1000.0
                        content_parts.append(piece)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                    if usage.get("cost") is not None:
                        try:
                            reported_cost = float(usage["cost"])
                        except (TypeError, ValueError):
                            reported_cost = None

        latency_ms = (time.perf_counter() - start) * 1000.0
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)

        # Prefer OpenRouter's own cost when it reports one and we have no config
        # override; otherwise compute from usage x pricing.
        if reported_cost is not None and pricing.source == "api":
            cost_usd = reported_cost
        else:
            cost_usd = pricing.cost(prompt_tokens, completion_tokens)

        return Attempt(
            code=None,  # extraction happens in the runner via bench.extract
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            price_source=pricing.source,  # type: ignore[arg-type]
            raw_response="".join(content_parts),
        )

    async def _request_json(self, method: str, path: str) -> dict:
        last_exc: Exception | None = None
        for attempt_no in range(self._max_retries + 1):
            try:
                resp = await self._client.request(method, path)
                if resp.status_code in _RETRYABLE_STATUS:
                    raise OpenRouterError(f"HTTP {resp.status_code} (retryable)")
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, OpenRouterError) as exc:
                last_exc = exc
                if attempt_no >= self._max_retries or not _is_retryable(exc):
                    break
                await asyncio.sleep(self._backoff(attempt_no))
        raise OpenRouterError(f"GET {path} failed: {last_exc}") from last_exc

    def _backoff(self, attempt_no: int) -> float:
        """Exponential backoff with full jitter, capped at ``max_delay``."""
        ceiling = min(self._max_delay, self._base_delay * (2**attempt_no))
        return random.uniform(0, ceiling)


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, OpenRouterError):
        return "retryable" in str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    # Timeouts / connection errors are transient.
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


__all__ = ["OpenRouterClient", "OpenRouterError", "ModelPricing", "FATAL_STATUS"]
