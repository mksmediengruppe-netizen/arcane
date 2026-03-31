"""
ARCANE Usage Tracker
Tracks all LLM API costs per project, per user, per worker.
Provides real-time budget monitoring, breakdown reports,
and persistent storage to PostgreSQL.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Optional

from shared.models.schemas import (
    BudgetStatus,
    Provider,
    Tier,
    UsageRecord,
)
from shared.utils.logger import get_logger, log_with_data

logger = get_logger("llm.usage_tracker")


class UsageTracker:
    """
    In-memory usage tracker with periodic flush to database.
    Aggregates costs by project, user, worker, and model.
    """

    def __init__(self):
        # project_id -> list of records
        self._records: dict[str, list[UsageRecord]] = defaultdict(list)
        # project_id -> budget_limit
        self._budgets: dict[str, float] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def record(self, usage: UsageRecord) -> None:
        """Record a single LLM API call."""
        async with self._lock:
            self._records[usage.project_id].append(usage)

        log_with_data(
            logger, "DEBUG",
            f"Usage recorded",
            project_id=usage.project_id,
            model=usage.model_id,
            cost=usage.cost_usd,
            worker=usage.worker,
            tier=usage.tier.value if usage.tier else "none",
        )

    async def record_batch(self, records: list[UsageRecord]) -> None:
        """Record multiple usage records at once."""
        async with self._lock:
            for r in records:
                self._records[r.project_id].append(r)

    def set_budget(self, project_id: str, limit: float) -> None:
        """Set or update the budget limit for a project."""
        self._budgets[project_id] = limit

    async def get_budget_status(self, project_id: str) -> BudgetStatus:
        """Get current budget status for a project."""
        async with self._lock:
            records = self._records.get(project_id, [])
            budget_limit = self._budgets.get(project_id, 5.0)

            total_spent = sum(r.cost_usd for r in records)
            remaining = max(0.0, budget_limit - total_spent)
            pct = (total_spent / budget_limit * 100) if budget_limit > 0 else 0

            # Breakdown by worker
            by_worker: dict[str, float] = defaultdict(float)
            for r in records:
                by_worker[r.worker] += r.cost_usd

            # Breakdown by model
            by_model: dict[str, float] = defaultdict(float)
            for r in records:
                by_model[r.model_id] += r.cost_usd

            return BudgetStatus(
                project_id=project_id,
                budget_limit=budget_limit,
                budget_spent=round(total_spent, 6),
                budget_remaining=round(remaining, 6),
                percentage_used=round(pct, 1),
                is_warning=pct >= 90,
                is_exceeded=pct >= 100,
                total_calls=len(records),
                breakdown_by_worker=dict(by_worker),
                breakdown_by_model=dict(by_model),
            )

    async def get_project_summary(self, project_id: str) -> dict:
        """Get a detailed summary of all usage for a project."""
        async with self._lock:
            records = self._records.get(project_id, [])

            if not records:
                return {
                    "project_id": project_id,
                    "total_calls": 0,
                    "total_cost": 0.0,
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_cached_tokens": 0,
                    "by_worker": {},
                    "by_model": {},
                    "by_tier": {},
                    "by_provider": {},
                    "escalation_count": 0,
                    "error_count": 0,
                    "avg_latency_ms": 0,
                }

            total_cost = sum(r.cost_usd for r in records)
            total_input = sum(r.input_tokens for r in records)
            total_output = sum(r.output_tokens for r in records)
            total_cached = sum(r.cached_tokens for r in records)
            escalations = sum(1 for r in records if r.escalated)
            errors = sum(1 for r in records if r.error)
            avg_latency = sum(r.latency_ms for r in records) / len(records)

            # Breakdowns
            by_worker: dict[str, dict] = defaultdict(
                lambda: {"calls": 0, "cost": 0.0, "tokens": 0}
            )
            for r in records:
                by_worker[r.worker]["calls"] += 1
                by_worker[r.worker]["cost"] += r.cost_usd
                by_worker[r.worker]["tokens"] += r.input_tokens + r.output_tokens

            by_model: dict[str, dict] = defaultdict(
                lambda: {"calls": 0, "cost": 0.0}
            )
            for r in records:
                by_model[r.model_id]["calls"] += 1
                by_model[r.model_id]["cost"] += r.cost_usd

            by_tier: dict[str, dict] = defaultdict(
                lambda: {"calls": 0, "cost": 0.0}
            )
            for r in records:
                tier_name = r.tier.value if r.tier else "none"
                by_tier[tier_name]["calls"] += 1
                by_tier[tier_name]["cost"] += r.cost_usd

            by_provider: dict[str, dict] = defaultdict(
                lambda: {"calls": 0, "cost": 0.0}
            )
            for r in records:
                by_provider[r.provider.value]["calls"] += 1
                by_provider[r.provider.value]["cost"] += r.cost_usd

            return {
                "project_id": project_id,
                "total_calls": len(records),
                "total_cost": round(total_cost, 6),
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_cached_tokens": total_cached,
                "by_worker": dict(by_worker),
                "by_model": dict(by_model),
                "by_tier": dict(by_tier),
                "by_provider": dict(by_provider),
                "escalation_count": escalations,
                "error_count": errors,
                "avg_latency_ms": round(avg_latency),
            }

    async def get_user_total_spent(self, user_id: str) -> float:
        """Get total spending across all projects for a user."""
        async with self._lock:
            total = 0.0
            for records in self._records.values():
                for r in records:
                    if r.user_id == user_id:
                        total += r.cost_usd
            return round(total, 6)

    async def get_all_records(self, project_id: str) -> list[UsageRecord]:
        """Get all raw usage records for a project."""
        async with self._lock:
            return list(self._records.get(project_id, []))

    async def flush_to_db(self, db_session) -> int:
        """
        Flush all in-memory records to the database.
        Returns the number of records flushed.
        Called periodically or on project completion.
        """
        async with self._lock:
            count = 0
            for project_id, records in self._records.items():
                for record in records:
                    # TODO: Insert into PostgreSQL usage_records table
                    count += 1
            # Clear flushed records
            self._records.clear()
            return count


# Singleton instance
_tracker: Optional[UsageTracker] = None


def get_usage_tracker() -> UsageTracker:
    """Get the global usage tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = UsageTracker()
    return _tracker
