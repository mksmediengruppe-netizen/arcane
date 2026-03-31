"""
ARCANE Memory — Adapter Engine
Bridges the old agent_loop.py API (init_task, record_action, after_chat, get_context_for_task)
to the full Memory v9 engine (shared.memory_v9.engine.SuperMemoryEngine).

Drop-in replacement for shared/memory/engine.py.
Old engine is backed up at shared/memory/engine.py.bak.

The old engine had 909 lines but broken embeddings (OpenRouter 429 errors → zero vectors)
and an outdated Qdrant client API (.search() instead of .query_points()).

This adapter delegates to memory_v9 which uses:
  - Local sentence-transformers embeddings (no API key needed)
  - SQLite-based learning (no MEMORY_DB_URL dependency)
  - Full 26-component memory system
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from shared.utils.logger import get_logger as _get_logger, log_with_data as _log_data
logger = _get_logger("memory_adapter")

# ── Import the real v9 engine ──────────────────────────────────
try:
    from shared.memory_v9.engine import SuperMemoryEngine as _V9Engine
    from shared.memory_v9.learning import ErrorPatterns, EpisodicReplay, ToolLearning
    from shared.memory_v9.semantic import get_semantic
    from shared.memory_v9.session import SessionMemory
    from shared.memory_v9.config import MemoryConfig
    _V9_AVAILABLE = True
    logger.info("Memory v9 engine loaded successfully")
except Exception as e:
    _V9_AVAILABLE = False
    logger.warning(f"Memory v9 import failed, falling back to stub: {e}")


class SuperMemoryEngine:
    """
    Adapter that exposes the OLD API expected by agent_loop.py:
      - init_task(user_message, user_id, chat_id)
      - record_action(tool_name, params, result, success)
      - after_chat(user_message, full_response, chat_id, success)
      - get_context_for_task(task_description) -> str
      - find_known_fix(error_msg) -> Optional[dict]
      - find_cross_user_fix(error_msg) -> Optional[dict]
      - get_stats() -> dict

    Internally delegates to the full memory_v9.SuperMemoryEngine.
    """

    def __init__(self, db_sync_url: str = "", qdrant_url: str = "", call_llm_func=None):
        """
        Accept old-style constructor args (db_sync_url, qdrant_url) for backward compat,
        but actually initialize v9 engine which uses its own config.
        """
        self._v9: Optional[_V9Engine] = None
        self._call_llm = call_llm_func

        # State tracking (mirrors old engine)
        self._current_user_id: str = ""
        self._current_chat_id: str = ""
        self._current_task: str = ""
        self._task_start_time: float = 0
        self._task_actions: list = []

        if _V9_AVAILABLE:
            try:
                self._v9 = _V9Engine(call_llm_func=call_llm_func, enable_planner=False)
                logger.info("Memory v9 SuperMemoryEngine initialized")
            except Exception as e:
                logger.warning(f"Memory v9 init failed: {e}")
                self._v9 = None
        else:
            logger.warning("Memory v9 not available, running in stub mode")

    # ═══════════════════════════════════════════════════════════
    # OLD API: init_task
    # Called by agent_loop.py at the start of each task
    # ═══════════════════════════════════════════════════════════
    def init_task(self, user_message: str, user_id: str = "", chat_id: str = ""):
        """Called at the start of each task. Sets context for memory operations."""
        self._current_user_id = user_id
        self._current_chat_id = chat_id
        self._current_task = user_message
        self._task_start_time = time.time()
        self._task_actions = []

        if self._v9:
            try:
                self._v9.init_task(
                    user_message=user_message,
                    file_content="",
                    user_id=user_id,
                    chat_id=chat_id,
                    api_key="",
                    api_url="",
                    ssh_host="",
                )
                logger.info(f"Memory v9: task initialized for user={user_id}, chat={chat_id}")
            except Exception as e:
                logger.warning(f"Memory v9 init_task failed: {e}")
        else:
            logger.info(f"Memory (stub): task initialized for user={user_id}, chat={chat_id}")

    # ═══════════════════════════════════════════════════════════
    # OLD API: record_action
    # Called by agent_loop.py after each tool execution
    # ═══════════════════════════════════════════════════════════
    def record_action(self, tool_name: str, params: dict, result: str, success: bool):
        """Record a tool action during the current task."""
        self._task_actions.append({
            "tool": tool_name,
            "params_summary": str(params)[:200],
            "result_summary": result[:200] if result else "",
            "success": success,
            "timestamp": time.time(),
        })

        if self._v9:
            try:
                # Delegate to v9's after_tool which does Tool Learning, Error Patterns, etc.
                result_dict = {
                    "success": success,
                    "output": result[:500] if result else "",
                }
                if not success:
                    result_dict["error"] = result[:500] if result else ""

                self._v9.after_tool(
                    tool_name=tool_name,
                    tool_args=params if isinstance(params, dict) else {},
                    result=result_dict,
                    preview=result[:500] if result else "",
                )
            except Exception as e:
                logger.debug(f"Memory v9 after_tool failed: {e}")
        else:
            # Stub: just track tool skill locally
            pass

    # ═══════════════════════════════════════════════════════════
    # OLD API: after_chat
    # Called by agent_loop.py after task completion
    # ═══════════════════════════════════════════════════════════
    def after_chat(
        self,
        user_message: str,
        full_response: str,
        chat_id: str = "",
        success: bool = True,
    ):
        """Called after task completion. Stores episode, reflection, and updates knowledge."""
        if self._v9:
            try:
                self._v9.after_chat(
                    user_message=user_message,
                    full_response=full_response,
                    chat_id=chat_id or self._current_chat_id,
                    success=success,
                )
                logger.info(f"Memory v9: after_chat completed (success={success})")
            except Exception as e:
                logger.warning(f"Memory v9 after_chat failed: {e}")
        else:
            logger.info(f"Memory (stub): after_chat (success={success})")

    # ═══════════════════════════════════════════════════════════
    # OLD API: get_context_for_task
    # Called by agent_loop.py to inject memory into system prompt
    # ═══════════════════════════════════════════════════════════
    # ── Intent keywords for cross-contamination filter ──
    _INTENT_KEYWORDS = {
        "devops": ["bitrix", "битрикс", "1с-битрикс", "install", "установ", "сервер",
                   "nginx", "docker", "ssh", "deploy", "apt", "systemctl", "certbot"],
        "web_design": ["лендинг", "landing", "дизайн", "design", "сайт", "website",
                       "html", "css", "hero", "секци", "визитк", "портфолио"],
    }

    @staticmethod
    def _detect_intent(text: str) -> str:
        """Detect broad intent category from text."""
        text_lower = text.lower()
        for intent, keywords in SuperMemoryEngine._INTENT_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return intent
        return "general"

    def get_context_for_task(self, task_description: str) -> str:
        """
        Build a memory context string to inject into the agent's system prompt.
        Uses v9's semantic search, error patterns, episodic replay, etc.
        FIX: Filters out memories from incompatible intent categories to prevent
        cross-contamination (e.g. Bitrix memories leaking into landing page tasks).
        """
        if not self._v9:
            return ""

        parts = []
        task_intent = self._detect_intent(task_description)

        # 1. Semantic memory search (local embeddings, no API needed)
        try:
            sem = get_semantic()
            # Raise min_score to 0.65 to reduce noise
            results = sem.search(task_description, limit=8, user_id=self._current_user_id,
                                 min_score=0.65)
            if results:
                # Filter out memories from incompatible intents
                filtered = []
                for r in results:
                    mem_intent = self._detect_intent(r.get("content", ""))
                    # Allow: same intent, or general memories
                    if mem_intent == task_intent or mem_intent == "general" or task_intent == "general":
                        filtered.append(r)
                    else:
                        logger.debug(
                            f"Memory filtered: task_intent={task_intent}, "
                            f"mem_intent={mem_intent}, content={r.get('content', '')[:80]}"
                        )

                if filtered:
                    parts.append("## Relevant memories:")
                    for r in filtered[:3]:
                        label = {
                            "episodic": "Past task",
                            "semantic": "Fact",
                            "procedural": "Skill",
                            "knowledge": "Document",
                        }.get(r.get("type", ""), "Note")
                        score = r.get("score", 0)
                        parts.append(f"- [{label}] {r.get('content', '')[:200]} (relevance: {score:.0%})")
        except Exception as e:
            logger.debug(f"Semantic search failed: {e}")

        # 2. Episodic replay — similar successful tasks
        try:
            replay = EpisodicReplay.get_success_replay_prompt(
                task_description, self._current_user_id
            )
            if replay:
                parts.append(f"\n{replay}")
        except Exception as e:
            logger.debug(f"Episodic replay failed: {e}")

        # 3. Error patterns with known fixes
        try:
            # Get recent high-success error fixes
            fixes = ErrorPatterns.get_top_fixes(limit=5)
            if fixes:
                parts.append("\n## Known error fixes:")
                for fix in fixes:
                    parts.append(
                        f"- Error: {fix.get('error', '')[:80]} → Fix: {fix.get('fix', '')[:100]}"
                    )
        except Exception as e:
            logger.debug(f"Error patterns failed: {e}")

        # 4. Tool learning — server profiles
        try:
            # Get skills for recently used tools
            for action in self._task_actions[-5:]:
                tool = action.get("tool", "")
                host = action.get("params_summary", "")
                if "host" in host:
                    profile = ToolLearning.get_server_profile(host)
                    if profile:
                        parts.append(f"\n{profile}")
                        break
        except Exception as e:
            logger.debug(f"Tool learning failed: {e}")

        return "\n".join(parts) if parts else ""

    # ═══════════════════════════════════════════════════════════
    # OLD API: find_known_fix / find_cross_user_fix
    # ═══════════════════════════════════════════════════════════
    def find_known_fix(self, error_msg: str) -> Optional[dict]:
        """Find a known fix for an error from Error Pattern DB."""
        if self._v9:
            try:
                return self._v9.find_known_fix(error_msg)
            except Exception:
                pass
        return None

    def find_cross_user_fix(self, error_msg: str) -> Optional[dict]:
        """Find a fix from anonymous cross-user experience."""
        if self._v9:
            try:
                return self._v9.find_cross_user_fix(error_msg)
            except Exception:
                pass
        return None

    # ═══════════════════════════════════════════════════════════
    # OLD API: get_stats
    # ═══════════════════════════════════════════════════════════
    def get_stats(self) -> dict:
        """Get memory statistics."""
        stats = {
            "engine": "v9" if self._v9 else "stub",
            "task_actions_count": len(self._task_actions),
            "current_user": self._current_user_id,
            "current_chat": self._current_chat_id,
        }

        if self._v9:
            try:
                sem = get_semantic()
                stats["semantic_entries"] = sem.count() if hasattr(sem, "count") else "N/A"
            except Exception:
                pass

            try:
                stats["error_patterns"] = ErrorPatterns.count() if hasattr(ErrorPatterns, "count") else "N/A"
            except Exception:
                pass

        return stats

    # ═══════════════════════════════════════════════════════════
    # EXTENDED API: expose v9 capabilities for future use
    # ═══════════════════════════════════════════════════════════
    @property
    def v9(self) -> Optional[Any]:
        """Direct access to the underlying v9 engine for advanced usage."""
        return self._v9

    def handle_tool(self, tool_name: str, args: dict) -> Optional[dict]:
        """Handle memory-specific tools (update_scratchpad, store_memory, recall_memory)."""
        if self._v9:
            try:
                return self._v9.handle_tool(tool_name, args)
            except Exception:
                pass
        return None
