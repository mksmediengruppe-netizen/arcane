"""
ARCANE Task Queue — Redis Streams based durable task queue.

Provides reliable task enqueue/dequeue with:
- At-least-once delivery via consumer groups
- Automatic retry for failed/timed-out tasks
- Task state tracking (pending → running → completed/failed)
- Graceful shutdown support (claim + re-enqueue)

Usage:
    queue = TaskQueue(redis_url="redis://localhost:6379/0")
    await queue.connect()
    task_id = await queue.enqueue({...task_data...})
    task = await queue.dequeue(consumer_name="worker-1")
    await queue.ack(task["task_id"])
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import redis.asyncio as aioredis

from shared.utils.logger import get_logger

logger = get_logger("core.task_queue")

# Redis key prefixes
STREAM_KEY = "arcane:tasks:stream"
GROUP_NAME = "arcane-workers"
TASK_STATE_PREFIX = "arcane:task:"
ACTIVE_TASKS_KEY = "arcane:tasks:active"
METRICS_KEY = "arcane:tasks:metrics"
DEAD_LETTER_KEY = "arcane:tasks:dead"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    RETRYING = "retrying"


@dataclass
class TaskPayload:
    """Serializable task payload."""
    task_id: str
    chat_id: str
    user_message: str
    user_id: str = ""
    project_id: str = ""
    model_strategy: str = "balance"
    premium_images: bool = False
    design_check: bool = False
    premium_review: bool = False
    priority: int = 0  # 0=normal, 1=high, 2=urgent
    created_at: float = field(default_factory=time.time)
    retry_count: int = 0
    max_retries: int = 2

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "chat_id": self.chat_id,
            "user_message": self.user_message,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "model_strategy": self.model_strategy,
            "premium_images": str(self.premium_images),
            "design_check": str(self.design_check),
            "premium_review": str(self.premium_review),
            "priority": str(self.priority),
            "created_at": str(self.created_at),
            "retry_count": str(self.retry_count),
            "max_retries": str(self.max_retries),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskPayload":
        return cls(
            task_id=data["task_id"],
            chat_id=data["chat_id"],
            user_message=data["user_message"],
            user_id=data.get("user_id", ""),
            project_id=data.get("project_id", ""),
            model_strategy=data.get("model_strategy", "balance"),
            premium_images=data.get("premium_images", "False") == "True",
            design_check=data.get("design_check", "False") == "True",
            premium_review=data.get("premium_review", "False") == "True",
            priority=int(data.get("priority", "0")),
            created_at=float(data.get("created_at", "0")),
            retry_count=int(data.get("retry_count", "0")),
            max_retries=int(data.get("max_retries", "2")),
        )


class TaskQueue:
    """Redis Streams based task queue with consumer groups."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0", max_retries: int = 2):
        self._redis_url = redis_url
        self._redis: Optional[aioredis.Redis] = None
        self._max_retries = max_retries
        self._connected = False

    async def connect(self) -> None:
        """Connect to Redis and create consumer group if needed."""
        if self._connected:
            return
        self._redis = aioredis.from_url(
            self._redis_url,
            decode_responses=True,
            max_connections=20,
        )
        # Verify connection
        await self._redis.ping()
        # Create consumer group (idempotent)
        try:
            await self._redis.xgroup_create(
                STREAM_KEY, GROUP_NAME, id="0", mkstream=True
            )
            logger.info(f"Created consumer group '{GROUP_NAME}' on stream '{STREAM_KEY}'")
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
            # Group already exists — fine
        self._connected = True
        logger.info(f"TaskQueue connected to {self._redis_url}")

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.aclose()
            self._connected = False

    async def enqueue(self, payload: TaskPayload) -> str:
        """Add a task to the queue. Returns task_id."""
        assert self._connected, "TaskQueue not connected"
        task_data = payload.to_dict()
        # Add to stream
        msg_id = await self._redis.xadd(STREAM_KEY, task_data)
        # Track task state (includes full payload for interrupt recovery)
        state = {
            "status": TaskStatus.PENDING.value,
            "stream_id": msg_id,
            "enqueued_at": str(time.time()),
        }
        # Store all payload fields for interrupt/resume
        state.update(payload.to_dict())
        await self._redis.hset(f"{TASK_STATE_PREFIX}{payload.task_id}", mapping=state)
        await self._redis.expire(f"{TASK_STATE_PREFIX}{payload.task_id}", 86400)  # 24h TTL
        # Increment metrics
        await self._redis.hincrby(METRICS_KEY, "total_enqueued", 1)
        logger.info(f"Enqueued task {payload.task_id} for chat {payload.chat_id} (stream_id={msg_id})")
        return payload.task_id

    async def dequeue(
        self, consumer_name: str, block_ms: int = 5000, count: int = 1
    ) -> Optional[TaskPayload]:
        """
        Read next task from the stream using consumer group.
        Blocks for up to block_ms milliseconds.
        Returns TaskPayload or None if no tasks available.
        """
        assert self._connected, "TaskQueue not connected"
        try:
            results = await self._redis.xreadgroup(
                GROUP_NAME,
                consumer_name,
                {STREAM_KEY: ">"},
                count=count,
                block=block_ms,
            )
        except aioredis.ResponseError as e:
            if "NOGROUP" in str(e):
                # Consumer group was deleted (e.g., after flush) — recreate and retry
                try:
                    await self._redis.xgroup_create(
                        STREAM_KEY, GROUP_NAME, id="0", mkstream=True
                    )
                except aioredis.ResponseError:
                    pass
                # Retry the read after group recreation
                try:
                    results = await self._redis.xreadgroup(
                        GROUP_NAME,
                        consumer_name,
                        {STREAM_KEY: ">"},
                        count=count,
                        block=block_ms,
                    )
                except Exception:
                    return None
            else:
                raise
        if not results:
            return None
        # results = [(stream_name, [(msg_id, data), ...])]
        stream_name, messages = results[0]
        if not messages:
            return None
        msg_id, data = messages[0]
        payload = TaskPayload.from_dict(data)
        # Update state to RUNNING
        await self._redis.hset(
            f"{TASK_STATE_PREFIX}{payload.task_id}",
            mapping={
                "status": TaskStatus.RUNNING.value,
                "started_at": str(time.time()),
                "worker": consumer_name,
                "stream_id": msg_id,
            },
        )
        # Track active task
        await self._redis.hset(ACTIVE_TASKS_KEY, payload.task_id, consumer_name)
        await self._redis.hincrby(METRICS_KEY, "total_started", 1)
        logger.info(f"Dequeued task {payload.task_id} by {consumer_name} (stream_id={msg_id})")
        return payload

    async def ack(self, task_id: str, result: Optional[dict] = None) -> None:
        """Acknowledge successful task completion."""
        assert self._connected, "TaskQueue not connected"
        state = await self._redis.hgetall(f"{TASK_STATE_PREFIX}{task_id}")
        if not state:
            logger.warning(f"Cannot ack unknown task {task_id}")
            return
        stream_id = state.get("stream_id", "")
        if stream_id:
            await self._redis.xack(STREAM_KEY, GROUP_NAME, stream_id)
        # Update state
        await self._redis.hset(
            f"{TASK_STATE_PREFIX}{task_id}",
            mapping={
                "status": TaskStatus.COMPLETED.value,
                "completed_at": str(time.time()),
                "result": json.dumps(result or {}),
            },
        )
        # Remove from active
        await self._redis.hdel(ACTIVE_TASKS_KEY, task_id)
        await self._redis.hincrby(METRICS_KEY, "total_completed", 1)
        logger.info(f"Acked task {task_id}")

    async def fail(self, task_id: str, error: str, retry: bool = True) -> bool:
        """
        Mark task as failed. If retry=True and retries remain, re-enqueue.
        Returns True if task was re-enqueued for retry.
        """
        assert self._connected, "TaskQueue not connected"
        state = await self._redis.hgetall(f"{TASK_STATE_PREFIX}{task_id}")
        if not state:
            logger.warning(f"Cannot fail unknown task {task_id}")
            return False
        stream_id = state.get("stream_id", "")
        if stream_id:
            await self._redis.xack(STREAM_KEY, GROUP_NAME, stream_id)
        # Remove from active
        await self._redis.hdel(ACTIVE_TASKS_KEY, task_id)
        # Check retry (use per-task max_retries if available, else queue default)
        retry_count = int(state.get("retry_count", "0"))
        max_retries = int(state.get("max_retries", str(self._max_retries)))
        if retry and retry_count < max_retries:
            # Re-enqueue with incremented retry count (only payload fields)
            payload_keys = ("task_id", "chat_id", "user_message", "user_id", "project_id",
                           "model_strategy", "premium_images", "design_check", "premium_review",
                           "priority", "created_at", "retry_count", "max_retries")
            new_data = {k: state[k] for k in payload_keys if k in state}
            new_data["retry_count"] = str(retry_count + 1)
            # Re-add to stream
            new_msg_id = await self._redis.xadd(STREAM_KEY, new_data)
            await self._redis.hset(
                f"{TASK_STATE_PREFIX}{task_id}",
                mapping={
                    "status": TaskStatus.RETRYING.value,
                    "stream_id": new_msg_id,
                    "retry_count": str(retry_count + 1),
                    "last_error": error,
                },
            )
            await self._redis.hincrby(METRICS_KEY, "total_retried", 1)
            logger.info(f"Task {task_id} failed, retrying ({retry_count + 1}/{max_retries}): {error}")
            return True
        else:
            # Move to dead letter
            await self._redis.hset(
                f"{TASK_STATE_PREFIX}{task_id}",
                mapping={
                    "status": TaskStatus.FAILED.value,
                    "failed_at": str(time.time()),
                    "error": error,
                },
            )
            await self._redis.lpush(DEAD_LETTER_KEY, task_id)
            await self._redis.hincrby(METRICS_KEY, "total_failed", 1)
            logger.warning(f"Task {task_id} permanently failed: {error}")
            return False

    async def interrupt(self, task_id: str, state_data: Optional[dict] = None) -> None:
        """Mark task as interrupted (for graceful shutdown). Can be resumed later."""
        assert self._connected, "TaskQueue not connected"
        # Get existing task state to preserve original payload fields
        existing = await self._redis.hgetall(f"{TASK_STATE_PREFIX}{task_id}")
        mapping = {
            "status": TaskStatus.INTERRUPTED.value,
            "interrupted_at": str(time.time()),
        }
        if state_data:
            mapping["agent_state"] = json.dumps(state_data)
        await self._redis.hset(f"{TASK_STATE_PREFIX}{task_id}", mapping=mapping)
        await self._redis.hdel(ACTIVE_TASKS_KEY, task_id)
        # Re-enqueue with original payload fields so dequeue can parse it
        # We need at minimum: task_id, chat_id, user_message
        re_enqueue_data = {}
        for key in ("task_id", "chat_id", "user_message", "user_id", "project_id",
                    "model_strategy", "premium_images", "design_check", "premium_review",
                    "priority", "created_at", "retry_count", "max_retries"):
            if key in existing:
                re_enqueue_data[key] = existing[key]
        if re_enqueue_data.get("task_id"):
            new_stream_id = await self._redis.xadd(STREAM_KEY, re_enqueue_data)
            # Persist new stream_id so ack/fail can reference the correct message
            await self._redis.hset(
                f"{TASK_STATE_PREFIX}{task_id}",
                "stream_id", new_stream_id,
            )
            logger.info(f"Interrupted task {task_id}, re-enqueued for restart")
        else:
            logger.warning(f"Interrupted task {task_id}, but no payload to re-enqueue")

    async def get_task_state(self, task_id: str) -> Optional[dict]:
        """Get current state of a task."""
        assert self._connected, "TaskQueue not connected"
        state = await self._redis.hgetall(f"{TASK_STATE_PREFIX}{task_id}")
        return state if state else None

    async def get_active_tasks(self) -> dict[str, str]:
        """Get all active tasks: {task_id: worker_name}."""
        assert self._connected, "TaskQueue not connected"
        return await self._redis.hgetall(ACTIVE_TASKS_KEY)

    async def get_metrics(self) -> dict[str, int]:
        """Get queue metrics."""
        assert self._connected, "TaskQueue not connected"
        raw = await self._redis.hgetall(METRICS_KEY)
        return {k: int(v) for k, v in raw.items()}

    async def get_queue_length(self) -> int:
        """Get number of pending messages in the stream."""
        assert self._connected, "TaskQueue not connected"
        info = await self._redis.xinfo_stream(STREAM_KEY)
        return info.get("length", 0)

    async def get_pending_count(self) -> int:
        """Get number of messages delivered but not yet acked."""
        assert self._connected, "TaskQueue not connected"
        try:
            info = await self._redis.xpending(STREAM_KEY, GROUP_NAME)
            return info.get("pending", 0)
        except Exception:
            return 0

    async def claim_stale_tasks(self, min_idle_ms: int = 300000, consumer_name: str = "reclaimer") -> list[str]:
        """
        Claim tasks that have been pending for too long (default 5 min).
        Used for recovering from crashed workers.
        """
        assert self._connected, "TaskQueue not connected"
        try:
            pending = await self._redis.xpending_range(
                STREAM_KEY, GROUP_NAME, min="-", max="+", count=100
            )
        except Exception:
            return []
        claimed = []
        for entry in pending:
            if entry.get("time_since_delivered", 0) >= min_idle_ms:
                msg_id = entry["message_id"]
                try:
                    result = await self._redis.xclaim(
                        STREAM_KEY, GROUP_NAME, consumer_name, min_idle_ms, [msg_id]
                    )
                    if result:
                        claimed.append(msg_id)
                except Exception as e:
                    logger.warning(f"Failed to claim {msg_id}: {e}")
        if claimed:
            logger.info(f"Claimed {len(claimed)} stale tasks")
        return claimed

    async def flush(self) -> None:
        """Clear all queue data. USE ONLY IN TESTS."""
        assert self._connected, "TaskQueue not connected"
        keys = await self._redis.keys("arcane:task*")
        if keys:
            await self._redis.delete(*keys)
        # Delete stream and related keys
        for key in [STREAM_KEY, ACTIVE_TASKS_KEY, METRICS_KEY, DEAD_LETTER_KEY]:
            try:
                await self._redis.delete(key)
            except Exception:
                pass
        # Recreate stream and consumer group
        try:
            await self._redis.xgroup_create(
                STREAM_KEY, GROUP_NAME, id="0", mkstream=True
            )
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise


def make_task_id() -> str:
    """Generate a unique task ID."""
    return f"task-{uuid.uuid4().hex[:12]}"
