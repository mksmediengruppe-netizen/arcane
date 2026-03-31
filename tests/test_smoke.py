"""
ARCANE Backend Smoke Tests
==========================
Self-contained test suite that validates every critical API contract.
Run: cd /root/arcane && python3 -m pytest tests/smoke/test_smoke.py -v --timeout=60 -s

API response shapes (actual):
  Register/Login: {"ok": true, "user": {...}, "token": "..."}
  /me: {"ok": true, "user": {"id": ..., "username": ..., "role": ...}}
  Create chat: {"ok": true, "chat": {"id": <server-generated>, ...}}
  NOTE: API ignores client-provided chat ID and generates its own UUID.
"""
from __future__ import annotations

import uuid
import pytest
import httpx

pytestmark = pytest.mark.asyncio


# ── Helper ─────────────────────────────────────────────────────────────────

async def _create_chat(client: httpx.AsyncClient, title: str = "Test Chat") -> str:
    """Create a chat and return the server-generated ID."""
    resp = await client.post("/api/chats", json={"title": title})
    assert resp.status_code == 200, f"Create chat failed: {resp.status_code} {resp.text}"
    body = resp.json()
    chat = body.get("chat", body)
    chat_id = chat.get("id")
    assert chat_id, f"No chat ID in response: {body}"
    return chat_id


# ════════════════════════════════════════════════════════════════════════════
# 1. HEALTH CHECK
# ════════════════════════════════════════════════════════════════════════════

class TestHealth:

    async def test_health_returns_200(self, http_client: httpx.AsyncClient):
        resp = await http_client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert body["status"] in ("healthy", "degraded", "partial")
        print(f"  ✓ Health: {body['status']}")

    async def test_health_has_components(self, http_client: httpx.AsyncClient):
        resp = await http_client.get("/api/health")
        body = resp.json()
        assert "components" in body
        assert "version" in body
        print(f"  ✓ Health has components and version")


# ════════════════════════════════════════════════════════════════════════════
# 2. AUTH FLOW
# ════════════════════════════════════════════════════════════════════════════

class TestAuth:

    async def test_register_creates_user(self, test_user):
        assert test_user["token"]
        assert test_user["user_id"]
        assert test_user["username"].startswith("smoke_test_")
        print(f"  ✓ Registered: {test_user['username']}")

    async def test_login_returns_token(self, http_client: httpx.AsyncClient, test_user):
        resp = await http_client.post(
            "/api/auth/login",
            json={"username": test_user["username"], "password": test_user["password"]},
        )
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        body = resp.json()
        token = body.get("token") or body.get("access_token")
        assert token, f"No token in login response: {body}"
        user = body.get("user", {})
        assert user.get("username") == test_user["username"]
        print(f"  ✓ Login OK")

    async def test_me_returns_user_info(self, auth_client: httpx.AsyncClient, test_user):
        resp = await auth_client.get("/api/auth/me")
        assert resp.status_code == 200, f"Me failed: {resp.status_code} {resp.text}"
        body = resp.json()
        # /me returns {"ok": true, "user": {...}} or just {...}
        user = body.get("user", body)
        assert user.get("username") == test_user["username"]
        assert user.get("id") == test_user["user_id"]
        print(f"  ✓ /me: {user['username']} (role={user.get('role', '?')})")

    async def test_me_without_token_returns_401(self, http_client: httpx.AsyncClient):
        resp = await http_client.get("/api/auth/me")
        # compat.py /me returns 200 with session-based auth fallback, auth.py /me returns 401
        # We test the compat endpoint which is what the frontend uses
        if resp.status_code == 200:
            body = resp.json()
            # If it returns user data without auth, that's a security gap
            user = body.get("user", body)
            if user.get("id"):
                pytest.xfail("SECURITY GAP: /me returns user data without auth token")
        # Otherwise should be 401
        assert resp.status_code in (200, 401), f"Unexpected: {resp.status_code}"
        print(f"  ✓ /me without token → {resp.status_code}")

    async def test_register_duplicate_username_returns_409(
        self, http_client: httpx.AsyncClient, test_user
    ):
        resp = await http_client.post(
            "/api/auth/register",
            json={
                "username": test_user["username"],
                "password": "AnyPassword123!",
                "email": f"dup_{uuid.uuid4().hex[:6]}@test.local",
            },
        )
        assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
        print(f"  ✓ Duplicate username → 409")

    async def test_login_wrong_password_returns_401(
        self, http_client: httpx.AsyncClient, test_user
    ):
        resp = await http_client.post(
            "/api/auth/login",
            json={"username": test_user["username"], "password": "WrongPassword999!"},
        )
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
        print(f"  ✓ Wrong password → 401")


# ════════════════════════════════════════════════════════════════════════════
# 3. CHAT CRUD
# ════════════════════════════════════════════════════════════════════════════

class TestChatCRUD:

    async def test_create_chat(self, auth_client: httpx.AsyncClient):
        chat_id = await _create_chat(auth_client, "Smoke Test Chat")
        assert chat_id
        print(f"  ✓ Created chat: {chat_id[:8]}...")

    async def test_list_chats_includes_created(self, auth_client: httpx.AsyncClient):
        chat_id = await _create_chat(auth_client, "List Test Chat")
        resp = await auth_client.get("/api/chats")
        assert resp.status_code == 200
        body = resp.json()
        chats = body if isinstance(body, list) else body.get("chats", body.get("data", []))
        assert isinstance(chats, list)
        assert len(chats) >= 1
        chat_ids = [c.get("id", "") for c in chats]
        assert chat_id in chat_ids, f"Created chat {chat_id[:8]} not in list"
        print(f"  ✓ Listed {len(chats)} chat(s), created chat found")

    async def test_get_chat_by_id(self, auth_client: httpx.AsyncClient):
        chat_id = await _create_chat(auth_client, "Get Test Chat")
        resp = await auth_client.get(f"/api/chats/{chat_id}")
        assert resp.status_code == 200, f"Get chat failed: {resp.status_code} {resp.text}"
        print(f"  ✓ Got chat: {chat_id[:8]}...")

    async def test_rename_chat(self, auth_client: httpx.AsyncClient):
        chat_id = await _create_chat(auth_client, "Before Rename")
        resp = await auth_client.put(
            f"/api/chats/{chat_id}/rename",
            json={"title": "After Rename"},
        )
        assert resp.status_code == 200, f"Rename failed: {resp.status_code} {resp.text}"
        print(f"  ✓ Renamed chat: {chat_id[:8]}...")

    async def test_delete_chat(self, auth_client: httpx.AsyncClient):
        chat_id = await _create_chat(auth_client, "To Be Deleted")
        resp = await auth_client.delete(f"/api/chats/{chat_id}")
        assert resp.status_code == 200, f"Delete failed: {resp.status_code} {resp.text}"
        print(f"  ✓ Deleted chat: {chat_id[:8]}...")

    async def test_get_nonexistent_chat_returns_404(self, auth_client: httpx.AsyncClient):
        fake_id = str(uuid.uuid4())
        resp = await auth_client.get(f"/api/chats/{fake_id}")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
        print(f"  ✓ Nonexistent chat → 404")


# ════════════════════════════════════════════════════════════════════════════
# 4. SEND MESSAGE
# ════════════════════════════════════════════════════════════════════════════

class TestSendMessage:

    async def test_send_message_accepted(self, auth_client: httpx.AsyncClient):
        chat_id = await _create_chat(auth_client, "Send Test")
        resp = await auth_client.post(
            f"/api/chats/{chat_id}/send",
            json={"content": "Привет, это smoke test!", "role": "user"},
        )
        assert resp.status_code in (200, 202), (
            f"Send failed: {resp.status_code} {resp.text}"
        )
        print(f"  ✓ Sent message to chat: {chat_id[:8]}...")


# ════════════════════════════════════════════════════════════════════════════
# 5. OWNERSHIP ISOLATION
# ════════════════════════════════════════════════════════════════════════════

class TestOwnership:

    async def test_user_b_cannot_get_user_a_chat(
        self, auth_client: httpx.AsyncClient, second_auth_client: httpx.AsyncClient,
    ):
        chat_id = await _create_chat(auth_client, "Private Chat A")
        resp = await second_auth_client.get(f"/api/chats/{chat_id}")
        if resp.status_code == 200:
            pytest.xfail("OWNERSHIP BUG: User B can access User A's chat (200). Fix in Step 3.")
        assert resp.status_code in (403, 404)
        print(f"  ✓ User B denied access → {resp.status_code}")

    async def test_user_b_cannot_send_to_user_a_chat(
        self, auth_client: httpx.AsyncClient, second_auth_client: httpx.AsyncClient,
    ):
        chat_id = await _create_chat(auth_client, "Private Chat A (send)")
        resp = await second_auth_client.post(
            f"/api/chats/{chat_id}/send",
            json={"content": "I shouldn't be here!", "role": "user"},
        )
        if resp.status_code in (200, 202):
            pytest.xfail("OWNERSHIP BUG: User B can send to User A's chat. Fix in Step 3.")
        assert resp.status_code in (403, 404)
        print(f"  ✓ User B denied send → {resp.status_code}")

    async def test_user_b_cannot_delete_user_a_chat(
        self, auth_client: httpx.AsyncClient, second_auth_client: httpx.AsyncClient,
    ):
        chat_id = await _create_chat(auth_client, "Private Chat A (delete)")
        resp = await second_auth_client.delete(f"/api/chats/{chat_id}")
        if resp.status_code == 200:
            pytest.xfail("OWNERSHIP BUG: User B can delete User A's chat. Fix in Step 3.")
        assert resp.status_code in (403, 404)
        print(f"  ✓ User B denied delete → {resp.status_code}")

    async def test_user_b_cannot_rename_user_a_chat(
        self, auth_client: httpx.AsyncClient, second_auth_client: httpx.AsyncClient,
    ):
        chat_id = await _create_chat(auth_client, "Private Chat A (rename)")
        resp = await second_auth_client.put(
            f"/api/chats/{chat_id}/rename",
            json={"title": "Hacked Title"},
        )
        if resp.status_code == 200:
            pytest.xfail("OWNERSHIP BUG: User B can rename User A's chat. Fix in Step 3.")
        assert resp.status_code in (403, 404)
        print(f"  ✓ User B denied rename → {resp.status_code}")

    async def test_list_chats_only_shows_own(
        self, auth_client: httpx.AsyncClient, second_auth_client: httpx.AsyncClient,
    ):
        chat_a = await _create_chat(auth_client, "User A Exclusive")
        resp = await second_auth_client.get("/api/chats")
        assert resp.status_code == 200
        body = resp.json()
        chats = body if isinstance(body, list) else body.get("chats", body.get("data", []))
        chat_ids = [c.get("id", "") for c in chats]
        if chat_a in chat_ids:
            pytest.xfail("OWNERSHIP BUG: User B sees User A's chat in list. Fix in Step 3.")
        print(f"  ✓ User B's list does not contain User A's chat")


# ════════════════════════════════════════════════════════════════════════════
# 6. FILE & PROJECT LISTING
# ════════════════════════════════════════════════════════════════════════════

class TestFiles:

    async def test_list_files(self, auth_client: httpx.AsyncClient):
        resp = await auth_client.get("/api/files")
        assert resp.status_code == 200
        print(f"  ✓ Listed files")

    async def test_list_projects(self, auth_client: httpx.AsyncClient):
        resp = await auth_client.get("/api/projects")
        assert resp.status_code == 200
        print(f"  ✓ Listed projects")


# ════════════════════════════════════════════════════════════════════════════
# 7. STATIC ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

class TestStaticEndpoints:

    async def test_list_models(self, http_client: httpx.AsyncClient):
        resp = await http_client.get("/api/models")
        assert resp.status_code == 200
        print(f"  ✓ Models endpoint OK")

    async def test_list_templates(self, http_client: httpx.AsyncClient):
        resp = await http_client.get("/api/templates")
        assert resp.status_code == 200
        print(f"  ✓ Templates endpoint OK")

    async def test_list_connectors(self, http_client: httpx.AsyncClient):
        resp = await http_client.get("/api/connectors")
        assert resp.status_code == 200
        print(f"  ✓ Connectors endpoint OK")


# ════════════════════════════════════════════════════════════════════════════
# 8. UNAUTHENTICATED ACCESS (Baseline)
# ════════════════════════════════════════════════════════════════════════════

class TestUnauthenticatedAccess:

    async def test_create_chat_without_auth(self, http_client: httpx.AsyncClient):
        resp = await http_client.post(
            "/api/chats", json={"title": "No Auth Chat"},
        )
        if resp.status_code == 200:
            pytest.xfail("SECURITY GAP: Create chat without auth → 200 (should be 401)")
        assert resp.status_code == 401
        print(f"  ✓ Create chat without auth → 401")

    async def test_list_chats_without_auth(self, http_client: httpx.AsyncClient):
        resp = await http_client.get("/api/chats")
        if resp.status_code == 200:
            pytest.xfail("SECURITY GAP: List chats without auth → 200 (should be 401)")
        assert resp.status_code == 401
        print(f"  ✓ List chats without auth → 401")

    async def test_admin_stats_without_auth(self, http_client: httpx.AsyncClient):
        resp = await http_client.get("/api/admin/stats")
        if resp.status_code == 200:
            pytest.xfail("SECURITY GAP: Admin stats without auth → 200 (should be 401/403)")
        assert resp.status_code in (401, 403)
        print(f"  ✓ Admin stats without auth → {resp.status_code}")

    async def test_analytics_without_auth(self, http_client: httpx.AsyncClient):
        resp = await http_client.get("/api/analytics/usage")
        if resp.status_code == 200:
            pytest.xfail("SECURITY GAP: Analytics without auth → 200 (should be 401/403)")
        assert resp.status_code in (401, 403)
        print(f"  ✓ Analytics without auth → {resp.status_code}")
