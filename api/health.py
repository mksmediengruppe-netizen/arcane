"""
ARCANE Health Check
GET /health endpoint returning status of all workers, DB, Redis,
MinIO, Qdrant, plus current costs and last successful project.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

import httpx

from config.settings import ArcaneConfig, get_config
from shared.utils.logger import get_logger

logger = get_logger("api.health")


async def check_postgres(config: ArcaneConfig) -> dict:
    """Check PostgreSQL connectivity."""
    try:
        import asyncpg
        conn = await asyncio.wait_for(
            asyncpg.connect(
                host=config.db.host,
                port=config.db.port,
                user=config.db.user,
                password=config.db.password,
                database=config.db.name,
            ),
            timeout=5.0,
        )
        version = await conn.fetchval("SELECT version()")
        await conn.close()
        return {"status": "healthy", "version": version[:50]}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)[:100]}


async def check_redis(config: ArcaneConfig) -> dict:
    """Check Redis connectivity."""
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(config.redis.url, socket_timeout=5)
        pong = await r.ping()
        info = await r.info("memory")
        await r.aclose()
        return {
            "status": "healthy" if pong else "unhealthy",
            "used_memory": info.get("used_memory_human", "unknown"),
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)[:100]}


async def check_minio(config: ArcaneConfig) -> dict:
    """Check MinIO connectivity."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            url = f"http{'s' if config.minio.secure else ''}://{config.minio.endpoint}/minio/health/live"
            resp = await client.get(url)
            return {
                "status": "healthy" if resp.status_code == 200 else "unhealthy",
                "endpoint": config.minio.endpoint,
            }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)[:100]}


async def check_qdrant(config: ArcaneConfig) -> dict:
    """Check Qdrant vector DB connectivity."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"http://{config.qdrant.host}:{config.qdrant.port}/healthz"
            )
            return {"status": "healthy" if resp.status_code == 200 else "unhealthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)[:100]}


async def check_openai(config: ArcaneConfig) -> dict:
    """Check OpenAI API connectivity."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{config.openai.base_url}/models",
                headers={"Authorization": f"Bearer {config.openai.api_key}"},
            )
            return {
                "status": "healthy" if resp.status_code == 200 else "degraded",
                "models_available": len(resp.json().get("data", [])) if resp.status_code == 200 else 0,
            }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)[:100]}


async def check_openrouter(config: ArcaneConfig) -> dict:
    """Check OpenRouter API connectivity."""
    if not config.openrouter.api_key:
        return {"status": "not_configured"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{config.openrouter.base_url}/models",
                headers={"Authorization": f"Bearer {config.openrouter.api_key}"},
            )
            return {
                "status": "healthy" if resp.status_code == 200 else "degraded",
            }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)[:100]}


async def get_health_report() -> dict[str, Any]:
    """
    Full health report for all ARCANE components.
    Called by GET /health endpoint.
    """
    config = get_config()
    start = time.monotonic()

    # Run all checks in parallel
    results = await asyncio.gather(
        check_postgres(config),
        check_redis(config),
        check_minio(config),
        check_qdrant(config),
        check_openai(config),
        check_openrouter(config),
        return_exceptions=True,
    )

    # Handle exceptions in results
    checks = {}
    names = ["postgresql", "redis", "minio", "qdrant", "openai", "openrouter"]
    for name, result in zip(names, results):
        if isinstance(result, Exception):
            checks[name] = {"status": "error", "error": str(result)[:100]}
        else:
            checks[name] = result

    # Overall status
    statuses = [c.get("status", "unknown") for c in checks.values()]
    if all(s == "healthy" for s in statuses):
        overall = "healthy"
    elif any(s in ("unhealthy", "error") for s in statuses):
        overall = "degraded"
    else:
        overall = "partial"

    elapsed_ms = int((time.monotonic() - start) * 1000)

    return {
        "status": overall,
        "version": "1.0.0",
        "system": "ARCANE",
        "environment": config.env.value,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "check_duration_ms": elapsed_ms,
        "components": checks,
    }
