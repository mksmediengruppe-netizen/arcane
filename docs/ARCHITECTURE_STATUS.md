# ARCANE Architecture Status

This document serves as the single source of truth for the current architectural state of the ARCANE project. It tracks the migration from the legacy "from-scratch" generation pipeline to the modern "scene-driven" component architecture.

**Last updated:** Phase 5 — 30 March 2026

## 1. Infra / Deployment
| Component | Status | Description | Owner | Next Action |
|---|---|---|---|---|
| **Service Manager** | Implemented | `systemd` (`arcane.service`) manages the backend process. | Core Team | None |
| **Port Configuration** | Implemented | Backend runs on port `8100` internally. | Core Team | Remove legacy `8900` references from docs. |
| **Reverse Proxy** | Implemented | Nginx handles SSL, routes `/api` to `8100`, and serves static files. | Core Team | None |
| **Docker Workers** | Deprecated | Legacy execution model. No longer the primary path. | Core Team | Remove from documentation. |

## 2. Auth / Ownership
| Component | Status | Description | Owner | Next Action |
|---|---|---|---|---|
| **Login Contract** | Implemented | Frontend and backend synchronized on `login_id` (email/username). | Core Team | None |
| **Chat Ownership** | Implemented | `_require_user_id()` and `_check_chat_ownership()` enforce strict isolation on `/status`, `/model`, `/feedback`, and SSE endpoints. | Core Team | Add automated security tests for ownership boundaries. |

## 3. Chats / Persistence
| Component | Status | Description | Owner | Next Action |
|---|---|---|---|---|
| **Session Storage** | Implemented | File-based persistence (`data/sessions.json`) prevents logout on restart. | Core Team | Migrate to PostgreSQL. |
| **Chat Store** | Partial | `_safe_db_write` is fully async, but data is still duplicated between in-memory dicts and PostgreSQL. | Core Team | Complete migration to pure PostgreSQL storage. |
| **Agent Status** | Implemented | Statuses (`coding`, `browsing`, `deploying`, `researching`) correctly mapped and sent via SSE. | Core Team | None |

## 4. Workspace / Artifacts
| Component | Status | Description | Owner | Next Action |
|---|---|---|---|---|
| **Public URL Contract** | Implemented | Unified to `/workspace/{chat_id}/`. Legacy `/projects/` and `/home/ubuntu/projects` paths have been removed. | Core Team | None |
| **File Downloads** | Implemented | ID-based routes (`/api/files/{id}/download`, `/preview`) are active. | Core Team | None |

## 5. Agent Loop
| Component | Status | Description | Owner | Next Action |
|---|---|---|---|---|
| **Task Queue** | Partial | Basic concurrency locks exist (`start_agent_for_chat`), but no robust message queue per chat. | Core Team | Implement Redis-based task queue. |
| **Rate Limiter** | Implemented | In-memory rate limiter with `_cleanup_expired()` garbage collection. | Core Team | Migrate to Redis for multi-process support. |

## 6. Landing Pipeline
| Component | Status | Description | Owner | Next Action |
|---|---|---|---|---|
| **Default Path** | Implemented | **Scene-driven pipeline** is the canonical default path. | Core Team | None |
| **Legacy Fallback** | **Gated** | The legacy `scene_plan_to_coder_prompt` path is behind `FEATURE_FLAG_LEGACY_CODER=false` in `.env`. Disabled by default. | Core Team | Remove legacy code entirely in Phase 6. |
| **Retry Logic** | Implemented | Scene pipeline features a robust 2-attempt retry with temperature scaling and delays. | Core Team | None |

## 7. Scene System
| Component | Status | Description | Owner | Next Action |
|---|---|---|---|---|
| **Scene Assembler** | Implemented | Handles slot resolution, CSS class deduplication, and SVG icon normalization. | Core Team | None |
| **Premium Scenes** | Implemented | All templates expanded to full responsive layouts with GSAP animations (60-140 lines). | Core Team | Add more niche-specific templates. |
| **Component Retriever** | **Implemented (v2)** | Metadata-based scoring engine: 19 templates catalogued with niches, styles, themes, complexity, and slot counts. Weighted scoring (niche 45%, style 30%, theme 25%) replaces static dict. `retrieve_best()` and `retrieve_templates()` APIs available. | Core Team | Add Qdrant vector embeddings for true RAG in Phase 6. |

## 8. Frontend Contracts
| Component | Status | Description | Owner | Next Action |
|---|---|---|---|---|
| **SSE Handling** | Implemented | `useChatsAPI.ts` correctly parses `agent_status`, `tool_executing`, and `title` events. | Core Team | None |
| **UI Artifacts** | Implemented | Empty placeholder messages show loading states (`isStreaming: true`). | Core Team | None |

## 9. Tests
| Component | Status | Description | Owner | Next Action |
|---|---|---|---|---|
| **Test Isolation** | Implemented | `conftest.py` uses `TestClient` for self-contained, in-process testing without requiring a live server. | Core Team | Expand test coverage for edge cases. |
| **E2E Tests** | Implemented | Fallback to `httpx` when `ARCANE_TEST_URL` is provided. | Core Team | Integrate into CI/CD pipeline. |
| **ComponentRetriever Tests** | **Implemented (P5)** | 16 dedicated tests validate scoring engine, niche matching, style filtering, fallback behavior, and edge cases. | Core Team | Add integration tests with scene_assembler. |
| **Test Dependencies** | **Fixed (P5)** | `requirements.txt` now includes `bcrypt>=4.1.0`, `aiohttp>=3.9.0`, `openai>=1.12.0` explicitly. | Core Team | None |

## 10. Feature Flags
| Flag | Default | Description |
|---|---|---|
| `FEATURE_FLAG_LEGACY_CODER` | `false` | Gates the legacy MultiConcept/Director → coder_prompt fallback path. When `false`, only the scene-driven pipeline is used. |
