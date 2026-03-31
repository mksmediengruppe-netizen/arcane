"""
ARCANE Backend Smoke Tests — Shared Fixtures
============================================
Uses function-scoped fixtures to avoid pytest-asyncio event loop issues.
User registration is cached via module-level dict to avoid re-registering.
"""
from __future__ import annotations

import os
import uuid
import pytest
import pytest_asyncio
import httpx

# ── Configuration ──────────────────────────────────────────────────────────
BASE_URL = os.getenv("ARCANE_TEST_URL", "http://localhost:8900")
TEST_USER_PREFIX = "smoke_test_"

# Cache registered users across tests (module-level, not async)
_user_cache: dict[str, dict] = {}


async def _ensure_user(client: httpx.AsyncClient, key: str) -> dict:
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


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest_asyncio.fixture
async def http_client():
    """Raw httpx client — no auth. Function-scoped."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        yield client


@pytest_asyncio.fixture
async def test_user(http_client: httpx.AsyncClient):
    """Get or register the primary test user."""
    return await _ensure_user(http_client, "primary")


@pytest_asyncio.fixture
async def auth_client(test_user):
    """httpx client with Bearer token for the test user. Function-scoped."""
    headers = {"Authorization": f"Bearer {test_user['token']}"}
    async with httpx.AsyncClient(
        base_url=BASE_URL, timeout=30.0, headers=headers
    ) as client:
        yield client


@pytest_asyncio.fixture
async def second_user(http_client: httpx.AsyncClient):
    """Get or register the second test user for ownership tests."""
    return await _ensure_user(http_client, "secondary")


@pytest_asyncio.fixture
async def second_auth_client(second_user):
    """httpx client with Bearer token for the second test user."""
    headers = {"Authorization": f"Bearer {second_user['token']}"}
    async with httpx.AsyncClient(
        base_url=BASE_URL, timeout=30.0, headers=headers
    ) as client:
        yield client
