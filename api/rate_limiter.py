"""
ARCANE Rate Limiter
Step 7: In-memory sliding window rate limiter.
Limits requests per user/IP to prevent abuse.
"""
from __future__ import annotations
import asyncio
import time
from collections import defaultdict, deque
from typing import Optional
from fastapi import Request, HTTPException
from shared.utils.logger import get_logger

logger = get_logger("api.rate_limiter")

# Rate limit configuration
# Key: limit name, Value: (max_requests, window_seconds)
RATE_LIMITS = {
    "default":      (120, 60),   # 120 req/min for general endpoints
    "auth":         (10,  60),   # 10 req/min for auth endpoints (login/register)
    "message":      (30,  60),   # 30 messages/min per user
    "upload":       (20,  60),   # 20 uploads/min
    "admin":        (300, 60),   # 300 req/min for admin (higher limit)
}

# P3-FIX BUG-011: In-memory storage — sufficient for single-process deployment.
# TODO: Replace with Redis-backed storage for multi-process/multi-worker deployments.
# For now, add periodic cleanup to prevent unbounded memory growth.
_request_log: dict[str, deque] = defaultdict(deque)
_CLEANUP_INTERVAL = 300  # cleanup every 5 minutes
_last_cleanup = time.time()

def _cleanup_expired():
    """Remove expired entries from rate limit log to prevent memory leak."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    expired_keys = []
    for key, timestamps in _request_log.items():
        while timestamps and now - timestamps[0] > 300:  # 5 min max window
            timestamps.popleft()
        if not timestamps:
            expired_keys.append(key)
    for key in expired_keys:
        del _request_log[key]
_lock = asyncio.Lock()


def _get_client_key(request: Request, limit_name: str) -> str:
    """Get a unique key for rate limiting based on user or IP."""
    # Try to get user_id from cookie or header
    user_id = None
    
    # Check session cookie
    token = request.cookies.get("arcane_session")
    if token:
        from api.compat import _sessions
        session = _sessions.get(token)
        if isinstance(session, dict):
            user_id = session.get("user_id")
        elif session:
            user_id = str(session)
    
    # Check JWT Bearer
    if not user_id:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            try:
                from api.auth import decode_token
                payload = decode_token(auth[7:])
                user_id = payload.get("sub")
            except Exception:
                pass
    
    if user_id:
        return f"user:{user_id}:{limit_name}"
    
    # Fall back to IP
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not ip:
        ip = request.client.host if request.client else "unknown"
    return f"ip:{ip}:{limit_name}"


async def check_rate_limit(
    request: Request,
    limit_name: str = "default",
    custom_max: Optional[int] = None,
    custom_window: Optional[int] = None,
) -> dict:
    """
    Check rate limit for a request.
    Raises HTTPException(429) if limit exceeded.
    Returns rate limit info dict.
    """
    max_requests, window_seconds = RATE_LIMITS.get(limit_name, RATE_LIMITS["default"])
    if custom_max is not None:
        max_requests = custom_max
    if custom_window is not None:
        window_seconds = custom_window
    
    key = _get_client_key(request, limit_name)
    now = time.monotonic()
    window_start = now - window_seconds
    
    async with _lock:
        q = _request_log[key]
        
        # Remove expired entries
        while q and q[0] < window_start:
            q.popleft()
        
        current_count = len(q)
        
        if current_count >= max_requests:
            # Calculate retry-after
            oldest = q[0] if q else now
            retry_after = int(oldest - window_start) + 1
            
            logger.warning(f"Rate limit exceeded: key={key} count={current_count} limit={max_requests}")
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Too many requests",
                    "limit": max_requests,
                    "window_seconds": window_seconds,
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )
        
        # Record this request
        q.append(now)
    
    return {
        "limit": max_requests,
        "remaining": max_requests - current_count - 1,
        "window_seconds": window_seconds,
        "reset_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + window_seconds)),
    }


async def get_rate_limit_status(request: Request) -> dict:
    """Get current rate limit status for a user/IP without consuming a request."""
    statuses = {}
    for limit_name, (max_req, window) in RATE_LIMITS.items():
        key = _get_client_key(request, limit_name)
        now = time.monotonic()
        window_start = now - window
        
        async with _lock:
            q = _request_log[key]
            while q and q[0] < window_start:
                q.popleft()
            current = len(q)
        
        statuses[limit_name] = {
            "limit": max_req,
            "used": current,
            "remaining": max(0, max_req - current),
            "window_seconds": window,
        }
    
    return {"limits": statuses}


async def cleanup_old_entries():
    """Periodically clean up expired rate limit entries."""
    while True:
        await asyncio.sleep(300)  # Every 5 minutes
        now = time.monotonic()
        async with _lock:
            keys_to_delete = []
            for key, q in _request_log.items():
                # Remove entries older than the longest window (60s)
                while q and q[0] < now - 60:
                    q.popleft()
                if not q:
                    keys_to_delete.append(key)
            for key in keys_to_delete:
                del _request_log[key]
        if keys_to_delete:
            logger.info(f"Rate limiter cleanup: removed {len(keys_to_delete)} expired keys")
