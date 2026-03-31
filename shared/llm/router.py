"""
ARCANE Model Router
Intelligent routing of LLM requests based on:
  - Role (coding, qa, browser, ssh, planner, orchestrator, search, classifier)
  - Tier (NANO → FAST → STANDARD → GENIUS → DEEP)
  - Strategy preset (economy, balance, quality, maximum)
  - Automatic escalation on failure
  - Fallback chains when a provider is down
"""

from __future__ import annotations

from typing import Optional

from shared.llm.client import (
    BudgetExceededError,
    ProviderUnavailableError,
    UnifiedLLMClient,
)
from shared.llm.model_registry import (
    MODELS,
    ROLES,
    STRATEGY_TIER_MAP,
    get_fallback_model,
    get_model_for_role,
    get_next_tier,
)
from shared.models.schemas import (
    LLMRequest,
    LLMResponse,
    Tier,
    UsageRecord,
)
from shared.utils.logger import get_logger, log_with_data

logger = get_logger("llm.router")


class ModelRouter:
    """
    Routes LLM requests through the correct model based on role,
    strategy, and tier. Handles automatic escalation when a lower
    tier fails to produce acceptable results.

    Usage:
        router = ModelRouter(client, strategy="balance")
        response = await router.route(
            messages=[...],
            role="coding",
            tools=[...],
            user_id="user123",
            project_id="proj456",
        )
    """

    def __init__(
        self,
        client: UnifiedLLMClient,
        strategy: str = "balance",
        budget_limit: float = 5.0,
        budget_spent: float = 0.0,
    ):
        self._client = client
        self._strategy = strategy
        self._budget_limit = budget_limit
        self._budget_spent = budget_spent
        self._usage_log: list[UsageRecord] = []

    @property
    def budget_remaining(self) -> float:
        return max(0.0, self._budget_limit - self._budget_spent)

    @property
    def total_cost(self) -> float:
        return self._budget_spent

    @property
    def usage_log(self) -> list[UsageRecord]:
        return self._usage_log

    def _resolve_tier(self, role: str, tier_override: Optional[Tier] = None) -> Tier:
        """Determine the starting tier for a role based on strategy."""
        if tier_override:
            return tier_override
        strategy_map = STRATEGY_TIER_MAP.get(self._strategy, STRATEGY_TIER_MAP["balance"])
        return strategy_map.get(role, Tier.FAST)

    def _resolve_model_id(self, role: str, tier: Tier) -> str | None:
        """Get the model ID for a role at a specific tier."""
        spec = get_model_for_role(role, tier)
        return spec.id if spec else None

    async def route(
        self,
        messages: list[dict],
        role: str,
        tools: list[dict] | None = None,
        tier_override: Tier | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        worker: str = "unknown",
        allow_escalation: bool = True,
        max_escalations: int = 2,
    ) -> LLMResponse:
        """
        Route a request through the model hierarchy.

        Flow:
        1. Resolve starting tier from strategy + role
        2. Get model for that tier
        3. Call UnifiedLLMClient
        4. If provider unavailable → try fallback chain
        5. If result quality is poor → escalate to next tier
        6. Track usage and cost
        """
        # Budget check
        if self._budget_spent >= self._budget_limit:
            raise BudgetExceededError(
                f"Budget exhausted: ${self._budget_spent:.2f} / ${self._budget_limit:.2f}"
            )

        current_tier = self._resolve_tier(role, tier_override)
        escalation_count = 0

        while True:
            model_id = self._resolve_model_id(role, current_tier)
            if not model_id:
                # No model for this tier, try next
                next_tier = get_next_tier(current_tier)
                if next_tier and allow_escalation:
                    current_tier = next_tier
                    continue
                raise ValueError(
                    f"No model available for role={role}, tier={current_tier}"
                )

            log_with_data(
                logger, "INFO",
                f"Routing request",
                role=role,
                tier=current_tier.value,
                model=model_id,
                strategy=self._strategy,
                budget_remaining=self.budget_remaining,
                escalation=escalation_count,
            )

            request = LLMRequest(
                messages=messages,
                model_id=model_id,
                role=role,
                tier=current_tier,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
                user_id=user_id,
                project_id=project_id,
            )

            try:
                response = await self._client.complete(
                    request, role=role, worker=worker
                )
                response.tier = current_tier

                # Track usage
                self._track_usage(
                    response, role, worker, user_id, project_id,
                    escalated=(escalation_count > 0),
                )

                return response

            except ProviderUnavailableError as e:
                # STEP 1: Try fallback chain FIRST (cheaper models)
                fallback_spec = get_fallback_model(role, model_id)
                if fallback_spec:
                    log_with_data(
                        logger, "INFO",
                        f"Trying fallback: {model_id} → {fallback_spec.id}",
                        role=role,
                        from_model=model_id,
                        to_model=fallback_spec.id,
                    )
                    fallback_request = LLMRequest(
                        messages=messages,
                        model_id=fallback_spec.id,
                        role=role,
                        tier=current_tier,
                        tools=tools,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=False,
                        user_id=user_id,
                        project_id=project_id,
                    )
                    try:
                        response = await self._client.complete(
                            fallback_request, role=role, worker=worker
                        )
                        response.tier = current_tier
                        self._track_usage(
                            response, role, worker, user_id, project_id,
                            escalated=True,
                        )
                        return response
                    except ProviderUnavailableError:
                        log_with_data(
                            logger, "WARNING",
                            f"Fallback {fallback_spec.id} also unavailable",
                            role=role,
                        )

                # STEP 2: Only if fallback failed — escalate tier (more expensive)
                if allow_escalation and escalation_count < max_escalations:
                    next_tier = get_next_tier(current_tier)
                    if next_tier:
                        escalation_count += 1
                        log_with_data(
                            logger, "WARNING",
                            f"Escalating from {current_tier.value} to {next_tier.value}",
                            role=role,
                            from_tier=current_tier.value,
                            to_tier=next_tier.value,
                            escalation=escalation_count,
                        )
                        current_tier = next_tier
                        continue
                raise

    async def route_with_self_healing(
        self,
        messages: list[dict],
        role: str,
        tools: list[dict] | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        worker: str = "unknown",
        max_heal_iterations: int = 5,
        error_handler=None,
    ) -> LLMResponse:
        """
        Route with automatic tier escalation on repeated failures.

        After N failures at the current tier, escalate to the next tier.
        This is used by the coding worker's self-healing loop.

        Args:
            error_handler: async callable(response, iteration) -> bool
                Returns True if the response is acceptable, False to retry.
        """
        current_tier = self._resolve_tier(role)
        failures_at_tier = 0
        max_failures_before_escalation = 2

        for iteration in range(1, max_heal_iterations + 1):
            try:
                response = await self.route(
                    messages=messages,
                    role=role,
                    tools=tools,
                    tier_override=current_tier,
                    user_id=user_id,
                    project_id=project_id,
                    worker=worker,
                    allow_escalation=False,  # we handle escalation here
                )

                # If no error handler, return immediately
                if error_handler is None:
                    return response

                # Check if result is acceptable
                is_ok = await error_handler(response, iteration)
                if is_ok:
                    return response

                # Result not acceptable — count as failure
                failures_at_tier += 1
                if failures_at_tier >= max_failures_before_escalation:
                    next_tier = get_next_tier(current_tier)
                    if next_tier:
                        log_with_data(
                            logger, "WARNING",
                            f"Self-healing escalation after {failures_at_tier} failures",
                            role=role,
                            from_tier=current_tier.value,
                            to_tier=next_tier.value,
                            iteration=iteration,
                        )
                        current_tier = next_tier
                        failures_at_tier = 0

            except ProviderUnavailableError:
                next_tier = get_next_tier(current_tier)
                if next_tier:
                    current_tier = next_tier
                    failures_at_tier = 0
                    continue
                raise

        # All iterations exhausted
        log_with_data(
            logger, "ERROR",
            f"Self-healing exhausted after {max_heal_iterations} iterations",
            role=role,
            final_tier=current_tier.value,
        )
        # Return last response anyway
        return await self.route(
            messages=messages,
            role=role,
            tools=tools,
            tier_override=current_tier,
            user_id=user_id,
            project_id=project_id,
            worker=worker,
        )

    def _track_usage(
        self,
        response: LLMResponse,
        role: str,
        worker: str,
        user_id: str | None,
        project_id: str | None,
        escalated: bool = False,
    ) -> None:
        """Record usage and update budget."""
        self._budget_spent += response.cost_usd

        record = UsageRecord(
            project_id=project_id or "",
            user_id=user_id or "",
            model_id=response.model_id,
            provider=response.provider,
            tier=response.tier,
            worker=worker,
            role=role,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cached_tokens=response.cached_tokens,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            escalated=escalated,
        )
        self._usage_log.append(record)

        # Budget warning
        pct = (self._budget_spent / self._budget_limit * 100) if self._budget_limit > 0 else 0
        if pct >= 90:
            log_with_data(
                logger, "WARNING",
                f"Budget warning: {pct:.0f}% used",
                budget_spent=self._budget_spent,
                budget_limit=self._budget_limit,
                project_id=project_id,
            )

    def update_budget(self, new_limit: float | None = None, new_spent: float | None = None):
        """Update budget parameters (e.g., after loading from DB)."""
        if new_limit is not None:
            self._budget_limit = new_limit
        if new_spent is not None:
            self._budget_spent = new_spent
