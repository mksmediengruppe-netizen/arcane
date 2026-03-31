# ARCANE Refactoring Changelog

## Refactoring Sprint — Steps 1–10

### Step 1: Smoke Test Suite
- Added `tests/test_smoke.py` with 29 automated tests covering auth, chat CRUD, ownership, files, admin, and analytics
- Added `tests/conftest.py` with shared fixtures and user caching

### Step 2: Unified Auth Context
- Extracted `_get_current_user(request)` helper — single source of truth for auth
- All protected endpoints now use `_require_auth()` and `_require_admin()` decorators
- JWT and session cookie auth unified through one code path

### Step 3: Ownership & Admin Authorization
- All chat endpoints now verify `chat.user_id == current_user.id`
- Admin endpoints enforce `role == "admin"` check
- Returns `403 Forbidden` (not `404`) on ownership violations to prevent enumeration

### Step 4: Workspace Isolation
- `/api/files` — added auth + chat_id workspace filtering
- `/api/files/download` and `/api/files/preview` — added auth checks
- `/api/projects` — added auth + filter by user's chats only
- New endpoint: `GET /api/chats/{chat_id}/files` — files scoped to a specific chat (with ownership check)
- New admin endpoints: `GET /api/admin/workspaces`, `DELETE /api/admin/workspace/{chat_id}`

### Step 5: Service Layer
- Created `api/analytics_service.py` — analytics logic extracted from compat.py; added `by_model` and `by_day` breakdowns
- Created `api/chat_service.py` — chat CRUD operations (create, list, delete, rename) extracted to service layer
- `list_chats` endpoint now delegates to `chat_service.list_chats_for_user()`

### Step 6: Error Handling & Logging
- Added global `HTTPException` handler — structured JSON `{ok, error, status_code}`
- Added `RequestValidationError` handler — detailed field-level validation errors
- Added catch-all `Exception` handler — logs full traceback, returns safe 500 in production
- Added `X-Request-ID` middleware — every response gets a unique trace ID

### Step 7: Rate Limiting
- Created `api/rate_limiter.py` — sliding window in-memory rate limiter
- Limits: `auth` (10/min), `message` (30/min), `upload` (20/min), `default` (120/min), `admin` (300/min)
- Applied to: `/api/auth/login`, `/api/auth/register`, `/api/chats/{id}/message`
- `GET /api/rate-limit/status` now returns real usage data per user/IP
- Background cleanup task removes expired entries every 5 minutes

### Step 8: Database Optimization
- Added composite index `idx_chats_user_updated (user_id, updated_at DESC)` — accelerates `list_chats`
- Added index `idx_chats_status` — accelerates admin dashboard status filtering
- Added composite index `idx_messages_chat_created (chat_id, created_at)` — accelerates message history loading
- Added indexes `idx_users_username`, `idx_users_email`, `idx_users_role` — accelerates login lookups
- All 6 indexes applied to production PostgreSQL database

### Step 9: Monitoring & Observability
- Created `api/metrics.py` — in-memory metrics: request counts, latency (p50/p95/p99), error rates, agent metrics
- Timing middleware now records all requests to metrics store
- `agent_runner.py` — hooks on agent start, completion, and failure
- New endpoint: `GET /api/admin/metrics` — full metrics summary (admin only)
- New endpoint: `GET /api/metrics` — lightweight health metrics (any authenticated user)

### Step 10: Documentation & Deployment
- Created `docs/API.md` — full API reference with all endpoints, request/response schemas, error codes
- Created `CHANGELOG.md` — this file
- Updated `README.md` with refactoring summary
