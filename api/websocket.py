"""
ARCANE WebSocket API
Real-time bidirectional communication between frontend and agent.

Event types (Server → Client):
  - agent_thinking: Agent is reasoning about the task
  - agent_tool_call: Agent selected a tool to use
  - agent_tool_result: Tool execution result
  - agent_message: Agent sends a message to user
  - agent_status: Agent status change (working, idle, error)
  - phase_update: Task plan phase changed
  - file_created: New file/artifact created
  - screenshot: Browser screenshot available
  - cost_update: Real-time cost tracking
  - takeover_request: Agent requests user to take over browser
  - task_complete: Task finished

Event types (Client → Server):
  - user_message: User sends a new message
  - user_cancel: User cancels current task
  - user_takeover_done: User finished browser takeover
  - user_file_upload: User uploads a file
  - set_strategy: User changes cost strategy
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect
from shared.utils.logger import get_logger

logger = get_logger("api.websocket")


class ConnectionManager:
    """
    Manages active WebSocket connections.
    Supports multiple connections per user (multiple tabs).
    """

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}  # user_id -> [websockets]
        self._project_subs: dict[str, set[str]] = {}  # project_id -> {user_ids}

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        if user_id not in self._connections:
            self._connections[user_id] = []
        self._connections[user_id].append(websocket)
        logger.info(f"WebSocket connected: user={user_id}, total={self.active_count}")

    def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        """Remove a disconnected WebSocket."""
        if user_id in self._connections:
            self._connections[user_id] = [
                ws for ws in self._connections[user_id] if ws != websocket
            ]
            if not self._connections[user_id]:
                del self._connections[user_id]
        logger.info(f"WebSocket disconnected: user={user_id}, total={self.active_count}")

    def subscribe_project(self, user_id: str, project_id: str) -> None:
        """Subscribe a user to project events."""
        if project_id not in self._project_subs:
            self._project_subs[project_id] = set()
        self._project_subs[project_id].add(user_id)

    async def send_to_user(self, user_id: str, event: dict) -> None:
        """Send an event to all connections of a user."""
        event["timestamp"] = time.time()
        event["id"] = str(uuid.uuid4())[:8]

        if user_id in self._connections:
            dead = []
            for ws in self._connections[user_id]:
                try:
                    await ws.send_json(event)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._connections[user_id].remove(ws)

    async def send_to_project(self, project_id: str, event: dict) -> None:
        """Send an event to all users subscribed to a project."""
        if project_id in self._project_subs:
            for user_id in self._project_subs[project_id]:
                await self.send_to_user(user_id, event)

    async def broadcast(self, event: dict) -> None:
        """Send an event to all connected users."""
        for user_id in list(self._connections.keys()):
            await self.send_to_user(user_id, event)

    @property
    def active_count(self) -> int:
        return sum(len(conns) for conns in self._connections.values())


class EventEmitter:
    """
    High-level event emitter for the agent loop.
    Provides typed methods for each event type.
    """

    def __init__(self, manager: ConnectionManager, user_id: str, project_id: str):
        self._manager = manager
        self._user_id = user_id
        self._project_id = project_id

    async def thinking(self, thought: str) -> None:
        """Agent is reasoning about the task."""
        await self._emit("agent_thinking", {"thought": thought[:500]})

    async def tool_call(self, tool_name: str, params: dict) -> None:
        """Agent selected a tool to use."""
        # Sanitize params (remove large content)
        safe_params = {}
        for k, v in params.items():
            if isinstance(v, str) and len(v) > 200:
                safe_params[k] = v[:200] + "..."
            else:
                safe_params[k] = v

        await self._emit("agent_tool_call", {
            "tool": tool_name,
            "params": safe_params,
        })

    async def tool_result(self, tool_name: str, result: Any, success: bool = True) -> None:
        """Tool execution result."""
        result_str = str(result)
        if len(result_str) > 1000:
            result_str = result_str[:1000] + "..."

        await self._emit("agent_tool_result", {
            "tool": tool_name,
            "result": result_str,
            "success": success,
        })

    async def message(self, text: str, message_type: str = "info") -> None:
        """Agent sends a message to the user."""
        await self._emit("agent_message", {
            "text": text,
            "type": message_type,  # info, ask, result, error
        })

    async def status(self, status: str, detail: str = "") -> None:
        """Agent status change."""
        await self._emit("agent_status", {
            "status": status,  # working, idle, error, waiting_user
            "detail": detail,
        })

    async def phase_update(self, phase_id: int, phase_title: str, total_phases: int) -> None:
        """Task plan phase changed."""
        await self._emit("phase_update", {
            "current_phase": phase_id,
            "phase_title": phase_title,
            "total_phases": total_phases,
        })

    async def file_created(self, filepath: str, file_type: str = "code") -> None:
        """New file/artifact created."""
        await self._emit("file_created", {
            "path": filepath,
            "type": file_type,  # code, image, document, config
        })

    async def screenshot(self, screenshot_path: str, url: str = "") -> None:
        """Browser screenshot available."""
        await self._emit("screenshot", {
            "path": screenshot_path,
            "url": url,
        })

    async def cost_update(self, total_cost: float, breakdown: dict = None) -> None:
        """Real-time cost tracking update."""
        await self._emit("cost_update", {
            "total_cost": round(total_cost, 4),
            "breakdown": breakdown or {},
        })

    async def takeover_request(self, reason: str, url: str = "") -> None:
        """Agent requests user to take over browser."""
        await self._emit("takeover_request", {
            "reason": reason,
            "url": url,
        })

    async def task_complete(self, summary: str, artifacts: list[str] = None) -> None:
        """Task finished."""
        await self._emit("task_complete", {
            "summary": summary,
            "artifacts": artifacts or [],
        })

    async def _emit(self, event_type: str, data: dict) -> None:
        """Emit an event to the user and project subscribers."""
        event = {
            "type": event_type,
            "project_id": self._project_id,
            "data": data,
        }
        await self._manager.send_to_user(self._user_id, event)
