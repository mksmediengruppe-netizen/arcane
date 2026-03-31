"""
ARCANE Rate Limiter
Per-user, per-provider rate limiting using a sliding window algorithm.
Prevents one user from exhausting API quotas for the entire server.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Optional

from config.settings import RateLimitConfig
from shared.models.schemas import Provider
from shared.utils.logger import get_logger, log_with_data

logger = get_logger("llm.rate_limiter")


class RateLimitExceededError(Exception):
    """Raised when a user exceeds their rate limit."""

    def __init__(self, user_id: str, provider: str, retry_after: float):
        self.user_id = user_id
        self.provider = provider
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded for user {user_id} on {provider}. "
            f"Retry after {retry_after:.1f}s"
        )


class SlidingWindow:
    """Sliding window counter for rate limiting."""

    def __init__(self, max_requests: int, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def try_acquire(self) -> tuple[bool, float]:
        """
        Try to acquire a slot. Returns (success, retry_after_seconds).
        If success is True, the request is allowed.
        If False, retry_after indicates when to try again.
        """
        async with self._lock:
            now = time.monotonic()
            cutoff = now - self.window_seconds

            # Remove expired timestamps
            self._timestamps = [t for t in self._timestamps if t > cutoff]

            if len(self._timestamps) < self.max_requests:
                self._timestamps.append(now)
                return True, 0.0
            else:
                # Calculate when the oldest entry will expire
                oldest = self._timestamps[0]
                retry_after = (oldest + self.window_seconds) - now
                return False, max(0.1, retry_after)

    @property
    def current_count(self) -> int:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        return len([t for t in self._timestamps if t > cutoff])


class RateLimiter:
    """
    Multi-dimensional rate limiter.
    Tracks requests per (user_id, provider) pair.
    """

    def __init__(self, config: RateLimitConfig):
        self._config = config
        # (user_id, provider) -> SlidingWindow
        self._windows: dict[tuple[str, str], SlidingWindow] = defaultdict(
            lambda: SlidingWindow(max_requests=60)
        )
        # Global per-provider windows
        self._global_windows: dict[str, SlidingWindow] = {}

    def _get_limit(self, provider: Provider) -> int:
        """Get the RPM limit for a provider."""
        if provider == Provider.OPENAI:
            return self._config.max_requests_per_minute_openai
        elif provider == Provider.OPENROUTER:
            return self._config.max_requests_per_minute_openrouter
        return 60

    def _get_window(self, user_id: str, provider: Provider) -> SlidingWindow:
        """Get or create a sliding window for a user+provider pair."""
        key = (user_id, provider.value)
        if key not in self._windows:
            limit = self._get_limit(provider)
            self._windows[key] = SlidingWindow(max_requests=limit)
        return self._windows[key]

    def _get_global_window(self, provider: Provider) -> SlidingWindow:
        """Get or create a global sliding window for a provider."""
        key = provider.value
        if key not in self._global_windows:
            # Global limit is 3x per-user limit
            limit = self._get_limit(provider) * 3
            self._global_windows[key] = SlidingWindow(max_requests=limit)
        return self._global_windows[key]

    async def acquire(
        self,
        user_id: str,
        provider: Provider,
        wait: bool = True,
        max_wait: float = 30.0,
    ) -> None:
        """
        Acquire a rate limit slot. If wait=True, blocks until a slot
        is available (up to max_wait seconds). Otherwise raises immediately.
        """
        window = self._get_window(user_id, provider)
        global_window = self._get_global_window(provider)

        start = time.monotonic()
        while True:
            # Check per-user limit
            user_ok, user_retry = await window.try_acquire()
            if not user_ok:
                if not wait or (time.monotonic() - start) > max_wait:
                    raise RateLimitExceededError(user_id, provider.value, user_retry)
                log_with_data(
                    logger, "DEBUG",
                    f"User rate limited, waiting {user_retry:.1f}s",
                    user_id=user_id,
                    provider=provider.value,
                    retry_after=user_retry,
                )
                await asyncio.sleep(min(user_retry, 1.0))
                continue

            # Check global limit
            global_ok, global_retry = await global_window.try_acquire()
            if not global_ok:
                if not wait or (time.monotonic() - start) > max_wait:
                    raise RateLimitExceededError(user_id, provider.value, global_retry)
                log_with_data(
                    logger, "DEBUG",
                    f"Global rate limited, waiting {global_retry:.1f}s",
                    provider=provider.value,
                    retry_after=global_retry,
                )
                await asyncio.sleep(min(global_retry, 1.0))
                continue

            # Both limits passed
            return

    def get_status(self, user_id: str) -> dict[str, dict]:
        """Get current rate limit status for a user."""
        status = {}
        for provider in Provider:
            window = self._get_window(user_id, provider)
            global_window = self._get_global_window(provider)
            limit = self._get_limit(provider)
            status[provider.value] = {
                "user_current": window.current_count,
                "user_limit": limit,
                "user_remaining": max(0, limit - window.current_count),
                "global_current": global_window.current_count,
                "global_limit": limit * 3,
            }
        return status
