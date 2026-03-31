"""
ARCANE Chat Service
Step 5: Business logic extracted from compat.py.
Provides reusable chat operations: create, list, delete, rename.
"""
from __future__ import annotations
import uuid
import time
from typing import Optional
from shared.utils.logger import get_logger

logger = get_logger("api.chat_service")


async def create_chat_for_user(
    user_id: str,
    title: str = "Новая задача",
    model_strategy: str = "balanced",
) -> dict:
    """Create a new chat for a user. Returns the created chat dict."""
    from api.chat_store import create_chat as _store_create
    
    chat_id = str(uuid.uuid4())
    await _store_create(
        chat_id=chat_id,
        title=title,
        user_id=user_id,
        model=model_strategy,
        status="idle",
    )
    
    from api.chat_store import get_chat
    chat = get_chat(chat_id)
    if not chat:
        # Return minimal dict if store not yet populated
        chat = {
            "id": chat_id,
            "title": title,
            "user_id": user_id,
            "status": "idle",
            "agent_status": "idle",
            "created_at": time.time(),
            "updated_at": time.time(),
            "model_strategy": model_strategy,
        }
    return chat


async def list_chats_for_user(user_id: str) -> list[dict]:
    """List all chats belonging to a user, sorted by updated_at desc."""
    from api.chat_store import get_chats
    
    all_chats = get_chats()
    user_chats = [
        c for c in all_chats.values()
        if c.get("user_id") == user_id or not c.get("user_id")  # include legacy chats
    ]
    # Sort by updated_at descending
    user_chats.sort(key=lambda c: c.get("updated_at", 0), reverse=True)
    return user_chats


async def delete_chat_for_user(chat_id: str, user_id: str) -> bool:
    """Delete a chat. Returns True if deleted, False if not found."""
    from api.chat_store import get_chat, delete_chat
    
    chat = get_chat(chat_id)
    if not chat:
        return False
    
    await delete_chat(chat_id)
    
    # Also clean up workspace if it exists
    import os
    from config.settings import get_config
    try:
        config = get_config()
        workspace = os.path.join(config.workspace_root, chat_id)
        if os.path.isdir(workspace):
            import shutil
            shutil.rmtree(workspace)
            logger.info(f"Cleaned up workspace for deleted chat {chat_id}")
    except Exception as e:
        logger.warning(f"Failed to clean workspace for chat {chat_id}: {e}")
    
    return True


async def rename_chat_for_user(chat_id: str, user_id: str, new_title: str) -> dict:
    """Rename a chat. Returns updated chat dict."""
    from api.chat_store import get_chat, update_chat
    
    chat = get_chat(chat_id)
    if not chat:
        raise ValueError(f"Chat not found: {chat_id}")
    
    new_title = new_title.strip()[:100] or "Новая задача"
    await update_chat(chat_id, title=new_title)
    
    updated = get_chat(chat_id) or {**chat, "title": new_title}
    return updated


def get_chat_summary(chat: dict) -> dict:
    """Return a summary dict for a chat (for list views)."""
    return {
        "id": chat.get("id", ""),
        "title": chat.get("title", "Новая задача"),
        "status": chat.get("status", "idle"),
        "agent_status": chat.get("agent_status", "idle"),
        "created_at": chat.get("created_at", ""),
        "updated_at": chat.get("updated_at", ""),
        "model_strategy": chat.get("model_strategy", "balanced"),
        "total_cost": chat.get("total_cost", 0.0),
        "message_count": chat.get("message_count", 0),
        "user_id": chat.get("user_id", ""),
    }
