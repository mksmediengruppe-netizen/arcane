"""
ARCANE UserProfile — Auto-extraction of user preferences from conversations.

After each completed task, analyzes the conversation to extract implicit and explicit
user preferences (language, coding style, frameworks, design preferences, etc.).

Preferences are stored in the user_preferences table and injected into the system
prompt for future tasks, enabling personalized agent behavior.

Uses a cheap model (gpt-5-nano) for extraction to minimize cost.
"""

from __future__ import annotations

import json
from typing import Optional

from shared.utils.logger import get_logger

logger = get_logger("core.user_profile")

# Categories of preferences we extract
PREFERENCE_CATEGORIES = {
    "language": "Preferred spoken/written language for communication",
    "coding_style": "Coding conventions, naming style, indentation, comments",
    "framework": "Preferred frameworks and libraries (React, FastAPI, etc.)",
    "design": "Design preferences (minimal, colorful, dark mode, etc.)",
    "communication": "Communication style (formal, casual, verbose, brief)",
    "tools": "Preferred tools and services (GitHub, Docker, etc.)",
    "deployment": "Deployment preferences (VPS, Vercel, Docker, etc.)",
}

EXTRACTION_PROMPT = """Analyze the following conversation between a user and an AI agent.
Extract any user preferences that were explicitly stated or strongly implied.

Return a JSON array of preferences. Each preference should have:
- "category": one of {categories}
- "key": a short descriptive key (e.g., "preferred_language", "css_framework")
- "value": the preference value (e.g., "Russian", "TailwindCSS")
- "confidence": 0.0-1.0 (1.0 = explicitly stated, 0.5 = implied, 0.3 = guessed)

Only include preferences you are reasonably confident about (confidence >= 0.3).
Return an empty array [] if no preferences can be extracted.
Return ONLY the JSON array, no other text.

Conversation:
{conversation}"""


async def extract_preferences(
    messages: list[dict],
    user_id: str,
    chat_id: str,
    llm_client=None,
) -> list[dict]:
    """
    Extract user preferences from a completed conversation.
    Uses a cheap model to minimize cost.

    Returns list of dicts: [{category, key, value, confidence}]
    """
    if not messages or not llm_client:
        return []

    # Build conversation text (only user and final assistant messages)
    conversation_parts = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""
        if role == "user" and content:
            conversation_parts.append(f"User: {content[:500]}")
        elif role == "assistant" and content and not msg.get("tool_calls"):
            conversation_parts.append(f"Agent: {content[:300]}")

    if len(conversation_parts) < 2:
        return []  # Too short to extract anything

    conversation_text = "\n".join(conversation_parts[-20:])  # Last 20 messages max

    categories_str = ", ".join(PREFERENCE_CATEGORIES.keys())
    prompt = EXTRACTION_PROMPT.format(
        categories=categories_str,
        conversation=conversation_text,
    )

    try:
        # Use the cheapest model available
        response = await llm_client.complete(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-5-nano",
            max_tokens=500,
            temperature=0.1,
        )

        content = response.content.strip()
        # Try to parse JSON from response
        if content.startswith("["):
            preferences = json.loads(content)
        else:
            # Try to find JSON array in response
            start = content.find("[")
            end = content.rfind("]") + 1
            if start >= 0 and end > start:
                preferences = json.loads(content[start:end])
            else:
                return []

        # Validate and filter
        valid_prefs = []
        for pref in preferences:
            if not isinstance(pref, dict):
                continue
            cat = pref.get("category", "")
            key = pref.get("key", "")
            value = pref.get("value", "")
            confidence = float(pref.get("confidence", 0.3))

            if cat in PREFERENCE_CATEGORIES and key and value and confidence >= 0.3:
                valid_prefs.append({
                    "category": cat,
                    "key": key[:255],
                    "value": str(value)[:1000],
                    "confidence": min(max(confidence, 0.0), 1.0),
                })

        logger.info(f"Extracted {len(valid_prefs)} preferences for user {user_id}")
        return valid_prefs

    except Exception as e:
        logger.warning(f"Preference extraction failed: {e}")
        return []


async def save_preferences(
    user_id: str,
    chat_id: str,
    preferences: list[dict],
) -> int:
    """
    Save extracted preferences to the database.
    Uses UPSERT logic: if a preference with the same (user_id, category, key) exists,
    update the value and increase confidence/times_confirmed.

    Returns number of preferences saved/updated.
    """
    if not preferences:
        return 0

    saved = 0
    try:
        from config.settings import get_config
        from shared.models.database import get_session_factory, UserPreference
        from sqlalchemy import select, update
        import datetime

        config = get_config()
        factory = get_session_factory(config.db.url)

        async with factory() as session:
            for pref in preferences:
                # Check if preference already exists
                result = await session.execute(
                    select(UserPreference).where(
                        UserPreference.user_id == user_id,
                        UserPreference.category == pref["category"],
                        UserPreference.key == pref["key"],
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    # Update: increase confidence and times_confirmed
                    new_confidence = min(
                        1.0,
                        existing.confidence + pref["confidence"] * 0.2
                    )
                    await session.execute(
                        update(UserPreference)
                        .where(UserPreference.id == existing.id)
                        .values(
                            value=pref["value"],
                            confidence=new_confidence,
                            times_confirmed=existing.times_confirmed + 1,
                            source_chat_id=chat_id,
                            updated_at=datetime.datetime.utcnow(),
                        )
                    )
                else:
                    # Insert new preference
                    new_pref = UserPreference(
                        user_id=user_id,
                        category=pref["category"],
                        key=pref["key"],
                        value=pref["value"],
                        confidence=pref["confidence"],
                        source="auto",
                        source_chat_id=chat_id,
                    )
                    session.add(new_pref)

                saved += 1

            await session.commit()

    except Exception as e:
        logger.warning(f"Failed to save preferences: {e}")

    logger.info(f"Saved {saved} preferences for user {user_id}")
    return saved


async def get_user_preferences(user_id: str) -> list[dict]:
    """
    Load user preferences from DB.
    Returns list of dicts sorted by confidence (highest first).
    """
    try:
        from config.settings import get_config
        from shared.models.database import get_session_factory, UserPreference
        from sqlalchemy import select

        config = get_config()
        factory = get_session_factory(config.db.url)

        async with factory() as session:
            result = await session.execute(
                select(UserPreference)
                .where(UserPreference.user_id == user_id)
                .order_by(UserPreference.confidence.desc())
            )
            prefs = result.scalars().all()
            return [
                {
                    "category": p.category,
                    "key": p.key,
                    "value": p.value,
                    "confidence": p.confidence,
                    "times_confirmed": p.times_confirmed,
                }
                for p in prefs
            ]
    except Exception as e:
        logger.warning(f"Failed to load preferences for {user_id}: {e}")
        return []


def preferences_to_prompt(preferences: list[dict]) -> str:
    """
    Format user preferences for injection into system prompt.
    Only includes high-confidence preferences.
    """
    if not preferences:
        return ""

    # Filter to confidence >= 0.5
    strong_prefs = [p for p in preferences if p["confidence"] >= 0.5]
    if not strong_prefs:
        return ""

    lines = []
    by_category: dict[str, list[str]] = {}
    for p in strong_prefs:
        cat = p["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(f"{p['key']}: {p['value']}")

    for cat, items in by_category.items():
        lines.append(f"  {cat}:")
        for item in items[:5]:  # Max 5 per category
            lines.append(f"    - {item}")

    return "<user_preferences>\n" + "\n".join(lines) + "\n</user_preferences>"
