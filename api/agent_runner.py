"""
ARCANE Agent Runner
Bridge between the Chat API and the Agent Loop.
Manages running agent instances per chat.
Stores messages in PostgreSQL, emits events via SSE.
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback
import uuid
from typing import Optional

from shared.utils.logger import get_logger

logger = get_logger("api.agent_runner")

# Active agent tasks per chat
_running_agents: dict[str, asyncio.Task] = {}
_cancel_flags: dict[str, bool] = {}
# FIX NEW-006: Per-chat message queue for sequential processing
_message_queues: dict[str, asyncio.Queue] = {}
_queue_processors: dict[str, asyncio.Task] = {}
_agent_instances: dict[str, object] = {}  # AgentLoop instances for resume
_agent_locks: dict[str, asyncio.Lock] = {}  # Per-chat locks to prevent race conditions
_task_queue_instance = None  # Lazy-initialized TaskQueue singleton




async def _rag_preprocess(user_message: str, config=None) -> str:
    """
    Variant 2: Pre-processing RAG pipeline.
    Analyzes the user message, detects if it's a website/landing page task,
    and if so, automatically runs search_design_inspiration and prepends
    the results as context. The agent sees references from the start.
    """
    # Quick check: is this a web design task?
    design_keywords = [
        "лендинг", "landing", "сайт", "website", "веб", "web", "страниц",
        "page", "дизайн", "design", "html", "homepage", "портфолио",
        "portfolio", "магазин", "shop", "store", "визитк", "card",
    ]
    msg_lower = user_message.lower()
    is_design_task = any(kw in msg_lower for kw in design_keywords)

    if not is_design_task:
        return user_message  # Not a design task, pass through

    logger.info("RAG pre-processing: detected design task, running search_design_inspiration")

    try:
        from workers.design_rag import get_design_rag
        rag = get_design_rag(config)

        # Build a smart query from the user message (first 200 chars, cleaned)
        # Extract key descriptive words
        import re as _re
        # Remove common Russian filler words
        clean = _re.sub(r'[^\w\s-]', ' ', msg_lower)
        # Take first 150 chars as query
        query = clean[:150].strip()

        results = await rag.search(
            query=query,
            min_tier="B",
            limit=6,
            diversity=True,
        )

        references = results.get("references", [])
        blueprint = results.get("suggested_blueprint", "")

        if not references:
            logger.info("RAG pre-processing: no references found, skipping")
            return user_message

        # Format references as context block
        ref_lines = []
        for i, ref in enumerate(references[:6], 1):
            title = ref.get("title", "Unknown")
            style = ref.get("design_style", "")
            colors = ref.get("primary_colors", [])
            typo = ref.get("typography_style", "")
            hero = ref.get("hero_type", "")
            layout = ref.get("layout_pattern", "")
            mood = ref.get("mood", "")
            tier = ref.get("quality_tier", "")
            score = ref.get("score", 0)

            ref_lines.append(
                f"  {i}. {title} (Tier {tier}, relevance {score:.2f})\n"
                f"     Style: {style} | Colors: {', '.join(colors[:4]) if colors else 'N/A'}\n"
                f"     Typography: {typo} | Hero: {hero} | Layout: {layout}\n"
                f"     Mood: {mood}"
            )

        context_block = (
            f"\n\n═══ DESIGN RESEARCH (auto-generated) ═══\n"
            f"Based on your request, here are the best matching premium design references:\n"
            f"Suggested blueprint: {blueprint}\n\n"
            + "\n".join(ref_lines)
            + f"\n\nUse these references as inspiration for color palettes, typography, "
            f"layout patterns, and overall mood. Synthesize the best elements — do NOT copy.\n"
            f"═══════════════════════════════════════════\n"
        )

        logger.info(
            f"RAG pre-processing: found {len(references)} references, "
            f"blueprint={blueprint}"
        )

        return user_message + context_block

    except Exception as e:
        logger.warning(f"RAG pre-processing failed (non-fatal): {e}")
        return user_message  # Graceful fallback — just pass the original message


async def start_agent_for_chat(
    chat_id: str,
    user_message: str,
    user_id: str = "",
    project_id: Optional[str] = None,
    model_strategy: str = "balance",
    premium_images: bool = False,
    design_check: bool = False,
    premium_review: bool = False,
) -> str:
    """Start the agent loop for a chat via the task queue.
    
    Returns the task_id. The worker pool will pick up and execute the task.
    Falls back to direct execution if Redis is unavailable.
    """
    from core.task_queue import TaskPayload, make_task_id
    
    task_id = make_task_id()
    payload = TaskPayload(
        task_id=task_id,
        chat_id=chat_id,
        user_message=user_message,
        user_id=user_id,
        project_id=project_id or "",
        model_strategy=model_strategy,
        premium_images=premium_images,
        design_check=design_check,
        premium_review=premium_review,
    )
    
    try:
        queue = await _get_task_queue()
        await queue.enqueue(payload)
        logger.info(f"Task {task_id} enqueued for chat {chat_id}")
        # S9: Record agent start
        try:
            from api.metrics import record_agent_started
            record_agent_started(chat_id)
        except Exception:
            pass
        return task_id
    except Exception as e:
        logger.warning(f"Redis queue unavailable, falling back to direct execution: {e}")
        return await _start_agent_direct(
            chat_id, user_message, user_id, project_id,
            model_strategy, premium_images, design_check, premium_review,
        )


async def _start_agent_direct(
    chat_id: str,
    user_message: str,
    user_id: str = "",
    project_id: Optional[str] = None,
    model_strategy: str = "balance",
    premium_images: bool = False,
    design_check: bool = False,
    premium_review: bool = False,
) -> str:
    """Original direct execution path (fallback when Redis unavailable)."""
    # PATCH-06: Per-chat lock to prevent race conditions
    if chat_id not in _agent_locks:
        _agent_locks[chat_id] = asyncio.Lock()
    async with _agent_locks[chat_id]:
        return await _start_agent_direct_inner(
            chat_id, user_message, user_id, project_id,
            model_strategy, premium_images, design_check, premium_review,
        )

async def _start_agent_direct_inner(
    chat_id: str,
    user_message: str,
    user_id: str = "",
    project_id: Optional[str] = None,
    model_strategy: str = "balance",
    premium_images: bool = False,
    design_check: bool = False,
    premium_review: bool = False,
) -> str:
    """Inner implementation of direct execution (called under lock)."""
    if chat_id in _running_agents and not _running_agents[chat_id].done():
        if chat_id not in _message_queues:
            _message_queues[chat_id] = asyncio.Queue(maxsize=10)
        try:
            _message_queues[chat_id].put_nowait({
                "user_message": user_message,
                "user_id": user_id,
                "project_id": project_id,
                "model_strategy": model_strategy,
                "premium_images": premium_images,
                "design_check": design_check,
                "premium_review": premium_review,
            })
            logger.info(f"Message queued for busy chat {chat_id}")
            if chat_id not in _queue_processors or _queue_processors[chat_id].done():
                _queue_processors[chat_id] = asyncio.create_task(_process_queue(chat_id))
            return f"direct-{chat_id}"
        except asyncio.QueueFull:
            logger.warning(f"Message queue full for chat {chat_id}")
    if chat_id in _running_agents:
        await stop_agent_for_chat(chat_id)
    elif chat_id in _agent_instances:
        _agent_instances.pop(chat_id, None)
    _cancel_flags[chat_id] = False
    task = asyncio.create_task(
        _run_agent(chat_id, user_message, user_id, project_id, model_strategy,
                   premium_images=premium_images, design_check=design_check,
                   premium_review=premium_review)
    )
    _running_agents[chat_id] = task
    try:
        from api.metrics import record_agent_started
        record_agent_started(chat_id)
    except Exception:
        pass
    return f"direct-{chat_id}"


async def _get_task_queue():
    """Get or create the task queue singleton."""
    global _task_queue_instance
    if _task_queue_instance is None:
        from core.task_queue import TaskQueue
        from config.settings import get_config
        cfg = get_config()
        _task_queue_instance = TaskQueue(redis_url=cfg.redis.url)
        await _task_queue_instance.connect()
    return _task_queue_instance


async def stop_agent_for_chat(chat_id: str, user_id: str = "") -> None:
    """Stop the agent for a chat and serialize state for later resume."""
    _cancel_flags[chat_id] = True

    # Serialize state before cancellation
    agent = _agent_instances.get(chat_id)
    if agent and hasattr(agent, "get_serializable_state"):
        try:
            state = agent.get_serializable_state()
            await _save_interrupted_task(chat_id, user_id, state, reason="user_stop")
            logger.info(f"Saved interrupted state for chat {chat_id}: iteration={state.get('iteration')}")
        except Exception as e:
            logger.warning(f"Failed to save interrupted state for {chat_id}: {e}")

    if chat_id in _running_agents:
        task = _running_agents[chat_id]
        if not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        del _running_agents[chat_id]

    _cancel_flags.pop(chat_id, None)
    _agent_instances.pop(chat_id, None)
    # FIX NEW-006: Clear message queue on explicit stop
    if chat_id in _message_queues:
        while not _message_queues[chat_id].empty():
            try:
                _message_queues[chat_id].get_nowait()
            except asyncio.QueueEmpty:
                break
        _message_queues.pop(chat_id, None)
    if chat_id in _queue_processors:
        _queue_processors[chat_id].cancel()
        _queue_processors.pop(chat_id, None)




async def _process_queue(chat_id: str) -> None:
    """FIX NEW-006: Process queued messages for a chat sequentially."""
    while chat_id in _message_queues and not _message_queues[chat_id].empty():
        # Wait for current agent to finish
        if chat_id in _running_agents:
            task = _running_agents[chat_id]
            if not task.done():
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        # Dequeue next message
        try:
            msg_data = _message_queues[chat_id].get_nowait()
        except asyncio.QueueEmpty:
            break
        logger.info(f"Processing queued message for chat {chat_id}")
        # Clean up previous agent instance
        _agent_instances.pop(chat_id, None)
        _cancel_flags[chat_id] = False
        # Start new agent for queued message
        task = asyncio.create_task(
            _run_agent(
                chat_id,
                msg_data["user_message"],
                msg_data.get("user_id", ""),
                msg_data.get("project_id"),
                msg_data.get("model_strategy", "balance"),
                premium_images=msg_data.get("premium_images", False),
                design_check=msg_data.get("design_check", False),
                premium_review=msg_data.get("premium_review", False),
            )
        )
        _running_agents[chat_id] = task
        try:
            await task
        except (asyncio.CancelledError, Exception) as e:
            logger.warning(f"Queued agent for {chat_id} failed: {e}")
    # Clean up empty queue
    _message_queues.pop(chat_id, None)
    _queue_processors.pop(chat_id, None)

async def resume_agent_for_chat(chat_id: str, user_response: str) -> None:
    """Resume a paused agent (waiting for user input or from saved state)."""
    agent = _agent_instances.get(chat_id)

    # If no in-memory agent, try to restore from DB
    if agent is None:
        agent = await _restore_interrupted_task(chat_id, user_response)
        if agent is None:
            raise RuntimeError(f"No paused agent found for chat {chat_id}")
        _agent_instances[chat_id] = agent

    _cancel_flags[chat_id] = False
    task = asyncio.create_task(_resume_agent(chat_id, agent, user_response))
    _running_agents[chat_id] = task


async def _run_agent(
    chat_id: str,
    user_message: str,
    user_id: str,
    project_id: Optional[str],
    model_strategy: str,
    premium_images: bool = False,
    design_check: bool = False,
    premium_review: bool = False,
) -> None:
    """Execute the agent loop for a user message."""
    from api.sse import SSEEmitter
    from core.agent_loop import AgentLoop
    from core.tool_executor import ToolExecutor
    from core.tool_registry import ToolRegistry
    from shared.llm.client import UnifiedLLMClient
    from shared.llm.router import ModelRouter
    from config.settings import get_config

    config = get_config()
    emitter = SSEEmitter(chat_id)

    try:
        await emitter.status("thinking", "Analyzing your request...")

        # Initialize components
        llm_client = UnifiedLLMClient(config)
        
        # Budget limit from top-level config
        budget_limit = getattr(config, "default_budget_limit", 5.0)

        # A4: Auto-strategy — if user didn't choose, classify task and pick
        effective_strategy = model_strategy
        if model_strategy == "auto" or not model_strategy:
            try:
                from core.planner import Planner
                _tmp_router = ModelRouter(
                    client=llm_client, strategy="economy", budget_limit=budget_limit,
                )
                _planner = Planner(router=_tmp_router)
                classification = await _planner.classify_task(
                    user_message, user_id=user_id, project_id=project_id or chat_id,
                )
                complexity = classification.get("complexity", "moderate")
                _COMPLEXITY_TO_STRATEGY = {
                    "trivial": "economy",
                    "simple": "economy",
                    "moderate": "balance",
                    "complex": "quality",
                    "expert": "maximum",
                }
                effective_strategy = _COMPLEXITY_TO_STRATEGY.get(complexity, "balance")
                logger.info(
                    f"Auto-strategy: complexity={complexity} -> strategy={effective_strategy}"
                )
                await emitter.status(
                    "thinking",
                    f"Task classified as {complexity}, using {effective_strategy} strategy",
                )
            except Exception as e:
                logger.warning(f"Auto-strategy classification failed: {e}, defaulting to balance")
                effective_strategy = "balance"

        # INTENT CLASSIFIER v2: Use LLM to understand TRUE user intent
        # Replaces brittle keyword matching — understands context like Manus does
        try:
            from core.intent_classifier import classify_intent, is_web_design_intent, get_strategy_for_intent
            _intent_result = await classify_intent(llm_client, user_message, chat_id=chat_id)
            _intent = _intent_result.get("intent", "general")
            logger.info(f"Intent classified: {_intent} (confidence={_intent_result.get('confidence', 0):.2f})")
            # Only enable design pipeline for GENUINE web_design tasks
            if is_web_design_intent(_intent_result) and not design_check:
                effective_strategy = get_strategy_for_intent(_intent_result, effective_strategy)
                design_check = True
                logger.info(f"Web design intent detected → strategy={effective_strategy}, design_check=True")
            elif _intent == "devops" and design_check is False:
                # Explicitly ensure devops tasks never get design pipeline
                design_check = False
                logger.info("DevOps intent detected → design pipeline disabled")
        except Exception as _ie:
            logger.warning(f"Intent classifier error: {_ie}, using keyword fallback")
            # Fallback: conservative keyword check (only clear web design terms)
            _web_only_kw = ["лендинг", "landing page", "одностраничн", "homepage"]
            if any(kw in user_message.lower() for kw in _web_only_kw):
                design_check = True
                effective_strategy = "quality"
        
        router = ModelRouter(
            client=llm_client,
            strategy=effective_strategy,
            budget_limit=budget_limit,
        )
        tool_registry = ToolRegistry()
        
        # Create workspace directory for this project
        # P1-1 FIX: Use canonical workspace root from settings
        workspace_dir = config.get_project_dir(project_id or chat_id)
        
        tool_executor = ToolExecutor(
            registry=tool_registry,
            project_dir=workspace_dir,
        )

        # Create agent loop
        agent = AgentLoop(
            llm_client=llm_client,
            router=router,
            tool_executor=tool_executor,
            event_emitter=_make_emitter(emitter),
            project_id=project_id or chat_id,
            user_id=user_id,
            max_iterations=50,
            max_consecutive_errors=5,
            premium_images=premium_images,
            design_check=design_check,
            premium_review=premium_review,
        )

        # Store instance for potential resume
        _agent_instances[chat_id] = agent

        # Variant 2: Pre-process with RAG (auto-inject design references)
        # Only run RAG for genuine web design tasks — not for devops/server tasks
        if design_check:
            enriched_message = await _rag_preprocess(user_message, config)
        else:
            enriched_message = user_message

        # INTELLIGENCE FIX: Load key facts from chat history into scratchpad
        # So the agent remembers SSH creds, file paths, etc. across messages
        try:
            from api.chat_store import get_messages as _get_stored_msgs
            import re as _re
            _prev_msgs = _get_stored_msgs(chat_id)
            if _prev_msgs and len(_prev_msgs) > 1:
                for _pm in _prev_msgs:
                    if _pm.get("role") == "user":
                        _content = _pm.get("content", "")
                        _ip_match = _re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', _content)
                        _pass_match = _re.search(r'(?:пароль|password|pass)[:\s]+(\S+)', _content, _re.IGNORECASE)
                        _login_match = _re.search(r'(?:логин|login|user)[:\s]+(\S+)', _content, _re.IGNORECASE)
                        if _ip_match:
                            agent._scratchpad.update("server_ip", _ip_match.group(1))
                        if _pass_match:
                            agent._scratchpad.update("server_password", _pass_match.group(1))
                        if _login_match:
                            agent._scratchpad.update("server_login", _login_match.group(1))
                logger.info(f"Intelligence: loaded context from {len(_prev_msgs)} previous messages")
        except Exception as _hist_err:
            logger.debug(f"History context loading failed (non-fatal): {_hist_err}")
        
        # Run the agent
        result = await agent.run(enriched_message)

        # Store result in DB
        await _store_result(chat_id, user_id, result, emitter)

    except asyncio.CancelledError:
        logger.info(f"Agent for chat {chat_id} was cancelled")
        await emitter.status("idle", "Task cancelled by user")

    except Exception as e:
        logger.error(f"Agent error for chat {chat_id}: {e}\n{traceback.format_exc()}")
        await emitter.message(f"Error: {str(e)}", "error")
        await emitter.status("idle", "Error occurred")

    finally:
        _running_agents.pop(chat_id, None)
        _cancel_flags.pop(chat_id, None)
        # FIX: Clean up agent instance to prevent stale context on next task
        _agent_instances.pop(chat_id, None)
        # FIX-GUARANTEED: Always update in-memory status to idle when task ends
        try:
            from api.chat_store import get_chat as _get_chat_fn, update_chat as _final_update
            _chat_data = _get_chat_fn(chat_id)
            if _chat_data and _chat_data.get("status") == "working":
                await _final_update(chat_id, status="idle")
                logger.info(f"FINALLY-FIX: Set chat {chat_id} status to idle")
        except Exception as _fe:
            logger.warning(f"FINALLY-FIX failed: {_fe}")


async def _resume_agent(chat_id: str, agent, user_response: str) -> None:
    """Resume a paused agent with user's response."""
    from api.sse import SSEEmitter

    emitter = SSEEmitter(chat_id)

    try:
        await emitter.status("thinking", "Resuming with your input...")
        result = await agent.resume(user_response)
        await _store_result(chat_id, "", result, emitter)

    except asyncio.CancelledError:
        logger.info(f"Resumed agent for chat {chat_id} was cancelled")
        await emitter.status("idle", "Task cancelled")

    except Exception as e:
        logger.error(f"Resume error for chat {chat_id}: {e}\n{traceback.format_exc()}")
        await emitter.message(f"Error: {str(e)}", "error")
        await emitter.status("idle", "Error occurred")

    finally:
        _running_agents.pop(chat_id, None)
        _cancel_flags.pop(chat_id, None)
        # FIX: Clean up agent instance to prevent stale context on next task
        _agent_instances.pop(chat_id, None)
        # FIX-GUARANTEED: Always update in-memory status to idle when task ends
        try:
            from api.chat_store import get_chat as _get_chat_fn2, update_chat as _final_update2
            _chat_data2 = _get_chat_fn2(chat_id)
            if _chat_data2 and _chat_data2.get("status") == "working":
                await _final_update2(chat_id, status="idle")
                logger.info(f"FINALLY-FIX-RESUME: Set chat {chat_id} status to idle")
        except Exception as _fe2:
            logger.warning(f"FINALLY-FIX-RESUME failed: {_fe2}")


async def _store_result(chat_id: str, user_id: str, result: dict, emitter) -> None:
    """Store agent result and notify frontend."""
    status = result.get("status", "completed")
    cost = result.get("total_cost", 0.0)
    iterations = result.get("iterations", 0)
    artifacts = result.get("artifacts", [])
    duration = result.get("duration_seconds", 0.0)

    # Emit final status
    # S9: Record agent completion metrics
    try:
        from api.metrics import record_agent_completed, record_agent_failed
        if status == "completed":
            record_agent_completed(chat_id, cost=cost)
        else:
            record_agent_failed(chat_id)
    except Exception:
        pass
    if status == "completed":
        await emitter.task_complete(
            summary=f"Task completed in {iterations} iterations (${cost:.4f})",
            artifacts=artifacts,
        )
    elif status == "waiting_user":
        await emitter.status("waiting_user", "Waiting for your input...")
        # Emit done to close SSE stream — agent is paused, not running
        await emitter.task_complete(
            summary=f"Waiting for user input after {iterations} iterations",
            artifacts=artifacts,
        )
    elif status == "budget_exceeded":
        await emitter.message(
            f"Budget limit reached (${cost:.2f} spent). Please increase the budget to continue.",
            "error",
        )
        await emitter.task_complete(
            summary=f"Budget exceeded after {iterations} iterations",
            artifacts=artifacts,
        )
    else:
        await emitter.status("idle", f"Task ended: {status}")
        # Emit task_complete to close SSE stream for any terminal status
        await emitter.task_complete(
            summary=f"Task ended with status: {status} ({iterations} iterations)",
            artifacts=artifacts,
        )

    # Persist steps AND status/cost to in-memory chat store for frontend retrieval
    # FIX: Also update status and total_cost in memory so GET /api/chats/{id} returns correct data
    # even when SSE client is disconnected (e.g. API-triggered tasks)
    try:
        from api.chat_store import update_chat as _update_chat, add_message as _add_message
        steps = emitter.get_steps() if hasattr(emitter, "get_steps") else []
        update_fields = {
            "status": "idle" if status == "completed" else status,
            "total_cost": cost,
        }
        if steps:
            update_fields["steps"] = steps
        await _update_chat(chat_id, **update_fields)
        logger.info(f"In-memory store updated for {chat_id}: status={update_fields['status']}, cost={cost}")
        # FIX: Also store assistant result message in memory if not already there
        # This ensures GET /api/chats/{id} returns the result even without SSE
        summary_text = result.get("summary", f"Task completed in {iterations} iterations")
        if summary_text:
            try:
                await _add_message(chat_id, role="assistant", content=summary_text)
                logger.info(f"Assistant message stored for {chat_id}")
            except Exception as msg_err:
                logger.warning(f"Failed to store assistant message: {msg_err}")
    except Exception as e:
        logger.warning(f"Failed to store steps/status: {e}")
    # Try to persist to database
    try:
        await _persist_to_db(chat_id, user_id, result)
    except Exception as e:
        logger.warning(f"Failed to persist result to DB: {e}")

    # Send Telegram notification (non-blocking)
    asyncio.create_task(
        _send_telegram_notification(user_id, status, cost, duration, iterations, artifacts)
    )


async def _persist_to_db(chat_id: str, user_id: str, result: dict) -> None:
    """Persist agent result to PostgreSQL."""
    try:
        from config.settings import get_config
        from shared.models.database import get_session_factory, Chat

        config = get_config()
        factory = get_session_factory(config.db.url)

        async with factory() as session:
            from sqlalchemy import update
            # Update chat status and cost
            await session.execute(
                update(Chat)
                .where(Chat.id == chat_id)
                .values(
                    status=result.get("status", "idle"),
                    total_cost=Chat.total_cost + result.get("total_cost", 0.0),
                    total_tokens=Chat.total_tokens + result.get("total_tokens", 0),
                    updated_at=__import__("datetime").datetime.utcnow(),
                )
            )
            await session.commit()
    except Exception as e:
        logger.debug(f"DB persist skipped: {e}")


def _make_emitter(sse_emitter):
    """Create an async event emitter function for the AgentLoop."""
    async def emit(event: dict):
        event_type = event.get("type", "status")
        if event_type == "thinking":
            await sse_emitter.status("thinking", f"Iteration {event.get('iteration', '?')}...")
        elif event_type == "tool_executing":
            step_id = await sse_emitter.tool_call(event.get("tool", "unknown"), event)
            # FIX 1: Store step_id in the mutable container passed from agent_loop
            container = event.get("_step_id_container")
            if isinstance(container, dict):
                container["step_id"] = step_id
        elif event_type == "tool_completed":
            await sse_emitter.tool_result(
                event.get("tool", "unknown"),
                event.get("result_preview", ""),
                event.get("success", True),
                step_id=event.get("step_id"),  # FIX 1: read explicit step_id from event
            )
        elif event_type == "tool_error":
            await sse_emitter.tool_result(
                event.get("tool", "unknown"),
                event.get("error", "Unknown error"),
                False,
                step_id=event.get("step_id"),  # FIX 1: read explicit step_id from event
            )
        elif event_type == "cost_update":
            await sse_emitter.cost_update(
                total_cost=event.get("total_cost", 0.0),
                breakdown={
                    "iteration_cost": event.get("iteration_cost", 0.0),
                    "input_tokens": event.get("input_tokens", 0),
                    "output_tokens": event.get("output_tokens", 0),
                    "budget_remaining": event.get("budget_remaining", 0.0),
                },
            )
        elif event_type == "model_info":
            await sse_emitter.model_info(
                model_id=event.get("model_id", "unknown"),
                provider=event.get("provider", "unknown"),
                tier=event.get("tier", ""),
            )
        elif event_type == "plan_update":
            await sse_emitter.plan_update(
                phases=event.get("phases", []),
                current_phase_id=event.get("current_phase_id", 1),
                goal=event.get("goal", ""),
            )
        elif event_type == "task_started":
            await sse_emitter.status("thinking", "Task started...")
        elif event_type == "task_completed":
            pass  # Handled in _store_result
        elif event_type == "error":
            await sse_emitter.message(event.get("message", "Error"), "error")
        elif event_type == "budget_exceeded":
            await sse_emitter.message(event.get("message", "Budget exceeded"), "error")
        elif event_type == "design_report":
            # G3: Forward design judge results to frontend
            await sse_emitter.message(
                f"Design Score: {event.get('overall_score', 'N/A')}/10\n"
                f"Verdict: {event.get('verdict', '')}\n"
                f"Strengths: {', '.join(event.get('strengths', []))}\n"
                f"Issues: {', '.join(event.get('issues', []))}",
                "design_report",
            )
        elif event_type == "phase_change":
            # E2: Forward phase changes to frontend
            await sse_emitter.status(
                event.get("phase", "working"),
                f"{event.get('phase', 'working').upper()} (iteration {event.get('iteration', '?')})",
            )
        else:
            await sse_emitter.status("working", event.get("message", str(event_type)))
    return emit


def get_active_agents() -> dict[str, dict]:
    """Get all active agents (local + Redis tracked)."""
    result = {}
    # Local agents (fallback mode)
    for chat_id, task in _running_agents.items():
        if not task.done():
            result[chat_id] = {
                "chat_id": chat_id,
                "status": "running",
                "source": "local",
            }
    # Try Redis pool info
    try:
        from core.worker_pool import _pool_instance
        if _pool_instance and _pool_instance.is_running:
            for w in _pool_instance.get_workers_info():
                if w["status"] == "busy" and w["current_chat_id"]:
                    result[w["current_chat_id"]] = {
                        "chat_id": w["current_chat_id"],
                        "task_id": w["current_task_id"],
                        "worker": w["name"],
                        "status": "running",
                        "source": "pool",
                    }
    except Exception:
        pass
    return result


def get_agent_state(chat_id: str) -> Optional[dict]:
    """Get state of a specific agent."""
    agent = _agent_instances.get(chat_id)
    if agent and hasattr(agent, "get_state"):
        return agent.get_state()
    return None


async def _save_interrupted_task(
    chat_id: str, user_id: str, state: dict, reason: str = "user_stop"
) -> None:
    """Save interrupted agent state to DB for later resume."""
    try:
        from config.settings import get_config
        from shared.models.database import get_session_factory, InterruptedTask
        from sqlalchemy import update
        import datetime

        config = get_config()
        factory = get_session_factory(config.db.url)

        async with factory() as session:
            # Deactivate any previous interrupted tasks for this chat
            await session.execute(
                update(InterruptedTask)
                .where(InterruptedTask.chat_id == chat_id, InterruptedTask.is_active == True)
                .values(is_active=False)
            )

            # Save new interrupted task
            interrupted = InterruptedTask(
                chat_id=chat_id,
                user_id=user_id,
                agent_state=state,
                messages_snapshot=state.get("messages", []),
                iteration=state.get("iteration", 0),
                total_cost=state.get("total_cost", 0.0),
                budget_remaining=state.get("budget_remaining", 0.0),
                reason=reason,
                expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=7),
            )
            session.add(interrupted)
            await session.commit()
            logger.info(f"Interrupted task saved: chat={chat_id}, reason={reason}")
    except Exception as e:
        logger.warning(f"Failed to save interrupted task: {e}")


async def _restore_interrupted_task(chat_id: str, user_message: str) -> Optional[object]:
    """Restore an interrupted agent from DB."""
    try:
        from config.settings import get_config
        from shared.models.database import get_session_factory, InterruptedTask
        from core.agent_loop import AgentLoop
        from core.tool_executor import ToolExecutor
        from core.tool_registry import ToolRegistry
        from shared.llm.client import UnifiedLLMClient
        from shared.llm.router import ModelRouter
        from sqlalchemy import select, update
        import datetime

        config = get_config()
        factory = get_session_factory(config.db.url)

        async with factory() as session:
            result = await session.execute(
                select(InterruptedTask)
                .where(
                    InterruptedTask.chat_id == chat_id,
                    InterruptedTask.is_active == True,
                    InterruptedTask.expires_at > datetime.datetime.utcnow(),
                )
                .order_by(InterruptedTask.created_at.desc())
                .limit(1)
            )
            interrupted = result.scalar_one_or_none()
            if not interrupted:
                return None

            state = interrupted.agent_state
            user_id = interrupted.user_id

            # Mark as resumed
            await session.execute(
                update(InterruptedTask)
                .where(InterruptedTask.id == interrupted.id)
                .values(is_active=False, resumed_at=datetime.datetime.utcnow())
            )
            await session.commit()

        # Rebuild agent with restored state
        llm_client = UnifiedLLMClient(config)
        budget_limit = state.get("budget_remaining", 5.0)
        router = ModelRouter(
            client=llm_client,
            strategy="balance",
            budget_limit=budget_limit,
        )
        tool_registry = ToolRegistry()
        # P1-1 FIX: Use canonical workspace root from settings
        workspace_dir = config.get_project_dir(chat_id)
        tool_executor = ToolExecutor(registry=tool_registry, project_dir=workspace_dir)

        from api.sse import SSEEmitter
        emitter = SSEEmitter(chat_id)

        agent = AgentLoop(
            llm_client=llm_client,
            router=router,
            tool_executor=tool_executor,
            event_emitter=_make_emitter(emitter),
            project_id=chat_id,
            user_id=user_id,
            max_iterations=50,
            max_consecutive_errors=5,
        )

        # Restore state
        agent.restore_state(state)
        logger.info(f"Restored interrupted agent for chat {chat_id}: iteration={state.get('iteration')}")
        return agent

    except Exception as e:
        logger.warning(f"Failed to restore interrupted task for {chat_id}: {e}")
        return None


async def _send_telegram_notification(
    user_id: str,
    status: str,
    cost: float,
    duration: float,
    iterations: int,
    artifacts: list,
) -> None:
    """Send Telegram notification about task completion (if user has linked Telegram)."""
    try:
        from workers.telegram_notifier import get_telegram_notifier

        notifier = get_telegram_notifier()
        if not notifier.is_configured:
            return

        # Look up user's Telegram chat_id from DB
        telegram_chat_id = await _get_user_telegram_id(user_id)
        if not telegram_chat_id:
            return

        summary = f"Completed in {iterations} iterations"

        if status == "completed":
            await notifier.notify_task_complete(
                chat_id=telegram_chat_id,
                task_summary=summary,
                cost_usd=cost,
                duration_seconds=duration,
                artifacts=artifacts,
            )
        elif status in ("error", "budget_exceeded"):
            await notifier.notify_task_failed(
                chat_id=telegram_chat_id,
                task_summary=summary,
                error_message=f"Task ended with status: {status}",
                cost_usd=cost,
            )

    except Exception as e:
        logger.debug(f"Telegram notification skipped: {e}")


async def _get_user_telegram_id(user_id: str) -> Optional[str]:
    """Get user's Telegram chat_id from the database."""
    try:
        from config.settings import get_config
        from shared.models.database import get_session_factory, User
        from sqlalchemy import select

        config = get_config()
        factory = get_session_factory(config.db.url)

        async with factory() as session:
            result = await session.execute(
                select(User.telegram_chat_id).where(User.id == user_id)
            )
            row = result.scalar_one_or_none()
            return row if row else None
    except Exception:
        return None
