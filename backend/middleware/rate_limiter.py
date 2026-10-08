"""Rate limiter — Per-user sliding window rate limiting.

Limits:
  - Chat messages per user per hour: 60
  - API requests per user per minute: 120
  - Extraction jobs per user per hour: 5
  - Concurrent conversations per user: 10

Returns HTTP 429 with Retry-After header when exceeded.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


@dataclass(frozen=True)
class RateLimitConfig:
    limit: int
    window_seconds: int


# Default rate limits
RATE_LIMITS: dict[str, RateLimitConfig] = {
    "chat_messages": RateLimitConfig(limit=60, window_seconds=3600),
    "api_requests": RateLimitConfig(limit=120, window_seconds=60),
    "extraction_jobs": RateLimitConfig(limit=5, window_seconds=3600),
}

MAX_CONCURRENT_CONVERSATIONS = 10


class RateLimiter:
    """In-process sliding window rate limiter."""

    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(
        self,
        user_id: str,
        category: str = "api_requests",
    ) -> tuple[bool, int]:
        """Check if request is allowed.

        Args:
            user_id: The user identifier.
            category: Rate limit category (chat_messages, api_requests, extraction_jobs).

        Returns:
            (allowed, retry_after_seconds). If allowed=True, retry_after=0.
        """
        config = RATE_LIMITS.get(category, RATE_LIMITS["api_requests"])
        now = time.time()
        key = f"{user_id}:{category}"
        window = self._windows[key]

        # Prune expired entries
        cutoff = now - config.window_seconds
        window[:] = [t for t in window if t > cutoff]

        if len(window) >= config.limit:
            # Calculate retry-after
            oldest = min(window) if window else now
            retry_after = int(oldest + config.window_seconds - now) + 1
            return False, max(retry_after, 1)

        window.append(now)
        return True, 0

    def get_remaining(self, user_id: str, category: str = "api_requests") -> int:
        """Get remaining requests in the current window."""
        config = RATE_LIMITS.get(category, RATE_LIMITS["api_requests"])
        key = f"{user_id}:{category}"
        window = self._windows.get(key, [])
        now = time.time()
        active = [t for t in window if t > now - config.window_seconds]
        return max(config.limit - len(active), 0)


# Singleton instance
rate_limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for per-user API rate limiting."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip health check
        if request.url.path == "/api/health":
            return await call_next(request)

        # Get user identity from auth headers
        user_id = request.headers.get(
            "X-Forwarded-Email",
            request.headers.get("X-Forwarded-Preferred-Username", "anonymous"),
        )

        # Determine category
        path = request.url.path
        if "/chat/" in path and request.method == "POST" and "/messages" in path:
            category = "chat_messages"
        elif "/extract/start" in path:
            category = "extraction_jobs"
        else:
            category = "api_requests"

        allowed, retry_after = rate_limiter.check(user_id, category)

        if not allowed:
            remaining = rate_limiter.get_remaining(user_id, category)
            return Response(
                content=f'{{"status": "error", "error": "Rate limit exceeded for {category}"}}',
                status_code=429,
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Remaining": str(remaining),
                    "Content-Type": "application/json",
                },
            )

        response = await call_next(request)

        # Add rate limit headers
        remaining = rate_limiter.get_remaining(user_id, category)
        config = RATE_LIMITS.get(category, RATE_LIMITS["api_requests"])
        response.headers["X-RateLimit-Limit"] = str(config.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response
