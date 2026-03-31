# ARCANE API Documentation

> Version: 1.0.0 | Base URL: `https://arcaneai.ru`

## Authentication

All protected endpoints require either:
- **Session cookie**: `arcane_session` (set after login)
- **Bearer token**: `Authorization: Bearer <jwt_token>` (returned at login/register)

Admin endpoints additionally require the user to have `role = "admin"`.

---

## Auth Endpoints

### `POST /api/auth/register`
Register a new user.

**Rate limit**: 10 req/min per IP

**Request body**:
```json
{
  "username": "string",
  "password": "string (min 8 chars)",
  "email": "string (optional)"
}
```

**Response** `200`:
```json
{
  "ok": true,
  "user": {"id": "uuid", "username": "...", "email": "...", "role": "user"},
  "token": "jwt_token"
}
```

---

### `POST /api/auth/login`
Login with username and password.

**Rate limit**: 10 req/min per IP

**Request body**:
```json
{"username": "string", "password": "string"}
```

**Response** `200`:
```json
{
  "ok": true,
  "user": {"id": "uuid", "username": "...", "role": "user"},
  "token": "jwt_token"
}
```

---

### `POST /api/auth/logout`
Logout and invalidate session cookie.

**Response** `200`: `{"ok": true}`

---

### `GET /api/auth/me`
Get current authenticated user info.

**Auth required**: Yes

**Response** `200`:
```json
{
  "id": "uuid",
  "username": "string",
  "email": "string",
  "role": "user|admin",
  "model_strategy": "economy|balance|quality|maximum",
  "budget_limit": 5.0
}
```

---

## Chat Endpoints

### `GET /api/chats`
List all chats for the current user.

**Auth required**: Yes

**Response** `200`:
```json
{
  "chats": [
    {
      "id": "uuid",
      "title": "string",
      "status": "idle|thinking|executing|completed|error",
      "created_at": "ISO8601",
      "updated_at": "ISO8601",
      "total_cost": 0.0,
      "total_tokens": 0
    }
  ]
}
```

---

### `POST /api/chats`
Create a new chat.

**Auth required**: Yes

**Request body**:
```json
{
  "title": "string (optional)",
  "model_strategy": "economy|balance|quality|maximum (optional)"
}
```

**Response** `200`: `{"id": "uuid", "title": "...", "status": "idle"}`

---

### `GET /api/chats/{chat_id}`
Get a specific chat by ID.

**Auth required**: Yes (must own the chat)

**Response** `200`: Chat object with full details.

---

### `DELETE /api/chats/{chat_id}`
Delete a chat and all its messages.

**Auth required**: Yes (must own the chat)

**Response** `200`: `{"ok": true}`

---

### `PATCH /api/chats/{chat_id}`
Rename a chat.

**Auth required**: Yes (must own the chat)

**Request body**: `{"title": "new title"}`

**Response** `200`: `{"ok": true, "title": "new title"}`

---

### `POST /api/chats/{chat_id}/message`
Send a message and receive streaming SSE response.

**Auth required**: Yes (must own the chat)

**Rate limit**: 30 req/min per user

**Request body**:
```json
{
  "content": "string",
  "model_strategy": "economy|balance|quality|maximum (optional)"
}
```

**Response**: `text/event-stream` with events:
- `data: {"type": "thinking", "content": "..."}`
- `data: {"type": "tool_call", "tool": "...", "args": {...}}`
- `data: {"type": "tool_result", "result": "..."}`
- `data: {"type": "message", "content": "..."}`
- `data: {"type": "done", "status": "completed|error", "cost": 0.0}`

---

### `GET /api/chats/{chat_id}/messages`
Get all messages in a chat.

**Auth required**: Yes (must own the chat)

**Response** `200`:
```json
{
  "messages": [
    {
      "id": "uuid",
      "role": "user|assistant|system|tool",
      "content": "string",
      "created_at": "ISO8601",
      "model_used": "string",
      "tokens_input": 0,
      "tokens_output": 0,
      "cost": 0.0
    }
  ]
}
```

---

### `GET /api/chats/{chat_id}/files`
List files in a chat's workspace.

**Auth required**: Yes (must own the chat)

**Response** `200`:
```json
{
  "files": [
    {
      "name": "filename.py",
      "path": "/workspace/...",
      "size": 1024,
      "modified": "ISO8601"
    }
  ]
}
```

---

## File Endpoints

### `GET /api/files`
List files in the current user's workspace.

**Auth required**: Yes

**Query params**: `chat_id` (optional, filter by chat workspace)

---

### `GET /api/files/download`
Download a file from the workspace.

**Auth required**: Yes

**Query params**: `path` (required)

---

### `GET /api/files/preview`
Preview a file's content.

**Auth required**: Yes

**Query params**: `path` (required)

---

## Models & Templates

### `GET /api/models`
List available AI models.

**Response** `200`:
```json
{
  "models": [
    {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "tier": "NANO"},
    {"id": "gpt-4o", "name": "GPT-4o", "tier": "STANDARD"}
  ]
}
```

---

### `GET /api/templates`
List task templates.

**Response** `200`: `{"templates": [...]}`

---

## Rate Limiting

### `GET /api/rate-limit/status`
Get current rate limit status for the authenticated user.

**Auth required**: Yes

**Response** `200`:
```json
{
  "limits": {
    "auth": {"limit": 10, "used": 2, "remaining": 8, "window_seconds": 60},
    "message": {"limit": 30, "used": 5, "remaining": 25, "window_seconds": 60},
    "default": {"limit": 120, "used": 10, "remaining": 110, "window_seconds": 60}
  }
}
```

---

## Monitoring

### `GET /health`
Full health check of all components.

**Response** `200`:
```json
{
  "status": "healthy|degraded|partial",
  "version": "1.0.0",
  "components": {
    "postgresql": {"status": "healthy"},
    "redis": {"status": "healthy"},
    "openai": {"status": "healthy", "models_available": 42}
  },
  "check_duration_ms": 120
}
```

---

### `GET /api/metrics`
Lightweight metrics for monitoring.

**Auth required**: Yes

**Response** `200`:
```json
{
  "uptime_seconds": 3600,
  "total_requests": 1500,
  "total_errors": 12,
  "error_rate_pct": 0.8,
  "agents_running": 2,
  "agents_completed": 45,
  "agents_failed": 3,
  "total_cost_usd": 1.2345
}
```

---

## Admin Endpoints

All admin endpoints require `role = "admin"`.

### `GET /api/admin/stats`
System-wide statistics.

### `GET /api/admin/metrics`
Full metrics summary with latency percentiles.

### `GET /api/admin/users`
List all users.

### `GET /api/admin/workspaces`
List all user workspaces with sizes.

### `DELETE /api/admin/workspace/{chat_id}`
Delete a specific chat workspace.

---

## Error Responses

All errors return a consistent JSON structure:

```json
{
  "ok": false,
  "error": "Human-readable error message",
  "status_code": 404
}
```

| Status | Meaning |
|--------|---------|
| `400` | Bad request / validation error |
| `401` | Not authenticated |
| `403` | Forbidden (not owner or not admin) |
| `404` | Resource not found |
| `409` | Conflict (e.g., username taken) |
| `429` | Rate limit exceeded |
| `500` | Internal server error |

---

## Response Headers

| Header | Description |
|--------|-------------|
| `X-Process-Time-Ms` | Request processing time in milliseconds |
| `X-Request-ID` | Unique request identifier for tracing |
| `Retry-After` | Seconds to wait before retrying (on 429) |
