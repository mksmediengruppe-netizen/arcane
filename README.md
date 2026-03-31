# ARCANE

**Autonomous AI Agency System — End-to-End Task Execution**

ARCANE is an autonomous AI system that operates as a full-service digital agency. It receives natural language instructions and delivers complete results: websites deployed to hosting, complex code written and tested, and digital assets generated.

> **Note:** ARCANE is currently undergoing an architectural migration. Please refer to [`docs/ARCHITECTURE_STATUS.md`](docs/ARCHITECTURE_STATUS.md) for the exact status of all components.

## Current Architecture (V2)

ARCANE is migrating to a **Scene-Driven Component Architecture** for website generation and a unified execution model.

- **Service Manager:** Runs via `systemd` (`arcane.service`).
- **Network:** Internal backend runs on port `8100`. Nginx handles SSL and reverse proxying.
- **Website Generation:** The default path is the **Scene Pipeline** (`scene_planner` -> `component_retriever` -> `scene_assembler`), which uses premium, responsive HTML/Tailwind/GSAP templates.
- **Artifacts:** All generated files are served from a unified `/workspace/{chat_id}/` contract.
- **Persistence:** Chat sessions and states are persisted to disk/PostgreSQL.

### Deprecated Architecture (V1)
*The following concepts are frozen or deprecated and are being phased out:*
- ❌ **Docker Workers:** The isolated "Hands" model is deprecated in favor of the unified agent loop.
- ❌ **From-Scratch Generation:** The giant `scene_plan_to_coder_prompt` fallback is frozen. All new development happens in the Scene Pipeline.
- ❌ **Port 8900:** The backend no longer runs on 8900.
- ❌ **DDG Search:** Replaced by more robust tool integrations.

## Key Features

**Intelligent Model Routing** — Uses tiered models (NANO/FAST/STANDARD/GENIUS/DEEP) with automatic escalation on failure and provider fallback chains.

**Self-Healing Loop** — Code is tested in a sandbox. If tests fail, the error is analyzed, and the code is automatically fixed (up to 5 iterations with tier escalation).

**Budget Control** — Per-project budget limits with real-time tracking. Four strategy presets: Economy ($0.08/landing), Balance ($0.40), Quality ($0.80), Maximum ($2.50).

**Rate Limiting** — Per-user, per-provider sliding window rate limiting prevents API quota exhaustion.

**Provider Fallback** — If OpenRouter is down, Claude requests automatically fall back to GPT-4.1 via OpenAI. Every model has a defined fallback chain.

## Project Structure

```
arcane/
├── api/             # FastAPI endpoints, SSE, auth, file serving
├── core/            # Orchestrator, agent loop, tool executor
├── shared/          # Unified LLM Client, Memory v9, Database models
├── workers/         # Scene assembler, component retriever
├── templates/       # Premium scenes (HTML/Tailwind/GSAP)
├── frontend/        # React/Vite frontend application
├── tests/           # Self-contained TestClient tests
└── docs/            # Architecture documentation
```

## Quick Start (Development)

```bash
cp .env.example .env
# Fill in API keys
pip install -r requirements.txt
# Run tests (self-contained)
pytest tests/
# Start server
uvicorn app:app --host 0.0.0.0 --port 8100
```

## Deployment (Production)

```bash
# On server (2.56.240.170)
cd /root/arcane
git pull origin main
sudo systemctl restart arcane
```

Domain: **https://arcaneai.ru**

## License

Proprietary. All rights reserved.
