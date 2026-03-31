"""
ARCANE Telegram Notifier

Sends task completion notifications to users via Telegram Bot API.

Setup:
1. Create a bot via @BotFather
2. Set TELEGRAM_BOT_TOKEN in environment
3. Users link their Telegram by sending /start to the bot
4. The bot stores the chat_id in the user's profile

Notifications are sent for:
- Task completion (with summary and cost)
- Task failure (with error details)
- Long-running task progress updates
"""

from __future__ import annotations

import os
import time
from typing import Optional

import httpx

from shared.utils.logger import get_logger

logger = get_logger("workers.telegram_notifier")

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


class TelegramNotifier:
    """Send notifications to users via Telegram."""

    def __init__(self, bot_token: Optional[str] = None):
        self._bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        """Check if Telegram bot token is set."""
        return bool(self._bot_token)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=f"{TELEGRAM_API_BASE}{self._bot_token}",
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> dict:
        """
        Send a text message to a Telegram chat.

        Args:
            chat_id: Telegram chat ID
            text: Message text (HTML or Markdown)
            parse_mode: "HTML" or "MarkdownV2"
            disable_notification: Send silently

        Returns:
            dict with success status and message_id
        """
        if not self.is_configured:
            return {"success": False, "error": "Telegram bot token not configured"}

        if not chat_id:
            return {"success": False, "error": "chat_id is required"}

        client = await self._get_client()

        try:
            resp = await client.post(
                "/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text[:4096],  # Telegram message limit
                    "parse_mode": parse_mode,
                    "disable_notification": disable_notification,
                },
            )
            data = resp.json()

            if data.get("ok"):
                message_id = data.get("result", {}).get("message_id")
                logger.info(f"Telegram message sent to {chat_id}: {message_id}")
                return {"success": True, "message_id": message_id}
            else:
                error = data.get("description", "Unknown error")
                logger.warning(f"Telegram send failed: {error}")
                return {"success": False, "error": error}

        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return {"success": False, "error": str(e)}

    async def send_document(
        self,
        chat_id: str,
        file_path: str,
        caption: str = "",
    ) -> dict:
        """Send a file/document to a Telegram chat."""
        if not self.is_configured:
            return {"success": False, "error": "Telegram bot token not configured"}

        if not os.path.isfile(file_path):
            return {"success": False, "error": f"File not found: {file_path}"}

        client = await self._get_client()

        try:
            with open(file_path, "rb") as f:
                resp = await client.post(
                    "/sendDocument",
                    data={
                        "chat_id": chat_id,
                        "caption": caption[:1024],
                    },
                    files={"document": (os.path.basename(file_path), f)},
                )
            data = resp.json()

            if data.get("ok"):
                return {"success": True, "message_id": data["result"]["message_id"]}
            else:
                return {"success": False, "error": data.get("description", "Unknown")}

        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Notification Templates ───────────────────────────────────────────────

    async def notify_task_complete(
        self,
        chat_id: str,
        task_summary: str,
        cost_usd: float = 0.0,
        duration_seconds: float = 0.0,
        artifacts: Optional[list[str]] = None,
    ) -> dict:
        """Send a task completion notification."""
        duration_str = _format_duration(duration_seconds)
        cost_str = f"${cost_usd:.4f}" if cost_usd > 0 else "N/A"

        text = (
            f"<b>✅ Task Complete</b>\n\n"
            f"{_escape_html(task_summary)}\n\n"
            f"⏱ Duration: {duration_str}\n"
            f"💰 Cost: {cost_str}"
        )

        if artifacts:
            text += "\n\n📎 Artifacts:\n"
            for artifact in artifacts[:5]:
                name = os.path.basename(artifact)
                text += f"  • {_escape_html(name)}\n"

        return await self.send_message(chat_id, text)

    async def notify_task_failed(
        self,
        chat_id: str,
        task_summary: str,
        error_message: str,
        cost_usd: float = 0.0,
    ) -> dict:
        """Send a task failure notification."""
        cost_str = f"${cost_usd:.4f}" if cost_usd > 0 else "N/A"

        text = (
            f"<b>❌ Task Failed</b>\n\n"
            f"{_escape_html(task_summary)}\n\n"
            f"<b>Error:</b> {_escape_html(error_message[:500])}\n"
            f"💰 Cost spent: {cost_str}"
        )

        return await self.send_message(chat_id, text)

    async def notify_task_progress(
        self,
        chat_id: str,
        task_summary: str,
        progress_message: str,
        iteration: int = 0,
        max_iterations: int = 0,
    ) -> dict:
        """Send a progress update for long-running tasks."""
        progress = ""
        if max_iterations > 0:
            pct = min(100, int(iteration / max_iterations * 100))
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            progress = f"\n\n{bar} {pct}% ({iteration}/{max_iterations})"

        text = (
            f"<b>⏳ Task in Progress</b>\n\n"
            f"{_escape_html(task_summary)}\n\n"
            f"{_escape_html(progress_message)}"
            f"{progress}"
        )

        return await self.send_message(chat_id, text, disable_notification=True)

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


def _escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s}s"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"


# Singleton
_notifier: Optional[TelegramNotifier] = None


def get_telegram_notifier(bot_token: Optional[str] = None) -> TelegramNotifier:
    """Get or create the singleton Telegram notifier."""
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier(bot_token)
    return _notifier
