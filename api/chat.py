"""
ARCANE Chat API
REST endpoints for chat, projects, file management, and agent control.

Endpoints:
  POST /api/chat/send          — Send a message to the agent
  GET  /api/chat/history/{id}  — Get chat history for a project
  POST /api/projects/create    — Create a new project
  GET  /api/projects/list      — List all projects
  GET  /api/projects/{id}      — Get project details
  DELETE /api/projects/{id}    — Delete a project
  GET  /api/files/{project_id} — List files in a project
  GET  /api/files/read         — Read a file content
  POST /api/agent/cancel       — Cancel current agent task
  GET  /api/agent/status       — Get agent status
  POST /api/settings/strategy  — Set cost strategy
  GET  /api/usage/summary      — Get usage/cost summary
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from shared.utils.logger import get_logger

logger = get_logger("api.chat")

router = APIRouter(prefix="/api", tags=["chat"])


# --- Request/Response Models ---

class SendMessageRequest(BaseModel):
    project_id: str
    message: str
    attachments: list[str] = []
    strategy: str = "balanced"  # economy, balanced, quality, maximum


class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""
    strategy: str = "balanced"


class SetStrategyRequest(BaseModel):
    project_id: str
    strategy: str


class ChatMessage(BaseModel):
    id: str
    role: str  # user, assistant, system
    content: str
    timestamp: float
    tool_calls: list[dict] = []
    attachments: list[str] = []
    cost_usd: float = 0.0


class ProjectInfo(BaseModel):
    id: str
    name: str
    description: str
    strategy: str
    created_at: float
    updated_at: float
    message_count: int
    total_cost_usd: float
    status: str  # active, completed, archived


class FileInfo(BaseModel):
    path: str
    name: str
    size: int
    modified: float
    file_type: str  # code, image, document, config


# --- In-memory storage (will be replaced with PostgreSQL) ---

_projects: dict[str, dict] = {}
_messages: dict[str, list[dict]] = {}  # project_id -> messages
_agent_tasks: dict[str, dict] = {}  # project_id -> current task info


# --- Endpoints ---

@router.post("/chat/send")
async def send_message(req: SendMessageRequest):
    """Send a message to the agent and start processing."""
    if req.project_id not in _projects:
        raise HTTPException(404, "Project not found")

    msg_id = str(uuid.uuid4())[:12]
    message = {
        "id": msg_id,
        "role": "user",
        "content": req.message,
        "timestamp": time.time(),
        "attachments": req.attachments,
    }

    if req.project_id not in _messages:
        _messages[req.project_id] = []
    _messages[req.project_id].append(message)

    # Update project
    _projects[req.project_id]["updated_at"] = time.time()
    _projects[req.project_id]["message_count"] = len(_messages[req.project_id])

    # The actual agent processing is triggered via WebSocket
    # This endpoint just records the message and returns
    return {
        "message_id": msg_id,
        "project_id": req.project_id,
        "status": "queued",
    }


@router.get("/chat/history/{project_id}")
async def get_chat_history(project_id: str, limit: int = 50, offset: int = 0):
    """Get chat history for a project."""
    if project_id not in _messages:
        return {"messages": [], "total": 0}

    messages = _messages[project_id]
    total = len(messages)
    page = messages[offset:offset + limit]

    return {
        "messages": page,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/projects/create")
async def create_project(req: CreateProjectRequest):
    """Create a new project."""
    project_id = str(uuid.uuid4())[:12]
    project = {
        "id": project_id,
        "name": req.name,
        "description": req.description,
        "strategy": req.strategy,
        "created_at": time.time(),
        "updated_at": time.time(),
        "message_count": 0,
        "total_cost_usd": 0.0,
        "status": "active",
    }
    _projects[project_id] = project

    # Create workspace directory
    workspace = f"/root/workspace/{project_id}"
    os.makedirs(workspace, exist_ok=True)

    logger.info(f"Project created: {project_id} ({req.name})")
    return project


@router.get("/projects/list")
async def list_projects(status: str = "active"):
    """List all projects."""
    projects = [
        p for p in _projects.values()
        if status == "all" or p["status"] == status
    ]
    projects.sort(key=lambda p: p["updated_at"], reverse=True)
    return {"projects": projects, "total": len(projects)}


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """Get project details."""
    if project_id not in _projects:
        raise HTTPException(404, "Project not found")
    return _projects[project_id]


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a project (archive it)."""
    if project_id not in _projects:
        raise HTTPException(404, "Project not found")
    _projects[project_id]["status"] = "archived"
    return {"status": "archived", "project_id": project_id}


@router.get("/files/{project_id}")
async def list_files(project_id: str):
    """List files in a project workspace."""
    workspace = f"/root/workspace/{project_id}"
    if not os.path.exists(workspace):
        return {"files": []}

    files = []
    for root, dirs, filenames in os.walk(workspace):
        # Skip hidden dirs and node_modules
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules" and d != "venv"]
        for filename in filenames:
            if filename.startswith("."):
                continue
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, workspace)
            stat = os.stat(filepath)

            file_type = "code"
            ext = os.path.splitext(filename)[1].lower()
            if ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
                file_type = "image"
            elif ext in (".md", ".txt", ".pdf", ".doc", ".docx"):
                file_type = "document"
            elif ext in (".json", ".yaml", ".yml", ".toml", ".env"):
                file_type = "config"

            files.append({
                "path": rel_path,
                "name": filename,
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "file_type": file_type,
            })

    files.sort(key=lambda f: f["modified"], reverse=True)
    return {"files": files, "total": len(files)}


@router.get("/files/read")
async def read_file(project_id: str, path: str):
    """Read a file from project workspace."""
    workspace = f"/root/workspace/{project_id}"
    full_path = os.path.join(workspace, path)

    # Security: prevent path traversal
    real_path = os.path.realpath(full_path)
    if not real_path.startswith(os.path.realpath(workspace)):
        raise HTTPException(403, "Access denied: path traversal detected")

    if not os.path.exists(full_path):
        raise HTTPException(404, "File not found")

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"path": path, "content": content, "size": len(content)}
    except UnicodeDecodeError:
        return {"path": path, "content": "[Binary file]", "binary": True}


@router.post("/agent/cancel")
async def cancel_agent(project_id: str):
    """Cancel the current agent task."""
    if project_id in _agent_tasks:
        _agent_tasks[project_id]["cancelled"] = True
        return {"status": "cancelling", "project_id": project_id}
    return {"status": "no_active_task", "project_id": project_id}


@router.get("/agent/status")
async def agent_status(project_id: str = ""):
    """Get agent status."""
    if project_id and project_id in _agent_tasks:
        return _agent_tasks[project_id]
    return {
        "status": "idle",
        "active_tasks": len(_agent_tasks),
    }


@router.post("/settings/strategy")
async def set_strategy(req: SetStrategyRequest):
    """Set cost strategy for a project."""
    if req.project_id not in _projects:
        raise HTTPException(404, "Project not found")

    valid = ["economy", "balanced", "quality", "maximum"]
    if req.strategy not in valid:
        raise HTTPException(400, f"Invalid strategy. Choose from: {valid}")

    _projects[req.project_id]["strategy"] = req.strategy
    return {"project_id": req.project_id, "strategy": req.strategy}


@router.get("/usage/summary")
async def usage_summary(project_id: str = ""):
    """Get usage and cost summary."""
    # This will be connected to UsageTracker
    return {
        "total_cost_usd": 0.0,
        "total_requests": 0,
        "total_tokens": 0,
        "breakdown_by_worker": {},
        "breakdown_by_model": {},
    }
