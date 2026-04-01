"""
ARCANE Worker Pool — Async worker pool with concurrency control.

Manages N concurrent agent workers that pull tasks from the Redis queue.
Supports:
- Configurable max_workers (default 5)
- Backpressure: workers only pull when they have capacity
- Graceful shutdown: saves all active agent states
- Health monitoring: tracks worker status and task progress
- Stale task recovery on startup

Usage:
    pool = WorkerPool(task_queue=queue, max_workers=5)
    await pool.start()
    # ... pool runs in background ...
    await pool.shutdown(timeout=30)
"""
from __future__ import annotations

import asyncio
import signal
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

from shared.utils.logger import get_logger

logger = get_logger("core.worker_pool")


class WorkerStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass
class WorkerInfo:
    """Runtime info for a single worker."""
    name: str
    status: WorkerStatus = WorkerStatus.IDLE
    current_task_id: Optional[str] = None
    current_chat_id: Optional[str] = None
    tasks_completed: int = 0
    tasks_failed: int = 0
    started_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)


class WorkerPool:
    """
    Async worker pool that pulls tasks from TaskQueue and executes them
    via the agent runner.
    """

    def __init__(
        self,
        task_queue,  # core.task_queue.TaskQueue
        max_workers: int = 5,
        poll_interval_ms: int = 2000,
        task_timeout: int = 700,  # slightly above HARD_TIMEOUT_SEC (600)
        on_task_start: Optional[Callable] = None,
        on_task_complete: Optional[Callable] = None,
        on_task_fail: Optional[Callable] = None,
    ):
        self._queue = task_queue
        self._max_workers = max_workers
        self._poll_interval_ms = poll_interval_ms
        self._task_timeout = task_timeout
        self._on_task_start = on_task_start
        self._on_task_complete = on_task_complete
        self._on_task_fail = on_task_fail

        self._workers: dict[str, WorkerInfo] = {}
        self._worker_tasks: dict[str, asyncio.Task] = {}
        self._agent_instances: dict[str, Any] = {}  # task_id -> AgentLoop instance
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._supervisor_task: Optional[asyncio.Task] = None

    @property
    def max_workers(self) -> int:
        return self._max_workers

    @property
    def active_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.status == WorkerStatus.BUSY)

    @property
    def idle_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.status == WorkerStatus.IDLE)

    @property
    def is_running(self) -> bool:
        return self._running

    def get_workers_info(self) -> list[dict]:
        """Get status of all workers."""
        return [
            {
                "name": w.name,
                "status": w.status.value,
                "current_task_id": w.current_task_id,
                "current_chat_id": w.current_chat_id,
                "tasks_completed": w.tasks_completed,
                "tasks_failed": w.tasks_failed,
                "uptime": time.time() - w.started_at,
                "idle_time": time.time() - w.last_activity if w.status == WorkerStatus.IDLE else 0,
            }
            for w in self._workers.values()
        ]

    def get_pool_stats(self) -> dict:
        """Get aggregate pool statistics."""
        return {
            "max_workers": self._max_workers,
            "active_workers": self.active_count,
            "idle_workers": self.idle_count,
            "total_completed": sum(w.tasks_completed for w in self._workers.values()),
            "total_failed": sum(w.tasks_failed for w in self._workers.values()),
            "running": self._running,
        }

    async def start(self) -> None:
        """Start the worker pool."""
        if self._running:
            logger.warning("WorkerPool already running")
            return

        self._running = True
        self._shutdown_event.clear()
        logger.info(f"Starting WorkerPool with {self._max_workers} workers")

        # Recover stale tasks from previous run
        try:
            claimed = await self._queue.claim_stale_tasks(
                min_idle_ms=60000, consumer_name="recovery"
            )
            if claimed:
                logger.info(f"Recovered {len(claimed)} stale tasks from previous run")
        except Exception as e:
            logger.warning(f"Stale task recovery failed: {e}")

        # Start worker coroutines
        for i in range(self._max_workers):
            name = f"worker-{i}"
            self._workers[name] = WorkerInfo(name=name)
            self._worker_tasks[name] = asyncio.create_task(
                self._worker_loop(name), name=f"arcane-{name}"
            )

        # Start supervisor
        self._supervisor_task = asyncio.create_task(
            self._supervisor_loop(), name="arcane-supervisor"
        )

        logger.info(f"WorkerPool started: {self._max_workers} workers active")

    async def shutdown(self, timeout: float = 30.0) -> list[str]:
        """
        Gracefully shutdown the pool.
        Returns list of task_ids that were interrupted and saved.
        """
        if not self._running:
            return []

        logger.info(f"Shutting down WorkerPool (timeout={timeout}s)...")
        self._running = False
        self._shutdown_event.set()

        interrupted_tasks = []

        # First: identify busy workers and save their task state BEFORE cancelling
        for name, info in self._workers.items():
            if info.current_task_id and info.status == WorkerStatus.BUSY:
                agent = self._agent_instances.get(info.current_task_id)
                state_data = None
                if agent and hasattr(agent, "get_serializable_state"):
                    try:
                        state_data = agent.get_serializable_state()
                    except Exception:
                        pass
                try:
                    await self._queue.interrupt(info.current_task_id, state_data)
                    interrupted_tasks.append(info.current_task_id)
                    logger.info(f"Saved interrupted task {info.current_task_id} from {name}")
                except Exception as e:
                    logger.error(f"Failed to save interrupted task {info.current_task_id}: {e}")
            info.status = WorkerStatus.STOPPING

        # Then: cancel all worker tasks
        for name, task in self._worker_tasks.items():
            task.cancel()

        # Cancel supervisor
        if self._supervisor_task and not self._supervisor_task.done():
            self._supervisor_task.cancel()

        # Wait for cancellations
        all_tasks = list(self._worker_tasks.values())
        if self._supervisor_task:
            all_tasks.append(self._supervisor_task)
        await asyncio.gather(*all_tasks, return_exceptions=True)

        # Cleanup
        for name in list(self._workers.keys()):
            self._workers[name].status = WorkerStatus.STOPPED
        self._agent_instances.clear()

        logger.info(f"WorkerPool shutdown complete. Interrupted tasks: {len(interrupted_tasks)}")
        return interrupted_tasks

    async def _worker_loop(self, worker_name: str) -> None:
        """Main loop for a single worker."""
        info = self._workers[worker_name]
        logger.info(f"{worker_name} started")

        while self._running and not self._shutdown_event.is_set():
            try:
                # Pull task from queue
                payload = await self._queue.dequeue(
                    consumer_name=worker_name,
                    block_ms=self._poll_interval_ms,
                )
                if payload is None:
                    continue  # No tasks available, loop back

                # Execute task
                info.status = WorkerStatus.BUSY
                info.current_task_id = payload.task_id
                info.current_chat_id = payload.chat_id
                info.last_activity = time.time()

                if self._on_task_start:
                    try:
                        await self._on_task_start(payload)
                    except Exception:
                        pass

                logger.info(f"{worker_name} executing task {payload.task_id} (chat={payload.chat_id})")

                try:
                    result = await asyncio.wait_for(
                        self._execute_task(payload, worker_name),
                        timeout=self._task_timeout,
                    )
                    await self._queue.ack(payload.task_id, result)
                    info.tasks_completed += 1

                    if self._on_task_complete:
                        try:
                            await self._on_task_complete(payload, result)
                        except Exception:
                            pass

                    logger.info(f"{worker_name} completed task {payload.task_id}")

                except asyncio.TimeoutError:
                    error_msg = f"Task timed out after {self._task_timeout}s"
                    await self._queue.fail(payload.task_id, error_msg, retry=False)
                    info.tasks_failed += 1
                    logger.error(f"{worker_name}: {error_msg} for task {payload.task_id}")

                    if self._on_task_fail:
                        try:
                            await self._on_task_fail(payload, error_msg)
                        except Exception:
                            pass

                except asyncio.CancelledError:
                    # Graceful shutdown — don't fail the task, it was already interrupted by shutdown()
                    # Keep worker state as BUSY so shutdown() can see it was active
                    logger.info(f"{worker_name} cancelled during task {payload.task_id}")
                    raise  # Propagate to outer CancelledError handler

                except Exception as e:
                    error_msg = f"{type(e).__name__}: {str(e)}"
                    retried = await self._queue.fail(payload.task_id, error_msg, retry=True)
                    info.tasks_failed += 1
                    logger.error(f"{worker_name} failed task {payload.task_id}: {error_msg}")

                    if self._on_task_fail:
                        try:
                            await self._on_task_fail(payload, error_msg)
                        except Exception:
                            pass

                    # Cleanup only on non-cancel paths
                    self._agent_instances.pop(payload.task_id, None)
                    info.status = WorkerStatus.IDLE
                    info.current_task_id = None
                    info.current_chat_id = None
                    info.last_activity = time.time()

                else:
                    # Cleanup on success path
                    self._agent_instances.pop(payload.task_id, None)
                    info.status = WorkerStatus.IDLE
                    info.current_task_id = None
                    info.current_chat_id = None
                    info.last_activity = time.time()

            except asyncio.CancelledError:
                break
            except ConnectionError as e:
                logger.warning(f"{worker_name} Redis connection lost: {e}, retrying in 2s")
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"{worker_name} unexpected error: {e}\n{traceback.format_exc()}")
                await asyncio.sleep(1)  # Brief pause before retrying

        info.status = WorkerStatus.STOPPED
        logger.info(f"{worker_name} stopped (completed={info.tasks_completed}, failed={info.tasks_failed})")

    async def _execute_task(self, payload, worker_name: str) -> dict:
        """
        Execute a single task by running the agent loop.
        Mirrors the exact initialization pattern from api/agent_runner.py.
        """
        from api.sse import SSEEmitter
        from api.agent_runner import _make_emitter
        from core.agent_loop import AgentLoop
        from core.tool_executor import ToolExecutor
        from core.tool_registry import ToolRegistry
        from shared.llm.client import UnifiedLLMClient
        from shared.llm.router import ModelRouter
        from config.settings import get_config

        config = get_config()
        emitter = SSEEmitter(payload.chat_id)

        try:
            await emitter.status("thinking", "Analyzing your request...")

            llm_client = UnifiedLLMClient(config)
            router = ModelRouter(
                client=llm_client,
                strategy=payload.model_strategy,
            )
            registry = ToolRegistry()
            workspace_dir = config.get_project_dir(payload.project_id or payload.chat_id)
            executor = ToolExecutor(
                registry=registry,
                project_dir=workspace_dir,
            )

            agent = AgentLoop(
                llm_client=llm_client,
                router=router,
                tool_executor=executor,
                event_emitter=_make_emitter(emitter),
                project_id=payload.project_id or payload.chat_id,
                user_id=payload.user_id,
                max_iterations=50,
                max_consecutive_errors=5,
                premium_images=payload.premium_images,
                design_check=payload.design_check,
                premium_review=payload.premium_review,
            )

            # Store agent instance for graceful shutdown state saving
            self._agent_instances[payload.task_id] = agent

            result = await agent.run(payload.user_message)
            
            # FIX: Emit task_complete to close SSE stream (was missing!)
            try:
                _tc_status = result.get("status", "completed")
                _tc_cost = result.get("total_cost", 0.0)
                _tc_iters = result.get("iterations", 0)
                _tc_arts = result.get("artifacts", [])
                await emitter.task_complete(
                    summary=f"Task completed in {_tc_iters} iterations (${_tc_cost:.4f})",
                    artifacts=_tc_arts,
                )
            except Exception as _tc_err:
                logger.warning(f"WORKER-FIX: Failed to emit task_complete: {_tc_err}")
                # Fallback: emit done directly
                try:
                    from api.sse import emit_to_chat
                    await emit_to_chat(payload.chat_id, "done", {"reason": "task_complete_fallback"})
                except Exception:
                    pass
            
            # FIX: Store result in in-memory chat store so GET /api/chats/{id} returns correct data
            try:
                from api.chat_store import update_chat as _wp_update_chat, add_message as _wp_add_message
                status = result.get("status", "completed")
                cost = result.get("total_cost", 0.0)
                iterations = result.get("iterations", 0)
                
                update_fields = {
                    "status": "idle" if status == "completed" else status,
                    "total_cost": cost,
                }
                steps = emitter.get_steps() if hasattr(emitter, "get_steps") else []
                if steps:
                    update_fields["steps"] = steps
                await _wp_update_chat(payload.chat_id, **update_fields)
                logger.info(f"WORKER-FIX: Updated chat store for {payload.chat_id}: status={update_fields['status']}, cost={cost}")
                
                # Store assistant result message
                summary_text = result.get("summary", f"Task completed in {iterations} iterations")
                if summary_text:
                    try:
                        await _wp_add_message(payload.chat_id, role="assistant", content=summary_text)
                    except Exception:
                        pass
            except Exception as _store_err:
                logger.warning(f"WORKER-FIX: Failed to store result: {_store_err}")
            
            return result

        except Exception as e:
            try:
                await emitter.status("error", str(e))
            except Exception:
                pass
            # FIX: Update chat store with failed status
            try:
                from api.chat_store import update_chat as _wp_fail_update
                await _wp_fail_update(payload.chat_id, status="failed", total_cost=0.0)
                logger.info(f"WORKER-FIX: Set chat {payload.chat_id} to failed on error: {e}")
            except Exception:
                pass
            raise

    async def _supervisor_loop(self) -> None:
        """
        Supervisor that monitors worker health and reclaims stale tasks.
        Runs every 30 seconds.
        """
        while self._running and not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(30)
                if not self._running:
                    break

                # Log pool status
                stats = self.get_pool_stats()
                logger.debug(
                    f"Pool status: {stats['active_workers']}/{stats['max_workers']} active, "
                    f"completed={stats['total_completed']}, failed={stats['total_failed']}"
                )

                # Reclaim stale tasks (workers that crashed)
                try:
                    claimed = await self._queue.claim_stale_tasks(
                        min_idle_ms=300000,  # 5 minutes
                        consumer_name="supervisor-reclaim",
                    )
                    if claimed:
                        logger.warning(f"Supervisor reclaimed {len(claimed)} stale tasks")
                except Exception as e:
                    logger.warning(f"Supervisor reclaim failed: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Supervisor error: {e}")


# ─── Singleton ───────────────────────────────────────────────

_pool_instance: Optional[WorkerPool] = None


async def get_worker_pool() -> WorkerPool:
    """Get or create the global worker pool instance."""
    global _pool_instance
    if _pool_instance is None:
        from core.task_queue import TaskQueue
        from config.settings import get_config

        config = get_config()
        queue = TaskQueue(redis_url=config.redis.url)
        await queue.connect()

        max_workers = int(getattr(config, "max_workers", 5))
        _pool_instance = WorkerPool(task_queue=queue, max_workers=max_workers)

    return _pool_instance


async def start_pool() -> WorkerPool:
    """Initialize and start the global worker pool."""
    pool = await get_worker_pool()
    if not pool.is_running:
        await pool.start()
    return pool


async def shutdown_pool(timeout: float = 30.0) -> list[str]:
    """Shutdown the global worker pool."""
    global _pool_instance
    if _pool_instance and _pool_instance.is_running:
        interrupted = await _pool_instance.shutdown(timeout=timeout)
        return interrupted
    return []
