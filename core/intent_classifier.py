"""
ARCANE Intent Classifier v1
----------------------------
Replaces keyword-based task routing with a fast LLM call that understands
the user's TRUE intent — just like Manus does.

Intent types:
  web_design   — create a website, landing page, UI, frontend
  devops       — server setup, install software, SSH, Docker, deploy
  coding       — write/fix code, scripts, bots, APIs (no UI)
  data         — analyze data, create charts, spreadsheets
  research     — find info, write reports, summarize
  media        — generate images, video, audio
  automation   — n8n, bots, scheduled tasks, integrations
  general      — everything else

Usage:
  from core.intent_classifier import classify_intent
  result = await classify_intent(llm_client, user_message)
  # result = {"intent": "devops", "confidence": 0.97, "reasoning": "..."}
"""

import json
import logging
from shared.models.schemas import LLMRequest
from typing import Optional

logger = logging.getLogger(__name__)

INTENT_SYSTEM_PROMPT = """You are a task intent classifier. Analyze the user's message and determine what type of task they want to accomplish.

Return ONLY a JSON object with these fields:
- "intent": one of: web_design, devops, coding, data, research, media, automation, general
- "confidence": float 0.0-1.0
- "reasoning": one sentence explaining why

Intent definitions:
- web_design: User wants to CREATE a new website, landing page, UI, frontend, HTML page, portfolio site
- devops: User wants to manage servers, install/configure software (even if that software is a CMS/website platform), SSH, Docker, Nginx, databases, Linux administration, deploy to VPS
- coding: Write code, scripts, bots, APIs, fix bugs — without creating a visual website
- data: Analyze data, create charts, Excel/CSV, dashboards
- research: Find information, write articles, summarize documents
- media: Generate or edit images, video, audio, speech
- automation: n8n workflows, Telegram bots, scheduled tasks, API integrations
- general: Conversation, simple questions, everything else

CRITICAL RULES:
- "Install 1C-Bitrix on a server" = devops (installing software on a server, not creating a website)
- "Install WordPress on VPS" = devops
- "Create a landing page for my company" = web_design
- "Set up Nginx" = devops
- "Write a Python script" = coding
- The KEY distinction: if the user is managing/configuring a SERVER or installing SOFTWARE on a server → devops, NOT web_design

Examples:
User: "установи битрикс на сервер 45.67.57.175 логин root пароль abc"
{"intent": "devops", "confidence": 0.99, "reasoning": "User wants to install software on a remote server via SSH"}

User: "сделай мне лендинг для моей компании"
{"intent": "web_design", "confidence": 0.97, "reasoning": "User wants to create a landing page website"}

User: "очисти сервер и поставь nginx php mysql"
{"intent": "devops", "confidence": 0.99, "reasoning": "Server setup and software installation task"}

User: "напиши телеграм бота на python"
{"intent": "coding", "confidence": 0.92, "reasoning": "Writing a bot script, no server management or visual website"}
"""


async def classify_intent(llm_client, user_message: str, chat_id: str = "") -> dict:
    """
    Classify the user's intent using a fast LLM call.
    Falls back to 'general' on any error.
    """
    try:
        # Use the cheapest/fastest model for classification
        # Load chat context for better classification
        _context_hint = ""
        if chat_id:
            try:
                from api.chat_store import get_messages as _get_msgs
                _prev = _get_msgs(chat_id)
                if _prev:
                    _hints = []
                    for _m in _prev[-5:]:
                        if _m.get("role") == "user":
                            _hints.append(f"User: {_m.get('content', '')[:100]}")
                        elif _m.get("role") == "assistant":
                            _hints.append(f"Assistant: {_m.get('content', '')[:100]}")
                    if _hints:
                        _context_hint = "\nPrevious messages in this chat:\n" + "\n".join(_hints) + "\n\nNow classify the LATEST message:"
            except Exception:
                pass
        
        _request = LLMRequest(
            model_id="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": _context_hint + user_message[:500]},
            ],
            temperature=0.0,
            max_tokens=150,
        )
        _resp = await llm_client.complete(_request, role="classifier", worker="intent")
        content = (_resp.content or "").strip()
        # Extract JSON from response
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        result = json.loads(content)
        intent = result.get("intent", "general")
        confidence = float(result.get("confidence", 0.5))
        reasoning = result.get("reasoning", "")
        logger.info(
            f"Intent classified: {intent} (confidence={confidence:.2f}) — {reasoning}"
        )
        return {"intent": intent, "confidence": confidence, "reasoning": reasoning}
    except Exception as e:
        logger.warning(f"Intent classification failed: {e}, defaulting to 'general'")
        return {"intent": "general", "confidence": 0.0, "reasoning": "classification failed"}


def is_web_design_intent(intent_result: dict) -> bool:
    """Returns True only if the task is genuinely about creating a new website/UI."""
    return (
        intent_result.get("intent") == "web_design"
        and intent_result.get("confidence", 0) >= 0.7
    )


def get_strategy_for_intent(intent_result: dict, requested_strategy: str) -> str:
    """
    Determine the best model strategy based on intent.
    Overrides only when necessary — respects user's explicit choice.
    """
    intent = intent_result.get("intent", "general")
    confidence = intent_result.get("confidence", 0.5)

    # Only override if confidence is high enough
    if confidence < 0.7:
        return requested_strategy

    strategy_map = {
        "web_design": "quality",    # Needs quality for visual output
        "devops": "standard",       # Standard is fine for server tasks
        "coding": "standard",       # Standard for code
        "data": "balance",          # Balance for data analysis
        "research": "balance",      # Balance for research
        "media": "quality",         # Quality for media generation
        "automation": "standard",   # Standard for automation
        "general": requested_strategy,  # Keep user's choice
    }

    suggested = strategy_map.get(intent, requested_strategy)

    # Never downgrade from what user explicitly chose
    strategy_rank = {"economy": 0, "balance": 1, "standard": 2, "quality": 3, "maximum": 4}
    if strategy_rank.get(suggested, 2) > strategy_rank.get(requested_strategy, 2):
        return suggested
    return requested_strategy
