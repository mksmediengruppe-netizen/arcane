"""
ARCANE SSE (Server-Sent Events) Endpoint
Compatibility layer for the existing frontend that uses SSE instead of WebSocket.

The frontend connects to /api/chats/{chat_id}/stream and expects these event types:
  - message: Agent text messages
  - agent_status: Agent status changes (thinking, coding, browsing, deploying, idle)
  - step_update: Tool execution progress
  - task_complete: Task finished
  - cost_update: Cost tracking
  - notification: System notifications
  - browser_takeover: Agent requests user to take over browser
  - research_step: Search/research progress
  - tool_progress: Tool execution details
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from shared.utils.logger import get_logger

# FIX NEW-008: Single source of truth for tool display names
TOOL_TITLE_MAP = {
            "shell_exec": "Выполнение команды",
            "file_write": "Запись файла",
            "file_read": "Чтение файла",
            "file_edit": "Редактирование файла",
            "browser_navigate": "Открытие страницы",
            "browser_click": "Клик в браузере",
            "browser_input": "Ввод в браузере",
            "browser_scroll": "Прокрутка страницы",
            "ssh_exec": "SSH команда",
            "search_web": "Поиск в интернете",
            "message": "Сообщение пользователю",
            "image_generate": "Генерация изображения",
            "design_judge": "Оценка дизайна",
        }


logger = get_logger("api.sse")

router = APIRouter(tags=["sse"])

# Global event queues per chat
_chat_queues: dict[str, list[asyncio.Queue]] = {}


def get_chat_queue(chat_id: str) -> asyncio.Queue:
    """Create and register a new event queue for a chat subscriber.
    FIX: New queues start empty — no stale events from previous subscribers.
    Old queues for the same chat are drained to prevent memory leak."""
    if chat_id not in _chat_queues:
        _chat_queues[chat_id] = []
    else:
        # Drain any stale events from existing queues to prevent
        # old events from being delivered to new subscribers
        for old_queue in _chat_queues[chat_id]:
            while not old_queue.empty():
                try:
                    old_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _chat_queues[chat_id].append(queue)
    return queue


def remove_chat_queue(chat_id: str, queue: asyncio.Queue) -> None:
    """Remove a subscriber queue."""
    if chat_id in _chat_queues:
        _chat_queues[chat_id] = [q for q in _chat_queues[chat_id] if q is not queue]
        if not _chat_queues[chat_id]:
            del _chat_queues[chat_id]


async def emit_to_chat(chat_id: str, event_type: str, data: dict) -> None:
    """Emit an SSE event to all subscribers of a chat."""
    if chat_id not in _chat_queues:
        return

    event = {
        "id": str(uuid.uuid4())[:8],
        "type": event_type,
        "data": data,
        "timestamp": time.time(),
    }

    dead_queues = []
    for queue in _chat_queues[chat_id]:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            dead_queues.append(queue)

    for q in dead_queues:
        _chat_queues[chat_id].remove(q)


class SSEEmitter:
    """
    SSE-compatible event emitter that bridges the Agent Loop events
    to the frontend's expected SSE format.
    """

    def __init__(self, chat_id: str):
        self._chat_id = chat_id
        self._steps: list = []
        self._current_step_id: str = ""

    async def thinking(self, thought: str) -> None:
        await emit_to_chat(self._chat_id, "agent_status", {
            "status": "thinking",
            "detail": thought[:300],
        })

    async def tool_call(self, tool_name: str, params: dict) -> str:
        # Map tool names to frontend-friendly status
        status_map = {
            "shell_exec": "coding",
            "file_write": "coding",
            "file_read": "coding",
            "file_edit": "coding",
            "browser_navigate": "browsing",
            "browser_click": "browsing",
            "browser_input": "browsing",
            "browser_scroll": "browsing",
            "ssh_exec": "deploying",
            "search_web": "researching",
        }
        status = status_map.get(tool_name, "working")

        # Friendly tool titles for the frontend
        title_map = TOOL_TITLE_MAP

        # Generate a stable step_id for this tool call
        self._current_step_id = f"step_{tool_name}_{int(time.time() * 1000)}"

        await emit_to_chat(self._chat_id, "agent_status", {
            "status": status,
            "detail": f"Using {tool_name}",
        })

        # Also emit step_update for the tool progress panel
        safe_params = {}
        for k, v in params.items():
            if isinstance(v, str) and len(v) > 150:
                safe_params[k] = v[:150] + "..."
            else:
                safe_params[k] = v

        step_data = {
            "step_id": self._current_step_id,
            "title": params.get("brief") or title_map.get(tool_name, tool_name),
            "tool": tool_name,
            "params": safe_params,
            "status": "running",
        }
        await emit_to_chat(self._chat_id, "step_update", step_data)
        # Accumulate step for persistence
        self._steps.append({**step_data, "start_time": time.time()})
        return self._current_step_id

    async def tool_result(self, tool_name: str, result, success: bool = True, step_id: str = None) -> None:
        result_str = str(result)
        # For message tool, keep full text; truncate others
        max_len = 10000 if tool_name == "message" else 500
        if len(result_str) > max_len:
            result_str = result_str[:max_len] + "..."

        # Use explicitly passed step_id to avoid race condition with _current_step_id
        if not step_id:
            step_id = getattr(self, "_current_step_id", f"step_{tool_name}_{int(time.time() * 1000)}")

        await emit_to_chat(self._chat_id, "tool_progress", {
            "tool": tool_name,
            "result": result_str,
            "success": success,
        })

        final_status = "success" if success else "failed"
        _title_map = TOOL_TITLE_MAP
        await emit_to_chat(self._chat_id, "step_update", {
            "step_id": step_id,
            "title": next((s["title"] for s in self._steps if s.get("step_id") == step_id), _title_map.get(tool_name, tool_name)),
            "tool": tool_name,
            "status": final_status,
            "result": result_str,
        })
        # Update step status in accumulated list
        for s in self._steps:
            if s.get("step_id") == step_id:
                s["status"] = final_status
                s["result"] = result_str[:200]
                s["duration"] = f"{time.time() - s.get('start_time', time.time()):.1f}s"
                break

    async def message(self, text: str, message_type: str = "info") -> None:
        await emit_to_chat(self._chat_id, "message", {
            "role": "assistant",
            "content": text,
            "type": message_type,
        })

    async def status(self, status: str, detail: str = "") -> None:
        await emit_to_chat(self._chat_id, "agent_status", {
            "status": status,
            "detail": detail,
        })

    async def phase_update(self, phase_id: int, phase_title: str, total_phases: int) -> None:
        await emit_to_chat(self._chat_id, "step_update", {
            "phase": phase_id,
            "phase_title": phase_title,
            "total_phases": total_phases,
            "status": "active",
        })

    async def file_created(self, filepath: str, file_type: str = "code") -> None:
        await emit_to_chat(self._chat_id, "notification", {
            "type": "file_created",
            "path": filepath,
            "file_type": file_type,
        })

    def get_steps(self) -> list:
        """Return accumulated steps for persistence."""
        return list(self._steps)

    async def screenshot(self, screenshot_path: str, url: str = "") -> None:
        await emit_to_chat(self._chat_id, "notification", {
            "type": "screenshot",
            "path": screenshot_path,
            "url": url,
        })

    async def cost_update(self, total_cost: float, breakdown: dict = None) -> None:
        await emit_to_chat(self._chat_id, "cost_update", {
            "total_cost": round(total_cost, 4),
            "breakdown": breakdown or {},
        })

    async def model_info(self, model_id: str, provider: str, tier: str = "") -> None:
        await emit_to_chat(self._chat_id, "model_info", {
            "model_id": model_id,
            "provider": provider,
            "tier": tier,
        })

    async def plan_update(self, phases: list, current_phase_id: int = 1, goal: str = "") -> None:
        await emit_to_chat(self._chat_id, "plan_update", {
            "phases": phases,
            "current_phase_id": current_phase_id,
            "goal": goal,
        })

    async def takeover_request(self, reason: str, url: str = "") -> None:
        await emit_to_chat(self._chat_id, "browser_takeover", {
            "reason": reason,
            "url": url,
            "action": "request",
        })

    async def task_complete(self, summary: str, artifacts: list[str] = None) -> None:
        await emit_to_chat(self._chat_id, "task_complete", {
            "summary": summary,
            "artifacts": artifacts or [],
        })

        await emit_to_chat(self._chat_id, "agent_status", {
            "status": "idle",
            "detail": "Task completed",
        })

        # Emit 'done' to signal SSE stream termination (Manus-style lifecycle)
        await emit_to_chat(self._chat_id, "done", {
            "reason": "task_complete",
        })

    async def research_step(self, query: str, results_count: int = 0) -> None:
        await emit_to_chat(self._chat_id, "research_step", {
            "query": query,
            "results_count": results_count,
        })

    async def waiting_user(self, question: str = "") -> None:
        """Signal that agent is waiting for user input — terminates SSE stream."""
        await emit_to_chat(self._chat_id, "agent_status", {
            "status": "waiting_user",
            "detail": question[:300] if question else "Waiting for user input",
        })
        # Emit 'done' to close the SSE stream (Manus-style)
        await emit_to_chat(self._chat_id, "done", {
            "reason": "waiting_user",
        })



@router.get("/api/chats/{chat_id}/stream")
@router.get("/api/chats/{chat_id}/subscribe")
async def stream_chat_events(chat_id: str, request: Request):
    """SSE endpoint for real-time chat events. P3-FIX BUG-004: Auth + ownership check."""
    # ── Auth check ──
    from api.compat import _require_user_id, _check_chat_ownership
    from api.chat_store import get_chat
    user_id = _require_user_id(request)
    chat = get_chat(chat_id)
    if chat:
        _check_chat_ownership(chat, user_id, request)

    queue = get_chat_queue(chat_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Send initial connection event
            yield _format_sse("agent_status", {"status": "connected"})

            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    event_type = event.get("type", "message")
                    event_data = event.get("data", {})
                    yield _format_sse(event_type, event_data)
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"

        finally:
            remove_chat_queue(chat_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_sse(event_type: str, data: dict) -> str:
    """Format data as an SSE event string."""
    json_data = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {json_data}\n\n"