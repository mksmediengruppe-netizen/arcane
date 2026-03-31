"""
ARCANE Error Learning Pipeline
Integrates with coding/SSH workers to:
  1. Check known fixes BEFORE self-healing
  2. Record fixes AFTER successful self-healing
  3. Categorize errors → select appropriate model tier
  4. Check negative playbooks before command execution
"""

from __future__ import annotations

import json
import os
import re
from enum import Enum
from typing import Optional

from shared.utils.logger import get_logger

logger = get_logger("error_learning")


# ─── Error Categories ────────────────────────────────────────────────────────

class ErrorCategory(str, Enum):
    SYNTAX = "syntax"
    DEPENDENCY = "dependency"
    PERMISSION = "permission"
    CONFIG = "config"
    TYPE_ERROR = "type_error"
    LOGIC = "logic"
    ARCHITECTURE = "architecture"
    INFRA = "infra"
    UNKNOWN = "unknown"


class Tier(str, Enum):
    NANO = "NANO"
    FAST = "FAST"
    STANDARD = "STANDARD"
    GENIUS = "GENIUS"
    DEEP = "DEEP"


ERROR_CATEGORY_TIER = {
    ErrorCategory.SYNTAX: Tier.NANO,
    ErrorCategory.DEPENDENCY: Tier.NANO,
    ErrorCategory.PERMISSION: Tier.NANO,
    ErrorCategory.CONFIG: Tier.FAST,
    ErrorCategory.TYPE_ERROR: Tier.FAST,
    ErrorCategory.LOGIC: Tier.GENIUS,
    ErrorCategory.ARCHITECTURE: Tier.GENIUS,
    ErrorCategory.INFRA: Tier.STANDARD,
    ErrorCategory.UNKNOWN: Tier.FAST,
}


# ─── Error Categorization ────────────────────────────────────────────────────

CATEGORY_PATTERNS = {
    ErrorCategory.SYNTAX: [
        r"SyntaxError", r"IndentationError", r"unexpected token",
        r"invalid syntax", r"unterminated string",
    ],
    ErrorCategory.DEPENDENCY: [
        r"ModuleNotFoundError", r"ImportError", r"No module named",
        r"npm ERR.*not found", r"pip.*No matching distribution",
        r"ENOENT.*package\.json",
    ],
    ErrorCategory.PERMISSION: [
        r"PermissionError", r"EACCES", r"Permission denied",
        r"Operation not permitted", r"sudo.*required",
    ],
    ErrorCategory.CONFIG: [
        r"Address already in use", r"Connection refused",
        r"No such file or directory", r"FileNotFoundError",
        r"port.*already.*in.*use", r"EADDRINUSE",
    ],
    ErrorCategory.TYPE_ERROR: [
        r"TypeError", r"ValueError", r"AttributeError",
        r"KeyError", r"IndexError",
    ],
    ErrorCategory.LOGIC: [
        r"AssertionError", r"Expected.*but got",
        r"test.*fail", r"incorrect.*result",
    ],
    ErrorCategory.INFRA: [
        r"No space left on device", r"Out of memory",
        r"MemoryError", r"disk.*full", r"Cannot allocate memory",
    ],
}


def categorize_error(error_output: str) -> ErrorCategory:
    """Categorize an error message into a category."""
    for category, patterns in CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, error_output, re.IGNORECASE):
                return category
    return ErrorCategory.UNKNOWN


def get_heal_tier(error_output: str) -> Tier:
    """Get the recommended model tier for healing an error."""
    category = categorize_error(error_output)
    return ERROR_CATEGORY_TIER.get(category, Tier.FAST)


# ─── Negative Playbooks ──────────────────────────────────────────────────────

_negative_playbooks = None


def _load_negative_playbooks() -> list[dict]:
    """Load negative playbooks from JSON file."""
    global _negative_playbooks
    if _negative_playbooks is not None:
        return _negative_playbooks

    paths = [
        os.path.join(os.path.dirname(__file__), "..", "templates", "negative_playbooks.json"),
        os.path.join(os.path.dirname(__file__), "templates", "negative_playbooks.json"),
        "/opt/arcane/templates/negative_playbooks.json",
    ]

    for path in paths:
        try:
            with open(path) as f:
                data = json.load(f)
                _negative_playbooks = list(data.values()) if isinstance(data, dict) else data
                return _negative_playbooks
        except (FileNotFoundError, json.JSONDecodeError):
            continue

    _negative_playbooks = []
    return _negative_playbooks


def check_negative_playbooks(command: str) -> Optional[str]:
    """
    Check if a command matches a known anti-pattern.
    Returns a warning string or None.
    """
    playbooks = _load_negative_playbooks()

    for pb in playbooks:
        pattern = pb.get("pattern", "")
        try:
            if re.search(pattern, command, re.IGNORECASE):
                error_count = pb.get("error_count", 0)
                common_error = pb.get("common_error", "")
                fix = pb.get("fix", "")
                return (
                    f"WARNING: This matches a known anti-pattern "
                    f"({error_count} previous failures). "
                    f"Common error: {common_error}. "
                    f"Recommended: {fix}"
                )
        except re.error:
            continue

    return None


# ─── Self-Healing Integration ─────────────────────────────────────────────────

class ErrorLearningMixin:
    """
    Mixin for coding/SSH workers to integrate error learning.
    Requires self._memory to be a SuperMemoryEngine instance.
    """

    def _check_known_fix_before_heal(self, error_output: str) -> Optional[dict]:
        """
        Check memory for a known fix BEFORE starting self-healing.
        Returns fix dict if found with high confidence, else None.
        """
        if not hasattr(self, "_memory") or self._memory is None:
            return None

        try:
            known_fix = self._memory.find_known_fix(error_output)
            if known_fix and known_fix.get("success_rate", 0) > 0.7:
                logger.info(
                    f"Found known fix (success_rate={known_fix['success_rate']:.0%}): "
                    f"{known_fix['fix_description'][:100]}"
                )
                return known_fix

            cross_fix = self._memory.find_cross_user_fix(error_output)
            if cross_fix and cross_fix.get("success_rate", 0) > 0.6:
                logger.info(
                    f"Found cross-user fix (success_rate={cross_fix['success_rate']:.0%}): "
                    f"{cross_fix['solution_pattern'][:100]}"
                )
                return {
                    "fix_description": cross_fix["solution_pattern"],
                    "success_rate": cross_fix["success_rate"],
                    "source": "cross_user",
                }
        except Exception as e:
            logger.warning(f"Error checking known fix: {e}")

        return None

    def _record_fix_after_heal(
        self,
        previous_stderr: str,
        fix_description: str,
        fix_tool: str = "coding",
        success: bool = True,
    ):
        """
        Record a fix AFTER successful self-healing iteration.
        """
        if not hasattr(self, "_memory") or self._memory is None:
            return

        try:
            self._memory.record_error_fix(
                error_msg=previous_stderr,
                fix_description=fix_description,
                fix_tool=fix_tool,
                success=success,
            )
            logger.info(f"Recorded error fix: {fix_description[:80]}")
        except Exception as e:
            logger.warning(f"Failed to record fix: {e}")

    def _get_heal_hint(self, error_output: str) -> str:
        """
        Get a hint for the LLM based on known solutions.
        Appended to the error output before sending to LLM.
        """
        if not hasattr(self, "_memory") or self._memory is None:
            return ""

        try:
            cross_fix = self._memory.find_cross_user_fix(error_output)
            if cross_fix:
                return (
                    f"\n\nKnown solution (success rate "
                    f"{cross_fix['success_rate']:.0%}): "
                    f"{cross_fix['solution_pattern']}"
                )
        except Exception:
            pass

        return ""
