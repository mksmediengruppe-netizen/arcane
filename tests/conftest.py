"""
ARCANE Backend Tests — Shared Fixtures (P4-FIX BUG-020)
========================================================
Self-contained tests using FastAPI TestClient (in-process).
No running server required. Falls back to httpx if ARCANE_TEST_URL is set.
"""
from __future__ import annotations
import os
import uuid
import pytest
import pytest_asyncio

# ── Mode selection ──────────────────────────────────────────────────────────
# If ARCANE_TEST_URL is set, use httpx against a live server (integration mode).
# Otherwise, use FastAPI TestClient for self-contained unit tests.
_LIVE_URL = os.getenv("ARCANE_TEST_URL")
_USE_LIVE = bool(_LIVE_URL)

if _USE_LIVE:
    import httpx
else:
    import sys
    # Ensure the arcane root is on sys.path for imports
    _arcane_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _arcane_root not in sys.path:
        sys.path.insert(0, _arcane_root)
    from httpx import ASGITransport, AsyncClient as httpx_AsyncClient
    from app import create_app


def _check_server_available():
    """Skip all tests if live server is configured but not reachable."""
    if not _USE_LIVE:
        return True  # TestClient mode — always available
    import socket
    from urllib.parse import urlparse
    parsed = urlparse(_LIVE_URL)
    host = parsed.hostname or "localhost"
    port = parsed.port or 8900  # default port for ARCANE backend
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    try:
        sock.connect((host, port))
        sock.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


_server_available = _check_server_available()
pytestmark = pytest.mark.skipif(
    not _server_available,
    reason=f"Server not available at {_LIVE_URL}" if _USE_LIVE else "App import failed",
)

TEST_USER_PREFIX = "smoke_test_"
_user_cache: dict[str, dict] = {}


async def _ensure_user(client, key: str) -> dict:
    """Register a user once and cache the result."""
    if key in _user_cache:
        return _user_cache[key]
    unique = uuid.uuid4().hex[:8]
    username = f"{TEST_USER_PREFIX}{key}_{unique}"
    password = f"TestPass_{unique}!"
    email = f"{username}@test.arcane.local"
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "email": email},
    )
    assert resp.status_code == 200, f"Register failed: {resp.status_code} {resp.text}"
    data = resp.json()
    token = data.get("token") or data.get("access_token")
    user = data["user"]
    assert token, f"No token in register response: {data}"
    result = {
        "username": username,
        "password": password,
        "email": email,
        "token": token,
        "user_id": user["id"],
        "user": user,
    }
    _user_cache[key] = result
    return result




@pytest.fixture(autouse=True)
async def _reset_db_engine():
    """Reset the async engine singleton between tests to avoid event loop conflicts."""
    yield
    # After each test, reset the engine so the next test gets a fresh one
    try:
        from shared.models import database as _db_mod
        if hasattr(_db_mod, '_async_engine') and _db_mod._async_engine is not None:
            try:
                await _db_mod._async_engine.dispose()
            except Exception:
                pass
            _db_mod._async_engine = None
            _db_mod._async_session_factory = None
    except ImportError:
        pass

@pytest.fixture(scope="session")
def base_url():
    return _LIVE_URL or "http://testserver"


@pytest_asyncio.fixture
async def http_client():
    """Raw client — no auth. Works in both live and TestClient modes."""
    if _USE_LIVE:
        async with httpx.AsyncClient(base_url=_LIVE_URL, timeout=30.0) as client:
            yield client
    else:
        app = create_app()
        transport = ASGITransport(app=app)
        async with httpx_AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as client:
            yield client


@pytest_asyncio.fixture
async def test_user(http_client):
    """Get or register the primary test user."""
    return await _ensure_user(http_client, "primary")


@pytest_asyncio.fixture
async def auth_client(test_user):
    """Client with Bearer token for the test user."""
    headers = {"Authorization": f"Bearer {test_user['token']}"}
    if _USE_LIVE:
        async with httpx.AsyncClient(
            base_url=_LIVE_URL, timeout=30.0, headers=headers
        ) as client:
            yield client
    else:
        app = create_app()
        transport = ASGITransport(app=app)
        async with httpx_AsyncClient(
            transport=transport, base_url="http://testserver", timeout=30.0, headers=headers
        ) as client:
            yield client


@pytest_asyncio.fixture
async def second_user(http_client):
    """Get or register the second test user for ownership tests."""
    return await _ensure_user(http_client, "secondary")


@pytest_asyncio.fixture
async def second_auth_client(second_user):
    """Client with Bearer token for the second test user."""
    headers = {"Authorization": f"Bearer {second_user['token']}"}
    if _USE_LIVE:
        async with httpx.AsyncClient(
            base_url=_LIVE_URL, timeout=30.0, headers=headers
        ) as client:
            yield client
    else:
        app = create_app()
        transport = ASGITransport(app=app)
        async with httpx_AsyncClient(
            transport=transport, base_url="http://testserver", timeout=30.0, headers=headers
        ) as client:
            yield client
