"""
ARCANE Parallel Execution Tests

Comprehensive tests for:
1. TaskQueue — enqueue/dequeue/ack/fail/retry/interrupt
2. WorkerPool — parallel execution, max workers, backpressure
3. Graceful shutdown — SIGTERM saves state, restart resumes
4. Concurrent tasks — 5+ tasks in parallel, no race conditions
5. Fallback — direct execution when Redis unavailable

Requires Redis running on localhost:6379 (or REDIS_URL env var).
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ─── Fixtures ────────────────────────────────────────────────

# Use DB 2 for tests to isolate from production worker pool on DB 1
REDIS_URL = os.getenv("REDIS_TEST_URL", "redis://localhost:6380/2")


@pytest_asyncio.fixture
async def task_queue():
    """Create a fresh TaskQueue connected to test Redis DB (DB 2, isolated from production)."""
    from core.task_queue import TaskQueue
    queue = TaskQueue(redis_url=REDIS_URL, max_retries=2)
    await queue.connect()
    await queue.flush()  # Clean slate
    yield queue
    await queue.flush()
    await queue.disconnect()


@pytest_asyncio.fixture
async def make_payload():
    """Factory for creating test TaskPayloads."""
    from core.task_queue import TaskPayload, make_task_id

    def _make(chat_id: str = None, message: str = "Создай лендинг для тестовой компании"):
        return TaskPayload(
            task_id=make_task_id(),
            chat_id=chat_id or f"chat-{uuid.uuid4().hex[:8]}",
            user_message=message,
            user_id=f"user-{uuid.uuid4().hex[:8]}",
            project_id=f"proj-{uuid.uuid4().hex[:8]}",
        )
    return _make


# ═══════════════════════════════════════════════════════════════
# 1. TaskQueue Tests
# ═══════════════════════════════════════════════════════════════

class TestTaskQueueBasic:
    """Basic enqueue/dequeue/ack operations."""

    @pytest.mark.asyncio
    async def test_enqueue_returns_task_id(self, task_queue, make_payload):
        payload = make_payload()
        task_id = await task_queue.enqueue(payload)
        assert task_id == payload.task_id
        assert task_id.startswith("task-")

    @pytest.mark.asyncio
    async def test_dequeue_returns_payload(self, task_queue, make_payload):
        payload = make_payload(message="Тестовое сообщение")
        await task_queue.enqueue(payload)

        result = await task_queue.dequeue(consumer_name="test-worker", block_ms=1000)
        assert result is not None
        assert result.task_id == payload.task_id
        assert result.chat_id == payload.chat_id
        assert result.user_message == "Тестовое сообщение"

    @pytest.mark.asyncio
    async def test_dequeue_empty_returns_none(self, task_queue):
        result = await task_queue.dequeue(consumer_name="test-worker", block_ms=100)
        assert result is None

    @pytest.mark.asyncio
    async def test_ack_completes_task(self, task_queue, make_payload):
        payload = make_payload()
        await task_queue.enqueue(payload)
        await task_queue.dequeue(consumer_name="test-worker", block_ms=1000)

        await task_queue.ack(payload.task_id, result={"url": "/demo/test/"})

        state = await task_queue.get_task_state(payload.task_id)
        assert state["status"] == "completed"
        assert "completed_at" in state

    @pytest.mark.asyncio
    async def test_fifo_order(self, task_queue, make_payload):
        """Tasks are dequeued in FIFO order."""
        p1 = make_payload(message="first")
        p2 = make_payload(message="second")
        p3 = make_payload(message="third")

        await task_queue.enqueue(p1)
        await task_queue.enqueue(p2)
        await task_queue.enqueue(p3)

        r1 = await task_queue.dequeue(consumer_name="w1", block_ms=100)
        r2 = await task_queue.dequeue(consumer_name="w2", block_ms=100)
        r3 = await task_queue.dequeue(consumer_name="w3", block_ms=100)

        assert r1.user_message == "first"
        assert r2.user_message == "second"
        assert r3.user_message == "third"


class TestTaskQueueRetry:
    """Failure handling and retry logic."""

    @pytest.mark.asyncio
    async def test_fail_with_retry(self, task_queue, make_payload):
        """Failed task is re-enqueued for retry."""
        payload = make_payload()
        await task_queue.enqueue(payload)
        await task_queue.dequeue(consumer_name="w1", block_ms=1000)

        retried = await task_queue.fail(payload.task_id, "LLM timeout", retry=True)
        assert retried is True

        state = await task_queue.get_task_state(payload.task_id)
        assert state["status"] == "retrying"
        assert state["retry_count"] == "1"

    @pytest.mark.asyncio
    async def test_fail_exhausts_retries(self, task_queue, make_payload):
        """After max retries, task goes to dead letter."""
        payload = make_payload()
        payload.max_retries = 1
        await task_queue.enqueue(payload)

        # First attempt
        await task_queue.dequeue(consumer_name="w1", block_ms=1000)
        retried = await task_queue.fail(payload.task_id, "error 1", retry=True)
        assert retried is True

        # Second attempt (retry)
        r2 = await task_queue.dequeue(consumer_name="w1", block_ms=1000)
        # The retried message has the state data, not a clean TaskPayload
        # But it should be dequeue-able
        assert r2 is not None

        # Fail again — should go to dead letter
        retried2 = await task_queue.fail(payload.task_id, "error 2", retry=True)
        assert retried2 is False  # No more retries

        state = await task_queue.get_task_state(payload.task_id)
        assert state["status"] == "failed"

    @pytest.mark.asyncio
    async def test_fail_no_retry(self, task_queue, make_payload):
        """Explicit no-retry goes straight to dead letter."""
        payload = make_payload()
        await task_queue.enqueue(payload)
        await task_queue.dequeue(consumer_name="w1", block_ms=1000)

        retried = await task_queue.fail(payload.task_id, "fatal error", retry=False)
        assert retried is False

        state = await task_queue.get_task_state(payload.task_id)
        assert state["status"] == "failed"


class TestTaskQueueInterrupt:
    """Interrupt and resume for graceful shutdown."""

    @pytest.mark.asyncio
    async def test_interrupt_saves_state(self, task_queue, make_payload):
        payload = make_payload()
        await task_queue.enqueue(payload)
        await task_queue.dequeue(consumer_name="w1", block_ms=1000)

        await task_queue.interrupt(payload.task_id, state_data={"iteration": 5, "tools_used": 3})

        state = await task_queue.get_task_state(payload.task_id)
        assert state["status"] == "interrupted"
        assert "agent_state" in state
        import json
        agent_state = json.loads(state["agent_state"])
        assert agent_state["iteration"] == 5

    @pytest.mark.asyncio
    async def test_interrupt_reenqueues(self, task_queue, make_payload):
        """Interrupted task is re-enqueued for pickup after restart."""
        payload = make_payload()
        await task_queue.enqueue(payload)
        await task_queue.dequeue(consumer_name="w1", block_ms=1000)

        await task_queue.interrupt(payload.task_id)

        # Should be available for dequeue again
        r2 = await task_queue.dequeue(consumer_name="w2", block_ms=1000)
        assert r2 is not None


class TestTaskQueueMetrics:
    """Queue metrics and monitoring."""

    @pytest.mark.asyncio
    async def test_metrics_tracking(self, task_queue, make_payload):
        p1 = make_payload()
        p2 = make_payload()
        await task_queue.enqueue(p1)
        await task_queue.enqueue(p2)

        metrics = await task_queue.get_metrics()
        assert metrics["total_enqueued"] == 2

        await task_queue.dequeue(consumer_name="w1", block_ms=1000)
        metrics = await task_queue.get_metrics()
        assert metrics["total_started"] == 1

        await task_queue.ack(p1.task_id)
        metrics = await task_queue.get_metrics()
        assert metrics["total_completed"] == 1

    @pytest.mark.asyncio
    async def test_queue_length(self, task_queue, make_payload):
        for _ in range(5):
            await task_queue.enqueue(make_payload())

        length = await task_queue.get_queue_length()
        assert length == 5

    @pytest.mark.asyncio
    async def test_active_tasks_tracking(self, task_queue, make_payload):
        p1 = make_payload()
        await task_queue.enqueue(p1)
        await task_queue.dequeue(consumer_name="w1", block_ms=1000)

        active = await task_queue.get_active_tasks()
        assert p1.task_id in active
        assert active[p1.task_id] == "w1"

        await task_queue.ack(p1.task_id)
        active = await task_queue.get_active_tasks()
        assert p1.task_id not in active


# ═══════════════════════════════════════════════════════════════
# 2. WorkerPool Tests
# ═══════════════════════════════════════════════════════════════

class TestWorkerPoolBasic:
    """Worker pool lifecycle and basic operations."""

    @pytest.mark.asyncio
    async def test_pool_starts_and_stops(self, task_queue):
        from core.worker_pool import WorkerPool
        pool = WorkerPool(task_queue=task_queue, max_workers=3)

        await pool.start()
        assert pool.is_running
        assert pool.idle_count == 3
        assert pool.active_count == 0

        interrupted = await pool.shutdown(timeout=5)
        assert not pool.is_running
        assert interrupted == []

    @pytest.mark.asyncio
    async def test_pool_stats(self, task_queue):
        from core.worker_pool import WorkerPool
        pool = WorkerPool(task_queue=task_queue, max_workers=4)
        await pool.start()

        stats = pool.get_pool_stats()
        assert stats["max_workers"] == 4
        assert stats["idle_workers"] == 4
        assert stats["active_workers"] == 0
        assert stats["running"] is True

        await pool.shutdown(timeout=5)

    @pytest.mark.asyncio
    async def test_workers_info(self, task_queue):
        from core.worker_pool import WorkerPool
        pool = WorkerPool(task_queue=task_queue, max_workers=2)
        await pool.start()

        info = pool.get_workers_info()
        assert len(info) == 2
        assert info[0]["name"] == "worker-0"
        assert info[1]["name"] == "worker-1"
        assert all(w["status"] == "idle" for w in info)

        await pool.shutdown(timeout=5)


class TestWorkerPoolExecution:
    """Task execution through the worker pool."""

    @pytest.mark.asyncio
    async def test_pool_executes_task(self, task_queue, make_payload):
        """Pool picks up and executes a task from the queue."""
        from core.worker_pool import WorkerPool

        completed_tasks = []

        async def on_complete(payload, result):
            completed_tasks.append(payload.task_id)

        pool = WorkerPool(
            task_queue=task_queue,
            max_workers=2,
            poll_interval_ms=500,
            on_task_complete=on_complete,
        )

        # Mock _execute_task to avoid needing real AgentLoop
        async def mock_execute(payload, worker_name):
            await asyncio.sleep(0.1)  # Simulate work
            return {"status": "done", "url": "/demo/test/"}

        pool._execute_task = mock_execute
        await pool.start()

        payload = make_payload()
        await task_queue.enqueue(payload)

        # Wait for task to be picked up and completed
        for _ in range(20):
            await asyncio.sleep(0.2)
            if completed_tasks:
                break

        assert payload.task_id in completed_tasks
        await pool.shutdown(timeout=5)

    @pytest.mark.asyncio
    async def test_pool_parallel_execution(self, task_queue, make_payload):
        """Multiple tasks execute in parallel, not sequentially."""
        from core.worker_pool import WorkerPool

        execution_log = []  # (task_id, start_time, end_time)

        async def mock_execute(payload, worker_name):
            start = time.time()
            await asyncio.sleep(0.5)  # Each task takes 0.5s
            end = time.time()
            execution_log.append((payload.task_id, start, end))
            return {"status": "done"}

        pool = WorkerPool(
            task_queue=task_queue,
            max_workers=5,
            poll_interval_ms=200,
        )
        pool._execute_task = mock_execute
        await pool.start()

        # Enqueue 5 tasks
        payloads = [make_payload() for _ in range(5)]
        for p in payloads:
            await task_queue.enqueue(p)

        # Wait for all to complete (should take ~0.5s if parallel, ~2.5s if sequential)
        for _ in range(30):
            await asyncio.sleep(0.2)
            if len(execution_log) == 5:
                break

        assert len(execution_log) == 5

        # Verify parallel execution: all tasks should overlap in time
        starts = [s for _, s, _ in execution_log]
        ends = [e for _, _, e in execution_log]
        total_wall_time = max(ends) - min(starts)

        # If truly parallel, wall time should be ~0.5s (not 5 * 0.5 = 2.5s)
        assert total_wall_time < 1.5, f"Tasks took {total_wall_time:.2f}s — not parallel!"

        await pool.shutdown(timeout=5)

    @pytest.mark.asyncio
    async def test_pool_respects_max_workers(self, task_queue, make_payload):
        """Pool doesn't exceed max_workers concurrent tasks."""
        from core.worker_pool import WorkerPool

        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def mock_execute(payload, worker_name):
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                max_concurrent = max(max_concurrent, current_concurrent)
            await asyncio.sleep(0.3)
            async with lock:
                current_concurrent -= 1
            return {"status": "done"}

        pool = WorkerPool(
            task_queue=task_queue,
            max_workers=3,
            poll_interval_ms=100,
        )
        pool._execute_task = mock_execute
        await pool.start()

        # Enqueue 10 tasks
        for _ in range(10):
            await task_queue.enqueue(make_payload())

        # Wait for all to complete
        for _ in range(60):
            await asyncio.sleep(0.2)
            metrics = await task_queue.get_metrics()
            if metrics.get("total_completed", 0) >= 10:
                break

        assert max_concurrent <= 3, f"Max concurrent was {max_concurrent}, expected <= 3"
        assert max_concurrent >= 2, f"Max concurrent was {max_concurrent}, expected >= 2 (parallelism)"

        await pool.shutdown(timeout=5)


class TestWorkerPoolFailure:
    """Task failure handling in the worker pool."""

    @pytest.mark.asyncio
    async def test_pool_handles_task_failure(self, task_queue, make_payload):
        """Failed tasks don't crash the worker — it continues processing."""
        from core.worker_pool import WorkerPool

        results = []

        async def mock_execute(payload, worker_name):
            if "fail" in payload.user_message:
                raise RuntimeError("Simulated failure")
            results.append(payload.task_id)
            return {"status": "done"}

        pool = WorkerPool(
            task_queue=task_queue,
            max_workers=2,
            poll_interval_ms=200,
        )
        pool._execute_task = mock_execute
        await pool.start()

        # Enqueue: fail, success, fail, success
        p_fail1 = make_payload(message="fail this task")
        p_ok1 = make_payload(message="succeed this task")
        p_fail2 = make_payload(message="fail again")
        p_ok2 = make_payload(message="succeed again")

        await task_queue.enqueue(p_fail1)
        await task_queue.enqueue(p_ok1)
        await task_queue.enqueue(p_fail2)
        await task_queue.enqueue(p_ok2)

        # Wait for processing
        for _ in range(30):
            await asyncio.sleep(0.3)
            if len(results) >= 2:
                break

        # Both success tasks should have completed
        assert p_ok1.task_id in results
        assert p_ok2.task_id in results

        # Workers should still be running
        assert pool.is_running
        stats = pool.get_pool_stats()
        assert stats["total_failed"] >= 2

        await pool.shutdown(timeout=5)

    @pytest.mark.asyncio
    async def test_pool_handles_timeout(self, task_queue, make_payload):
        """Tasks that exceed timeout are failed without crashing the pool."""
        from core.worker_pool import WorkerPool

        async def mock_execute(payload, worker_name):
            await asyncio.sleep(10)  # Will timeout
            return {"status": "done"}

        pool = WorkerPool(
            task_queue=task_queue,
            max_workers=1,
            poll_interval_ms=200,
            task_timeout=1,  # 1 second timeout
        )
        pool._execute_task = mock_execute
        await pool.start()

        payload = make_payload()
        await task_queue.enqueue(payload)

        # Wait for timeout
        for _ in range(15):
            await asyncio.sleep(0.5)
            state = await task_queue.get_task_state(payload.task_id)
            if state and state.get("status") == "failed":
                break

        state = await task_queue.get_task_state(payload.task_id)
        assert state["status"] == "failed"
        assert pool.is_running  # Pool still alive

        await pool.shutdown(timeout=5)


# ═══════════════════════════════════════════════════════════════
# 3. Graceful Shutdown Tests
# ═══════════════════════════════════════════════════════════════

class TestGracefulShutdown:
    """Graceful shutdown saves active task state."""

    @pytest.mark.asyncio
    async def test_shutdown_saves_active_tasks(self, task_queue, make_payload):
        """Active tasks are interrupted and saved during shutdown."""
        from core.worker_pool import WorkerPool

        async def mock_execute(payload, worker_name):
            await asyncio.sleep(30)  # Long-running task
            return {"status": "done"}

        pool = WorkerPool(
            task_queue=task_queue,
            max_workers=3,
            poll_interval_ms=200,
        )
        pool._execute_task = mock_execute
        await pool.start()

        # Enqueue 3 tasks
        payloads = [make_payload() for _ in range(3)]
        for p in payloads:
            await task_queue.enqueue(p)

        # Wait for tasks to start
        for _ in range(20):
            await asyncio.sleep(0.2)
            if pool.active_count >= 2:
                break

        assert pool.active_count >= 2, "Tasks should be running"

        # Shutdown — should save state
        interrupted = await pool.shutdown(timeout=5)
        assert len(interrupted) >= 2, f"Expected >= 2 interrupted tasks, got {len(interrupted)}"

        # Verify interrupted tasks are in the queue state
        for task_id in interrupted:
            state = await task_queue.get_task_state(task_id)
            assert state["status"] == "interrupted"

    @pytest.mark.asyncio
    async def test_shutdown_with_no_active_tasks(self, task_queue):
        """Clean shutdown when no tasks are running."""
        from core.worker_pool import WorkerPool

        pool = WorkerPool(task_queue=task_queue, max_workers=2)
        await pool.start()
        await asyncio.sleep(0.3)

        interrupted = await pool.shutdown(timeout=5)
        assert interrupted == []
        assert not pool.is_running

    @pytest.mark.asyncio
    async def test_interrupted_tasks_resumable(self, task_queue, make_payload):
        """Interrupted tasks can be picked up by a new pool after restart."""
        from core.worker_pool import WorkerPool

        started_tasks = []

        async def slow_execute(payload, worker_name):
            started_tasks.append(payload.task_id)
            await asyncio.sleep(30)
            return {"status": "done"}

        # Pool 1: start and interrupt
        pool1 = WorkerPool(task_queue=task_queue, max_workers=2, poll_interval_ms=200)
        pool1._execute_task = slow_execute
        await pool1.start()

        payload = make_payload()
        await task_queue.enqueue(payload)

        for _ in range(20):
            await asyncio.sleep(0.2)
            if started_tasks:
                break

        interrupted = await pool1.shutdown(timeout=3)
        assert len(interrupted) >= 1

        # Pool 2: should pick up the interrupted task
        resumed_tasks = []

        async def fast_execute(payload, worker_name):
            resumed_tasks.append(payload.task_id)
            return {"status": "resumed"}

        pool2 = WorkerPool(task_queue=task_queue, max_workers=2, poll_interval_ms=200)
        pool2._execute_task = fast_execute
        await pool2.start()

        for _ in range(20):
            await asyncio.sleep(0.3)
            if resumed_tasks:
                break

        assert len(resumed_tasks) >= 1, "Interrupted task should have been resumed"
        await pool2.shutdown(timeout=5)


# ═══════════════════════════════════════════════════════════════
# 4. Concurrent Tasks — Race Condition Tests
# ═══════════════════════════════════════════════════════════════

class TestConcurrentTasks:
    """Race condition and data integrity tests."""

    @pytest.mark.asyncio
    async def test_no_duplicate_execution(self, task_queue, make_payload):
        """Each task is executed exactly once, even with multiple workers."""
        from core.worker_pool import WorkerPool

        execution_counts = {}
        lock = asyncio.Lock()

        async def mock_execute(payload, worker_name):
            async with lock:
                execution_counts[payload.task_id] = execution_counts.get(payload.task_id, 0) + 1
            await asyncio.sleep(0.1)
            return {"status": "done"}

        pool = WorkerPool(
            task_queue=task_queue,
            max_workers=5,
            poll_interval_ms=100,
        )
        pool._execute_task = mock_execute
        await pool.start()

        # Enqueue 20 tasks
        for _ in range(20):
            await task_queue.enqueue(make_payload())

        # Wait for all to complete
        for _ in range(60):
            await asyncio.sleep(0.2)
            metrics = await task_queue.get_metrics()
            if metrics.get("total_completed", 0) >= 20:
                break

        # Each task should have been executed exactly once
        for task_id, count in execution_counts.items():
            assert count == 1, f"Task {task_id} executed {count} times!"

        assert len(execution_counts) == 20
        await pool.shutdown(timeout=5)

    @pytest.mark.asyncio
    async def test_same_chat_different_tasks(self, task_queue, make_payload):
        """Multiple tasks for the same chat_id are handled correctly."""
        from core.worker_pool import WorkerPool

        results = []
        lock = asyncio.Lock()

        async def mock_execute(payload, worker_name):
            await asyncio.sleep(0.1)
            async with lock:
                results.append((payload.chat_id, payload.user_message))
            return {"status": "done"}

        pool = WorkerPool(
            task_queue=task_queue,
            max_workers=3,
            poll_interval_ms=200,
        )
        pool._execute_task = mock_execute
        await pool.start()

        # Same chat, different messages
        chat_id = "shared-chat-123"
        for i in range(5):
            p = make_payload(chat_id=chat_id, message=f"message-{i}")
            await task_queue.enqueue(p)

        for _ in range(30):
            await asyncio.sleep(0.2)
            if len(results) >= 5:
                break

        assert len(results) == 5
        messages = sorted([msg for _, msg in results])
        assert messages == [f"message-{i}" for i in range(5)]

        await pool.shutdown(timeout=5)

    @pytest.mark.asyncio
    async def test_high_throughput(self, task_queue, make_payload):
        """50 tasks processed without errors or data loss."""
        from core.worker_pool import WorkerPool

        completed = set()
        lock = asyncio.Lock()

        async def mock_execute(payload, worker_name):
            await asyncio.sleep(0.05)  # Fast tasks
            async with lock:
                completed.add(payload.task_id)
            return {"status": "done"}

        pool = WorkerPool(
            task_queue=task_queue,
            max_workers=5,
            poll_interval_ms=100,
        )
        pool._execute_task = mock_execute
        await pool.start()

        task_ids = set()
        for _ in range(50):
            p = make_payload()
            task_ids.add(p.task_id)
            await task_queue.enqueue(p)

        # Wait for all
        for _ in range(100):
            await asyncio.sleep(0.2)
            if len(completed) >= 50:
                break

        assert completed == task_ids, f"Missing tasks: {task_ids - completed}"
        await pool.shutdown(timeout=5)


# ═══════════════════════════════════════════════════════════════
# 5. Fallback Tests
# ═══════════════════════════════════════════════════════════════

class TestFallback:
    """Fallback to direct execution when Redis is unavailable."""

    @pytest.mark.asyncio
    async def test_start_agent_falls_back_on_redis_error(self):
        """start_agent_for_chat falls back to direct execution if Redis fails."""
        from core.task_queue import TaskPayload, make_task_id

        # Mock _get_task_queue to raise
        with patch("api.agent_runner._get_task_queue", side_effect=ConnectionError("Redis down")):
            with patch("api.agent_runner._start_agent_direct", new_callable=AsyncMock) as mock_direct:
                mock_direct.return_value = "direct-fallback"
                from api.agent_runner import start_agent_for_chat
                result = await start_agent_for_chat(
                    chat_id="test-chat",
                    user_message="test",
                    user_id="test-user",
                )
                mock_direct.assert_called_once()

    @pytest.mark.asyncio
    async def test_task_payload_serialization(self):
        """TaskPayload round-trips through dict serialization."""
        from core.task_queue import TaskPayload

        original = TaskPayload(
            task_id="task-abc123",
            chat_id="chat-xyz",
            user_message="Создай лендинг для ресторана",
            user_id="user-1",
            project_id="proj-1",
            model_strategy="quality",
            premium_images=True,
            design_check=True,
            premium_review=False,
            priority=1,
            retry_count=1,
            max_retries=3,
        )

        d = original.to_dict()
        restored = TaskPayload.from_dict(d)

        assert restored.task_id == original.task_id
        assert restored.chat_id == original.chat_id
        assert restored.user_message == original.user_message
        assert restored.premium_images is True
        assert restored.design_check is True
        assert restored.premium_review is False
        assert restored.priority == 1
        assert restored.retry_count == 1
        assert restored.max_retries == 3
