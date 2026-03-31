"""
ARCANE Premium Scenes — Compatibility Matrix
shared/design/premium_scenes/compatibility.py

Матрица совместимости: какие модификаторы разрешены для каждой сцены,
какие слоты обязательны, и специальные правила.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from shared.design.premium_scenes.modifier_enums import validate_modifier_payload


# ─────────────────────────────────────────────────────────────────
#  COMPATIBILITY PROFILE
# ─────────────────────────────────────────────────────────────────

RuleFunc = Callable[[Mapping[str, str], Mapping[str, Any], set[str], int], list[str]]


@dataclass
class CompatibilityProfile:
    """Defines what's allowed for a specific scene."""
    scene_id: str
    allowed: dict[str, set[str]] = field(default_factory=dict)
    required_slots: list[str] = field(default_factory=list)
    rules: list[RuleFunc] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
#  COMPATIBILITY MATRIX
# ─────────────────────────────────────────────────────────────────

COMPATIBILITY_MATRIX: dict[str, CompatibilityProfile] = {

    # ── Hero: Editorial Split ──────────────────────────────────
    "hero.editorial_split.v1": CompatibilityProfile(
        scene_id="hero.editorial_split.v1",
        allowed={
            "theme_pack": {"light_trust_v1", "warm_editorial_v1", "neutral_minimal_v1", "dark_premium_v1", "warm_gold_v1", "dark_elegant_v1"},
            "heading_mode": {"serif_classic", "sans_executive", "display_bold"},
            "body_mode": {"body_clean", "body_editorial"},
            "media_style": {"portrait_editorial", "rect_soft", "square_crop"},
            "button_style": {"filled_accent", "outline_clean", "pill_accent"},
            "decorator_mode": {"none", "grain_soft", "gradient_orbs"},
            "trust_mode": {"none", "social_proof_light", "authority_facts"},
            "spacing_mode": {"balanced_exec", "airy_editorial"},
            "motion_profile": {"motion_off", "motion_minimal", "motion_subtle"},
            "container_mode": {"container_wide", "container_standard"},
        },
        required_slots=["headline", "subheadline", "cta_primary_text", "cta_primary_href", "hero_media_url"],
    ),

    # ── Hero: Legal Authority ──────────────────────────────────
    "hero.legal_authority.v1": CompatibilityProfile(
        scene_id="hero.legal_authority.v1",
        allowed={
            "theme_pack": {"light_trust_v1", "neutral_minimal_v1", "warm_gold_v1", "dark_elegant_v1"},
            "heading_mode": {"serif_classic", "sans_executive"},
            "body_mode": {"body_clean", "body_compact"},
            "media_style": {"portrait_editorial", "rect_soft", "none"},
            "button_style": {"filled_accent", "outline_clean"},
            "decorator_mode": {"none", "line_divider"},
            "trust_mode": {"authority_facts", "legal_precision", "discreet_assurance"},
            "spacing_mode": {"compact_trust", "balanced_exec"},
            "motion_profile": {"motion_off", "motion_minimal"},
            "container_mode": {"container_standard", "container_narrow"},
        },
        required_slots=["headline", "subheadline", "cta_primary_text", "cta_primary_href"],
    ),

    # ── Hero: Cinematic Fullbleed ──────────────────────────────
    "hero.cinematic_fullbleed.v1": CompatibilityProfile(
        scene_id="hero.cinematic_fullbleed.v1",
        allowed={
            "theme_pack": {"dark_premium_v1", "dark_tech_v1", "warm_gold_v1", "dark_elegant_v1"},
            "heading_mode": {"display_bold", "sans_executive", "serif_classic"},
            "body_mode": {"body_clean", "body_editorial"},
            "media_style": {"fullbleed"},
            "button_style": {"filled_accent", "outline_clean", "pill_accent"},
            "decorator_mode": {"none", "grain_soft", "gradient_orbs"},
            "trust_mode": {"none", "social_proof_light"},
            "spacing_mode": {"balanced_exec", "airy_editorial"},
            "motion_profile": {"motion_minimal", "motion_subtle"},
            "container_mode": {"container_wide", "container_standard"},
        },
        required_slots=["headline", "cta_primary_text", "cta_primary_href", "hero_media_url"],
    ),

    # ── Hero: Product Showcase ─────────────────────────────────
    "hero.product_showcase.v1": CompatibilityProfile(
        scene_id="hero.product_showcase.v1",
        allowed={
            "theme_pack": {"light_trust_v1", "neutral_minimal_v1", "dark_tech_v1", "warm_gold_v1", "dark_elegant_v1"},
            "heading_mode": {"sans_executive", "display_bold"},
            "body_mode": {"body_clean", "body_compact"},
            "media_style": {"rect_soft", "square_crop"},
            "button_style": {"filled_accent", "pill_accent"},
            "decorator_mode": {"none", "grid_faint", "gradient_orbs"},
            "trust_mode": {"none", "social_proof_light"},
            "spacing_mode": {"balanced_exec"},
            "motion_profile": {"motion_minimal", "motion_subtle"},
            "container_mode": {"container_wide", "container_standard"},
        },
        required_slots=["headline", "subheadline", "cta_primary_text", "cta_primary_href", "hero_media_url"],
    ),

    # ── Trust: Authority Facts Rail ────────────────────────────
    "trust.authority_facts_rail.v1": CompatibilityProfile(
        scene_id="trust.authority_facts_rail.v1",
        allowed={
            "theme_pack": {"light_trust_v1", "neutral_minimal_v1", "dark_premium_v1", "warm_gold_v1", "dark_elegant_v1"},
            "heading_mode": {"sans_executive", "serif_classic"},
            "body_mode": {"body_compact", "body_clean"},
            "decorator_mode": {"none", "line_divider"},
            "trust_mode": {"authority_facts", "legal_precision"},
            "spacing_mode": {"compact_trust", "balanced_exec"},
            "motion_profile": {"motion_off", "motion_minimal"},
            "container_mode": {"container_wide", "container_standard"},
            "divider_style": {"line_soft", "line_strict", "line_none"},
        },
        required_slots=["facts"],
    ),

    # ── Trust: Case Grid ──────────────────────────────────────
    "trust.case_grid.v1": CompatibilityProfile(
        scene_id="trust.case_grid.v1",
        allowed={
            "theme_pack": {"light_trust_v1", "neutral_minimal_v1", "warm_editorial_v1", "warm_gold_v1", "dark_elegant_v1"},
            "heading_mode": {"serif_classic", "sans_executive"},
            "body_mode": {"body_clean", "body_compact"},
            "surface_style": {"surface_soft", "surface_clean"},
            "decorator_mode": {"none"},
            "trust_mode": {"authority_facts", "social_proof_light"},
            "spacing_mode": {"balanced_exec"},
            "motion_profile": {"motion_off", "motion_minimal"},
            "container_mode": {"container_standard", "container_narrow"},
        },
        required_slots=["cases"],
    ),

    # ── Trust: Comparison Block ────────────────────────────────
    "trust.comparison_block.v1": CompatibilityProfile(
        scene_id="trust.comparison_block.v1",
        allowed={
            "theme_pack": {"light_trust_v1", "neutral_minimal_v1", "warm_gold_v1", "dark_elegant_v1"},
            "heading_mode": {"sans_executive", "serif_classic"},
            "body_mode": {"body_clean", "body_compact"},
            "surface_style": {"surface_soft", "surface_clean"},
            "decorator_mode": {"none"},
            "spacing_mode": {"balanced_exec", "compact_trust"},
            "motion_profile": {"motion_off", "motion_minimal"},
            "container_mode": {"container_standard", "container_narrow"},
        },
        required_slots=["headline", "before_items", "after_items"],
    ),

    # ── Features: Bento Premium ───────────────────────────────
    "features.bento_grid.v1": CompatibilityProfile(
        scene_id="features.bento_grid.v1",
        allowed={
            "theme_pack": {"light_trust_v1", "warm_editorial_v1", "neutral_minimal_v1", "dark_premium_v1", "warm_gold_v1", "dark_elegant_v1"},
            "heading_mode": {"sans_executive", "serif_classic", "display_bold"},
            "body_mode": {"body_clean", "body_compact"},
            "surface_style": {"surface_soft", "surface_clean", "surface_dark"},
            "media_style": {"rect_soft", "square_crop", "none"},
            "accent_card_mode": {"accent_fill", "accent_outline", "accent_glow_soft"},
            "decorator_mode": {"none", "grain_soft"},
            "spacing_mode": {"balanced_exec", "airy_editorial"},
            "motion_profile": {"motion_off", "motion_minimal"},
            "container_mode": {"container_wide", "container_standard"},
        },
        required_slots=["headline", "features"],
    ),

    # ── Features: Editorial Cards ──────────────────────────────
    "features.editorial_cards.v1": CompatibilityProfile(
        scene_id="features.editorial_cards.v1",
        allowed={
            "theme_pack": {"light_trust_v1", "warm_editorial_v1", "neutral_minimal_v1", "warm_gold_v1", "dark_elegant_v1"},
            "heading_mode": {"serif_classic", "sans_executive"},
            "body_mode": {"body_editorial", "body_clean"},
            "surface_style": {"surface_soft", "surface_clean"},
            "media_style": {"rect_soft", "square_crop", "none"},
            "decorator_mode": {"none", "line_divider"},
            "spacing_mode": {"airy_editorial", "balanced_exec"},
            "motion_profile": {"motion_off", "motion_minimal"},
            "container_mode": {"container_standard", "container_narrow"},
        },
        required_slots=["headline", "features"],
    ),

    # ── Features: Process Timeline ────────────────────────────
    "features.timeline_process.v1": CompatibilityProfile(
        scene_id="features.timeline_process.v1",
        allowed={
            "theme_pack": {"light_trust_v1", "neutral_minimal_v1", "dark_premium_v1", "warm_gold_v1", "dark_elegant_v1"},
            "heading_mode": {"sans_executive", "serif_classic"},
            "body_mode": {"body_clean", "body_compact"},
            "decorator_mode": {"none", "line_divider"},
            "spacing_mode": {"balanced_exec", "compact_trust"},
            "motion_profile": {"motion_off", "motion_minimal"},
            "container_mode": {"container_standard", "container_narrow"},
        },
        required_slots=["headline", "steps"],
    ),

    # ── Proof: Stats Bar ──────────────────────────────────────
    "proof.stats_counters.v1": CompatibilityProfile(
        scene_id="proof.stats_counters.v1",
        allowed={
            "theme_pack": {"light_trust_v1", "neutral_minimal_v1", "dark_premium_v1", "dark_tech_v1", "warm_gold_v1", "dark_elegant_v1"},
            "heading_mode": {"sans_executive", "display_bold"},
            "body_mode": {"body_compact", "body_clean"},
            "decorator_mode": {"none", "line_divider"},
            "divider_style": {"line_soft", "line_strict", "line_none"},
            "spacing_mode": {"compact_trust", "balanced_exec"},
            "motion_profile": {"motion_off", "motion_minimal"},
            "container_mode": {"container_wide", "container_standard"},
        },
        required_slots=["stats"],
    ),

    # ── Testimonials: Quote Wall ──────────────────────────────
    "testimonials.quote_wall.v1": CompatibilityProfile(
        scene_id="testimonials.quote_wall.v1",
        allowed={
            "theme_pack": {"light_trust_v1", "warm_editorial_v1", "neutral_minimal_v1", "warm_gold_v1", "dark_elegant_v1"},
            "heading_mode": {"serif_classic", "sans_executive"},
            "body_mode": {"body_editorial", "body_clean"},
            "surface_style": {"surface_soft", "surface_clean"},
            "decorator_mode": {"none", "grain_soft"},
            "spacing_mode": {"balanced_exec", "airy_editorial"},
            "motion_profile": {"motion_off", "motion_minimal"},
            "container_mode": {"container_standard", "container_wide"},
        },
        required_slots=["testimonials"],
    ),

    # ── Testimonials: Marquee ─────────────────────────────────
    "testimonials.marquee.v1": CompatibilityProfile(
        scene_id="testimonials.marquee.v1",
        allowed={
            "theme_pack": {"light_trust_v1", "neutral_minimal_v1", "dark_premium_v1", "warm_gold_v1", "dark_elegant_v1"},
            "heading_mode": {"sans_executive", "serif_classic"},
            "body_mode": {"body_compact", "body_clean"},
            "surface_style": {"surface_soft", "surface_clean", "surface_dark"},
            "decorator_mode": {"none"},
            "spacing_mode": {"compact_trust", "balanced_exec"},
            "motion_profile": {"motion_minimal", "motion_subtle"},
            "container_mode": {"container_wide"},
        },
        required_slots=["testimonials"],
    ),

    # ── CTA: Executive Split ──────────────────────────────────
    "cta.executive_split.v1": CompatibilityProfile(
        scene_id="cta.executive_split.v1",
        allowed={
            "theme_pack": {"light_trust_v1", "dark_premium_v1", "neutral_minimal_v1", "warm_gold_v1", "dark_elegant_v1"},
            "heading_mode": {"serif_classic", "sans_executive", "display_bold"},
            "body_mode": {"body_clean", "body_compact"},
            "button_style": {"filled_accent", "outline_clean", "pill_accent"},
            "decorator_mode": {"none", "gradient_orbs", "grain_soft"},
            "trust_mode": {"none", "discreet_assurance"},
            "spacing_mode": {"balanced_exec", "airy_editorial"},
            "motion_profile": {"motion_off", "motion_minimal"},
            "container_mode": {"container_standard", "container_narrow"},
        },
        required_slots=["headline", "cta_primary_text", "cta_primary_href"],
    ),

    # ── Footer: Authority Contact ──────────────────────────────
    "footer.authority_contact.v1": CompatibilityProfile(
        scene_id="footer.authority_contact.v1",
        allowed={
            "theme_pack": {"light_trust_v1", "neutral_minimal_v1", "dark_premium_v1", "warm_gold_v1", "dark_elegant_v1"},
            "heading_mode": {"sans_executive", "serif_classic"},
            "body_mode": {"body_compact", "body_clean"},
            "decorator_mode": {"none", "line_divider"},
            "divider_style": {"line_soft", "line_strict", "line_none"},
            "icon_style": {"icon_minimal", "icon_outline", "icon_none"},
            "spacing_mode": {"compact_trust", "balanced_exec"},
            "motion_profile": {"motion_off"},
            "container_mode": {"container_wide", "container_standard"},
        },
        required_slots=["brand_name"],
    ),
}


# ─────────────────────────────────────────────────────────────────
#  VALIDATION
# ─────────────────────────────────────────────────────────────────

def validate_scene_compatibility(
    *,
    scene_id: str,
    modifiers: Mapping[str, str],
    content: Mapping[str, Any],
    niche_tags: Sequence[str] | None = None,
    viewport: int = 1440,
) -> dict[str, Any]:
    """Validate modifiers and content slots for a given scene."""
    result: dict[str, Any] = {
        "ok": True,
        "errors": [],
        "warnings": [],
        "scene_id": scene_id,
    }

    # Validate enum values
    enum_errors = validate_modifier_payload(modifiers)
    if enum_errors:
        result["ok"] = False
        result["errors"].extend(enum_errors)
        return result

    # Check scene is known
    if scene_id not in COMPATIBILITY_MATRIX:
        result["warnings"].append(f"Unknown scene profile: {scene_id!r} — skipping compatibility check")
        return result

    profile = COMPATIBILITY_MATRIX[scene_id]

    # Check allowed values per key
    for key, allowed_values in profile.allowed.items():
        value = modifiers.get(key)
        if value is None:
            continue
        if value not in allowed_values:
            result["errors"].append(
                f"Modifier {key!r}={value!r} not allowed for scene {scene_id!r}. "
                f"Allowed: {sorted(allowed_values)}"
            )

    # Check required content slots
    for slot in profile.required_slots:
        value = content.get(slot)
        if value in (None, "", []):
            result["errors"].append(
                f"Required content slot {slot!r} is missing for scene {scene_id!r}"
            )

    # Run custom rules
    niche_tag_set = set(niche_tags or [])
    for rule in profile.rules:
        result["errors"].extend(rule(modifiers, content, niche_tag_set, viewport))

    result["ok"] = len(result["errors"]) == 0
    return result


def recommend_safe_defaults(
    scene_id: str,
    *,
    niche_tags: Sequence[str] | None = None,
) -> dict[str, str]:
    """Return safe default modifiers for a given scene and niche."""
    niche_tag_set = set(niche_tags or [])
    is_warm = bool({"beauty", "restaurant", "hospitality", "luxury_service"} & niche_tag_set)
    is_legal = bool({"legal", "real_estate", "finance"} & niche_tag_set)
    is_tech = bool({"saas", "tech", "software"} & niche_tag_set)

    defaults_map: dict[str, dict[str, str]] = {
        "hero.editorial_split.v1": {
            "theme_pack": "warm_editorial_v1" if is_warm else "light_trust_v1",
            "heading_mode": "serif_classic" if is_warm or is_legal else "sans_executive",
            "body_mode": "body_clean",
            "media_style": "portrait_editorial",
            "button_style": "filled_accent",
            "decorator_mode": "none",
            "trust_mode": "none",
            "spacing_mode": "balanced_exec",
            "motion_profile": "motion_minimal",
            "container_mode": "container_standard",
        },
        "hero.legal_authority.v1": {
            "theme_pack": "light_trust_v1",
            "heading_mode": "serif_classic",
            "body_mode": "body_clean",
            "media_style": "portrait_editorial",
            "button_style": "outline_clean",
            "decorator_mode": "none",
            "trust_mode": "authority_facts",
            "spacing_mode": "balanced_exec",
            "motion_profile": "motion_minimal",
            "container_mode": "container_standard",
        },
        "hero.cinematic_fullbleed.v1": {
            "theme_pack": "dark_premium_v1",
            "heading_mode": "display_bold",
            "body_mode": "body_clean",
            "media_style": "fullbleed",
            "button_style": "pill_accent",
            "decorator_mode": "grain_soft",
            "trust_mode": "none",
            "spacing_mode": "airy_editorial",
            "motion_profile": "motion_subtle",
            "container_mode": "container_standard",
        },
        "hero.product_showcase.v1": {
            "theme_pack": "dark_tech_v1" if is_tech else "light_trust_v1",
            "heading_mode": "display_bold",
            "body_mode": "body_clean",
            "media_style": "rect_soft",
            "button_style": "pill_accent",
            "decorator_mode": "grid_faint",
            "trust_mode": "none",
            "spacing_mode": "balanced_exec",
            "motion_profile": "motion_minimal",
            "container_mode": "container_wide",
        },
        "features.bento_grid.v1": {
            "theme_pack": "warm_editorial_v1" if is_warm else "light_trust_v1",
            "heading_mode": "sans_executive",
            "body_mode": "body_clean",
            "surface_style": "surface_soft",
            "media_style": "rect_soft",
            "accent_card_mode": "accent_fill",
            "decorator_mode": "none",
            "spacing_mode": "balanced_exec",
            "motion_profile": "motion_minimal",
            "container_mode": "container_wide",
        },
        "features.editorial_cards.v1": {
            "theme_pack": "warm_editorial_v1" if is_warm else "light_trust_v1",
            "heading_mode": "serif_classic",
            "body_mode": "body_editorial",
            "surface_style": "surface_soft",
            "media_style": "rect_soft",
            "decorator_mode": "none",
            "spacing_mode": "airy_editorial",
            "motion_profile": "motion_minimal",
            "container_mode": "container_standard",
        },
        "features.timeline_process.v1": {
            "theme_pack": "light_trust_v1",
            "heading_mode": "sans_executive",
            "body_mode": "body_clean",
            "decorator_mode": "none",
            "spacing_mode": "balanced_exec",
            "motion_profile": "motion_minimal",
            "container_mode": "container_standard",
        },
        "trust.authority_facts_rail.v1": {
            "theme_pack": "light_trust_v1",
            "heading_mode": "sans_executive",
            "body_mode": "body_compact",
            "decorator_mode": "none",
            "trust_mode": "authority_facts",
            "spacing_mode": "compact_trust",
            "motion_profile": "motion_off",
            "container_mode": "container_wide",
            "divider_style": "line_soft",
        },
        "trust.case_grid.v1": {
            "theme_pack": "light_trust_v1",
            "heading_mode": "serif_classic",
            "body_mode": "body_clean",
            "surface_style": "surface_soft",
            "decorator_mode": "none",
            "trust_mode": "social_proof_light",
            "spacing_mode": "balanced_exec",
            "motion_profile": "motion_minimal",
            "container_mode": "container_standard",
        },
        "trust.comparison_block.v1": {
            "theme_pack": "light_trust_v1",
            "heading_mode": "sans_executive",
            "body_mode": "body_clean",
            "surface_style": "surface_soft",
            "decorator_mode": "none",
            "spacing_mode": "balanced_exec",
            "motion_profile": "motion_minimal",
            "container_mode": "container_standard",
        },
        "proof.stats_counters.v1": {
            "theme_pack": "light_trust_v1",
            "heading_mode": "display_bold",
            "body_mode": "body_compact",
            "decorator_mode": "none",
            "divider_style": "line_soft",
            "spacing_mode": "compact_trust",
            "motion_profile": "motion_minimal",
            "container_mode": "container_wide",
        },
        "testimonials.quote_wall.v1": {
            "theme_pack": "warm_editorial_v1" if is_warm else "light_trust_v1",
            "heading_mode": "serif_classic",
            "body_mode": "body_editorial",
            "surface_style": "surface_soft",
            "decorator_mode": "none",
            "spacing_mode": "airy_editorial",
            "motion_profile": "motion_minimal",
            "container_mode": "container_standard",
        },
        "testimonials.marquee.v1": {
            "theme_pack": "light_trust_v1",
            "heading_mode": "sans_executive",
            "body_mode": "body_compact",
            "surface_style": "surface_soft",
            "decorator_mode": "none",
            "spacing_mode": "compact_trust",
            "motion_profile": "motion_subtle",
            "container_mode": "container_wide",
        },
        "cta.executive_split.v1": {
            "theme_pack": "dark_premium_v1",
            "heading_mode": "serif_classic" if is_warm or is_legal else "sans_executive",
            "body_mode": "body_clean",
            "button_style": "filled_accent",
            "decorator_mode": "gradient_orbs",
            "trust_mode": "none",
            "spacing_mode": "balanced_exec",
            "motion_profile": "motion_minimal",
            "container_mode": "container_standard",
        },
        "footer.authority_contact.v1": {
            "theme_pack": "light_trust_v1",
            "heading_mode": "sans_executive",
            "body_mode": "body_compact",
            "decorator_mode": "none",
            "divider_style": "line_soft",
            "icon_style": "icon_minimal",
            "spacing_mode": "compact_trust" if is_legal else "balanced_exec",
            "motion_profile": "motion_off",
            "container_mode": "container_wide",
        },
    }

    return defaults_map.get(scene_id, {})
