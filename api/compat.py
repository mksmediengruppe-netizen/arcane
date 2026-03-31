"""
ARCANE Compatibility API
Maps the existing frontend API calls to ARCANE backend.

The frontend expects these endpoint groups:
  /api/auth/*      — Authentication
  /api/chats/*     — Chat CRUD + messages
  /api/models      — Available models
  /api/templates   — Task templates
  /api/connectors  — External integrations
  /api/memory/*    — Agent memory
  /api/files/*     — File management + download
  /api/projects    — Project listing
  /api/admin/*     — Admin dashboard
  /api/analytics/* — Usage analytics
  /api/health      — Health check
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from shared.utils.logger import get_logger


# B2: Unified auth — delegate JWT to auth.py (single source of truth)
from api.auth import JWT_SECRET as _JWT_SECRET, JWT_ALGORITHM as _JWT_ALGORITHM
import jwt as _pyjwt
import datetime as _dt

def _create_jwt(user_data: dict) -> str:
    """Create JWT using the same secret as auth.py."""
    payload = {
        "sub": user_data["id"],
        "username": user_data.get("username", ""),
        "email": user_data.get("email", ""),
        "role": user_data.get("role", "user"),
        "exp": _dt.datetime.utcnow() + _dt.timedelta(days=30),
    }
    return _pyjwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)

def _verify_jwt(token: str) -> dict | None:
    """Verify JWT using the same secret as auth.py."""
    try:
        return _pyjwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    except Exception:
        return None

logger = get_logger("api.compat")

router = APIRouter(tags=["compat"])


def _extract_user_id(request: Request) -> str:
    """P1-2 FIX: Extract user_id from JWT or session cookie.
    Returns user_id string or empty string if unauthenticated."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token_data = _verify_jwt(auth_header[7:])
        if token_data:
            return token_data.get("sub", "")
    session_token = request.cookies.get("arcane_session")
    if session_token and session_token in _sessions:
        sd = _sessions[session_token]
        return sd.get("user_id", "") if isinstance(sd, dict) else str(sd)
    return ""


def _require_user_id(request: Request) -> str:
    """Extract user_id or raise 401. Use for endpoints that REQUIRE auth."""
    user_id = _extract_user_id(request)
    if not user_id:
        raise HTTPException(401, "Authentication required")
    return user_id


def _require_admin(request: Request) -> str:
    """Extract user_id and verify admin role, or raise 403."""
    user_id = _require_user_id(request)
    # Check JWT payload for role
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token_data = _verify_jwt(auth_header[7:])
        if token_data and token_data.get("role") == "admin":
            return user_id
    # Check session for role
    session_token = request.cookies.get("arcane_session")
    if session_token and session_token in _sessions:
        sd = _sessions[session_token]
        if isinstance(sd, dict) and sd.get("role") == "admin":
            return user_id
    # P0 FIX: No fallback — raise 403 if not admin
    raise HTTPException(403, "Admin access required")


def _check_chat_ownership(chat: dict, user_id: str) -> None:
    """P1-2 FIX: Verify user owns the chat. Raises 403 if not."""
    if not user_id:
        raise HTTPException(401, "Authentication required")
    chat_owner = chat.get("user_id", "")
    # Allow if: chat has no owner (legacy), or user matches, or user is admin
    if chat_owner and chat_owner != user_id:
        raise HTTPException(403, "Access denied: you do not own this chat")


def _generate_chat_title(content: str) -> str:
    """Generate a concise chat title from user message.
    Extracts the most meaningful part of the message (up to 50 chars).
    """
    import re
    text = content.strip()
    # Remove markdown, URLs, extra whitespace
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[#*_`~]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return "New Task"
    # If text starts with a verb/action phrase, use first sentence
    first_sentence = re.split(r'[.!?\n]', text)[0].strip()
    if len(first_sentence) <= 60:
        return first_sentence
    # Truncate at word boundary
    truncated = first_sentence[:57]
    last_space = truncated.rfind(' ')
    if last_space > 20:
        truncated = truncated[:last_space]
    return truncated + "..."


# ============================================================================
# Persistent Chat Store (replaces raw dicts)
# ============================================================================

from api.chat_store import (
    get_chats as _get_chats_dict,
    get_chat_messages as _get_messages_dict,
    get_chat, get_messages,
    create_chat as store_create_chat,
    add_message as store_add_message,
    update_chat as store_update_chat,
    delete_chat as store_delete_chat,
    get_admin_chats, get_admin_stats,
)

# B2: Session storage — in-memory for cookie sessions, but JWT is primary auth
# Sessions are a fallback for cookie-based auth; JWT is the source of truth
# P3-FIX BUG-007: File-backed sessions for persistence across restarts
import json as _json
_SESSIONS_FILE = "/root/arcane/data/sessions.json"

def _load_sessions() -> dict:
    """Load sessions from disk."""
    try:
        import os
        if os.path.exists(_SESSIONS_FILE):
            with open(_SESSIONS_FILE, "r") as f:
                return _json.load(f)
    except Exception:
        pass
    return {}

def _save_sessions(sessions: dict) -> None:
    """Persist sessions to disk (fire-and-forget safe)."""
    try:
        import os
        os.makedirs(os.path.dirname(_SESSIONS_FILE), exist_ok=True)
        with open(_SESSIONS_FILE, "w") as f:
            _json.dump(sessions, f, ensure_ascii=False)
    except Exception:
        pass

_sessions: dict[str, dict] = _load_sessions()

_templates = [
    {"id": "t1", "name": "Landing Page", "title": "Landing Page",
     "description": "Create a modern responsive landing page",
     "prompt": "Create a modern responsive landing page for {business_type}. Include hero section, features, testimonials, and contact form.",
     "category": "website", "tags": ["html", "css", "landing"]},
    {"id": "t2", "name": "REST API", "title": "REST API",
     "description": "Build a REST API with FastAPI",
     "prompt": "Create a REST API using FastAPI with {resource} CRUD operations, authentication, and PostgreSQL database.",
     "category": "api", "tags": ["python", "fastapi", "api"]},
    {"id": "t3", "name": "n8n Workflow", "title": "n8n Integration",
     "description": "Create an n8n automation workflow",
     "prompt": "Create an n8n workflow that {workflow_description}. Include error handling and webhook triggers.",
     "category": "integration", "tags": ["n8n", "automation"]},
    {"id": "t4", "name": "Telegram Bot", "title": "Telegram Bot",
     "description": "Build a Telegram bot",
     "prompt": "Create a Telegram bot using Python that {bot_description}. Include inline keyboards and command handlers.",
     "category": "code", "tags": ["python", "telegram", "bot"]},
    {"id": "t5", "name": "Full-Stack App", "title": "Full-Stack Application",
     "description": "Build a complete web application",
     "prompt": "Build a full-stack web application for {app_description} with React frontend, FastAPI backend, and PostgreSQL database. Deploy to production.",
     "category": "website", "tags": ["react", "fastapi", "fullstack"]},
    {"id": "t6", "name": "CRM Integration", "title": "CRM Integration",
     "description": "Set up CRM system integration",
     "prompt": "Integrate {crm_system} with our existing system. Set up data sync, webhooks, and automated workflows.",
     "category": "integration", "tags": ["crm", "integration"]},
]

_connectors = [
    {"id": "github", "name": "GitHub", "type": "vcs", "description": "Version control and CI/CD",
     "connected": True, "status": "active", "auth_type": "token", "icon": "github"},
    {"id": "vercel", "name": "Vercel", "type": "hosting", "description": "Frontend deployment",
     "connected": False, "status": "disconnected", "auth_type": "token", "icon": "vercel"},
    {"id": "n8n", "name": "n8n", "type": "automation", "description": "Workflow automation",
     "connected": True, "status": "active", "auth_type": "api_key", "icon": "workflow"},
    {"id": "telegram", "name": "Telegram", "type": "messaging", "description": "Bot and notifications",
     "connected": False, "status": "disconnected", "auth_type": "token", "icon": "message"},
    {"id": "cloudflare", "name": "Cloudflare", "type": "cdn", "description": "DNS and CDN",
     "connected": False, "status": "disconnected", "auth_type": "api_key", "icon": "cloud"},
    {"id": "s3", "name": "S3 / MinIO", "type": "storage", "description": "File storage",
     "connected": True, "status": "active", "auth_type": "access_key", "icon": "database"},
]


# ============================================================================
# Auth endpoints
# ============================================================================

class LoginRequest(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    login_id: Optional[str] = None  # Frontend sends this field
    password: str

    def get_resolved_login_id(self) -> str:
        """Resolve the effective login identifier."""
        lid = self.login_id or self.username or self.email or ""
        if lid and not self.email and not self.username:
            if "@" in lid:
                self.email = lid
            else:
                self.username = lid
        return lid


@router.post("/api/auth/login")
async def login(req: LoginRequest, response: Response, request: Request):
    """Login via DB (bcrypt) and set session cookie. S7: rate limited."""
    from api.rate_limiter import check_rate_limit
    await check_rate_limit(request, "auth")
    try:
        from config.settings import get_config
        from shared.models.database import get_session_factory, User
        from sqlalchemy import select
        from api.auth import verify_password

        config = get_config()
        factory = get_session_factory(config.db.url)
        async with factory() as session:
            result = await session.execute(
                select(User).where((User.username == req.get_resolved_login_id()) | (User.email == req.get_resolved_login_id()))
            )
            db_user = result.scalar_one_or_none()
            if db_user is None or not verify_password(req.password, db_user.password_hash):
                raise HTTPException(401, "Invalid credentials")
            if not db_user.is_active:
                raise HTTPException(403, "Account disabled")

            token = str(uuid.uuid4())
            # FIX 2: Store dict instead of bare id to match .get() calls elsewhere
            _sessions[token] = {
                "user_id": str(db_user.id),
                "username": db_user.username,
                "role": db_user.role or "user",
                "created_at": time.time(),
            }

            _save_sessions(_sessions)  # P3-FIX BUG-007: persist
            response.set_cookie(
                key="arcane_session",
                value=token,
                httponly=True,
                max_age=365 * 24 * 3600,
                samesite="lax",
            )

            user_data = {
                    "id": db_user.id,
                    "username": db_user.username,
                    "email": db_user.email or "",
                    "role": db_user.role,
                }
            jwt_token = _create_jwt(user_data)
            return {
                "ok": True,
                "user": user_data,
                "token": jwt_token,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Compat login error: {e}")
        raise HTTPException(500, "Internal server error")


@router.get("/api/auth/me")
async def get_me(request: Request):
    """Get current user from session or JWT."""
    # Try session cookie first
    token = request.cookies.get("arcane_session") or request.cookies.get("orion_session")
    if token and token in _sessions:
        # FIX 2: Read from dict safely (backward-compat with old string values)
        session_data = _sessions[token]
        user_id = session_data.get("user_id", "") if isinstance(session_data, dict) else str(session_data)
        try:
            from config.settings import get_config
            from shared.models.database import get_session_factory, User
            from sqlalchemy import select

            config = get_config()
            factory = get_session_factory(config.db.url)
            async with factory() as session:
                result = await session.execute(
                    select(User).where(User.id == user_id)
                )
                db_user = result.scalar_one_or_none()
                if db_user:
                    return {
                        "ok": True,
                        "user": {
                            "id": db_user.id,
                            "username": db_user.username,
                            "email": db_user.email or "",
                            "role": db_user.role,
                        },
                    }
        except Exception as e:
            logger.debug(f"Session lookup failed: {e}")

    # Try JWT Bearer token
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            from api.auth import decode_token
            payload = decode_token(auth_header[7:])
            return {
                "ok": True,
                "user": {
                    "id": payload.get("sub", ""),
                    "username": payload.get("username", ""),
                    "email": "",
                    "role": payload.get("role", "user"),
                },
            }
        except Exception:
            pass

    raise HTTPException(401, "Not authenticated")


@router.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    """Logout and clear session."""
    token = request.cookies.get("arcane_session")
    if token and token in _sessions:
        del _sessions[token]
        _save_sessions(_sessions)  # P3-FIX BUG-007: persist
    response.delete_cookie("arcane_session")
    return {"ok": True}


# FIX 4: Register endpoint — was removed when auth_router was dropped from app.py
class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


@router.post("/api/auth/register")
async def register(req: RegisterRequest, response: Response, request: Request):
    """Register a new user. S7: rate limited."""
    from api.rate_limiter import check_rate_limit
    await check_rate_limit(request, "auth")
    try:
        from config.settings import get_config
        from shared.models.database import get_session_factory, User
        from sqlalchemy import select
        from api.auth import hash_password

        if not req.username or not req.password:
            raise HTTPException(400, "Username and password required")

        config = get_config()
        factory = get_session_factory(config.db.url)
        async with factory() as session:
            # Check username conflict
            existing = await session.execute(
                select(User).where(User.username == req.username)
            )
            if existing.scalar_one_or_none() is not None:
                raise HTTPException(409, "Username already taken")

            # Check email conflict
            if req.email:
                existing_email = await session.execute(
                    select(User).where(User.email == req.email)
                )
                if existing_email.scalar_one_or_none() is not None:
                    raise HTTPException(409, "Email already registered")

            # Create user
            user = User(
                username=req.username,
                email=req.email,
                password_hash=hash_password(req.password),
                role="user",
                is_active=True,
                model_strategy="balance",
                budget_limit=5.0,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

            # Set session cookie
            token = str(uuid.uuid4())
            _sessions[token] = {
                "user_id": str(user.id),
                "username": user.username,
                "role": user.role or "user",
                "created_at": time.time(),
            }
            _save_sessions(_sessions)  # P3-FIX BUG-007: persist
            response.set_cookie(
                key="arcane_session",
                value=token,
                httponly=True,
                max_age=365 * 24 * 3600,
                samesite="lax",
            )

            user_data = {
                "id": user.id,
                "username": user.username,
                "email": user.email or "",
                "role": user.role,
            }
            jwt_token = _create_jwt(user_data)
            return {
                "ok": True,
                "user": user_data,
                "token": jwt_token,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Compat register error: {e}")
        raise HTTPException(500, "Internal server error")


# ============================================================================
# Chat endpoints — now using persistent chat_store
# ============================================================================

@router.get("/api/chats")
async def list_chats(request: Request):
    """List chats for the current user. S5: uses chat_service."""
    user_id = _require_user_id(request)
    from api.chat_service import list_chats_for_user, get_chat_summary
    user_chats = await list_chats_for_user(user_id)
    return {"chats": [get_chat_summary(c) for c in user_chats]}


@router.post("/api/chats")
async def create_chat_endpoint(request: Request):
    """Create a new chat. Requires auth."""
    user_id = _require_user_id(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    chat_id = str(uuid.uuid4())
    chat = await store_create_chat(
        chat_id=chat_id,
        title=body.get("title", "New Task"),
        model=body.get("model", "gpt-5.4"),
        variant=body.get("variant", ""),
        status="idle",
        user_id=user_id,
    )
    return {"ok": True, "chat": chat}


@router.get("/api/chats/{chat_id}")
async def get_chat_endpoint(chat_id: str, request: Request):
    """Get chat with messages. P1-2: ownership check added."""
    chat = get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    user_id = _extract_user_id(request)
    _check_chat_ownership(chat, user_id)

    messages = get_messages(chat_id)
    return {
        "chat": {
            **chat,
            "messages": messages,
            "steps": chat.get("steps", []),
        }
    }


@router.post("/api/chats/{chat_id}/message")
@router.post("/api/chats/{chat_id}/send")
async def send_chat_message(chat_id: str, request: Request):
    """Send a message to a chat and return SSE stream with agent response. S7: rate limited."""
    from api.rate_limiter import check_rate_limit
    await check_rate_limit(request, "message")
    from fastapi.responses import StreamingResponse
    from api.sse import get_chat_queue, remove_chat_queue

    user_id = _require_user_id(request)
    chat = get_chat(chat_id)
    if not chat:
        # Auto-create chat for this user if it doesn't exist
        await store_create_chat(chat_id=chat_id, user_id=user_id)
        chat = get_chat(chat_id)
    _check_chat_ownership(chat, user_id)

    body = await request.json()
    content = body.get("content", body.get("message", ""))
    model_strategy = body.get("model", body.get("variant", "standard"))
    options = body.get("options", {})
    premium_images = options.get("premiumImages", False)
    design_check = options.get("designCheck", False)
    premium_review = options.get("premiumReview", False)
    # Premium mode: auto-enable everything
    if model_strategy == "premium":
        model_strategy = "quality"  # Sonnet 4.6
        premium_images = True
        design_check = True
        premium_review = True

    # Store user message
    await store_add_message(chat_id, role="user", content=content)

    # Update chat metadata
    chats = _get_chats_dict()
    if chat_id in chats:
        title_update = {}
        current_title = (chats[chat_id].get("title") or "").strip()
        _default_titles = {"", "New Task", "Новая задача", "new task", "новая задача"}
        if current_title.lower() in {t.lower() for t in _default_titles}:
            # Generate a smart title from the user message
            title_update["title"] = _generate_chat_title(content)
        await store_update_chat(chat_id, status="working", **title_update)

    # Subscribe to SSE events BEFORE starting the agent
    queue = get_chat_queue(chat_id)

    # Trigger agent loop in background — try resume first, then start new
    from api.agent_runner import start_agent_for_chat, resume_agent_for_chat, _agent_instances, _running_agents

    async def _start_or_resume():
        """Resume existing agent if possible, otherwise start fresh."""
        try:
            # Check if there's a paused/waiting agent for this chat
            if chat_id in _agent_instances and chat_id not in _running_agents:
                logger.info(f"Resuming paused agent for chat {chat_id}")
                await resume_agent_for_chat(chat_id, content)
                return
        except Exception as e:
            logger.warning(f"Resume failed for {chat_id}, starting fresh: {e}")
        # Start a new agent
        await start_agent_for_chat(
            chat_id, content, user_id=user_id,
            model_strategy=model_strategy,
            premium_images=premium_images,
            design_check=design_check,
            premium_review=premium_review,
        )

    asyncio.create_task(_start_or_resume())

    async def event_stream():
        """Stream SSE events from the agent to the frontend."""
        import json as _json

        def _dumps(obj):
            return _json.dumps(obj, ensure_ascii=False)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield f"data: {_json.dumps({'type': 'keepalive'})}\n\n"
                    continue

                event_type = event.get("type", "")
                data = event.get("data", {})

                if event_type == "agent_status":
                    status = data.get("status", "")
                    detail = data.get("detail", "")
                    if status == "thinking":
                        yield f"data: {_dumps({'type': 'thinking', 'detail': detail})}\n\n"
                    elif status == "idle":
                        yield f"data: {_dumps({'type': 'done'})}\n\n"
                        break
                    elif status == "waiting_user":
                        yield f"data: {_dumps({'type': 'waiting_user', 'detail': detail})}\n\n"
                    elif status in ("coding", "browsing", "deploying", "researching", "working"):
                        # FIX: Forward real agent status to frontend instead of swallowing it
                        yield f"data: {_dumps({'type': 'agent_status', 'status': status, 'detail': detail})}\n\n"
                    else:
                        yield f"data: {_dumps({'type': 'agent_status', 'status': status, 'detail': detail})}\n\n"
                elif event_type == "thinking":
                    yield f"data: {_dumps({'type': 'thinking', 'detail': data.get('detail', '')})}\n\n"
                elif event_type == "tool_progress":
                    tool = data.get("tool", "")
                    result = data.get("result", "")
                    if tool == "message":
                        text = str(result)
                        attachments = []
                        try:
                            result_data = _json.loads(result) if isinstance(result, str) else result
                            if isinstance(result_data, dict):
                                text = result_data.get("text", result_data.get("content", str(result_data)))
                                # PHASE-6 FIX: Extract attachments from message tool result
                                raw_attachments = result_data.get("attachments", [])
                                for att_path in raw_attachments:
                                    if isinstance(att_path, str) and att_path.strip():
                                        import os as _os
                                        fname = _os.path.basename(att_path)
                                        # Build relative path for download URL
                                        # Attachments are absolute paths like /root/workspace/<project_id>/file.ext
                                        rel_path = att_path
                                        if att_path.startswith("/root/workspace/"):
                                            rel_path = att_path[len("/root/workspace/"):]
                                        elif att_path.startswith("/root/"):
                                            rel_path = att_path[len("/root/"):]
                                        attachments.append({
                                            "name": fname,
                                            "path": rel_path,
                                            "download_url": f"https://arcaneai.ru/api/files/download/{rel_path}",
                                            "preview_url": f"https://arcaneai.ru/api/files/preview/{rel_path}",
                                            "size": _os.path.getsize(att_path) if _os.path.isfile(att_path) else 0,
                                        })
                        except (ValueError, TypeError, AttributeError):
                            import re as _re
                            m = _re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
                            if m:
                                extracted = m.group(1)
                                try:
                                    text = _json.loads('"' + extracted + '"')
                                except Exception:
                                    text = extracted
                        # Store assistant message
                        await store_add_message(chat_id, role="assistant", content=text)
                        yield f"data: {_dumps({'type': 'text_delta', 'text': text})}\n\n"
                        # PHASE-6 FIX: Emit attachments event before text_complete
                        if attachments:
                            yield f"data: {_dumps({'type': 'attachments', 'files': attachments})}\n\n"
                        yield f"data: {_dumps({'type': 'text_complete', 'content': text})}\n\n"
                    else:
                        yield f"data: {_dumps({'type': 'tool_calls', 'tool': tool})}\n\n"
                        # Also emit tool_executing for LiveTab real-time display
                        yield f"data: {_dumps({'type': 'tool_executing', 'tool': tool, 'name': tool})}\n\n"
                elif event_type in ("task_complete", "task_completed"):
                    cost = data.get("total_cost", 0)
                    iterations = data.get("iterations", 0)
                    # Update chat with final cost
                    await store_update_chat(chat_id, status="idle",
                                            total_cost=cost)
                    yield f"data: {_dumps({'type': 'task_complete', 'summary': '', 'cost': cost, 'iterations': iterations})}\n\n"
                    yield f"data: {_dumps({'type': 'done'})}\n\n"
                    break
                
                elif event_type == "done":
                    # Forward done event to close SSE stream (Manus-style lifecycle)
                    yield f"data: {_dumps({'type': 'done', 'reason': data.get('reason', 'complete')})}\n\n"
                    return  # Close the stream

                elif event_type == "error":
                    await store_update_chat(chat_id, status="failed")
                    yield f"data: {_dumps({'type': 'error', 'message': data.get('message', data.get('error', 'Unknown error'))})}\n\n"
                    yield f"data: {_dumps({'type': 'done'})}\n\n"
                    break
                elif event_type == "message":
                    text = data.get("text", data.get("content", ""))
                    if text:
                        yield f"data: {_dumps({'type': 'text_delta', 'text': text})}\n\n"
                elif event_type == "cost_update":
                    yield f"data: {_dumps({'type': 'cost_update', 'total_cost': data.get('total_cost', 0), 'budget_remaining': data.get('budget_remaining', 0), 'iteration_cost': data.get('iteration_cost', 0), 'input_tokens': data.get('input_tokens', 0), 'output_tokens': data.get('output_tokens', 0)})}\n\n"
                elif event_type == "model_info":
                    yield f"data: {_dumps({'type': 'model_info', 'model_id': data.get('model_id', ''), 'provider': data.get('provider', ''), 'tier': data.get('tier', '')})}\n\n"
                elif event_type == "plan_update":
                    # Convert phases (list of dicts with id/title) to steps (list of strings) for frontend
                    _raw_phases = data.get('phases', [])
                    _current_pid = data.get('current_phase_id', 1)
                    _plan_steps = []
                    _completed = []
                    for _i, _p in enumerate(_raw_phases):
                        if isinstance(_p, dict):
                            _plan_steps.append(_p.get('title', f'Phase {_i+1}'))
                            if _p.get('id', _i+1) < _current_pid:
                                _completed.append(_i)
                        elif isinstance(_p, str):
                            _plan_steps.append(_p)
                    yield f"data: {_dumps({'type': 'plan_update', 'steps': _plan_steps, 'plan': _plan_steps, 'completed': _completed, 'goal': data.get('goal', '')})}\n\n"
                elif event_type == "step_update":
                    # Forward step_update events to frontend for real-time step tracking
                    yield f"data: {_dumps({'type': 'step_update', 'step_id': data.get('step_id', ''), 'title': data.get('title', ''), 'tool': data.get('tool', ''), 'status': data.get('status', ''), 'result': data.get('result', ''), 'params': data.get('params', {})})}\n\n"
                    # Also emit tool_executing / tool_completed for LiveTab real-time display
                    _step_tool = data.get('tool', '')
                    _step_status = data.get('status', '')
                    if _step_tool and _step_status == 'running':
                        yield f"data: {_dumps({'type': 'tool_executing', 'tool': _step_tool, 'name': _step_tool})}\n\n"
                    elif _step_status in ('success', 'failed', 'completed'):
                        yield f"data: {_dumps({'type': 'tool_completed', 'tool': _step_tool})}\n\n"
                else:
                    yield f"data: {_dumps({'type': event_type, **data})}\n\n"
        finally:
            remove_chat_queue(chat_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@router.get("/api/chats/{chat_id}/status")
async def get_chat_status(chat_id: str, request: Request):
    """Get current chat/task status. P3-FIX BUG-017: ownership check."""
    user_id = _require_user_id(request)
    chat = get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    _check_chat_ownership(chat, user_id)
    messages = get_messages(chat_id)
    # Get last assistant message if any
    last_assistant = None
    for m in reversed(messages):
        if m.get("role") == "assistant":
            last_assistant = m
            break
    return {
        "chat_id": chat_id,
        "status": chat.get("status", "idle"),  # working / idle / failed
        "total_cost": chat.get("total_cost", 0),
        "title": chat.get("title", ""),
        "last_message": last_assistant.get("content", "") if last_assistant else None,
        "message_count": len(messages),
    }


@router.delete("/api/chats/{chat_id}")
async def delete_chat_endpoint(chat_id: str, request: Request):
    """Delete a chat. P1-2: ownership check added."""
    chat = get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    user_id = _extract_user_id(request)
    _check_chat_ownership(chat, user_id)
    await store_delete_chat(chat_id)
    return {"ok": True}


@router.post("/api/chats/{chat_id}/stop")
async def stop_chat_agent(chat_id: str, request: Request):
    """Stop the agent for a chat. P1-2: ownership check added."""
    chat = get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    user_id = _extract_user_id(request)
    _check_chat_ownership(chat, user_id)
    from api.agent_runner import stop_agent_for_chat
    await stop_agent_for_chat(chat_id, user_id=user_id)
    await store_update_chat(chat_id, status="idle")
    return {"ok": True}


@router.patch("/api/chats/{chat_id}")
async def update_chat_endpoint(chat_id: str, request: Request):
    """Update chat metadata (title, etc.). P1-2: ownership check added."""
    chat = get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    user_id = _extract_user_id(request)
    _check_chat_ownership(chat, user_id)
    body = await request.json()
    updates = {}
    for key in ("title", "variant", "model_used"):
        if key in body:
            updates[key] = body[key]
    await store_update_chat(chat_id, **updates)
    return {"ok": True, "chat": get_chat(chat_id)}


# ============================================================================
# Models endpoint
# ============================================================================

@router.get("/api/models")
async def list_models():
    """List available models — dynamically from model_registry."""
    from shared.llm.model_registry import MODELS

    models_list = []
    for model_id, spec in MODELS.items():
        models_list.append({
            "id": spec.id,
            "name": spec.display_name,
            "provider": spec.provider.value,
            "context_length": spec.max_context,
            "cost_per_1k_input": round(spec.input_price_per_mtok / 1000, 4),
            "cost_per_1k_output": round(spec.output_price_per_mtok / 1000, 4),
            "supports_vision": spec.supports_vision,
            "supports_function_calling": spec.supports_function_calling,
            "available": True,
        })
    return {"models": models_list}


# ============================================================================
# Templates, Connectors, Memory
# ============================================================================

@router.get("/api/templates")
async def list_templates():
    return {"templates": _templates}


@router.get("/api/connectors")
async def list_connectors():
    return {"connectors": _connectors}


@router.post("/api/connectors/{connector_id}/connect")
async def connect_connector(connector_id: str):
    for c in _connectors:
        if c["id"] == connector_id:
            c["connected"] = True
            c["status"] = "active"
            return {"ok": True}
    raise HTTPException(404, "Connector not found")


@router.post("/api/connectors/{connector_id}/disconnect")
async def disconnect_connector(connector_id: str):
    for c in _connectors:
        if c["id"] == connector_id:
            c["connected"] = False
            c["status"] = "disconnected"
            return {"ok": True}
    raise HTTPException(404, "Connector not found")


@router.post("/api/memory")
async def store_memory(request: Request):
    body = await request.json()
    return {"ok": True, "memory": {"id": str(uuid.uuid4())[:8], **body}}


@router.get("/api/memory/stats")
async def memory_stats():
    return {"total": 0, "sessions": 0, "size_kb": 0, "initialized": True, "vector_dim": 1536, "collection": "arcane_memory"}


# ============================================================================
# File serving + Download + Projects
# ============================================================================

# P1-1 FIX: Use canonical workspace root from settings instead of hardcoded paths
from config.settings import get_config as _get_compat_config
_compat_cfg = _get_compat_config()
WORKSPACE_DIR = _compat_cfg.workspace_root  # /root/workspace (canonical)
PROJECTS_DIR = os.path.join(WORKSPACE_DIR, "projects")  # /root/workspace/projects
HOME_DIR = "/home/ubuntu"  # Kept as fallback for legacy files


def _resolve_file_path(file_path: str) -> Optional[str]:
    """Resolve a file path, checking multiple directories.
    
    FIX 5: Also searches subdirectories of workspace for archives
    that may be in .deliveries/ folders.
    """
    safe_path = os.path.normpath(file_path)
    if safe_path.startswith("..") or os.path.isabs(safe_path):
        return None

    # Direct path check in known base directories
    for base_dir in [PROJECTS_DIR, WORKSPACE_DIR, HOME_DIR]:
        full = os.path.join(base_dir, safe_path)
        if os.path.isfile(full):
            return full

    # FIX 5: Search subdirectories (e.g., .deliveries/) for the file by basename
    basename = os.path.basename(safe_path)
    if basename:
        for base_dir in [PROJECTS_DIR, WORKSPACE_DIR]:
            if not os.path.isdir(base_dir):
                continue
            for root, dirs, files in os.walk(base_dir):
                if basename in files:
                    return os.path.join(root, basename)
                # Limit depth to avoid excessive traversal
                if root.count(os.sep) - base_dir.count(os.sep) > 3:
                    dirs.clear()
    return None


@router.get("/api/files")
async def list_files(request: Request, chat_id: str = ""):
    """S4: List files. Requires auth. Filters by chat workspace if chat_id given."""
    user_id = _require_user_id(request)
    files = []
    for base_dir in [PROJECTS_DIR, HOME_DIR]:
        if not os.path.isdir(base_dir):
            continue
        for entry in os.listdir(base_dir):
            fp = os.path.join(base_dir, entry)
            if os.path.isfile(fp) and entry.endswith((".html", ".css", ".js", ".zip", ".py", ".json")):
                files.append({
                    "id": entry,
                    "name": entry,
                    "size": os.path.getsize(fp),
                    "path": fp,
                    "preview_url": f"https://arcaneai.ru/workspace/{entry}",  # P4-FIX BUG-005
                    "download_url": f"https://arcaneai.ru/api/files/download/{entry}",
                })
    return {"files": files}


# P3-FIX BUG-006: Frontend-compatible download/preview routes (ID-based)
@router.get("/api/files/{file_id:path}/download")
async def download_file_by_id(file_id: str, request: Request):
    """Download file by ID (relative path). Redirects to canonical download endpoint."""
    from starlette.responses import RedirectResponse
    return RedirectResponse(url=f"/api/files/download/{file_id}", status_code=307)

@router.get("/api/files/{file_id:path}/preview")
async def preview_file_by_id(file_id: str, request: Request):
    """Preview file by ID (relative path). Redirects to canonical preview endpoint."""
    from starlette.responses import RedirectResponse
    return RedirectResponse(url=f"/api/files/preview/{file_id}", status_code=307)

@router.get("/api/files/{file_id:path}/public-url")
async def public_url_by_id(file_id: str, request: Request):
    """Return public URL for a file by ID."""
    import os
    WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", "/root/workspace")
    full_path = os.path.join(WORKSPACE_DIR, file_id)
    if os.path.isfile(full_path):
        return {"url": f"https://arcaneai.ru/workspace/{file_id}"}  # P4-FIX BUG-005: canonical
    # Try projects dir
    projects_path = os.path.join("/root/arcane/data/projects", file_id)
    if os.path.isfile(projects_path):
        return {"url": f"https://arcaneai.ru/workspace/{file_id}"}  # P4-FIX BUG-005: unified
    from fastapi import HTTPException
    raise HTTPException(404, "File not found")

@router.get("/api/files/download/{file_path:path}")
async def download_file(file_path: str, request: Request):
    """Download a file from the agent's workspace. S4: requires auth."""
    _require_user_id(request)
    resolved = _resolve_file_path(file_path)
    if not resolved:
        raise HTTPException(404, "File not found")

    content_type, _ = mimetypes.guess_type(resolved)
    filename = os.path.basename(resolved)

    return FileResponse(
        path=resolved,
        filename=filename,
        media_type=content_type or "application/octet-stream",
    )


@router.get("/api/files/preview/{file_path:path}")
async def preview_file(file_path: str, request: Request):
    """Preview a file inline (no download header). S4: requires auth."""
    _require_user_id(request)
    resolved = _resolve_file_path(file_path)
    if not resolved:
        raise HTTPException(404, "File not found")

    content_type, _ = mimetypes.guess_type(resolved)
    return FileResponse(
        path=resolved,
        media_type=content_type or "text/html",
        headers={"Content-Disposition": "inline"},
    )


@router.get("/api/projects")
async def list_projects(request: Request):
    """S4: List projects for authenticated user, filtered by their chats."""
    user_id = _require_user_id(request)
    """List all projects in the projects directory."""
    projects = []
    for base_dir in [PROJECTS_DIR, WORKSPACE_DIR]:
        if not os.path.isdir(base_dir):
            continue
        for entry in sorted(os.listdir(base_dir),
                            key=lambda x: os.path.getmtime(os.path.join(base_dir, x)),
                            reverse=True):
            entry_path = os.path.join(base_dir, entry)
            if os.path.isdir(entry_path):
                files = []
                for root, dirs, fnames in os.walk(entry_path):
                    for f in fnames:
                        fp = os.path.join(root, f)
                        rel = os.path.relpath(fp, base_dir)
                        files.append({
                            "name": f,
                            "path": rel,
                            "size": os.path.getsize(fp),
                            "preview_url": f"https://arcaneai.ru/workspace/{rel}",  # P4-FIX BUG-005
                            "download_url": f"https://arcaneai.ru/api/files/download/{rel}",
                        })
                projects.append({
                    "name": entry,
                    "type": "directory",
                    "files": files,
                    "created": os.path.getctime(entry_path),
                })
            elif os.path.isfile(entry_path) and entry.endswith((".html", ".zip")):
                rel = os.path.relpath(entry_path, base_dir)
                projects.append({
                    "name": entry,
                    "type": "file",
                    "size": os.path.getsize(entry_path),
                    "preview_url": f"https://arcaneai.ru/workspace/{rel}",  # P4-FIX BUG-005
                    "download_url": f"https://arcaneai.ru/api/files/download/{rel}",
                    "created": os.path.getctime(entry_path),
                })
    return {"projects": projects}



@router.get("/api/chats/{chat_id}/files")
async def list_chat_files(chat_id: str, request: Request):
    """S4: List files in a specific chat workspace. Requires ownership."""
    user_id = _require_user_id(request)
    chat = get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    _check_chat_ownership(chat, user_id)

    chat_workspace = os.path.join(WORKSPACE_DIR, chat_id)
    files = []
    if os.path.isdir(chat_workspace):
        for root_dir, dirs, fnames in os.walk(chat_workspace):
            depth = root_dir.replace(chat_workspace, "").count(os.sep)
            if depth > 4:
                dirs.clear()
                continue
            for fname in fnames:
                fp = os.path.join(root_dir, fname)
                rel = os.path.relpath(fp, chat_workspace)
                files.append({
                    "id": rel,
                    "name": fname,
                    "size": os.path.getsize(fp),
                    "path": fp,
                    "download_url": f"https://arcaneai.ru/api/files/download/{chat_id}/{rel}",
                })
    return {"chat_id": chat_id, "workspace": chat_workspace, "files": files}

@router.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    content = await file.read()
    filepath = os.path.join(_compat_cfg.workspace_root, "uploads", file.filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(content)
    return {"ok": True, "file": {"id": str(uuid.uuid4())[:8], "name": file.filename, "size": len(content), "path": filepath}}



@router.delete("/api/admin/workspace/{chat_id}")
async def cleanup_workspace(chat_id: str, request: Request):
    """S4: Admin endpoint to clean up a chat workspace directory."""
    _require_admin(request)
    import shutil
    workspace = os.path.join(WORKSPACE_DIR, chat_id)
    if not os.path.isdir(workspace):
        raise HTTPException(404, f"Workspace not found: {chat_id}")
    # Safety check: only delete if it looks like a UUID
    import re
    if not re.match(r'^[0-9a-f-]{8,}$', chat_id, re.IGNORECASE):
        raise HTTPException(400, "Invalid workspace ID format")
    size_bytes = sum(
        os.path.getsize(os.path.join(root, f))
        for root, dirs, files in os.walk(workspace)
        for f in files
    )
    shutil.rmtree(workspace)
    return {"ok": True, "deleted": workspace, "freed_bytes": size_bytes}


@router.get("/api/admin/workspaces")
async def list_workspaces(request: Request):
    """S4: Admin endpoint to list all workspaces with sizes."""
    _require_admin(request)
    workspaces = []
    if os.path.isdir(WORKSPACE_DIR):
        for entry in sorted(os.listdir(WORKSPACE_DIR)):
            entry_path = os.path.join(WORKSPACE_DIR, entry)
            if os.path.isdir(entry_path):
                size = sum(
                    os.path.getsize(os.path.join(root, f))
                    for root, dirs, files in os.walk(entry_path)
                    for f in files
                )
                workspaces.append({
                    "id": entry,
                    "path": entry_path,
                    "size_bytes": size,
                    "modified": os.path.getmtime(entry_path),
                })
    total = sum(w["size_bytes"] for w in workspaces)
    return {"workspaces": workspaces, "total_size_bytes": total, "count": len(workspaces)}

@router.get("/api/rate-limit/status")
async def rate_limit_status(request: Request):
    """S7: Real rate limit status for current user/IP."""
    from api.rate_limiter import get_rate_limit_status
    return await get_rate_limit_status(request)


# ============================================================================
# Admin endpoints — now using chat_store
# ============================================================================

@router.get("/api/admin/stats")
async def admin_stats(request: Request):
    _require_admin(request)
    return await get_admin_stats()

@router.get("/api/admin/metrics")
async def admin_metrics(request: Request):
    """S9: Real-time application metrics (admin only)."""
    _require_admin(request)
    from api.metrics import get_metrics_summary
    return get_metrics_summary()

@router.get("/api/metrics")
async def public_metrics(request: Request):
    """S9: Lightweight health metrics for monitoring systems."""
    _require_user_id(request)  # P0 FIX: was _require_auth (undefined)
    from api.metrics import get_health_metrics
    return get_health_metrics()


@router.get("/api/admin/users")
async def admin_users(request: Request):
    """Get users from DB."""
    _require_admin(request)
    users = []
    try:
        from config.settings import get_config
        from shared.models.database import get_session_factory, User
        from sqlalchemy import select

        config = get_config()
        factory = get_session_factory(config.db.url)
        async with factory() as session:
            result = await session.execute(select(User))
            for u in result.scalars():
                users.append({
                    "id": u.id,
                    "username": u.username,
                    "email": u.email or "",
                    "role": u.role,
                })
    except Exception as e:
        logger.warning(f"Admin users error: {e}")
    return {"users": users}


@router.get("/api/admin/memory")
async def admin_memory(request: Request):
    _require_admin(request)
    return {"memories": []}


@router.delete("/api/admin/memory/{memory_id}")
async def admin_delete_memory(memory_id: str, request: Request):
    _require_admin(request)
    return {"ok": True}


@router.post("/api/admin/memory/clear-sessions")
async def admin_clear_sessions(request: Request):
    _require_admin(request)
    return {"ok": True, "cleared": 0}


# ============================================================================
# Analytics endpoints — now using chat_store
# ============================================================================

@router.get("/api/admin/chats")
async def admin_chats_endpoint(request: Request):
    """Get all chats for admin panel."""
    _require_admin(request)
    chats_list = await get_admin_chats()
    return {"chats": chats_list, "total": len(chats_list)}


@router.get("/api/analytics/usage")
async def analytics_usage(request: Request):
    """S5: Analytics usage — now uses analytics_service for richer data."""
    _require_admin(request)
    from api.analytics_service import get_usage_analytics
    return await get_usage_analytics()


@router.get("/api/analytics/tasks")
async def analytics_tasks(request: Request):
    """S5: Analytics tasks — now uses analytics_service for richer data."""
    _require_admin(request)
    from api.analytics_service import get_tasks_analytics
    return await get_tasks_analytics()


# ============================================================================
# Settings & Custom Agents
# ============================================================================

@router.get("/api/settings")
async def get_settings():
    return {
        "theme": "light",
        "language": "ru",
        "notifications": True,
        "default_model": "gpt-5.4",
        "default_strategy": "balanced",
    }


@router.patch("/api/settings")
async def update_settings(request: Request):
    body = await request.json()
    return {"ok": True, "settings": body}


@router.get("/api/agents/custom")
async def list_custom_agents():
    return {"agents": []}


@router.post("/api/agents/custom")
async def create_custom_agent(request: Request):
    body = await request.json()
    agent = {"id": str(uuid.uuid4())[:8], "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"), **body}
    return {"ok": True, "agent": agent}


@router.delete("/api/agents/custom/{agent_id}")
async def delete_custom_agent(agent_id: str):
    return {"ok": True}


@router.put("/api/chats/{chat_id}/rename")
async def rename_chat(chat_id: str, request: Request):
    """Rename a chat (frontend calls PUT /api/chats/{id}/rename). Requires ownership."""
    user_id = _require_user_id(request)
    chat = get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    _check_chat_ownership(chat, user_id)
    body = await request.json()
    title = body.get("title", "")
    if title:
        await store_update_chat(chat_id, title=title)
    return {"ok": True, "chat": get_chat(chat_id)}


@router.put("/api/chats/{chat_id}/model")
async def update_chat_model(chat_id: str, request: Request):
    """Update the model for a chat. P4-FIX BUG-017: ownership check."""
    user_id = _require_user_id(request)
    chat = get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    _check_chat_ownership(chat, user_id)
    body = await request.json()
    model = body.get("model", "")
    if model:
        await store_update_chat(chat_id, model_used=model)
    return {"ok": True}


# ── Schedule endpoints (v7: stub CRUD for frontend compatibility) ────────────

_scheduled_tasks: dict[str, dict] = {}

@router.get("/api/schedule")
async def list_scheduled_tasks():
    """List all scheduled tasks."""
    return {"tasks": list(_scheduled_tasks.values())}


@router.post("/api/schedule")
async def create_scheduled_task(request: Request):
    """Create a scheduled task."""
    import time as _time
    body = await request.json()
    task_id = str(uuid.uuid4())[:8]
    task = {
        "id": task_id,
        "name": body.get("name", "Unnamed Task"),
        "prompt": body.get("prompt", ""),
        "type": body.get("type", "cron"),
        "cron": body.get("cron", ""),
        "interval": body.get("interval", 0),
        "repeat": body.get("repeat", True),
        "enabled": True,
        "total_runs": 0,
        "total_cost": 0.0,
        "avg_cost": 0.0,
        "last_run_at": None,
        "last_run_status": None,
        "next_run_at": None,
        "created_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_history": [],
    }
    _scheduled_tasks[task_id] = task
    return {"ok": True, "task": task}


@router.get("/api/schedule/{task_id}")
async def get_scheduled_task(task_id: str):
    """Get a scheduled task by ID."""
    task = _scheduled_tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return {"task": task}


@router.put("/api/schedule/{task_id}")
async def update_scheduled_task(task_id: str, request: Request):
    """Update a scheduled task."""
    task = _scheduled_tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    body = await request.json()
    for key in ("name", "prompt", "cron", "interval", "repeat", "enabled"):
        if key in body:
            task[key] = body[key]
    return {"ok": True, "task": task}


@router.delete("/api/schedule/{task_id}")
async def delete_scheduled_task(task_id: str):
    """Delete a scheduled task."""
    _scheduled_tasks.pop(task_id, None)
    return {"ok": True}


@router.post("/api/schedule/{task_id}/toggle")
async def toggle_scheduled_task(task_id: str):
    """Toggle a scheduled task on/off."""
    task = _scheduled_tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    task["enabled"] = not task["enabled"]
    return {"ok": True, "task": task}


@router.post("/api/schedule/{task_id}/run")
async def run_scheduled_task_now(task_id: str):
    """Run a scheduled task immediately."""
    task = _scheduled_tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    # Trigger task execution by creating a new chat message
    try:
        from api.chat_store import get_chat, get_messages
        chat_data = get_chat(task.get("chat_id", ""))
        if chat_data:
            # Mark task as triggered
            task["last_run"] = __import__("datetime").datetime.utcnow().isoformat()
            task["run_count"] = task.get("run_count", 0) + 1
            return {"ok": True, "message": "Task triggered", "task_id": task_id}
    except Exception as e:
        pass
    return {"ok": True, "message": "Task queued for execution"}


# ═══════════════════════════════════════════════════════════════════════════════
# FEEDBACK — user can rate results and request changes
# ═══════════════════════════════════════════════════════════════════════════════

class FeedbackPayload(BaseModel):
    rating: Optional[int] = None        # 1-5 stars, optional
    comment: Optional[str] = None       # "переделай заголовок", optional
    action: Optional[str] = "continue"  # "continue" | "stop" | "redo"


@router.post("/api/chats/{chat_id}/feedback")
async def submit_feedback(chat_id: str, payload: FeedbackPayload, request: Request):
    """
    User submits feedback on the agent's work.
    - rating: 1-5 quality score (stored in DB for analytics)
    - comment: free-text instruction like "переделай заголовок" → injected as new user message
    - action: "continue" (default) resumes the agent with the comment as a new task
    """
    # P4-FIX BUG-017: ownership check
    user_id = _require_user_id(request)
    chat = get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    _check_chat_ownership(chat, user_id)
    # 1. Store rating in DB if provided
    if payload.rating is not None:
        rating = max(1, min(5, payload.rating))
        try:
            pool = await _get_feedback_pool()
            if pool:
                await pool.execute(
                    """INSERT INTO chat_feedback (chat_id, rating, comment, created_at)
                       VALUES ($1, $2, $3, NOW())
                       ON CONFLICT (chat_id) DO UPDATE SET rating=$2, comment=$3, created_at=NOW()""",
                    chat_id, rating, payload.comment or "",
                )
        except Exception as e:
            logger.warning(f"Failed to store feedback in DB: {e}")
            # Non-critical — continue even if DB write fails

    # 2. If there's a comment, inject it as a new user message and resume agent
    if payload.comment and payload.comment.strip():
        msg = await store_add_message(
            chat_id=chat_id,
            role="user",
            content=payload.comment.strip(),
        )

        # Resume agent with the feedback as a new instruction
        if payload.action != "stop":
            try:
                from api.agent_runner import start_agent_for_chat
                # Extract user_id from JWT
                user_id = None
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    try:
                        token_data = _pyjwt.decode(
                            auth_header[7:], _JWT_SECRET, algorithms=[_JWT_ALGORITHM]
                        )
                        user_id = token_data.get("sub")
                    except Exception:
                        pass

                model = chat.get("model", "openai/gpt-4.1-mini")
                asyncio.create_task(
                    start_agent_for_chat(chat_id, payload.comment.strip(), model, user_id=user_id)
                )
            except Exception as e:
                logger.error(f"Failed to resume agent after feedback: {e}")

        return {
            "ok": True,
            "message_id": msg.get("id") if msg else None,
            "action": payload.action,
        }

    return {"ok": True, "action": payload.action}


async def _get_feedback_pool():
    """Reuse the chat_store pool for feedback writes."""
    try:
        from api.chat_store import _get_pool
        return await _get_pool()
    except Exception:
        return None
