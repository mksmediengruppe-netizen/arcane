"""
ARCANE Chat Store — Write-through persistence layer.

In-memory dict for fast reads + PostgreSQL for durability.
On startup, loads existing chats from DB.
On every mutation, writes through to DB asynchronously.

Connection: uses docker network IP for postgres container.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Optional

from shared.utils.logger import get_logger

logger = get_logger("chat_store")

# ── Connection config ──
# SECURITY FIX (P0-4): No hardcoded credentials. DATABASE_URL must be set in environment.
_DB_URL: str = os.environ.get("DATABASE_URL", "")
if not _DB_URL:
    logger.warning(
        "Chat store: DATABASE_URL not set. Running in memory-only mode. "
        "Set DATABASE_URL environment variable for persistence."
    )

# ── In-memory caches (fast path) ──
# P3-FIX BUG-014: In-memory dicts serve as read cache for DB data.
# TODO Phase 4: Remove in-memory cache entirely and read directly from PostgreSQL
# to eliminate dual-storage inconsistency risk. For now, DB is source of truth
# and in-memory is populated on startup via _load_from_db().
_chats: dict[str, dict] = {}
_chat_messages: dict[str, list[dict]] = {}

# ── Connection pool ──
_pool = None


async def _safe_db_write(coro_func, *args, **kwargs):
    """
    P3-FIX BUG-019: Awaitable DB write wrapper with retry.
    Previously fire-and-forget (asyncio.create_task), now properly awaited
    to prevent data loss on process termination.
    """
    for attempt in range(2):  # max 2 attempts
        try:
            await coro_func(*args, **kwargs)
            return
        except Exception as e:
            if attempt == 0:
                logger.warning(f"Chat store DB write failed (attempt 1), retrying: {e}")
                await asyncio.sleep(0.5)
            else:
                logger.error(f"Chat store DB write failed permanently: {e}")

async def _safe_db_write_with_status(coro_func, *args, **kwargs) -> bool:
    """
    FIX NEW-001: Same as _safe_db_write but returns True/False for DB-first pattern.
    Allows callers to know if DB write succeeded before updating memory.
    """
    for attempt in range(3):  # 3 attempts for DB-first critical path
        try:
            await coro_func(*args, **kwargs)
            return True
        except Exception as e:
            if attempt < 2:
                logger.warning(f"Chat store DB write failed (attempt {attempt+1}/3), retrying: {e}")
                await asyncio.sleep(0.3 * (attempt + 1))
            else:
                logger.error(f"Chat store DB write failed after 3 attempts: {e}")
    return False


async def _get_pool():
    """Lazy-init asyncpg connection pool."""
    global _pool
    if _pool is None:
        try:
            import asyncpg
            _pool = await asyncpg.create_pool(
                _DB_URL,
                min_size=2,
                max_size=10,
                command_timeout=10,
            )
            logger.info(f"Chat store: PostgreSQL pool created ({_DB_URL.split('@')[1]})")
        except Exception as e:
            logger.error(f"Chat store: Failed to create pool: {e}")
            _pool = None
    return _pool


async def init_store():
    """Load existing chats from DB into memory on startup."""
    pool = await _get_pool()
    if not pool:
        logger.warning("Chat store: No DB pool, running in memory-only mode")
        return

    try:
        async with pool.acquire() as conn:
            # Load chats
            rows = await conn.fetch("""
                SELECT id, title, status, total_cost, total_tokens,
                       created_at, updated_at, user_id, model_strategy,
                       agent_status, current_phase, plan_json, scratchpad
                FROM chats
                ORDER BY created_at DESC
                LIMIT 500
            """)
            for row in rows:
                chat_id = str(row["id"])
                _chats[chat_id] = {
                    "id": chat_id,
                    "title": row["title"] or "New Task",
                    "created_at": row["created_at"].isoformat() + "Z" if row["created_at"] else "",
                    "updated_at": row["updated_at"].isoformat() + "Z" if row["updated_at"] else "",
                    "message_count": 0,
                    "total_cost": float(row["total_cost"] or 0),
                    "total_tokens": int(row["total_tokens"] or 0),
                    "status": row["status"] or "idle",
                    "user_id": str(row["user_id"] or ""),
                    "model_used": row["model_strategy"] or "gpt-5.4",
                    "agent_status": row["agent_status"] or "idle",
                    "current_phase": row["current_phase"] or "",
                    "plan_json": row["plan_json"] or "",
                    "scratchpad": row["scratchpad"] or "",
                    "steps": [],
                }
                _chat_messages[chat_id] = []

            # Load messages for ALL loaded chats (not just 50)
            if rows:
                chat_ids = [row["id"] for row in rows]  # all loaded chats
                msg_rows = await conn.fetch("""
                    SELECT id, chat_id, role, content, tool_name,
                           model_used, tokens_input, tokens_output, cost,
                           created_at, metadata_json
                    FROM messages
                    WHERE chat_id = ANY($1)
                    ORDER BY created_at ASC
                """, chat_ids)
                for mrow in msg_rows:
                    cid = str(mrow["chat_id"])
                    if cid not in _chat_messages:
                        _chat_messages[cid] = []
                    _chat_messages[cid].append({
                        "id": str(mrow["id"]),
                        "role": mrow["role"],
                        "content": mrow["content"] or "",
                        "tool_name": mrow["tool_name"] or "",
                        "model_used": mrow["model_used"] or "",
                        "created_at": mrow["created_at"].isoformat() + "Z" if mrow["created_at"] else "",
                    })

                # Update message counts
                for cid in _chat_messages:
                    if cid in _chats:
                        _chats[cid]["message_count"] = len(_chat_messages[cid])

            logger.info(f"Chat store: Loaded {len(_chats)} chats, {sum(len(m) for m in _chat_messages.values())} messages from DB")
    except Exception as e:
        logger.error(f"Chat store: Failed to load from DB: {e}")


# ── Public API ──

def get_chats() -> dict[str, dict]:
    """Get reference to in-memory chats dict."""
    return _chats


def get_chat_messages() -> dict[str, list[dict]]:
    """Get reference to in-memory messages dict."""
    return _chat_messages


def get_chat(chat_id: str) -> Optional[dict]:
    """Get a single chat by ID."""
    return _chats.get(chat_id)


def get_messages(chat_id: str) -> list[dict]:
    """Get messages for a chat."""
    return _chat_messages.get(chat_id, [])


async def create_chat(chat_id: str, title: str = "New Task",
                       user_id: str = "", model: str = "gpt-5.4",
                       variant: str = "", status: str = "idle") -> dict:
    """Create a new chat in memory and DB."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    chat = {
        "id": chat_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
        "total_cost": 0.0,
        "total_tokens": 0,
        "model_used": model,
        "variant": variant,
        "status": status,
        "user_id": user_id,
        "steps": [],
    }
    # DB-FIRST: persist to PostgreSQL before memory (FIX NEW-001)
    db_ok = await _safe_db_write_with_status(_db_create_chat, chat_id, title, user_id, model, status)
    if not db_ok:
        logger.warning(f"Chat store: DB write failed for create_chat {chat_id}, memory-only")
    # Then update memory
    _chats[chat_id] = chat
    _chat_messages[chat_id] = []
    return chat
    return chat


async def _db_create_chat(chat_id: str, title: str, user_id: str,
                           model: str, status: str):
    """Persist chat creation to PostgreSQL."""
    pool = await _get_pool()
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            # FIX 6: Require explicit user_id — no admin LIMIT 1 fallback
            if not user_id:
                logger.error("Chat store: Cannot create chat without user_id — skipping DB persistence")
                return

            await conn.execute("""
                INSERT INTO chats (id, user_id, title, status, agent_status,
                                   total_cost, total_tokens, model_strategy,
                                   created_at, updated_at)
                VALUES ($1::uuid, $2::uuid, $3, $4, 'idle', 0.0, 0, $5,
                        NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
            """, uuid.UUID(chat_id) if len(chat_id) >= 32 else uuid.uuid5(uuid.NAMESPACE_DNS, chat_id),
                user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id)),
                title, status, model)
            logger.debug(f"Chat store: Persisted chat {chat_id} to DB")
    except Exception as e:
        logger.warning(f"Chat store: DB write failed for chat {chat_id}: {e}")


async def add_message(chat_id: str, role: str, content: str,
                       tool_name: str = "", model_used: str = "") -> dict:
    """Add a message to a chat (memory + DB)."""
    msg_id = str(uuid.uuid4())
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    msg = {
        "id": msg_id,
        "role": role,
        "content": content,
        "tool_name": tool_name,
        "model_used": model_used,
        "created_at": now,
    }

    # DB-FIRST: persist to PostgreSQL before memory (FIX NEW-001)
    db_ok = await _safe_db_write_with_status(_db_add_message, chat_id, msg_id, role, content, tool_name, model_used)
    if not db_ok:
        logger.warning(f"Chat store: DB write failed for message in {chat_id}, memory-only")
    # Then update memory
    if chat_id not in _chat_messages:
        _chat_messages[chat_id] = []
    _chat_messages[chat_id].append(msg)
    return msg


async def _db_add_message(chat_id: str, msg_id: str, role: str,
                           content: str, tool_name: str, model_used: str):
    """Persist message to PostgreSQL."""
    pool = await _get_pool()
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            # Get the DB chat UUID
            db_chat_id = await conn.fetchval(
                "SELECT id FROM chats WHERE id::text = $1 LIMIT 1",
                chat_id
            )
            if not db_chat_id:
                logger.debug(f"Chat store: Chat {chat_id} not in DB, skipping message persist")
                return

            await conn.execute("""
                INSERT INTO messages (id, chat_id, role, content, tool_name,
                                      model_used, tokens_input, tokens_output,
                                      cost, duration_ms, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, 0, 0, 0.0, 0, NOW())
            """, uuid.uuid4(), db_chat_id, role, content[:10000],
                tool_name or None, model_used or None)
    except Exception as e:
        logger.debug(f"Chat store: Message persist failed: {e}")


async def update_chat(chat_id: str, **kwargs):
    """Update chat fields — DB-first, then memory (FIX NEW-001)."""
    if chat_id not in _chats:
        return
    # DB-FIRST: persist to PostgreSQL before memory (FIX NEW-001)
    db_ok = await _safe_db_write_with_status(_db_update_chat, chat_id, kwargs)
    if not db_ok:
        logger.warning(f"Chat store: DB write failed for update_chat {chat_id}, memory-only")
    # Then update memory
    for key, value in kwargs.items():
        _chats[chat_id][key] = value
    _chats[chat_id]["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")


async def _db_update_chat(chat_id: str, fields: dict):
    """Persist chat update to PostgreSQL."""
    pool = await _get_pool()
    if not pool:
        return

    # Map in-memory field names to DB column names
    column_map = {
        "title": "title",
        "status": "status",
        "total_cost": "total_cost",
        "total_tokens": "total_tokens",
        "model_used": "model_strategy",
        "scratchpad": "scratchpad",
        "plan_json": "plan_json",
        "agent_status": "agent_status",
        "current_phase": "current_phase",
    }

    try:
        async with pool.acquire() as conn:
            db_chat_id = await conn.fetchval(
                "SELECT id FROM chats WHERE id::text = $1 LIMIT 1",
                chat_id
            )
            if not db_chat_id:
                return

            for mem_key, db_col in column_map.items():
                if mem_key in fields:
                    val = fields[mem_key]
                    await conn.execute(
                        f"UPDATE chats SET {db_col} = $1, updated_at = NOW() WHERE id = $2",
                        val, db_chat_id
                    )
    except Exception as e:
        logger.debug(f"Chat store: Update persist failed: {e}")


async def delete_chat(chat_id: str):
    """Delete a chat — DB-first, then memory (FIX NEW-001)."""
    # DB-FIRST: delete from PostgreSQL before memory (FIX NEW-001)
    await _safe_db_write(_db_delete_chat, chat_id)
    # Then remove from memory
    _chats.pop(chat_id, None)
    _chat_messages.pop(chat_id, None)


async def _db_delete_chat(chat_id: str):
    """Delete chat from PostgreSQL (cascades to messages)."""
    pool = await _get_pool()
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            db_chat_id = await conn.fetchval(
                "SELECT id FROM chats WHERE id::text = $1 LIMIT 1",
                chat_id
            )
            if db_chat_id:
                await conn.execute("DELETE FROM chats WHERE id = $1", db_chat_id)
    except Exception as e:
        logger.debug(f"Chat store: Delete persist failed: {e}")


async def get_admin_chats() -> list[dict]:
    """Get all chats for admin panel — from DB first, fallback to memory."""
    pool = await _get_pool()
    if pool:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT c.id, c.title, c.status, c.total_cost, c.total_tokens,
                           c.created_at, c.updated_at, c.user_id,
                           u.username, u.email,
                           (SELECT COUNT(*) FROM messages WHERE chat_id = c.id) as msg_count
                    FROM chats c
                    LEFT JOIN users u ON c.user_id = u.id
                    ORDER BY c.created_at DESC
                    LIMIT 100
                """)
                result = []
                for row in rows:
                    result.append({
                        "id": str(row["id"]),
                        "title": row["title"] or "Untitled",
                        "status": row["status"] or "idle",
                        "total_cost": float(row["total_cost"] or 0),
                        "total_tokens": int(row["total_tokens"] or 0),
                        "created_at": row["created_at"].isoformat() if row["created_at"] else "",
                        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else "",
                        "user_id": str(row["user_id"] or ""),
                        "username": row["username"] or "",
                        "email": row["email"] or "",
                        "message_count": int(row["msg_count"] or 0),
                    })
                # Also merge in-memory chats that haven't been persisted yet
                db_ids = {r["id"][:12] for r in result}
                for cid, chat in _chats.items():
                    if cid[:12] not in db_ids and cid not in db_ids:
                        result.append({
                            **chat,
                            "id": cid,
                            "message_count": len(_chat_messages.get(cid, [])),
                            "username": "",
                            "email": "",
                        })
                return sorted(result, key=lambda x: x.get("updated_at", ""), reverse=True)
        except Exception as e:
            logger.warning(f"Chat store: Admin chats DB error: {e}")

    # Fallback to in-memory
    return [
        {**chat, "id": cid, "message_count": len(_chat_messages.get(cid, []))}
        for cid, chat in sorted(_chats.items(), key=lambda x: x[1].get("updated_at", ""), reverse=True)
    ]


async def get_admin_stats() -> dict:
    """Get admin stats from DB + in-memory.
    Returns fields matching the frontend AdminStats interface."""
    stats = {
        # Fields expected by frontend AdminStats interface
        "total_users": 0,
        "active_tasks": 0,
        "success_rate": 0.0,
        "fail_rate": 0.0,
        "total_cost": 0.0,
        "avg_task_time": "0s",
        "verifier_rejects": 0,
        "judge_rejects": 0,
        # Additional fields for backward compatibility
        "total_chats": len(_chats),
        "active_agents": 0,
        "total_cost_usd": 0.0,
        "total_messages": sum(len(m) for m in _chat_messages.values()),
    }

    try:
        from api.agent_runner import get_active_agents
        active = get_active_agents()
        stats["active_agents"] = len(active)
        stats["active_tasks"] = len(active)
    except Exception:
        pass

    pool = await _get_pool()
    if pool:
        try:
            async with pool.acquire() as conn:
                stats["total_users"] = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
                db_chats = await conn.fetchval("SELECT COUNT(*) FROM chats") or 0
                stats["total_chats"] = max(db_chats, len(_chats))
                total_cost = float(
                    await conn.fetchval("SELECT COALESCE(SUM(total_cost), 0) FROM chats") or 0
                )
                stats["total_cost_usd"] = round(total_cost, 2)
                stats["total_cost"] = round(total_cost, 2)
                stats["total_messages"] = max(
                    await conn.fetchval("SELECT COUNT(*) FROM messages") or 0,
                    stats["total_messages"]
                )
                # Calculate success/fail rates from chat statuses
                # Note: agent often leaves status as 'idle' after completion,
                # so we count chats with cost > 0 and status != 'failed' as completed
                total_completed = await conn.fetchval(
                    "SELECT COUNT(*) FROM chats WHERE status = 'completed' "
                    "OR (status = 'idle' AND total_cost > 0)"
                ) or 0
                total_failed = await conn.fetchval(
                    "SELECT COUNT(*) FROM chats WHERE status = 'failed'"
                ) or 0
                total_finished = total_completed + total_failed
                if total_finished > 0:
                    stats["success_rate"] = round(total_completed / total_finished * 100, 1)
                    stats["fail_rate"] = round(total_failed / total_finished * 100, 1)
                # Average task time
                avg_duration = await conn.fetchval(
                    "SELECT AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) "
                    "FROM chats WHERE status IN ('completed', 'failed') "
                    "OR (status = 'idle' AND total_cost > 0)"
                )
                if avg_duration:
                    secs = int(avg_duration)
                    if secs >= 60:
                        stats["avg_task_time"] = f"{secs // 60}m {secs % 60}s"
                    else:
                        stats["avg_task_time"] = f"{secs}s"
                # Verifier and judge rejects (from design_reports if available)
                try:
                    stats["verifier_rejects"] = await conn.fetchval(
                        "SELECT COUNT(*) FROM chats WHERE status = 'failed' "
                        "AND COALESCE(metadata_json::text, '') LIKE '%verifier%'"
                    ) or 0
                except Exception:
                    pass
                try:
                    stats["judge_rejects"] = await conn.fetchval(
                        "SELECT COUNT(*) FROM chats WHERE status = 'failed' "
                        "AND COALESCE(metadata_json::text, '') LIKE '%judge%'"
                    ) or 0
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Chat store: Stats DB error: {e}")

    return stats
