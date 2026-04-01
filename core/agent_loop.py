"""
ARCANE Agent Loop
The autonomous execution engine. Implements the Manus-style agent loop:
  1. Analyze context — understand user intent and current state
  2. Think — reason about the next action
  3. Select tool — choose the right tool via function calling
  4. Execute — run the tool in the sandbox
  5. Observe — append result to context
  6. Iterate — repeat until task is complete
  7. Deliver — send results to user

Key principles:
  - MUST always respond with a tool call (never raw text)
  - One tool call per iteration (no parallel calls)
  - Self-healing on errors (retry, escalate tier, try alternative)
  - Budget-aware (stop before exceeding limits)
  - Streaming status updates via WebSocket
"""

from __future__ import annotations

import asyncio
import time
import traceback
from enum import Enum
from typing import Any, Callable, Optional

from shared.llm.client import BadRequestError, BudgetExceededError, ProviderUnavailableError, UnifiedLLMClient
from shared.prompt_templates import detect_language, get_prompt_section, build_full_prompt
from shared.llm.router import ModelRouter
from shared.llm.usage_tracker import UsageTracker, get_usage_tracker
from shared.models.schemas import (
    AgentState,
    LLMRequest,
    LLMResponse,
    ProjectState,
    TaskPhase,
    Tier,
    ToolCall,
)
from shared.utils.error_analyzer import analyze_error, is_critical, should_escalate_tier
from shared.utils.logger import get_logger, log_with_data
from core.context_manager import Scratchpad, ContextCompactor, GoalAnchor
from core.user_profile import get_user_preferences, preferences_to_prompt, extract_preferences, save_preferences

# FrontendDirector — separates creative direction from coding
try:
    from workers.frontend_director import FrontendDirector
    _director_available = True
except ImportError:
    _director_available = False

# MultiConcept + DesignRanker — generate and rank multiple concepts
try:
    from workers.multi_concept import generate_and_rank as _multi_concept_generate
    _multi_concept_available = True
except ImportError:
    _multi_concept_available = False

# VisualRAG v2 — screenshot-enhanced references
try:
    from workers.visual_rag_v2 import get_visual_rag
    _visual_rag_available = True
except ImportError:
    _visual_rag_available = False

# Scene-Driven Code-RAG pipeline — premium HTML assembly from templates
try:
    from workers.scene_planner import plan_page as _scene_plan_page
    from workers.scene_assembler import assemble_page as _scene_assemble_page
    _scene_driven_available = True
except ImportError:
    _scene_driven_available = False
# Judge Panel v3 — 5 specialized judges
try:
    from workers.judge_panel import get_judge_panel, take_screenshots as _take_judge_screenshots
    _judge_panel_available = True
except ImportError:
    _judge_panel_available = False

# Frontend Finisher — applies judge fixes
try:
    from workers.frontend_finisher import get_frontend_finisher
    _finisher_available = True
except ImportError:
    _finisher_available = False

# Design Intelligence — Scene Library, Anti-Clone, Trust Engine
try:
    from workers.design_intelligence import get_scene_library, get_anti_clone, get_trust_engine
    _design_intel_available = True
except ImportError:
    _design_intel_available = False

# Memory v9
try:
    from shared.memory.engine import SuperMemoryEngine
    _memory_available = True
except ImportError:
    _memory_available = False

logger = get_logger("core.agent_loop")


class LoopStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    BUDGET_EXCEEDED = "budget_exceeded"
    WAITING_USER = "waiting_user"



# ─── Intent → Complexity mapping (PATCH-09) ──────────────────────
INTENT_COMPLEXITY: dict[str, dict] = {
    "complex": {
        "markers": [
            "сайт", "лендинг", "landing", "website", "приложение", "application",
            "dashboard", "полный", "full", "complete", "redesign", "migrate",
            "магазин", "shop", "store", "портал", "portal", "платформ", "platform",
            "многостранич", "multi-page", "fullstack", "фулстек",
        ],
        "max_iterations": 50,
    },
    "moderate": {
        "markers": [
            "настрой", "установи", "setup", "configure", "integrate", "deploy",
            "автоматиз", "automat", "workflow", "api", "исправ", "fix", "bug",
            "добав", "add", "feature", "обнов", "update", "refactor",
        ],
        "max_iterations": 30,
    },
    "simple": {
        "markers": [
            "проверь", "check", "status", "покажи", "show", "найди", "find",
            "скажи", "tell", "объясни", "explain", "помоги", "help", "что такое",
            "what is", "как", "how", "список", "list",
        ],
        "max_iterations": 15,
    },
}

class AgentLoop:
    """
    The main autonomous execution engine.

    Receives a user message, builds a plan, and iteratively executes
    tool calls until the task is complete or budget is exhausted.
    """

    def __init__(
        self,
        llm_client: UnifiedLLMClient,
        router: ModelRouter,
        tool_executor: Any,  # ToolExecutor instance
        event_emitter: Optional[Callable] = None,
        project_id: str = "",
        user_id: str = "",
        max_iterations: int = 25,  # FIX NEW-007: Raised from 20
        max_consecutive_errors: int = 5,
        premium_images: bool = False,
        design_check: bool = False,
        premium_review: bool = False,
    ):
        self._client = llm_client
        self._router = router
        self._tool_executor = tool_executor
        self._emit = event_emitter or (lambda *a, **kw: None)
        self._project_id = project_id
        self._user_id = user_id
        self._max_iterations = max_iterations
        self._max_consecutive_errors = max_consecutive_errors
        # FIX: Define adaptive iteration limits for task complexity
        self._adaptive_iteration_limits = {
            "complex": 50,
            "moderate": 30,
            "simple": 15,
        }
        self._tracker = get_usage_tracker()

        # State
        self._messages: list[dict] = []
        self._status = LoopStatus.RUNNING
        self._iteration = 0
        self._detected_lang = "ru"  # FIX NEW-004: auto-detect from first user message
        self._consecutive_errors = 0
        self._current_phase: str = "planning"
        self._artifacts: list[str] = []
        self._start_time: float = 0

        # Context management (v5)
        self._scratchpad = Scratchpad()
        self._compactor = ContextCompactor(
            max_context_tokens=128000,
            threshold_ratio=0.75,
            keep_recent=12,
        )
        self._goal_anchor = GoalAnchor()

        # Premium feature flags
        self._premium_images = premium_images
        self._design_check = design_check
        self._premium_review = premium_review

        # FrontendDirector instance (lazy init)
        self._director: Optional[FrontendDirector] = None
        self._scene_plan: Optional[dict] = None

        # Memory v9 engine
        if _memory_available:
            try:
                self._memory = SuperMemoryEngine()
            except Exception as e:
                logger.warning(f"Memory v9 init failed: {e}")
                self._memory = None
        else:
            self._memory = None

    @property
    def status(self) -> LoopStatus:
        return self._status

    @property
    def iteration(self) -> int:
        return self._iteration


    def _adjust_max_iterations(self, user_message: str) -> None:
        """Dynamically adjust max iterations based on task complexity (PATCH-09).
        Uses module-level INTENT_COMPLEXITY for easy tuning.
        """
        msg_lower = user_message.lower()
        detected = "moderate"  # default
        for level, cfg in INTENT_COMPLEXITY.items():
            if any(m in msg_lower for m in cfg["markers"]):
                detected = level
                break
        self._max_iterations = INTENT_COMPLEXITY[detected]["max_iterations"]
        logger.info(f"Task complexity: {detected}, max_iterations: {self._max_iterations}")


    async def _log_usage_to_db(self, model: str, tokens_in: int, tokens_out: int, cost: float) -> None:
        """FIX NEW-013: Explicitly log LLM usage to database for cost tracking."""
        try:
            from api.chat_store import update_chat
            current = self._chat_data.get("total_cost", 0.0) if hasattr(self, "_chat_data") else 0.0
            current_tokens = self._chat_data.get("total_tokens", 0) if hasattr(self, "_chat_data") else 0
            await update_chat(self._chat_id,
                total_cost=current + cost,
                total_tokens=current_tokens + tokens_in + tokens_out,
                model_used=model)
            logger.debug(f"Usage logged: model={model}, tokens={tokens_in+tokens_out}, cost=${cost:.4f}")
        except Exception as e:
            logger.warning(f"Failed to log usage: {e}")

    def _build_system_prompt(self, tools_schema: list[dict]) -> str:
        """
        Build the system prompt — Manus-style.
        Role + tool_use rules + agent_loop + context.
        FIX NEW-004: Now auto-detects user language.
        """
        # FIX NEW-004: Auto-detect language from first user message
        if self._detected_lang == "ru" and self._iteration <= 1:
            try:
                from api.chat_store import get_messages
                msgs = get_messages(self._chat_id)
                for m in msgs:
                    if m.get("role") == "user" and m.get("content"):
                        self._detected_lang = detect_language(m["content"])
                        logger.info(f"Detected language: {self._detected_lang}")
                        break
            except Exception:
                pass
        history_block = self._get_chat_history_context()
        # FIX NEW-004: Full bilingual system prompt
        lang = self._detected_lang or "ru"
        base_prompt = build_full_prompt(lang)
        return f"""{base_prompt}
<budget>
Проект: {self._project_id} | Бюджет: ${self._router.budget_remaining:.2f} | Итерация: {self._iteration}/{self._max_iterations}
</budget>
{self._goal_anchor.to_prompt_section()}
{self._scratchpad.to_prompt_section()}
{history_block}{self._get_user_preferences_context()}
{self._get_memory_context()}"""
    def _get_user_preferences_context(self) -> str:
        """Get user preferences context for system prompt."""
        if hasattr(self, "_user_prefs_prompt") and self._user_prefs_prompt:
            return self._user_prefs_prompt
        return ""



    async def _inject_gsap_if_missing(self, filepath: str) -> None:
        """
        Auto-inject GSAP ScrollTrigger animations into HTML files.
        Only injects if GSAP is not already present.
        This ensures ALL landing pages have smooth scroll animations,
        whether generated by scene_assembler or by the LLM directly.
        """
        import os
        if not os.path.exists(filepath):
            return
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()
        # Skip if GSAP already present
        if "gsap" in html.lower() and "scrolltrigger" in html.lower():
            logger.debug(f"GSAP already present in {filepath}")
            return
        # Skip non-landing pages (small files, scripts, etc.)
        if len(html) < 3000 or "</body>" not in html:
            return
        # P0 FIX (NEW-005): GSAP JavaScript extracted to shared/templates/gsap_scroll_trigger.html
        # Load GSAP template from file (cached after first read)
        if not hasattr(self, '_gsap_cache') or not self._gsap_cache:
            import os as _os
            _tpl_path = _os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                "shared", "templates", "gsap_scroll_trigger.html"
            )
            try:
                with open(_tpl_path, "r", encoding="utf-8") as _tf:
                    self._gsap_cache = _tf.read()
            except Exception as _e:
                logger.warning(f"Failed to load GSAP template: {_e}")
                return
        html = html.replace("</body>", self._gsap_cache + "\n</body>")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"GSAP ScrollTrigger injected into {filepath}")

    def _get_chat_history_context(self) -> str:
        """
        Load previous messages from chat_store to give the agent full conversation context.
        This is the KEY fix for conversational intelligence — without this,
        every message starts from scratch and the agent has amnesia.
        """
        if not self._project_id:
            return ""
        try:
            from api.chat_store import get_messages
            stored_messages = get_messages(self._project_id)
            if not stored_messages or len(stored_messages) <= 1:
                return ""
            
            # Build conversation history (exclude the current message — it's already in self._messages)
            # Only include user and assistant messages, skip tool calls
            history_lines = []
            # Take last 20 messages max to avoid context overflow
            recent = stored_messages[-20:-1] if len(stored_messages) > 1 else []
            
            for msg in recent:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if not content or not role:
                    continue
                if role == "user":
                    # Truncate very long messages
                    if len(content) > 500:
                        content = content[:500] + "..."
                    history_lines.append(f"Пользователь: {content}")
                elif role == "assistant":
                    if len(content) > 500:
                        content = content[:500] + "..."
                    history_lines.append(f"ARCANE: {content}")
            
            if not history_lines:
                return ""
            
            return (
                "\n<conversation_history>\n"
                "Предыдущие сообщения в этом чате (используй этот контекст, НЕ переспрашивай то что уже обсуждали):\n"
                + "\n".join(history_lines)
                + "\n</conversation_history>\n"
            )
        except Exception as e:
            logger.debug(f"Failed to load chat history: {e}")
            return ""

    def _get_memory_context(self) -> str:
        """Get memory context to inject into system prompt."""
        if not self._memory:
            return ""
        try:
            # Get the last user message for context
            last_user_msg = ""
            for msg in reversed(self._messages):
                if msg.get("role") == "user":
                    last_user_msg = msg.get("content", "")
                    break
            context = self._memory.get_context_for_task(last_user_msg)
            if context:
                return f"\n<memory_context>\n{context}\n</memory_context>"
        except Exception as e:
            logger.warning(f"Memory context retrieval failed: {e}")
        return ""

    async def _run_scene_driven_pipeline(self, user_message: str, temperature_boost: float = 0.0) -> bool:
        """
        Scene-Driven Code-RAG pipeline.
        1. plan_page() — detect niche, select scenes, extract content via LLM
        2. assemble_page() — render HTML from templates + modifiers
        3. Save HTML to project file and inject result into conversation
        Returns True if successful (skip old pipeline), False to fallback.
        """
        if not _scene_driven_available:
            return False
        try:
            await self._emit_event("phase_change", {
                "phase": "scene_planning",
                "iteration": 0,
                "tool": "scene_planner",
            })
            logger.info("Scene-Driven pipeline: starting plan_page()")
            page_plan = await _scene_plan_page(
                user_brief=user_message,
                llm_client=self._client,
            )
            # Pass LLM client to page_plan for blueprint assembly
            page_plan.meta["_llm_client"] = self._client
            await self._emit_event("scene_plan_created", {
                "design_family": "scene_driven_v1",
                "concept_name": f"{page_plan.niche} — {page_plan.global_theme}",
                "sections_count": len(page_plan.scenes),
                "mood": page_plan.niche_tags,
                "accent_color": page_plan.global_theme,
                "used_multi_concept": False,
                "used_visual_rag": False,
            })
            logger.info(
                f"Scene-Driven: planned {len(page_plan.scenes)} scenes, "
                f"niche={page_plan.niche}, theme={page_plan.global_theme}"
            )
            await self._emit_event("phase_change", {
                "phase": "assembling",
                "iteration": 0,
                "tool": "scene_assembler",
            })
            html_content = await _scene_assemble_page(
                page_plan,
                fetch_images=True,
                lang="ru",
            )
            if not html_content or len(html_content) < 2000:
                logger.warning("Scene-Driven: assembled HTML too short, falling back")
                return False
            import os
            project_dir = f"/root/workspace/{self._project_id}"  # P4-FIX BUG-005: unified path
            os.makedirs(project_dir, exist_ok=True)
            niche_slug = page_plan.niche.replace("_", "-")
            # P1-FIX: Use project_id prefix to prevent artifact mismatch between projects
            short_id = self._project_id[:8] if len(self._project_id) > 8 else self._project_id
            filename = f"{short_id}_{niche_slug}_landing.html"
            filepath = os.path.join(project_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content)
            # AUTO-DEPLOY to /var/www/demo/{slug}/
            try:
                from workers.scene_assembler import auto_deploy as _auto_deploy
                deploy_name = page_plan.niche.replace('_', ' ').title()
                # Use project brief if available for better slug
                if hasattr(page_plan, 'brief') and page_plan.brief:
                    deploy_name = page_plan.brief[:50]
                deploy_result = await _auto_deploy(html_content, deploy_name)
                public_url = deploy_result['url']
                logger.info(f"Scene-Driven: AUTO-DEPLOYED to {public_url}")
            except Exception as deploy_err:
                logger.warning(f"Auto-deploy failed (non-fatal): {deploy_err}")
                public_url = f"https://arcaneai.ru/workspace/{self._project_id}/{filename}"  # P4-FIX BUG-005
            
            logger.info(
                f"Scene-Driven: HTML saved to {filepath} "
                f"({len(html_content):,} chars), URL: {public_url}"
            )
            self._messages.append({
                "role": "user",
                "content": (
                    f"SCENE-DRIVEN PIPELINE COMPLETED SUCCESSFULLY.\n\n"
                    f"The landing page has been assembled from premium scene templates.\n"
                    f"Niche: {page_plan.niche}\n"
                    f"Theme: {page_plan.global_theme}\n"
                    f"Scenes: {', '.join(s.scene_id for s in page_plan.scenes)}\n\n"
                    f"File saved to: {filepath}\n"
                    f"Public URL (LIVE): {public_url}\n\n"
                    f"IMPORTANT: The HTML file is already created and DEPLOYED. Your ONLY job now is to:\n"
                    f"1. Review the file at {filepath} using read_file tool\n"
                    f"2. Make any minor content improvements if needed (edit_file tool)\n"
                    f"3. Send the result message with the LIVE preview URL: {public_url}\n\n"
                    f"The landing page is ALREADY LIVE at {public_url}\n"
                    f"Do NOT regenerate the HTML from scratch. The scene templates are premium quality."
                ),
            })
            self._scratchpad.update(
                "scene_plan_summary",
                f"Scene-Driven: niche={page_plan.niche}, theme={page_plan.global_theme}, "
                f"scenes={len(page_plan.scenes)}, file={filename}"
            )
            self._scratchpad.update("scene_driven_file", filepath)
            self._scratchpad.update("scene_driven_url", public_url)
            return True
        except Exception as e:
            logger.warning(f"Scene-Driven pipeline failed (non-fatal): {e}")
            import traceback as _tb
            logger.debug(_tb.format_exc())
            return False

    async def _run_frontend_director(self, user_message: str) -> None:
        """
        Scene-Driven pipeline — the ONLY execution path for web_design tasks.
        
        Flow: classify → plan_page → assemble_page → deploy
        
        No legacy fallback. If scene pipeline fails after retries,
        we inject a minimal scene plan from defaults rather than
        letting the LLM generate HTML from scratch.
        
        CUTOVER v1: 2026-03-31
        """
        if not _scene_driven_available:
            logger.error("CUTOVER BLOCK: scene_driven module not available — cannot proceed with web_design task")
            await self._emit_event("error", {
                "message": "Scene pipeline module not available. Please check server configuration.",
            })
            return

        try:
            await self._emit_event("phase_change", {
                "phase": "directing",
                "iteration": 0,
                "tool": "frontend_director",
            })

            # Intent gate: only proceed for genuine web_design tasks
            is_landing = False
            try:
                from core.intent_classifier import classify_intent
                intent_result = await classify_intent(self._client, user_message)
                intent = intent_result.get("intent", "")
                is_landing = intent == "web_design"
                logger.info(f"FrontendDirector: intent='{intent}' (confidence={intent_result.get('confidence', 0)})")
            except Exception as e:
                # Fallback to keyword detection
                landing_keywords = [
                    "лендинг", "landing page", "одностранич", "промо-сайт",
                    "сайт-визитк", "homepage design", "create website", "сделай сайт",
                    "создай сайт", "разработай сайт", "build a website",
                ]
                is_landing = any(kw in user_message.lower() for kw in landing_keywords)
                logger.warning(f"FrontendDirector: intent_classifier failed ({e}), keyword fallback={is_landing}")

            if not is_landing:
                logger.info("FrontendDirector: not a web_design task, skipping")
                return

            logger.info("SCENE-ONLY PATH: starting scene-driven pipeline (no legacy fallback)")

            # ═══ Scene-Driven Code-RAG — 3 attempts with progressive temperature ═══
            import asyncio as _asyncio
            _MAX_RETRIES = 3
            _last_error = None

            for _attempt in range(1, _MAX_RETRIES + 1):
                logger.info(f"Scene-Driven pipeline: attempt {_attempt}/{_MAX_RETRIES}")
                try:
                    success = await self._run_scene_driven_pipeline(
                        user_message,
                        temperature_boost=0.1 * (_attempt - 1),  # 0.0, 0.1, 0.2
                    )
                    if success:
                        logger.info(f"Scene-Driven pipeline SUCCEEDED on attempt {_attempt}")
                        return
                except Exception as e:
                    _last_error = e
                    logger.warning(f"Scene-Driven attempt {_attempt} raised: {e}")

                if _attempt < _MAX_RETRIES:
                    _delay = 2 * _attempt  # 2s, 4s
                    logger.warning(f"Scene-Driven failed on attempt {_attempt}, waiting {_delay}s before retry...")
                    await _asyncio.sleep(_delay)

            # ═══ All retries exhausted — inject minimal scene guidance ═══
            # Instead of letting the LLM go freestyle (the old hidden from-scratch path),
            # we inject a structured fallback prompt so the agent at least follows
            # a consistent section structure.
            logger.error(
                f"SCENE-DRIVEN PIPELINE FAILED after {_MAX_RETRIES} attempts. "
                f"Last error: {_last_error}. Injecting minimal scene guidance."
            )
            await self._emit_event("warning", {
                "message": f"Scene pipeline failed after {_MAX_RETRIES} attempts. Using minimal guidance.",
            })

            # Minimal structured guidance — NOT the old coder_prompt, but a section skeleton
            # This ensures the agent at least produces consistent structure
            self._messages.append({
                "role": "user",
                "content": (
                    "SCENE PIPELINE FALLBACK — FOLLOW THIS STRUCTURE:\n\n"
                    "The automated scene pipeline could not generate templates. "
                    "Create a SINGLE HTML file with these MANDATORY sections in order:\n"
                    "1. HERO — full-width, background image, headline + CTA button\n"
                    "2. ABOUT / FEATURES — 3-4 cards or columns\n"
                    "3. SERVICES / PORTFOLIO — grid layout\n"
                    "4. TESTIMONIALS — 2-3 client quotes\n"
                    "5. CTA — call-to-action banner\n"
                    "6. CONTACTS — address, phone, email, map placeholder\n"
                    "7. FOOTER — copyright, social links\n\n"
                    "Requirements:\n"
                    "- Mobile-first responsive (works on 360px+)\n"
                    "- Use Google Fonts (not system fonts)\n"
                    "- Professional color palette (NOT random)\n"
                    "- Real placeholder content in Russian (NO lorem ipsum)\n"
                    "- All images via Unsplash (https://images.unsplash.com/...)\n"
                    "- GSAP ScrollTrigger animations\n"
                    "- Semantic HTML5 structure\n"
                ),
            })
            self._scratchpad.update(
                "scene_plan_summary",
                f"FALLBACK: scene pipeline failed after {_MAX_RETRIES} attempts, using minimal guidance"
            )

        except Exception as e:
            logger.error(f"FrontendDirector FATAL: {e}")
            import traceback as _tb
            logger.debug(_tb.format_exc())
            self._scene_plan = None


    async def run(self, user_message: str) -> dict:
        """
        Main entry point. Run the agent loop for a user message.
        Returns a summary dict with status, iterations, cost, artifacts.
        """
        self._start_time = time.monotonic()
        self._status = LoopStatus.RUNNING
        self._iteration = 0
        self._consecutive_errors = 0

        # Add user message to conversation
        self._messages.append({"role": "user", "content": user_message})

        # Set goal anchor from first user message
        if not self._goal_anchor.goal:
            self._goal_anchor.set_goal(user_message)

        # Load user preferences (non-blocking, cached)
        try:
            prefs = await get_user_preferences(self._user_id)
            self._user_prefs_prompt = preferences_to_prompt(prefs)
        except Exception as e:
            logger.debug(f"Failed to load user preferences: {e}")
            self._user_prefs_prompt = ""

        # Memory v9: initialize task context
        if self._memory:
            try:
                self._memory.init_task(
                    user_message=user_message,
                    user_id=self._user_id,
                    chat_id=self._project_id,
                )
            except Exception as e:
                logger.warning(f"Memory init_task failed: {e}")

        await self._emit_event("task_started", {
            "message": user_message,
            "project_id": self._project_id,
        })

        # ═══ FrontendDirector: create scene plan for landing page tasks ═══
        # FIX #3+5: Design pipeline is now OPTIONAL and intent-gated.
        # It only runs when:
        #   1. design_check flag is True (user opted in or premium mode)
        #   2. FrontendDirector module is available
        #   3. Intent classifier confirms this is a web_design task
        # For non-design tasks (SSH, API, automation), this is completely skipped.
        _design_pipeline_ran = False
        if self._design_check and _director_available:
            try:
                from core.intent_classifier import classify_intent
                _intent_result = await classify_intent(self._client, user_message)
                _is_design = _intent_result.get("intent") == "web_design"
            except Exception:
                _is_design = False
            if _is_design:
                await self._run_frontend_director(user_message)
                _design_pipeline_ran = True
            else:
                logger.info("Design pipeline skipped — not a web_design task")

        _design_judge_passes = 0  # Track how many times we've run the judge
        _MAX_JUDGE_PASSES = 2     # Maximum judge evaluation cycles

        try:
            while self._status == LoopStatus.RUNNING:
                self._iteration += 1
                # DAY0-FIX3: Hard timeout on entire task (600s = 10 min)
                _elapsed = time.monotonic() - self._start_time
                if _elapsed > 600:  # TASK_HARD_TIMEOUT
                    logger.warning(f"HARD TIMEOUT: Task exceeded 600s (elapsed={_elapsed:.0f}s)")
                    self._status = LoopStatus.FAILED
                    await self._emit_event("error", {
                        "message": f"Hard timeout: task exceeded 600s ({_elapsed:.0f}s elapsed).",
                    })
                    if self._artifacts:
                        await self._emit_event("info", {
                            "message": f"Timeout. Delivering {len(self._artifacts)} artifact(s) as-is.",
                        })
                    break

                if self._iteration > self._max_iterations:
                    self._status = LoopStatus.FAILED
                    await self._emit_event("error", {
                        "message": f"Max iterations ({self._max_iterations}) exceeded",
                    })
                    break

                # Run one iteration of the loop
                should_continue = await self._run_iteration()

                if not should_continue:
                    # Agent signaled completion (message type='result') or failure.
                    # If COMPLETED and design_check is enabled, run the Vision Judge
                    # INSIDE the loop so we can resume if score is too low.
                    if self._status == LoopStatus.COMPLETED and self._design_check and _design_pipeline_ran and _design_judge_passes < _MAX_JUDGE_PASSES:
                        judge_resumed = await self._run_design_judge_evaluation(_design_judge_passes)
                        if judge_resumed:
                            _design_judge_passes += 1
                            # Status was set back to RUNNING, continue the while loop
                            continue
                        else:
                            _design_judge_passes += 1
                    # If not resumed, break out of the loop
                    break

        except BudgetExceededError as e:
            self._status = LoopStatus.BUDGET_EXCEEDED
            await self._emit_event("budget_exceeded", {"message": str(e)})

        except Exception as e:
            self._status = LoopStatus.FAILED
            logger.error(f"Agent loop fatal error: {e}\n{traceback.format_exc()}")
            await self._emit_event("error", {
                "message": f"Fatal error: {str(e)[:200]}",
            })

        elapsed = time.monotonic() - self._start_time
        summary = {
            "status": self._status.value,
            "iterations": self._iteration,
            "total_cost": self._router.total_cost,
            "budget_remaining": self._router.budget_remaining,
            "elapsed_seconds": round(elapsed, 1),
            "artifacts": self._artifacts,
        }

        # Memory v9: store episode after task
        if self._memory:
            try:
                self._memory.after_chat(
                    user_message=user_message,
                    full_response=str(self._artifacts),
                    chat_id=self._project_id,
                    success=(self._status == LoopStatus.COMPLETED),
                )
            except Exception as e:
                logger.warning(f"Memory after_chat failed: {e}")

        # Premium Review: second LLM reviews the result
        if self._status == LoopStatus.COMPLETED and self._premium_review:
            await self._run_premium_review()

        # UserProfile: extract preferences from completed conversations
        if self._status == LoopStatus.COMPLETED and len(self._messages) >= 4:
            try:
                prefs = await extract_preferences(
                    messages=self._messages,
                    user_id=self._user_id,
                    chat_id=self._project_id,
                    llm_client=self._client,
                )
                if prefs:
                    await save_preferences(self._user_id, self._project_id, prefs)
            except Exception as e:
                logger.debug(f"Preference extraction failed: {e}")

        # ═══ AUTO-DELIVER FALLBACK ═══
        # If agent completed but never sent message(type="result"), send it automatically
        if self._status == LoopStatus.COMPLETED:
            has_result_message = any(
                m.get("role") == "assistant" and "type" in str(m.get("content", ""))
                and '"result"' in str(m.get("content", ""))
                for m in self._messages
                if isinstance(m, dict)
            )
            # More reliable check: look for message tool calls with type=result
            has_result_tool = any(
                m.get("role") == "assistant"
                and any(
                    tc.get("function", {}).get("name") == "message"
                    and '"result"' in tc.get("function", {}).get("arguments", "")
                    for tc in (m.get("tool_calls", []) if isinstance(m.get("tool_calls"), list) else [])
                )
                for m in self._messages
                if isinstance(m, dict)
            )
            if not has_result_tool:
                logger.warning("Agent completed without sending result message — auto-delivering")
                # Build auto-result message
                artifacts_list = self._artifacts[:5]  # Limit to 5
                urls = []
                for a in artifacts_list:
                    if a.endswith(('.html', '.htm')):
                        import os
                        fname = os.path.basename(a)
                        urls.append(f"https://arcaneai.ru/workspace/{self._project_id}/{fname}")  # P4-FIX BUG-005
                result_text = f"Задача выполнена. Создано файлов: {len(self._artifacts)}."
                if urls:
                    result_text += f" Результат: {urls[0]}"
                try:
                    await self._emit_event("agent_message", {
                        "type": "result",
                        "text": result_text,
                        "attachments": artifacts_list,
                    })
                except Exception as e:
                    logger.error(f"Auto-deliver failed: {e}")

        await self._emit_event("task_completed", summary)
        return summary

    async def _run_design_judge_evaluation(self, pass_number: int) -> bool:
        """
        Run the 5-Judge Panel evaluation on the latest HTML artifact.
        If score < 7.5, applies FrontendFinisher (PATCH/REFACTOR/REBUILD)
        and injects feedback to resume the agent loop.
        Falls back to V2 single judge if panel is unavailable.
        """
        # DAY0-FIX4: Judge budget cap — skip if budget is >70% consumed or >$0.50 spent
        JUDGE_BUDGET_CAP = 0.50  # Max total cost before skipping judge
        JUDGE_BUDGET_RATIO = 0.70  # Skip if >70% of budget consumed
        current_cost = self._router.total_cost
        budget_limit = getattr(self._router, '_budget_limit', 5.0)
        budget_ratio = current_cost / budget_limit if budget_limit > 0 else 1.0
        if current_cost > JUDGE_BUDGET_CAP:
            logger.info(
                f"DAY0-FIX4: Judge skipped — total cost ${current_cost:.2f} exceeds "
                f"judge cap ${JUDGE_BUDGET_CAP:.2f}"
            )
            return False
        if budget_ratio > JUDGE_BUDGET_RATIO:
            logger.info(
                f"DAY0-FIX4: Judge skipped — budget {budget_ratio:.0%} consumed "
                f"(${current_cost:.2f}/${budget_limit:.2f})"
            )
            return False
        html_artifacts = [a for a in self._artifacts if a.endswith(('.html', '.htm'))]
        if not html_artifacts or self._iteration < 2:
            return False

        try:
            last_html = html_artifacts[-1]
            logger.info(f"Judge evaluation pass #{pass_number + 1} on: {last_html}")

            score = 0.0
            action = "REFACTOR"
            feedback_text = ""
            panel_result = None

            # ═══ PRIMARY: 5-Judge Panel ═══
            if _judge_panel_available:
                try:
                    # Take screenshots
                    screenshots = await _take_judge_screenshots(last_html)
                    desktop_b64 = screenshots.get("desktop")
                    mobile_b64 = screenshots.get("mobile")

                    if not desktop_b64:
                        logger.warning("No desktop screenshot — falling back to V2")
                        raise RuntimeError("No desktop screenshot")

                    # Run 5-judge panel
                    from config.settings import get_config
                    panel = get_judge_panel(get_config())
                    panel_result = await panel.evaluate(
                        desktop_screenshot_b64=desktop_b64,
                        mobile_screenshot_b64=mobile_b64,
                        html_content=None,
                        user_brief=self._goal_anchor.goal if hasattr(self._goal_anchor, 'goal') else None,
                    )

                    score = panel_result.get("overall_score", 0)
                    action = panel_result.get("action", "REFACTOR")
                    feedback_text = panel.format_feedback_for_agent(panel_result)

                    # Emit detailed design report
                    judges_summary = {}
                    for jname, jr in panel_result.get("judges", {}).items():
                        judges_summary[jname] = {
                            "score": jr.get("score", 0),
                            "verdict": jr.get("verdict", "?"),
                            "summary": jr.get("summary", ""),
                        }

                    await self._emit_event("design_report", {
                        "overall_score": score,
                        "action": action,
                        "pass_number": pass_number + 1,
                        "method": "5-judge-panel",
                        "judges": judges_summary,
                        "critical_issues": panel_result.get("critical_issues_summary", ""),
                        "fix_count": len(panel_result.get("all_fix_instructions", [])),
                        "elapsed_seconds": panel_result.get("elapsed_seconds", 0),
                        "file": last_html,
                    })

                    logger.info(
                        f"5-Judge Panel: score={score}/10, action={action}, "
                        f"fixes={len(panel_result.get('all_fix_instructions', []))}, "
                        f"elapsed={panel_result.get('elapsed_seconds', 0)}s"
                    )

                    # Record in Trust Engine
                    if _design_intel_available:
                        try:
                            trust = get_trust_engine()
                            trust.record_result(
                                model_id=self._router._resolve_model_id("orchestrator", self._router._resolve_tier("orchestrator")) or "unknown",
                                role="orchestrator",
                                task_type="landing_page",
                                score=score,
                                metadata={"pass": pass_number + 1, "action": action},
                            )
                        except Exception as te:
                            logger.debug(f"Trust Engine record failed: {te}")

                except Exception as panel_err:
                    logger.warning(f"5-Judge Panel failed: {panel_err}, falling back to V2")
                    panel_result = None

            # ═══ FALLBACK: V2 single judge ═══
            if panel_result is None:
                try:
                    from workers.design_judge_v2 import get_vision_judge
                    from config.settings import get_config
                    judge = get_vision_judge(get_config())
                    _jr = await judge.evaluate_html(
                        html_path=last_html,
                        context=f"Task: {self._goal_anchor.goal if hasattr(self._goal_anchor, 'goal') else 'landing page'}",
                        model="google/gemini-2.5-flash",
                        include_mobile=True,
                    )
                    if _jr.get("success"):
                        score = _jr.get("overall_score", 0)
                        action = "PATCH" if score >= 7.5 else "REFACTOR" if score >= 5.0 else "REBUILD"
                        # Build feedback from V2 fields
                        issues = "\n".join(f"- {ci}" for ci in _jr.get("critical_issues", []))
                        fixes = "\n".join(
                            f"- [{fi.get('section', '?')}] {fi.get('problem', '?')} -> FIX: {fi.get('fix', '?')}"
                            if isinstance(fi, dict) else f"- {fi}"
                            for fi in _jr.get("fix_instructions", [])
                        )
                        feedback_text = (
                            f"DESIGN JUDGE V2: {score}/10 — {action}\n\n"
                            f"ISSUES:\n{issues}\n\nFIXES:\n{fixes}"
                        )
                        await self._emit_event("design_report", {
                            "overall_score": score, "action": action,
                            "method": "v2-fallback", "pass_number": pass_number + 1,
                            "file": last_html,
                        })
                    else:
                        logger.warning(f"V2 fallback also failed: {_jr.get('error')}")
                        return False
                except Exception as v2_err:
                    logger.warning(f"V2 fallback failed: {v2_err}")
                    return False

            # ═══ Score check ═══
            if score >= 7.5:
                logger.info(f"Score {score} >= 7.5 — design approved")
                # Record in Anti-Clone Memory
                if _design_intel_available and hasattr(self, '_scene_plan') and self._scene_plan:
                    try:
                        anti_clone = get_anti_clone()
                        anti_clone.record(self._scene_plan, score=score, user_id=self._user_id)
                    except Exception:
                        pass
                return False

            if self._iteration >= (self._max_iterations - 3):
                logger.info(f"Score {score} < 7.5 but near iteration limit — cannot resume")
                return False

            logger.info(f"Score {score} < 7.5, action={action} — applying fixes (pass #{pass_number + 1})")

            # ═══ Apply FrontendFinisher if available and panel gave structured fixes ═══
            finisher_applied = False
            if _finisher_available and panel_result and action in ("PATCH", "REFACTOR"):
                try:
                    finisher = get_frontend_finisher(self._client, self._router)
                    if finisher:
                        # Read current HTML
                        import aiofiles
                        async with aiofiles.open(last_html, 'r', encoding='utf-8') as f:
                            current_html = await f.read()

                        fix_result = await finisher.apply_fixes(
                            html_content=current_html,
                            panel_result=panel_result,
                            scene_plan=getattr(self, '_scene_plan', None),
                        )

                        if fix_result.get("html") and fix_result["action_taken"] != "REBUILD":
                            # Write the fixed HTML back
                            async with aiofiles.open(last_html, 'w', encoding='utf-8') as f:
                                await f.write(fix_result["html"])
                            finisher_applied = True
                            logger.info(
                                f"FrontendFinisher applied: {fix_result['action_taken']}, "
                                f"{fix_result.get('changes_summary', '')[:100]}"
                            )
                except ImportError:
                    logger.debug("aiofiles not available for finisher")
                except Exception as fin_err:
                    logger.warning(f"FrontendFinisher failed: {fin_err}")

            # ═══ Inject feedback as active user message ═══
            if action == "REBUILD":
                rebuild_msg = (
                    f"DESIGN JUDGE PANEL (Pass #{pass_number + 1}): {score}/10 — REBUILD REQUIRED\n\n"
                    f"{feedback_text}\n\n"
                    f"The current design has fundamental problems. You MUST delete the current "
                    f"HTML file and start fresh with a COMPLETELY DIFFERENT visual approach. "
                    f"Do NOT try to fix the existing file — rebuild from scratch."
                )
                self._messages.append({"role": "user", "content": rebuild_msg})
            else:
                finisher_note = ""
                if finisher_applied:
                    finisher_note = (
                        f"\n\nNOTE: The FrontendFinisher has already applied automated CSS fixes "
                        f"to {last_html}. Review the file and make any additional improvements "
                        f"that the automated fixes could not handle (content changes, structural "
                        f"changes, new sections, etc.)."
                    )

                improvement_msg = (
                    f"DESIGN JUDGE PANEL (Pass #{pass_number + 1}): {score}/10 — {action}\n\n"
                    f"{feedback_text}"
                    f"{finisher_note}\n\n"
                    f"You MUST fix ALL remaining issues. Target score: 8.5+. "
                    f"Edit the existing HTML file at {last_html}."
                )
                self._messages.append({"role": "user", "content": improvement_msg})

            # Save to scratchpad
            self._scratchpad["design_judge_feedback"] = feedback_text[:2000]
            self._scratchpad["improvement_needed"] = True
            self._scratchpad["target_score"] = "8.5+"
            self._scratchpad["judge_pass"] = pass_number + 1
            self._scratchpad["judge_action"] = action
            if finisher_applied:
                self._scratchpad["finisher_applied"] = True

            # Resume the agent loop
            self._status = LoopStatus.RUNNING
            self._max_iterations = min(self._max_iterations + 5, 65)  # FIX: Raised hard cap for design judge
            logger.info(
                f"Judge feedback injected (action={action}, finisher={'yes' if finisher_applied else 'no'}), "
                f"resuming loop (+8 iterations, pass #{pass_number + 1})"
            )
            return True

        except Exception as e:
            logger.warning(f"Design judge evaluation failed: {e}")
            return False

    async def _run_iteration(self) -> bool:
        """
        Run a single iteration of the agent loop.
        Returns True to continue, False to stop.
        """
        # Get tools schema from executor
        tools_schema = self._tool_executor.get_tools_schema()

        # Context compaction check — prevent context window overflow
        if self._compactor.needs_compaction(self._messages, self._iteration):
            logger.info(f"Context compaction triggered at iteration {self._iteration}")
            self._messages = self._compactor.compact(self._messages, self._iteration)

        # Build system prompt with current state
        system_prompt = self._build_system_prompt(tools_schema)

        # Prepare messages for LLM
        llm_messages = [
            {"role": "system", "content": system_prompt},
            *self._messages,
        ]

        await self._emit_event("thinking", {
            "iteration": self._iteration,
            "phase": self._current_phase,
            "total_cost": round(self._router.total_cost, 6),
            "budget_remaining": round(self._router.budget_remaining, 4),
        })

        # Call LLM via router (handles tier selection and fallback)
        # P0 FIX (NEW-014): Iteration-level timeout watchdog
        # HTTP-level timeout exists in httpx client, but if retry + fallback chain
        # takes too long (worst case: timeout * retries * models = 18 min),
        # this watchdog ensures a single iteration never exceeds 180 seconds.
        ITERATION_TIMEOUT = 180  # 3 minutes max per LLM call
        try:
            response = await asyncio.wait_for(
                self._router.route(
                    messages=llm_messages,
                    role="orchestrator",
                    tools=tools_schema,
                    user_id=self._user_id,
                    project_id=self._project_id,
                    worker="agent_loop",
                    max_tokens=16384,
                ),
                timeout=ITERATION_TIMEOUT,
            )
        except asyncio.TimeoutError:
            # P0 FIX (NEW-014): Iteration timed out — retry instead of hanging
            logger.error(
                f"Iteration {self._iteration} LLM call timed out after {ITERATION_TIMEOUT}s"
            )
            self._consecutive_errors += 1
            if self._consecutive_errors >= self._max_consecutive_errors:
                self._status = LoopStatus.FAILED
                await self._emit_event("error", {
                    "message": f"LLM call timed out after {ITERATION_TIMEOUT}s "
                               f"({self._consecutive_errors} consecutive errors)",
                })
                return False
            self._messages.append({
                "role": "system",
                "content": (
                    f"[System: LLM call timed out after {ITERATION_TIMEOUT}s. "
                    f"This may be due to provider overload. Retrying with next available model.]"
                ),
            })
            await asyncio.sleep(2)
            return True
        except BadRequestError as e:
            # Tool call ID mismatch — clean broken tool messages from history
            logger.warning(f"BadRequestError (tool_call mismatch): {str(e)[:200]}")
            cleaned = []
            for msg in self._messages:
                if msg.get("role") == "tool":
                    continue  # Remove tool responses with stale call IDs
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    # Convert tool-call assistant message to plain text
                    tc_names = [tc["function"]["name"] for tc in msg.get("tool_calls", []) if "function" in tc]
                    cleaned.append({
                        "role": "assistant",
                        "content": f"[Previously called tools: {', '.join(tc_names)}. Results were applied successfully.]",
                    })
                    continue
                cleaned.append(msg)
            self._messages = cleaned
            self._messages.append({
                "role": "user",
                "content": "[System: Message history was cleaned due to a model switch. Continue from where you left off.]",
            })
            return True
        except ProviderUnavailableError as e:
            self._consecutive_errors += 1
            if self._consecutive_errors >= self._max_consecutive_errors:
                self._status = LoopStatus.FAILED
                return False
            # Add error to context and retry
            self._messages.append({
                "role": "assistant",
                "content": f"[System: LLM provider error — {str(e)[:100]}. Retrying...]",
            })
            await asyncio.sleep(2)
            return True

        # Track usage
        await self._tracker.record(
            self._build_usage_record(response, "orchestrator")
        )

        # Emit real-time cost and model info to frontend
        await self._emit_event("cost_update", {
            "total_cost": round(self._router.total_cost, 6),
            "budget_remaining": round(self._router.budget_remaining, 4),
            "iteration_cost": round(response.cost_usd, 6),
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
        })
        await self._emit_event("model_info", {
            "model_id": response.model_id,
            "provider": response.provider,
            "tier": response.tier.value if hasattr(response.tier, "value") else str(response.tier),
        })

        # Process response
        if response.tool_calls:
            self._consecutive_errors = 0
            return await self._execute_tool_calls(response)
        elif response.content:
            # Manus-style: text responses are NEVER acceptable.
            # The agent MUST always use tool calls. If it needs to talk to the user,
            # it must use the message tool.
            self._consecutive_errors += 1
            logger.warning(
                f"Agent returned text instead of tool call (attempt {self._consecutive_errors}): "
                f"{response.content[:200]}"
            )
            self._messages.append({
                "role": "assistant",
                "content": response.content,
            })
            self._messages.append({
                "role": "system",
                "content": (
                    "Напоминание: используй инструмент message чтобы ответить пользователю. "
                    "Для финального ответа — message(type=\'result\'). "
                    "Для промежуточного обновления — message(type=\'info\')."
                ),
            })
            # If model keeps ignoring tools, escalate tier
            if self._consecutive_errors >= 3:
                logger.warning("Too many text responses, possible model issue")
                self._status = LoopStatus.FAILED
                await self._emit_event("error", {
                    "message": "Agent failed to use tools after multiple attempts",
                })
                return False
            return True
        else:
            # Empty response — retry
            self._consecutive_errors += 1
            if self._consecutive_errors >= self._max_consecutive_errors:
                self._status = LoopStatus.FAILED
                return False
            return True

    async def _execute_tool_calls(self, response: LLMResponse) -> bool:
        """Execute tool calls from the LLM response."""
        # Add assistant message with tool calls to conversation
        assistant_msg = {"role": "assistant", "content": response.content or ""}
        if response.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments if isinstance(tc.arguments, str) else __import__("json").dumps(tc.arguments),
                    },
                }
                for tc in response.tool_calls
            ]
        self._messages.append(assistant_msg)

        # E1: Tool-to-phase mapping for state machine
        _TOOL_TO_PHASE = {
            "plan": "planning", "web_search": "planning", "get_template": "planning", "search_design_inspiration": "planning",
            "file_write": "coding", "file_edit": "coding", "file_create": "coding",
            "image_generate": "coding", "update_scratchpad": "coding",
            "shell_exec": "deploying", "deploy_to_vps": "deploying",
            "create_archive": "deploying", "ssh_exec": "deploying",
            "browser_navigate": "verifying", "browser_view": "verifying",
            "design_judge": "verifying", "browser_click": "verifying",
            "message": "delivering",
        }

        # Execute each tool call (one at a time, as per Manus protocol)
        for tool_call in response.tool_calls:
            # E2: Detect phase change and emit SSE event
            new_phase = _TOOL_TO_PHASE.get(tool_call.name, self._current_phase)
            if new_phase != self._current_phase:
                self._current_phase = new_phase
                await self._emit_event("phase_change", {
                    "phase": new_phase,
                    "iteration": self._iteration,
                    "tool": tool_call.name,
                })

            # FIX 1: Emit tool_executing. The emitter callback returns step_id
            # via a mutable container, since _emit_event creates a new dict.
            _step_id_container = {}
            _tc_args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
            _tool_event = {
                "tool": tool_call.name,
                "iteration": self._iteration,
                "_step_id_container": _step_id_container,
                "brief": _tc_args.get("brief", ""),
            }
            await self._emit_event("tool_executing", _tool_event)
            _step_id = _step_id_container.get("step_id")

            try:
                result = await self._tool_executor.execute(
                    tool_name=tool_call.name,
                    arguments=tool_call.arguments,
                    project_id=self._project_id,
                    user_id=self._user_id,
                )

                # Add tool result to conversation
                # VISION INJECTION: For browser tools, inject screenshot as image
                # so the LLM can SEE the page (like Manus does), not just read text.
                _BROWSER_VISION_TOOLS = {
                    "browser_navigate", "browser_view", "browser_click",
                    "browser_input", "browser_scroll", "browser_press_key",
                    "browser_select", "browser_find",
                }
                if tool_call.name in _BROWSER_VISION_TOOLS:
                    # Extract base64 screenshot from result string
                    _b64 = self._extract_screenshot_b64(result)
                    if _b64:
                        # Multimodal message: text + image
                        self._messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": [
                                {"type": "text", "text": self._truncate_result(result)},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{_b64}",
                                        "detail": "high",
                                    },
                                },
                            ],
                        })
                    else:
                        self._messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": self._truncate_result(result),
                        })
                else:
                    self._messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": self._truncate_result(result),
                    })

                # For message tool, send full result; truncate others
                preview_len = 10000 if tool_call.name == "message" else 200
                await self._emit_event("tool_completed", {
                    "tool": tool_call.name,
                    "success": True,
                    "result_preview": str(result)[:preview_len],
                    "step_id": _step_id,  # FIX 1: explicit step_id, not via event mutation
                })

                # If scratchpad tool was called, update the local scratchpad
                if tool_call.name == "update_scratchpad":
                    _args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
                    _key = _args.get("key", "")
                    _val = _args.get("value", "")
                    if _key:
                        self._scratchpad.update(_key, _val)

                # If plan tool was called, emit plan_update with phases
                if tool_call.name == "plan" and isinstance(tool_call.arguments, dict):
                    phases = tool_call.arguments.get("phases", [])
                    if phases:
                        await self._emit_event("plan_update", {
                            "phases": phases,
                            "current_phase_id": tool_call.arguments.get("current_phase_id", 1),
                            "goal": tool_call.arguments.get("goal", ""),
                        })

                # Memory v9: record action
                if self._memory:
                    try:
                        self._memory.record_action(
                            tool_name=tool_call.name,
                            params=tool_call.arguments if isinstance(tool_call.arguments, dict) else {},
                            result=str(result)[:500],
                            success=True,
                        )
                    except Exception:
                        pass

                # Reset consecutive info counter when agent does real work (non-message tools)
                if tool_call.name != "message":
                    self._consecutive_info_messages = 0
                # Check for special tool results
                if tool_call.name == "message" and isinstance(tool_call.arguments, dict):
                    msg_type = tool_call.arguments.get("type", "")
                    if msg_type == "result":
                        # PHASE-6 FIX: Emit task_complete with artifacts list
                        # so frontend knows about all created files
                        _attachments = tool_call.arguments.get("attachments", [])
                        if _attachments:
                            logger.info(f"Message result has {len(_attachments)} attachments: {_attachments}")
                        _all_artifacts = list(set(self._artifacts + list(_attachments)))
                        await self._emit_event("task_completed", {
                            "summary": tool_call.arguments.get("text", "")[:200],
                            "artifacts": _all_artifacts,
                            "iterations": self._iteration,
                            "total_cost": round(self._router.total_cost, 6) if hasattr(self, "_router") else 0,
                        })
                        self._status = LoopStatus.COMPLETED
                        return False
                    elif msg_type == "ask":
                        self._status = LoopStatus.WAITING_USER
                        return False
                    elif msg_type == "info":
                        # Info messages are progress updates, continue the loop.
                        # But if agent sends too many consecutive info messages without
                        # doing real work, force-stop to prevent infinite loops.
                        self._consecutive_info_messages = getattr(self, '_consecutive_info_messages', 0) + 1
                        if self._consecutive_info_messages >= 3:
                            logger.warning(f"Agent sent {self._consecutive_info_messages} consecutive info messages — force-completing")
                            self._status = LoopStatus.COMPLETED
                            return False

                # Track artifacts + GSAP injection for HTML files
                if tool_call.name in ("file_write", "file_create", "file_edit"):
                    path = tool_call.arguments.get("path", "")
                    if path:
                        self._artifacts.append(path)
                        # Auto-inject GSAP animations into HTML files written by LLM
                        if path.endswith(".html"):
                            try:
                                await self._inject_gsap_if_missing(path)
                            except Exception as _gsap_err:
                                logger.debug(f"GSAP injection skipped: {_gsap_err}")

            except Exception as e:
                error_str = str(e)
                error_report = analyze_error(error_str)

                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"ERROR: {error_str[:1000]}\n\nAnalysis: {error_report.root_cause}\nSuggested fixes: {', '.join(error_report.suggested_fixes)}",
                })

                await self._emit_event("tool_error", {
                    "tool": tool_call.name,
                    "error": error_str[:200],
                    "category": error_report.category.value,
                    "severity": error_report.severity.value,
                    "step_id": _step_id,  # FIX 1: explicit step_id
                })

                self._consecutive_errors += 1

                if is_critical(error_report):
                    self._status = LoopStatus.FAILED
                    return False

                if self._consecutive_errors >= self._max_consecutive_errors:
                    self._status = LoopStatus.FAILED
                    return False

        return True

    def _is_task_complete(self, content: str) -> bool:
        """Deprecated: Manus-style loop never uses this.
        Task completion is signaled ONLY by message(type='result') tool call."""
        return False

    def _extract_screenshot_b64(self, result: Any) -> str | None:
        """
        Extract base64-encoded screenshot from browser tool result.
        Browser tools now return screenshot_b64 in their result dict.
        The result is passed as a string, so we need to parse it.
        """
        try:
            result_str = str(result)
            # Fast path: look for our b64 marker
            marker = "screenshot_b64:"
            idx = result_str.find(marker)
            if idx != -1:
                b64_start = idx + len(marker)
                b64_end = result_str.find("\n", b64_start)
                if b64_end == -1:
                    b64_end = len(result_str)
                return result_str[b64_start:b64_end].strip()
            return None
        except Exception:
            return None

    def _truncate_result(self, result: Any, max_length: int = 4000) -> str:
        """Truncate tool result to fit in context window."""
        text = str(result)
        if len(text) <= max_length:
            return text
        half = max_length // 2
        return text[:half] + f"\n\n... [truncated {len(text) - max_length} chars] ...\n\n" + text[-half:]

    def _build_usage_record(self, response: LLMResponse, role: str):
        """Build a UsageRecord from an LLM response."""
        from shared.models.schemas import UsageRecord
        return UsageRecord(
            project_id=self._project_id,
            user_id=self._user_id,
            model_id=response.model_id,
            provider=response.provider,
            tier=response.tier,
            worker="agent_loop",
                    max_tokens=16384,
            role=role,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cached_tokens=response.cached_tokens,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
        )

    async def _run_premium_review(self) -> None:
        """Premium Review: second LLM reviews the result as a senior engineer."""
        try:
            # Collect artifacts content
            artifacts_content = []
            for path in self._artifacts:
                try:
                    with open(path) as f:
                        artifacts_content.append(f"--- {path} ---\n{f.read()[:5000]}")
                except Exception:
                    pass

            if not artifacts_content:
                return

            scratchpad_data = self._scratchpad.to_dict() if hasattr(self._scratchpad, 'to_dict') else str(self._scratchpad)
            review_prompt = f"""You are a senior engineer reviewing work output.
Original task: {self._goal_anchor.goal if hasattr(self._goal_anchor, 'goal') else 'unknown'}
Scratchpad data (user-provided facts): {scratchpad_data}

Generated files:
{chr(10).join(artifacts_content)}

Check:
1. Does the code compile/work correctly?
2. Are ALL user-provided data (phone, email, address, names, prices) used correctly? NOT invented?
3. Is HTML responsive (mobile-friendly)?
4. Any bugs, security issues, or missing features?

Return JSON: {{"score": 0-100, "issues": ["..."], "data_correct": true/false, "passed": true/false}}
If passed=false, list exact fixes needed."""

            response = await self._router.route(
                messages=[{"role": "user", "content": review_prompt}],
                role="qa",
            )

            import json as _json
            try:
                review = _json.loads(response.content)
            except (TypeError, _json.JSONDecodeError):
                # Try to extract JSON from response
                import re
                m = re.search(r'\{[^{}]*"score"[^{}]*\}', response.content or "")
                if m:
                    review = _json.loads(m.group())
                else:
                    review = {"score": 0, "issues": ["Could not parse review"], "passed": True}

            await self._emit_event("premium_review", review)
            logger.info(f"Premium review: score={review.get('score')}, passed={review.get('passed')}")

            # If review failed and has issues, auto-fix
            if not review.get("passed", True) and review.get("issues"):
                fix_prompt = f"Ревьюер нашёл проблемы: {review['issues']}. Исправь их."
                self._messages.append({"role": "user", "content": fix_prompt})
                # Run 1-2 more iterations to fix
                for _ in range(2):
                    should_continue = await self._run_iteration()
                    if not should_continue:
                        break

        except Exception as e:
            logger.warning(f"Premium review failed: {e}")

    async def _emit_event(self, event_type: str, data: dict) -> None:
        """Emit a WebSocket event to the frontend."""
        event = {
            "type": event_type,
            "project_id": self._project_id,
            "iteration": self._iteration,
            "max_iterations": self._max_iterations,
            "total_cost": round(self._router.total_cost, 6) if hasattr(self, "_router") else 0,
            "timestamp": time.time(),
            **data,
        }
        try:
            if asyncio.iscoroutinefunction(self._emit):
                await self._emit(event)
            else:
                self._emit(event)
        except Exception as e:
            logger.warning(f"Failed to emit event: {e}")

        log_with_data(
            logger, "INFO",
            f"Event: {event_type}",
            **{k: v for k, v in data.items() if not isinstance(v, (list, dict))},
        )

    async def resume(self, user_response: str) -> dict:
        """Resume the loop after waiting for user input."""
        if self._status != LoopStatus.WAITING_USER:
            raise RuntimeError(f"Cannot resume: status is {self._status}")

        self._messages.append({"role": "user", "content": user_response})
        self._status = LoopStatus.RUNNING
        self._consecutive_errors = 0

        return await self._continue_loop()

    async def _continue_loop(self) -> dict:
        """Continue the loop from current state."""
        try:
            while self._status == LoopStatus.RUNNING:
                self._iteration += 1
                if self._iteration > self._max_iterations:
                    self._status = LoopStatus.FAILED
                    break
                should_continue = await self._run_iteration()
                if not should_continue:
                    break
        except BudgetExceededError as e:
            self._status = LoopStatus.BUDGET_EXCEEDED
        except Exception as e:
            self._status = LoopStatus.FAILED
            logger.error(f"Agent loop error: {e}")

        elapsed = time.monotonic() - self._start_time
        return {
            "status": self._status.value,
            "iterations": self._iteration,
            "total_cost": self._router.total_cost,
            "elapsed_seconds": round(elapsed, 1),
            "artifacts": self._artifacts,
        }

    def get_state(self) -> dict:
        """Get current agent state for debugging/monitoring."""
        return {
            "status": self._status.value,
            "iteration": self._iteration,
            "consecutive_errors": self._consecutive_errors,
            "message_count": len(self._messages),
            "current_phase": self._current_phase,
            "total_cost": self._router.total_cost,
            "budget_remaining": self._router.budget_remaining,
            "artifacts": self._artifacts,
            "scratchpad": self._scratchpad.to_dict(),
            "goal_anchor": self._goal_anchor.to_dict(),
            "compaction_count": self._compactor.compaction_count,
        }

    def get_serializable_state(self) -> dict:
        """Get full serializable state for on_stop persistence."""
        return {
            "messages": self._messages,
            "iteration": self._iteration,
            "consecutive_errors": self._consecutive_errors,
            "current_phase": self._current_phase,
            "artifacts": self._artifacts,
            "scratchpad": self._scratchpad.to_dict(),
            "goal_anchor": self._goal_anchor.to_dict(),
            "total_cost": self._router.total_cost,
            "budget_remaining": self._router.budget_remaining,
        }

    def restore_state(self, state: dict) -> None:
        """Restore agent state from on_stop persistence."""
        self._messages = state.get("messages", [])
        self._iteration = state.get("iteration", 0)
        self._consecutive_errors = state.get("consecutive_errors", 0)
        self._current_phase = state.get("current_phase")
        self._artifacts = state.get("artifacts", [])
        if "scratchpad" in state:
            self._scratchpad = Scratchpad.from_dict(state["scratchpad"])
        if "goal_anchor" in state:
            self._goal_anchor = GoalAnchor.from_dict(state["goal_anchor"])
        logger.info(
            f"Agent state restored: iteration={self._iteration}, "
            f"messages={len(self._messages)}, artifacts={len(self._artifacts)}"
        )
