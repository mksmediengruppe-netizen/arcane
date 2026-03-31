"""
ARCANE Model Registry
Complete catalog of all LLM models with pricing, capabilities,
role assignments, tier mappings, and fallback chains.

Updated: 2026-03-26 — GPT-5 family, corrected prices, optimized roles.
"""

from __future__ import annotations

from shared.models.schemas import ModelSpec, ModelRole, Provider, Tier


# ═══════════════════════════════════════════════════════════════════════════════
# MODEL CATALOG — every model ARCANE can use
# ═══════════════════════════════════════════════════════════════════════════════

MODELS: dict[str, ModelSpec] = {

    # ── GPT-4.1 Family (via OpenRouter) ──────────────────────────────────────

    "gpt-4.1-nano": ModelSpec(
        id="gpt-4.1-nano",
        provider=Provider.OPENROUTER,
        display_name="GPT-4.1 Nano",
        input_price_per_mtok=0.10,
        output_price_per_mtok=0.40,
        cached_input_price_per_mtok=0.025,
        max_context=1047576,
        supports_vision=False,
        supports_function_calling=True,
    ),
    "gpt-4.1-mini": ModelSpec(
        id="gpt-4.1-mini",
        provider=Provider.OPENROUTER,
        display_name="GPT-4.1 Mini",
        input_price_per_mtok=0.40,
        output_price_per_mtok=1.60,
        cached_input_price_per_mtok=0.10,
        max_context=1047576,
        supports_vision=True,
        supports_function_calling=True,
    ),
    "gpt-4.1": ModelSpec(
        id="gpt-4.1",
        provider=Provider.OPENROUTER,
        display_name="GPT-4.1",
        input_price_per_mtok=2.00,
        output_price_per_mtok=8.00,
        cached_input_price_per_mtok=0.50,
        max_context=1047576,
        supports_vision=True,
        supports_function_calling=True,
    ),

    # ── GPT-5 Family (via OpenRouter) ───────────────────────────────────────

    "gpt-5-nano": ModelSpec(
        id="gpt-5-nano",
        provider=Provider.OPENROUTER,
        display_name="GPT-5 Nano",
        input_price_per_mtok=0.05,
        output_price_per_mtok=0.40,
        cached_input_price_per_mtok=0.0125,
        max_context=1047576,
        supports_vision=False,
        supports_function_calling=True,
    ),
    "gpt-5-mini": ModelSpec(
        id="gpt-5-mini",
        provider=Provider.OPENROUTER,
        display_name="GPT-5 Mini",
        input_price_per_mtok=0.25,
        output_price_per_mtok=2.00,
        cached_input_price_per_mtok=0.0625,
        max_context=1047576,
        supports_vision=True,
        supports_function_calling=True,
    ),
    "gpt-5": ModelSpec(
        id="gpt-5",
        provider=Provider.OPENROUTER,
        display_name="GPT-5",
        input_price_per_mtok=1.25,
        output_price_per_mtok=10.00,
        cached_input_price_per_mtok=0.3125,
        max_context=1047576,
        supports_vision=True,
        supports_function_calling=True,
    ),
    "gpt-5.4": ModelSpec(
        id="gpt-5.4",
        provider=Provider.OPENROUTER,
        display_name="GPT-5.4",
        input_price_per_mtok=2.50,
        output_price_per_mtok=15.00,
        cached_input_price_per_mtok=0.625,
        max_context=1047576,
        supports_vision=True,
        supports_function_calling=True,
    ),

    # ── Reasoning Models (via OpenRouter) ────────────────────────────────────

    "o4-mini": ModelSpec(
        id="o4-mini",
        provider=Provider.OPENROUTER,
        display_name="o4-mini (Reasoning)",
        input_price_per_mtok=1.10,
        output_price_per_mtok=4.40,
        cached_input_price_per_mtok=0.275,
        max_context=200000,
        supports_vision=True,
        supports_function_calling=True,
    ),
    "o3": ModelSpec(
        id="o3",
        provider=Provider.OPENROUTER,
        display_name="o3 (Deep Reasoning)",
        input_price_per_mtok=2.00,
        output_price_per_mtok=8.00,
        cached_input_price_per_mtok=0.50,
        max_context=200000,
        supports_vision=True,
        supports_function_calling=True,
    ),

    # ── OpenRouter (Anthropic) ───────────────────────────────────────────────

    "claude-sonnet-4": ModelSpec(
        id="claude-sonnet-4",
        provider=Provider.OPENROUTER,
        display_name="Claude Sonnet 4.6",
        input_price_per_mtok=3.00,
        output_price_per_mtok=15.00,
        cached_input_price_per_mtok=0.30,
        max_context=200000,
        supports_vision=True,
        supports_function_calling=True,
    ),
    "claude-opus-4": ModelSpec(
        id="claude-opus-4",
        provider=Provider.OPENROUTER,
        display_name="Claude Opus 4.6",
        input_price_per_mtok=5.00,
        output_price_per_mtok=25.00,
        cached_input_price_per_mtok=0.50,
        max_context=200000,
        supports_vision=True,
        supports_function_calling=True,
    ),

    # ── OpenRouter (Google) ──────────────────────────────────────────────────

    "gemini-2.5-flash": ModelSpec(
        id="gemini-2.5-flash",
        provider=Provider.OPENROUTER,
        display_name="Gemini 2.5 Flash",
        input_price_per_mtok=0.30,
        output_price_per_mtok=2.50,
        cached_input_price_per_mtok=0.075,
        max_context=1048576,
        supports_vision=True,
        supports_function_calling=True,
    ),
    "gemini-2.5-pro": ModelSpec(
        id="gemini-2.5-pro",
        provider=Provider.OPENROUTER,
        display_name="Gemini 2.5 Pro",
        input_price_per_mtok=1.25,
        output_price_per_mtok=10.00,
        cached_input_price_per_mtok=0.3125,
        max_context=1048576,
        supports_vision=True,
        supports_function_calling=True,
    ),

    # ── OpenRouter (DeepSeek) ────────────────────────────────────────────────

    "deepseek-r1": ModelSpec(
        id="deepseek-r1",
        provider=Provider.OPENROUTER,
        display_name="DeepSeek R1",
        input_price_per_mtok=0.55,
        output_price_per_mtok=2.19,
        cached_input_price_per_mtok=0.14,
        max_context=128000,
        supports_vision=False,
        supports_function_calling=True,
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
# ROLE → TIER → MODEL MAPPING
# Each role has tiers (NANO, FAST, STANDARD, GENIUS, DEEP).
# Strategy presets select which tier to start with.
# GPT-5 family is primary; Claude/Gemini are fallbacks via OpenRouter.
# ═══════════════════════════════════════════════════════════════════════════════

ROLES: dict[str, ModelRole] = {

    "classifier": ModelRole(
        name="classifier",
        tiers={
            Tier.NANO: "gpt-5-nano",
            Tier.FAST: "gpt-4.1-mini",
        },
        fallback_chain={
            "gpt-5-nano": "gpt-4.1-nano",
            "gpt-4.1-nano": "gpt-4.1-mini",
            "gpt-4.1-mini": "gemini-2.5-flash",
        },
        default_tier=Tier.NANO,
    ),

    "planner": ModelRole(
        name="planner",
        tiers={
            Tier.FAST: "gpt-5-mini",
            Tier.STANDARD: "gpt-5",       # OPTIMIZED: was gpt-5.4 ($2.50/$15) → gpt-5 ($1.25/$10) = 50% savings
            Tier.GENIUS: "gpt-5.4",
        },
        fallback_chain={
            "gpt-5.4": "gpt-5",
            "gpt-5": "gpt-5-mini",
            "gpt-5-mini": "gemini-2.5-flash",
            "gemini-2.5-flash": "claude-sonnet-4",
        },
        default_tier=Tier.STANDARD,
    ),

    "orchestrator": ModelRole(
        name="orchestrator",
        tiers={
            Tier.FAST: "gpt-5-mini",
            Tier.STANDARD: "gpt-5",       # OPTIMIZED: was gpt-5.4 ($2.50/$15) → gpt-5 ($1.25/$10) = 50% savings
            Tier.GENIUS: "gpt-5.4",       # Premium users still get GPT-5.4
        },
        fallback_chain={
            "gpt-5.4": "gpt-5",
            "gpt-5": "gpt-5-mini",
            "gpt-5-mini": "gemini-2.5-flash",
            "gemini-2.5-flash": "claude-sonnet-4",
        },
        default_tier=Tier.STANDARD,
    ),

    "coding": ModelRole(
        name="coding",
        tiers={
            Tier.NANO: "gpt-5-nano",
            Tier.FAST: "gpt-5-mini",
            Tier.STANDARD: "claude-sonnet-4",
            Tier.GENIUS: "claude-opus-4",
        },
        fallback_chain={
            "claude-opus-4": "gpt-5.4",
            "gpt-5.4": "gpt-5",
            "gpt-5": "gpt-5-mini",
            "gpt-5-mini": "gemini-2.5-flash",
            "gemini-2.5-flash": "claude-sonnet-4",
        },
        default_tier=Tier.FAST,
    ),

    "browser": ModelRole(
        name="browser",
        tiers={
            Tier.FAST: "gpt-5-mini",
            Tier.STANDARD: "gpt-5",       # OPTIMIZED: was gpt-5.4 → gpt-5
        },
        fallback_chain={
            "gpt-5.4": "gpt-5",
            "gpt-5": "gpt-5-mini",
            "gpt-5-mini": "gemini-2.5-flash",
            "gemini-2.5-flash": "claude-sonnet-4",
        },
        default_tier=Tier.STANDARD,
    ),

    "ssh": ModelRole(
        name="ssh",
        tiers={
            Tier.FAST: "gpt-5-mini",
            Tier.STANDARD: "gpt-5",
        },
        fallback_chain={
            "gpt-5": "gpt-5-mini",
            "gpt-5-mini": "gemini-2.5-flash",
            "gemini-2.5-flash": "gpt-4.1-mini",
        },
        default_tier=Tier.FAST,
    ),

    "qa": ModelRole(
        name="qa",
        tiers={
            Tier.STANDARD: "gpt-5",
            Tier.DEEP: "o3",
        },
        fallback_chain={
            "o3": "gpt-5.4",
            "gpt-5.4": "gpt-5",
            "gpt-5": "gpt-5-mini",
            "gpt-5-mini": "gemini-2.5-flash",
            "gemini-2.5-flash": "claude-sonnet-4",
        },
        default_tier=Tier.STANDARD,
    ),

    "search": ModelRole(
        name="search",
        tiers={
            Tier.NANO: "gpt-5-nano",
            Tier.FAST: "gpt-4.1-mini",
        },
        fallback_chain={
            "gpt-4.1-mini": "gpt-5-nano",
            "gpt-5-nano": "gpt-4.1-nano",
            "gpt-4.1-nano": "gemini-2.5-flash",
        },
        default_tier=Tier.FAST,
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY PRESETS — which tier each role starts at
# ═══════════════════════════════════════════════════════════════════════════════

STRATEGY_TIER_MAP: dict[str, dict[str, Tier]] = {
    "economy": {
        "classifier": Tier.NANO,
        "planner": Tier.FAST,
        "orchestrator": Tier.FAST,
        "coding": Tier.NANO,
        "browser": Tier.FAST,
        "ssh": Tier.FAST,
        "qa": Tier.STANDARD,
        "search": Tier.NANO,
    },
    "balance": {
        "classifier": Tier.NANO,
        "planner": Tier.STANDARD,
        "orchestrator": Tier.STANDARD,
        "coding": Tier.FAST,
        "browser": Tier.STANDARD,
        "ssh": Tier.FAST,
        "qa": Tier.STANDARD,
        "search": Tier.FAST,
    },
    "quality": {
        "classifier": Tier.NANO,
        "planner": Tier.STANDARD,
        "orchestrator": Tier.STANDARD,
        "coding": Tier.STANDARD,
        "browser": Tier.STANDARD,
        "ssh": Tier.STANDARD,
        "qa": Tier.DEEP,
        "search": Tier.FAST,
    },
    "maximum": {
        "classifier": Tier.NANO,
        "planner": Tier.GENIUS,
        "orchestrator": Tier.GENIUS,
        "coding": Tier.GENIUS,
        "browser": Tier.STANDARD,
        "ssh": Tier.STANDARD,
        "qa": Tier.DEEP,
        "search": Tier.FAST,
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# ESCALATION ORDER — when a tier fails, escalate to the next
# ═══════════════════════════════════════════════════════════════════════════════

TIER_ESCALATION_ORDER: list[Tier] = [
    Tier.NANO,
    Tier.FAST,
    Tier.STANDARD,
    Tier.GENIUS,
    Tier.DEEP,
]


def get_next_tier(current: Tier) -> Tier | None:
    """Return the next tier in escalation order, or None if at max."""
    try:
        idx = TIER_ESCALATION_ORDER.index(current)
        if idx + 1 < len(TIER_ESCALATION_ORDER):
            return TIER_ESCALATION_ORDER[idx + 1]
    except ValueError:
        pass
    return None


def get_model_for_role(role: str, tier: Tier) -> ModelSpec | None:
    """Resolve a model spec for a given role and tier."""
    role_def = ROLES.get(role)
    if not role_def:
        return None
    model_id = role_def.tiers.get(tier)
    if not model_id:
        # Find nearest lower tier
        for t in reversed(TIER_ESCALATION_ORDER):
            if t.value <= tier.value and t in role_def.tiers:
                model_id = role_def.tiers[t]
                break
    if not model_id:
        return None
    return MODELS.get(model_id)


def get_fallback_model(role: str, current_model_id: str) -> ModelSpec | None:
    """Get the fallback model when the current one is unavailable."""
    role_def = ROLES.get(role)
    if not role_def:
        return None
    fallback_id = role_def.fallback_chain.get(current_model_id)
    if not fallback_id:
        return None
    return MODELS.get(fallback_id)
