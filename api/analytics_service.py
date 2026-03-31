"""
ARCANE Analytics Service
Step 5: Extracted from compat.py to separate service layer.
Provides analytics data with richer by_day and by_model breakdowns.
"""
from __future__ import annotations
import asyncio
from typing import Optional
from shared.utils.logger import get_logger

logger = get_logger("api.analytics_service")


async def get_usage_analytics() -> dict:
    """Get usage analytics from DB + in-memory store."""
    from api.chat_store import _get_pool, get_chats
    
    result = {
        "total_requests": 0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "by_model": {},
        "by_day": [],
    }
    
    # Supplement with in-memory data
    chats = get_chats()
    result["total_requests"] = len(chats)
    
    pool = await _get_pool()
    if pool:
        try:
            async with pool.acquire() as conn:
                result["total_requests"] = max(
                    await conn.fetchval("SELECT COUNT(*) FROM chats") or 0,
                    result["total_requests"]
                )
                result["total_tokens"] = int(
                    await conn.fetchval("SELECT COALESCE(SUM(total_tokens), 0) FROM chats") or 0
                )
                result["total_cost_usd"] = round(float(
                    await conn.fetchval("SELECT COALESCE(SUM(total_cost), 0) FROM chats") or 0
                ), 4)
                
                # By model breakdown
                model_rows = await conn.fetch(
                    "SELECT model_strategy, COUNT(*) as cnt, COALESCE(SUM(total_cost), 0) as cost "
                    "FROM chats GROUP BY model_strategy"
                )
                for row in model_rows:
                    model = row["model_strategy"] or "unknown"
                    result["by_model"][model] = {
                        "requests": row["cnt"],
                        "cost": round(float(row["cost"]), 4),
                    }
                
                # By day breakdown (last 30 days)
                day_rows = await conn.fetch(
                    "SELECT DATE(created_at) as day, COUNT(*) as cnt, "
                    "COALESCE(SUM(total_cost), 0) as cost "
                    "FROM chats "
                    "WHERE created_at >= NOW() - INTERVAL '30 days' "
                    "GROUP BY DATE(created_at) "
                    "ORDER BY day DESC "
                    "LIMIT 30"
                )
                result["by_day"] = [
                    {
                        "date": str(row["day"]),
                        "requests": row["cnt"],
                        "cost": round(float(row["cost"]), 4),
                    }
                    for row in day_rows
                ]
        except Exception as e:
            logger.warning(f"Analytics usage DB error: {e}")
    
    return result


async def get_tasks_analytics() -> dict:
    """Get task analytics from DB + in-memory store."""
    from api.chat_store import _get_pool, get_chats
    
    chats = get_chats()
    result = {
        "total_tasks": len(chats),
        "completed": 0,
        "failed": 0,
        "in_progress": 0,
        "average_duration_seconds": 0,
        "by_status": {},
        "by_day": [],
    }
    
    # Count from in-memory
    for chat in chats.values():
        status = chat.get("status", "idle")
        result["by_status"][status] = result["by_status"].get(status, 0) + 1
        if status == "completed":
            result["completed"] += 1
        elif status == "failed":
            result["failed"] += 1
        elif status in ("thinking", "executing", "working"):
            result["in_progress"] += 1
    
    pool = await _get_pool()
    if pool:
        try:
            async with pool.acquire() as conn:
                result["total_tasks"] = max(
                    await conn.fetchval("SELECT COUNT(*) FROM chats") or 0,
                    result["total_tasks"]
                )
                result["completed"] = max(
                    await conn.fetchval(
                        "SELECT COUNT(*) FROM chats WHERE status = 'completed' "
                        "OR (status = 'idle' AND total_cost > 0)"
                    ) or 0,
                    result["completed"]
                )
                result["failed"] = max(
                    await conn.fetchval("SELECT COUNT(*) FROM chats WHERE status = 'failed'") or 0,
                    result["failed"]
                )
                avg = await conn.fetchval(
                    "SELECT AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) "
                    "FROM chats WHERE updated_at IS NOT NULL "
                    "AND status IN ('completed', 'failed', 'idle')"
                )
                result["average_duration_seconds"] = round(float(avg or 0), 1)
                
                # By day breakdown
                day_rows = await conn.fetch(
                    "SELECT DATE(created_at) as day, COUNT(*) as cnt, "
                    "SUM(CASE WHEN status = 'completed' OR (status = 'idle' AND total_cost > 0) THEN 1 ELSE 0 END) as completed, "
                    "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed "
                    "FROM chats "
                    "WHERE created_at >= NOW() - INTERVAL '30 days' "
                    "GROUP BY DATE(created_at) "
                    "ORDER BY day DESC "
                    "LIMIT 30"
                )
                result["by_day"] = [
                    {
                        "date": str(row["day"]),
                        "total": row["cnt"],
                        "completed": row["completed"],
                        "failed": row["failed"],
                    }
                    for row in day_rows
                ]
        except Exception as e:
            logger.warning(f"Analytics tasks DB error: {e}")
    
    return result
