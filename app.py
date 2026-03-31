"""
ARCANE — Autonomous Runtime for Code, Automation, Networking & Engineering
Main application entry point.

Domain: arcaneai.ru
Architecture:
  FastAPI async server with SSE + WebSocket support.
  Agent Loop runs as background task per chat.
  Workers are instantiated on demand.
  Frontend served via Nginx reverse proxy.
"""

from __future__ import annotations

import asyncio
import os
import time

from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

import traceback
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.compat import router as compat_router
from api.sse import router as sse_router
from api.websocket import ConnectionManager
from config.settings import get_config
from shared.utils.logger import get_logger

logger = get_logger("app")
config = get_config()

# Global instances
ws_manager = ConnectionManager()

VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    logger.info("=" * 60)
    logger.info(f"ARCANE v{VERSION} starting up...")
    logger.info(f"Domain: arcaneai.ru")
    logger.info(f"Environment: {config.env.value}")
    logger.info(f"Port: {config.port}")
    logger.info("=" * 60)

    # Create workspace directories
    for d in [
        "/root/workspace",
        "/root/workspace/screenshots",
        "/root/workspace/uploads",
        "/root/workspace/projects",
        "/root/workspace/sandbox",
    ]:
        os.makedirs(d, exist_ok=True)

    # Initialize database tables
    try:
        from shared.models.database import init_database
        await init_database(config.db.url)
        logger.info("Database tables initialized")
    except Exception as e:
        logger.warning(f"Database init skipped: {e}")

    # Load chats from DB into memory
    try:
        from api.chat_store import init_store
        await init_store()
        logger.info("Chat store initialized from DB")
    except Exception as e:
        logger.warning(f"Chat store init skipped: {e}")

    # S7: Start rate limiter cleanup background task
    from api.rate_limiter import cleanup_old_entries
    asyncio.create_task(cleanup_old_entries())
    logger.info("Rate limiter active")
    # ═══ WORKER POOL STARTUP ═══
    try:
        from core.worker_pool import start_pool
        pool = await start_pool()
        logger.info(f"Worker pool started: {pool.max_workers} workers")
    except Exception as e:
        logger.warning(f"Worker pool startup failed (falling back to direct execution): {e}")
    yield

    # ═══ GRACEFUL SHUTDOWN (P0 — Worker Pool + Legacy) ═══
    logger.info("ARCANE shutting down — saving agent states...")
    # Phase 0: Shutdown worker pool (saves all active agent states to Redis)
    try:
        from core.worker_pool import shutdown_pool
        interrupted = await shutdown_pool(timeout=20.0)
        if interrupted:
            logger.info(f"Worker pool: {len(interrupted)} task(s) interrupted and saved")
        else:
            logger.info("Worker pool: shutdown clean (no active tasks)")
    except Exception as e:
        logger.warning(f"Worker pool shutdown error: {e}")
    # Phase 1: Legacy fallback — save any direct-execution agents
    from api.agent_runner import _running_agents, _agent_instances, stop_agent_for_chat

    active_chats = list(_running_agents.keys())
    if active_chats:
        logger.info(f"Saving state for {len(active_chats)} active agent(s): {active_chats}")
        save_tasks = []
        for chat_id in active_chats:
            save_tasks.append(
                asyncio.create_task(stop_agent_for_chat(chat_id, user_id="system_shutdown"))
            )

        # Give agents up to 15 seconds to save their state
        if save_tasks:
            done, pending = await asyncio.wait(save_tasks, timeout=15.0)
            saved_count = sum(1 for t in done if not t.exception())
            failed_count = len(done) - saved_count + len(pending)

            # Cancel any that didn't finish in time
            for t in pending:
                t.cancel()

            logger.info(
                f"Graceful shutdown: {saved_count} agent(s) saved, "
                f"{failed_count} failed/timed out"
            )
    else:
        logger.info("No active agents to save")

    # Phase 2: Clean up remaining references
    _running_agents.clear()
    _agent_instances.clear()

    # Phase 3: Close DB connection pool
    try:
        from api.chat_store import _get_pool
        pool = await _get_pool()
        if pool:
            await asyncio.wait_for(pool.close(), timeout=5.0)
            logger.info("Database connection pool closed")
    except Exception as e:
        logger.warning(f"DB pool close: {e}")

    # Phase 4: Close Redis connection
    try:
        from api.agent_runner import _task_queue_instance
        if _task_queue_instance:
            await _task_queue_instance.disconnect()
            logger.info("Redis connection closed")
    except Exception as e:
        logger.warning(f"Redis close: {e}")
    logger.info("ARCANE shutdown complete")



# ═══════════════════════════════════════════════════════════════════
# FIX NEW-010: WebSocket rate limiting
# ═══════════════════════════════════════════════════════════════════
import time as _time
from collections import defaultdict as _defaultdict

_ws_rate_limits: dict[str, list[float]] = _defaultdict(list)
_WS_RATE_LIMIT = 30   # max messages per minute per user
_WS_RATE_WINDOW = 60  # sliding window in seconds

def _check_ws_rate_limit(user_id: str) -> bool:
    """
    Check if a WebSocket user has exceeded the rate limit.
    Uses a sliding window of _WS_RATE_WINDOW seconds.
    Returns True if the message is allowed, False if rate limited.
    """
    now = _time.time()
    cutoff = now - _WS_RATE_WINDOW
    # Remove expired timestamps
    _ws_rate_limits[user_id] = [t for t in _ws_rate_limits[user_id] if t > cutoff]
    if len(_ws_rate_limits[user_id]) >= _WS_RATE_LIMIT:
        return False
    _ws_rate_limits[user_id].append(now)
    return True

def create_app() -> FastAPI:
    """Factory function for creating the FastAPI app."""
    application = FastAPI(
        title="ARCANE",
        description="Autonomous Runtime for Code, Automation, Networking & Engineering",
        version=VERSION,
        lifespan=lifespan,
    )

    # CORS — allow arcaneai.ru and local dev
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://arcaneai.ru",
            "https://www.arcaneai.ru",
            "http://arcaneai.ru",
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ─── Global Exception Handlers (S6) ─────────────────────────────────
    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """S6: Structured HTTP error responses."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "ok": False,
                "error": str(exc.detail),
                "status_code": exc.status_code,
            },
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """S6: Structured validation error responses."""
        errors = []
        for error in exc.errors():
            errors.append({
                "field": ".".join(str(x) for x in error.get("loc", [])),
                "message": error.get("msg", ""),
                "type": error.get("type", ""),
            })
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "error": "Validation error",
                "details": errors,
            },
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """S6: Catch-all for unhandled exceptions — log and return 500."""
        tb = traceback.format_exc()
        logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc} | {tb}")
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": "Internal server error",
                "message": str(exc) if config.debug else "An unexpected error occurred",
            },
        )

    # Request timing middleware
    @application.middleware("http")
    async def timing_middleware(request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        duration = (time.monotonic() - start) * 1000
        response.headers["X-Process-Time-Ms"] = f"{duration:.1f}"
        # S9: Record metrics
        try:
            from api.metrics import record_response
            record_response(request.url.path, request.method, response.status_code, duration)
        except Exception:
            pass
        return response

    # S6: Request ID middleware — adds X-Request-ID to every response
    import uuid as _uuid
    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(_uuid.uuid4())[:8]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # ─── API Routes ──────────────────────────────────────────────────────

    # Health endpoint
    @application.get("/api/health")
    async def health_check():
        from api.health import get_health_report
        return await get_health_report()

    # Compatibility layer for frontend-new (FIRST — handles cookies + JWT)
    application.include_router(compat_router)

    # NOTE: auth_router removed (Bug #7 fix) — compat.py handles /api/auth/login, /me, /logout
    # auth.py still provides utility functions (create_token, decode_token, hash_password)
    # but its router caused split-brain auth (72h JWT vs 30d cookie in compat.py)

    # SSE (Server-Sent Events)
    application.include_router(sse_router)

    # Chat API (projects, chats, messages)
    # REMOVED (P0-3): Legacy in-memory chat router disabled.
    # All chat functionality is handled by api/compat.py which uses persistent chat_store.
    # from api.chat import router as chat_router
    # application.include_router(chat_router)

    # ─── Root endpoint ───────────────────────────────────────────────────

    @application.get("/")
    async def root():
        from api.agent_runner import get_active_agents
        # Include worker pool stats
        try:
            from core.worker_pool import _pool_instance
            if _pool_instance:
                status_data["worker_pool"] = _pool_instance.get_pool_stats()
        except Exception:
            pass
        return {
            "name": "ARCANE",
            "version": VERSION,
            "domain": "arcaneai.ru",
            "description": "Autonomous Runtime for Code, Automation, Networking & Engineering",
            "status": "running",
            "active_agents": len(get_active_agents()),
            "ws_connections": ws_manager.active_count,
            "endpoints": {
                "health": "/api/health",
                "auth": "/api/auth/login",
                "chats": "/api/v2/chats",
                "sse": "/api/v2/stream/{chat_id}",
                "ws": "/ws/{chat_id}",
            },
        }

    # ─── WebSocket ───────────────────────────────────────────────────────

    @application.websocket("/ws/{user_id}")
    async def websocket_endpoint(websocket: WebSocket, user_id: str):
        await ws_manager.connect(websocket, user_id)
        try:
            while True:
                data = await websocket.receive_json()
                # FIX NEW-010: Rate limit check
                ws_user = data.get("user_id", "anonymous")
                if not _check_ws_rate_limit(ws_user):
                    await websocket.send_json({"type": "error", "message": "Rate limit exceeded. Max 30 messages/minute."})
                    continue
                event_type = data.get("type", "")
                if event_type == "ping":
                    await ws_manager.send_to_user(user_id, {"type": "pong"})
                elif event_type == "user_cancel":
                    chat_id = data.get("chat_id", "")
                    if chat_id:
                        from api.agent_runner import stop_agent_for_chat
                        await stop_agent_for_chat(chat_id)
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket, user_id)
        except Exception as e:
            logger.error(f"WebSocket error for user {user_id}: {e}")
            ws_manager.disconnect(websocket, user_id)

    # ─── Static files (frontend) ─────────────────────────────────────────

    frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
    if os.path.isdir(frontend_dist):
        application.mount(
            "/assets",
            StaticFiles(directory=os.path.join(frontend_dist, "assets")),
            name="assets",
        )

        @application.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            if full_path.startswith("api/") or full_path.startswith("ws/"):
                return JSONResponse({"error": "Not found"}, status_code=404)
            file_path = os.path.join(frontend_dist, full_path)
            if os.path.isfile(file_path):
                return FileResponse(file_path)
            return FileResponse(os.path.join(frontend_dist, "index.html"))

    return application


# Create the app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=config.port,
        reload=config.debug,
        log_level="info",
    )
