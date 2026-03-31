"""
ARCANE E2E Test Configuration (P4-FIX BUG-020)
================================================
Self-contained tests using FastAPI TestClient when no live server is available.
Provides fixtures for testing the full agent pipeline:
- API client for chat endpoints
- SSE event collector
- Cost and timing assertions
"""
from __future__ import annotations
import asyncio
import json
import os
import time
from typing import AsyncGenerator, Optional

import pytest
import pytest_asyncio

# ── Mode selection ──────────────────────────────────────────────────────────
_LIVE_URL = os.environ.get("ARCANE_TEST_URL")
_USE_LIVE = bool(_LIVE_URL)

if _USE_LIVE:
    import httpx
else:
    import sys
    _arcane_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if _arcane_root not in sys.path:
        sys.path.insert(0, _arcane_root)
    from httpx import ASGITransport, AsyncClient as httpx_AsyncClient
    from app import create_app

TEST_USER = os.environ.get("ARCANE_TEST_USER", "admin")
TEST_PASS = os.environ.get("ARCANE_TEST_PASS", "admin")


@pytest_asyncio.fixture(scope="session")
async def auth_token() -> str:
    """Authenticate and return JWT token."""
    if _USE_LIVE:
        async with httpx.AsyncClient(base_url=_LIVE_URL, timeout=30.0) as client:
            resp = await client.post(
                "/api/auth/login",
                json={"username": TEST_USER, "password": TEST_PASS},
            )
    else:
        app = create_app()
        transport = ASGITransport(app=app)
        async with httpx_AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as client:
            resp = await client.post(
                "/api/auth/login",
                json={"username": TEST_USER, "password": TEST_PASS},
            )
    if resp.status_code != 200:
        pytest.skip(f"Cannot authenticate: {resp.status_code} {resp.text[:200]}")
    data = resp.json()
    return data.get("token") or data.get("access_token", "")


@pytest_asyncio.fixture(scope="session")
async def api_client(auth_token: str) -> AsyncGenerator:
    """Authenticated HTTP client for ARCANE API."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    if _USE_LIVE:
        async with httpx.AsyncClient(
            base_url=_LIVE_URL,
            headers=headers,
            timeout=httpx.Timeout(300.0),
        ) as client:
            yield client
    else:
        app = create_app()
        transport = ASGITransport(app=app)
        async with httpx_AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers=headers,
            timeout=300.0,
        ) as client:
            yield client


class SSECollector:
    """Collect SSE events from a chat stream."""

    def __init__(self):
        self.events: list[dict] = []
        self.cost_events: list[dict] = []
        self.phase_events: list[dict] = []
        self.tool_events: list[dict] = []
        self.design_reports: list[dict] = []
        self.errors: list[dict] = []

    def add_event(self, event_type: str, data: dict):
        self.events.append({"type": event_type, **data})
        if event_type == "cost_update":
            self.cost_events.append(data)
        elif event_type == "agent_status" and "phase" in str(data):
            self.phase_events.append(data)
        elif event_type == "tool_progress":
            self.tool_events.append(data)
        elif event_type == "design_report":
            self.design_reports.append(data)
        elif event_type == "error":
            self.errors.append(data)

    @property
    def total_cost(self) -> float:
        if self.cost_events:
            return self.cost_events[-1].get("total_cost", 0.0)
        return 0.0

    @property
    def tools_used(self) -> list[str]:
        return [e.get("tool", "") for e in self.tool_events]


@pytest.fixture
def sse_collector() -> SSECollector:
    return SSECollector()


async def send_message_and_wait(
    client,
    message: str,
    chat_id: Optional[str] = None,
    timeout_seconds: int = 300,
) -> tuple[str, SSECollector]:
    """
    Send a message to a chat and collect all SSE events until task_complete.
    Returns (chat_id, SSECollector).
    """
    import uuid

    if not chat_id:
        chat_id = str(uuid.uuid4())

    # Create chat
    await client.post(
        "/api/chats",
        json={"id": chat_id, "title": message[:50]},
    )

    # Send message
    await client.post(
        f"/api/chats/{chat_id}/send",
        json={"content": message, "role": "user"},
    )

    # Collect SSE events
    collector = SSECollector()
    event_type = ""
    start = time.monotonic()

    async with client.stream("GET", f"/api/chats/{chat_id}/send") as stream:
        async for line in stream.aiter_lines():
            if time.monotonic() - start > timeout_seconds:
                break
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                    collector.add_event(event_type, data)
                except (json.JSONDecodeError, UnboundLocalError):
                    pass
                if event_type in ("task_complete", "error", "budget_exceeded"):
                    break

    return chat_id, collector
