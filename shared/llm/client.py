"""
ARCANE Unified LLM Client
Single async interface to all LLM providers (OpenAI, OpenRouter).
Handles: provider routing, fallback chains, rate limiting, retries,
streaming, cost calculation, and structured logging.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Optional

import httpx

from config.settings import ArcaneConfig, get_config
from shared.llm.model_registry import MODELS, get_fallback_model
from shared.llm.rate_limiter import RateLimiter
from shared.models.schemas import (
    LLMRequest,
    LLMResponse,
    Provider,
    ToolCall,
    UsageRecord,
)
from shared.utils.logger import get_logger, log_with_data

logger = get_logger("llm.client")


class ProviderUnavailableError(Exception):
    """Raised when a provider is unreachable after retries."""
    pass


class BadRequestError(Exception):
    """Raised on 400 errors that won't be fixed by switching models (e.g. tool_call_id mismatch)."""
    pass


class BudgetExceededError(Exception):
    """Raised when project budget is exhausted."""
    pass


class UnifiedLLMClient:
    """
    Async LLM client that abstracts away provider differences.

    Usage:
        client = UnifiedLLMClient()
        response = await client.complete(LLMRequest(
            messages=[{"role": "user", "content": "Hello"}],
            model_id="gpt-4.1-mini",
        ))
    """

    def __init__(self, config: Optional[ArcaneConfig] = None):
        self._config = config or get_config()
        self._rate_limiter = RateLimiter(self._config.rate_limit)
        self._http_clients: dict[Provider, httpx.AsyncClient] = {}
        self._usage_records: list[UsageRecord] = []

    async def _get_http_client(self, provider: Provider) -> httpx.AsyncClient:
        """Lazy-initialize HTTP clients per provider."""
        if provider not in self._http_clients:
            if provider == Provider.OPENAI:
                self._http_clients[provider] = httpx.AsyncClient(
                    base_url=self._config.openai.base_url,
                    headers={
                        "Authorization": f"Bearer {self._config.openai.api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=httpx.Timeout(self._config.openai.timeout),
                )
            elif provider == Provider.OPENROUTER:
                self._http_clients[provider] = httpx.AsyncClient(
                    base_url=self._config.openrouter.base_url,
                    headers={
                        "Authorization": f"Bearer {self._config.openrouter.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://arcane.mksitdev.ru",
                        "X-Title": "ARCANE",
                    },
                    timeout=httpx.Timeout(self._config.openrouter.timeout),
                )
        return self._http_clients[provider]

    def _calculate_cost(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ) -> float:
        """Calculate cost in USD for a given model and token counts."""
        spec = MODELS.get(model_id)
        if not spec:
            return 0.0
        non_cached_input = max(0, input_tokens - cached_tokens)
        cached_price = spec.cached_input_price_per_mtok or spec.input_price_per_mtok
        cost = (
            (non_cached_input / 1_000_000) * spec.input_price_per_mtok
            + (cached_tokens / 1_000_000) * cached_price
            + (output_tokens / 1_000_000) * spec.output_price_per_mtok
        )
        return round(cost, 6)

    def _build_request_body(self, request: LLMRequest, model_id: str) -> dict:
        """Build the JSON body for the chat completions endpoint."""
        body: dict[str, Any] = {
            "model": model_id,
            "messages": request.messages,
            "temperature": request.temperature,
            "stream": request.stream,
        }
        if request.max_tokens:
            body["max_tokens"] = request.max_tokens
        if request.tools:
            body["tools"] = request.tools
            body["tool_choice"] = "required"
        return body

    def _apply_prompt_caching(self, body: dict, model_id: str) -> dict:
        """
        Apply Anthropic prompt caching via OpenRouter.

        Anthropic supports cache_control breakpoints on messages.
        We mark the system prompt and the first user message as cacheable,
        since these are stable across iterations of the agent loop.

        This saves ~90% on input token costs for cached content.
        Only applies to Claude models routed through OpenRouter.
        """
        spec = MODELS.get(model_id)
        if not spec or spec.provider != Provider.OPENROUTER:
            return body

        # Only apply to Anthropic models (Claude family)
        if not model_id.startswith("claude-"):
            return body

        messages = body.get("messages", [])
        if not messages:
            return body

        # Deep copy messages to avoid mutating originals
        import copy
        cached_messages = copy.deepcopy(messages)

        # Mark system prompt for caching (always first message, always stable)
        if cached_messages and cached_messages[0].get("role") == "system":
            content = cached_messages[0].get("content", "")
            if isinstance(content, str) and len(content) > 1024:
                # Convert to content blocks format with cache_control
                cached_messages[0]["content"] = [
                    {
                        "type": "text",
                        "text": content,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]

        # Mark tools schema for caching (stable across iterations)
        if body.get("tools") and len(json.dumps(body["tools"])) > 2048:
            # OpenRouter passes cache_control on the last tool
            tools = copy.deepcopy(body.get("tools", []))
            if tools:
                tools[-1]["cache_control"] = {"type": "ephemeral"}
                body["tools"] = tools

        body["messages"] = cached_messages

        log_with_data(
            logger, "DEBUG",
            f"Applied prompt caching for {model_id}",
            model=model_id,
            system_cached=bool(
                cached_messages
                and cached_messages[0].get("role") == "system"
                and isinstance(cached_messages[0].get("content"), list)
            ),
        )

        return body

    def _parse_tool_calls(self, raw_calls: list[dict]) -> list[ToolCall]:
        """Parse raw tool call dicts from API response."""
        result = []
        for tc in raw_calls:
            func = tc.get("function", {})
            args_str = func.get("arguments", "{}")
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                args = {"raw": args_str}
            result.append(ToolCall(
                id=tc.get("id", ""),
                name=func.get("name", ""),
                arguments=args,
            ))
        return result

    async def complete(
        self,
        request: LLMRequest,
        role: str = "unknown",
        worker: str = "unknown",
    ) -> LLMResponse:
        """
        Send a completion request with automatic fallback.

        If the primary model/provider fails, tries the fallback chain.
        Respects rate limits per user and per provider.
        """
        model_id = request.model_id
        if not model_id:
            raise ValueError("model_id is required in LLMRequest")

        spec = MODELS.get(model_id)
        if not spec:
            raise ValueError(f"Unknown model: {model_id}")

        # Rate limit check
        if request.user_id:
            await self._rate_limiter.acquire(request.user_id, spec.provider)

        # Try primary model, then fallback chain
        attempts: list[str] = [model_id]
        current_spec = spec
        max_fallbacks = 3

        for attempt_num in range(max_fallbacks + 1):
            try:
                response = await self._call_provider(
                    request, current_spec.id, current_spec.provider
                )
                return response

            except ProviderUnavailableError as e:
                log_with_data(
                    logger, "WARNING",
                    f"Provider unavailable for {current_spec.id}, trying fallback",
                    model=current_spec.id,
                    provider=current_spec.provider.value,
                    error=str(e),
                    attempt=attempt_num + 1,
                )
                # Try fallback
                fallback = get_fallback_model(role, current_spec.id)
                if fallback and fallback.id not in attempts:
                    current_spec = fallback
                    attempts.append(fallback.id)
                    log_with_data(
                        logger, "INFO",
                        f"Falling back to {fallback.id}",
                        fallback_model=fallback.id,
                        provider=fallback.provider.value,
                    )
                    continue
                else:
                    raise ProviderUnavailableError(
                        f"All fallbacks exhausted. Tried: {attempts}"
                    )

        raise ProviderUnavailableError(f"Max fallback attempts reached: {attempts}")

    async def _call_provider(
        self,
        request: LLMRequest,
        model_id: str,
        provider: Provider,
    ) -> LLMResponse:
        """Make the actual HTTP call to a provider."""
        client = await self._get_http_client(provider)
        body = self._build_request_body(request, model_id)

        # OpenRouter uses different model naming
        if provider == Provider.OPENROUTER:
            body["model"] = self._openrouter_model_name(model_id)
            # Ignore Azure provider — blocked for content policy
            body["provider"] = {"ignore": ["Azure"], "allow_fallbacks": True}
            # Apply prompt caching for Anthropic models
            body = self._apply_prompt_caching(body, model_id)

        # DEBUG: log the request body for troubleshooting
        import copy as _copy
        _debug_body = _copy.deepcopy(body)
        _debug_body.pop("messages", None)  # too large
        log_with_data(
            logger, "INFO",
            f"REQUEST BODY DEBUG for {model_id}",
            model=model_id,
            provider=provider.value,
            body_keys=list(body.keys()),
            body_no_messages=str(_debug_body)[:500],
            tools_count=len(body.get("tools", [])),
        )

        start_time = time.monotonic()
        max_retries = self._config.openai.max_retries

        last_error: Optional[Exception] = None
        for retry in range(max_retries):
            try:
                resp = await client.post("/chat/completions", json=body)

                if resp.status_code == 429:
                    # Check if this is quota exceeded (not just rate limit)
                    try:
                        err_body = resp.json()
                        err_code = err_body.get("error", {}).get("code", "")
                        err_msg = err_body.get("error", {}).get("message", "")
                    except Exception:
                        err_code = ""
                        err_msg = ""
                    if err_code == "insufficient_quota" or "exceeded your current quota" in err_msg:
                        raise ProviderUnavailableError(
                            f"Quota exceeded for {provider.value}: {err_msg}"
                        )
                    # Normal rate limit — wait and retry
                    retry_after = int(resp.headers.get("Retry-After", "5"))
                    log_with_data(
                        logger, "WARNING",
                        f"Rate limited by {provider.value}, waiting {retry_after}s",
                        provider=provider.value,
                        retry_after=retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if resp.status_code == 400:
                    # Bad request — log the error body for debugging
                    try:
                        err_body = resp.json()
                        err_msg = str(err_body)
                    except Exception:
                        err_msg = resp.text[:500]
                    log_with_data(
                        logger, "WARNING",
                        f"400 Bad Request from {provider.value} for {model_id}: {err_msg}",
                        model=model_id,
                        provider=provider.value,
                        status=400,
                        error_body=err_msg[:300],
                    )
                    # Check if this is a tool_call_id mismatch — switching models won't help
                    if 'tool call' in err_msg.lower() or 'tool_call' in err_msg.lower():
                        raise BadRequestError(
                            f"Tool call mismatch for {model_id}: {err_msg[:200]}"
                        )
                    raise ProviderUnavailableError(
                        f"Bad request for {model_id} via {provider.value}: {err_msg[:200]}"
                    )

                if resp.status_code >= 500:
                    # Server error — retry
                    await asyncio.sleep(2 ** retry)
                    continue

                resp.raise_for_status()
                data = resp.json()
                latency_ms = int((time.monotonic() - start_time) * 1000)

                return self._parse_response(data, model_id, provider, latency_ms)

            except httpx.ConnectError as e:
                last_error = e
                await asyncio.sleep(2 ** retry)
            except httpx.TimeoutException as e:
                last_error = e
                await asyncio.sleep(2 ** retry)
            except httpx.ReadError as e:
                last_error = e
                await asyncio.sleep(2 ** retry)
            except httpx.RemoteProtocolError as e:
                last_error = e
                await asyncio.sleep(2 ** retry)
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (401, 403):
                    raise ProviderUnavailableError(
                        f"Auth error for {provider.value}: {e.response.status_code}"
                    )
                last_error = e
                await asyncio.sleep(2 ** retry)

        raise ProviderUnavailableError(
            f"Failed after {max_retries} retries for {model_id}: {last_error}"
        )

    def _parse_response(
        self,
        data: dict,
        model_id: str,
        provider: Provider,
        latency_ms: int,
    ) -> LLMResponse:
        """Parse the raw API response into a normalized LLMResponse."""
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        usage = data.get("usage", {})

        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cached_tokens = usage.get("prompt_tokens_details", {}).get(
            "cached_tokens", 0
        )

        tool_calls = None
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls:
            tool_calls = self._parse_tool_calls(raw_tool_calls)

        cost = self._calculate_cost(model_id, input_tokens, output_tokens, cached_tokens)

        response = LLMResponse(
            content=message.get("content") or message.get("reasoning"),
            tool_calls=tool_calls,
            model_id=model_id,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            finish_reason=choice.get("finish_reason") or "stop",
            raw_response=data,
        )

        log_with_data(
            logger, "INFO",
            f"LLM call completed",
            model=model_id,
            provider=provider.value,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            has_tool_calls=tool_calls is not None,
        )

        return response

    async def stream(
        self,
        request: LLMRequest,
        role: str = "unknown",
        worker: str = "unknown",
    ) -> AsyncIterator[str]:
        """
        Stream a completion response, yielding content chunks.
        Falls back to non-streaming on failure.
        """
        model_id = request.model_id
        if not model_id:
            raise ValueError("model_id is required")

        spec = MODELS.get(model_id)
        if not spec:
            raise ValueError(f"Unknown model: {model_id}")

        if request.user_id:
            await self._rate_limiter.acquire(request.user_id, spec.provider)

        request.stream = True
        client = await self._get_http_client(spec.provider)
        body = self._build_request_body(request, model_id)

        if spec.provider == Provider.OPENROUTER:
            body["model"] = self._openrouter_model_name(model_id)
            # Ignore Azure provider — blocked for content policy
            body["provider"] = {"ignore": ["Azure"], "allow_fallbacks": True}

        try:
            async with client.stream("POST", "/chat/completions", json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        chunk_str = line[6:]
                        if chunk_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(chunk_str)
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        except Exception as e:
            log_with_data(
                logger, "ERROR",
                f"Streaming failed, falling back to non-streaming",
                model=model_id,
                error=str(e),
            )
            request.stream = False
            response = await self.complete(request, role=role, worker=worker)
            if response.content:
                yield response.content

    def _openrouter_model_name(self, model_id: str) -> str:
        """Convert internal model ID to OpenRouter format."""
        mapping = {
            # OpenAI models via OpenRouter
            "gpt-4.1-nano": "openai/gpt-4.1-nano",
            "gpt-4.1-mini": "openai/gpt-4.1-mini",
            "gpt-4.1": "openai/gpt-4.1",
            "gpt-5-nano": "openai/gpt-5-nano",
            "gpt-5-mini": "openai/gpt-5-mini",
            "gpt-5": "openai/gpt-5",
            "gpt-5.4": "openai/gpt-5.4",
            "o4-mini": "openai/o4-mini",
            "o3": "openai/o3",
            # Anthropic models
            "claude-sonnet-4": "anthropic/claude-sonnet-4",
            "claude-opus-4": "anthropic/claude-opus-4",
            # Google models
            "gemini-2.5-flash": "google/gemini-2.5-flash",
            "gemini-2.5-pro": "google/gemini-2.5-pro",
            # DeepSeek models
            "deepseek-r1": "deepseek/deepseek-r1",
        }
        return mapping.get(model_id, model_id)

    async def close(self):
        """Close all HTTP clients."""
        for client in self._http_clients.values():
            await client.aclose()
        self._http_clients.clear()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
