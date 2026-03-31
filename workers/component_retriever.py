"""
ARCANE Premium Scenes — Component Retriever v2
workers/component_retriever.py

Real metadata-driven retrieval with niche filtering, style scoring, and ranking.
Replaces the static dict lookup with a proper catalog + scoring pipeline.

Each template has metadata: section_type, niches, styles, themes, complexity, slots.
Retrieval: filter by section_type → score by niche/style/theme affinity → rank → return top-N.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────────────
TEMPLATES_BASE = Path(os.environ.get(
    "ARCANE_TEMPLATES_DIR",
    "/root/arcane/templates/premium_scenes",
))


# ─────────────────────────────────────────────────────────────────
#  TEMPLATE METADATA
# ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TemplateMeta:
    """Rich metadata for a single HTML template."""
    scene_id: str
    file: str
    section_type: str          # hero, trust, features, proof, testimonials, cta, footer, gallery, pricing, parallax, about
    niches: frozenset[str]     # which niches this template fits best ("*" = universal)
    styles: frozenset[str]     # visual style tags: editorial, cinematic, minimal, bold, elegant, tech
    themes: frozenset[str]     # compatible theme packs: light_trust_v1, dark_premium_v1, etc.
    complexity: int            # 1=simple section, 2=medium, 3=rich/animated
    slots: frozenset[str]      # required content slots: headline, subheadline, features, stats, etc.
    description: str = ""      # human-readable description for debugging


# ─────────────────────────────────────────────────────────────────
#  TEMPLATE CATALOG — single source of truth
# ─────────────────────────────────────────────────────────────────
_UNIVERSAL = frozenset({"*"})
_ALL_THEMES = frozenset({
    "light_trust_v1", "dark_premium_v1", "dark_tech_v1", "dark_elegant_v1",
    "warm_editorial_v1", "warm_gold_v1", "neutral_minimal_v1",
})

TEMPLATE_CATALOG: tuple[TemplateMeta, ...] = (
    # ── HERO ──
    TemplateMeta(
        scene_id="hero.editorial_split.v1",
        file="hero_editorial_split.html",
        section_type="hero",
        niches=frozenset({"real_estate", "legal", "finance", "education", "saas", "medical"}),
        styles=frozenset({"editorial", "clean", "professional"}),
        themes=frozenset({"light_trust_v1", "neutral_minimal_v1", "warm_editorial_v1"}),
        complexity=2,
        slots=frozenset({"headline", "subheadline", "cta_text", "image_url"}),
        description="Split-layout hero with editorial typography, image on one side",
    ),
    TemplateMeta(
        scene_id="hero.legal_authority.v1",
        file="hero_legal_authority.html",
        section_type="hero",
        niches=frozenset({"legal", "finance", "medical", "real_estate"}),
        styles=frozenset({"authoritative", "formal", "trust"}),
        themes=frozenset({"light_trust_v1", "dark_elegant_v1"}),
        complexity=2,
        slots=frozenset({"headline", "subheadline", "cta_text", "credentials"}),
        description="Authority-focused hero for professional services",
    ),
    TemplateMeta(
        scene_id="hero.cinematic_fullbleed.v1",
        file="hero_cinematic_fullbleed.html",
        section_type="hero",
        niches=frozenset({"restaurant", "fitness", "beauty", "hospitality", "luxury_service"}),
        styles=frozenset({"cinematic", "bold", "immersive"}),
        themes=frozenset({"dark_premium_v1", "dark_elegant_v1", "warm_gold_v1", "warm_editorial_v1"}),
        complexity=3,
        slots=frozenset({"headline", "subheadline", "cta_text", "bg_image_url"}),
        description="Full-bleed cinematic hero with background image/video",
    ),
    TemplateMeta(
        scene_id="hero.product_showcase.v1",
        file="hero_product_showcase.html",
        section_type="hero",
        niches=frozenset({"saas", "education"}),
        styles=frozenset({"tech", "modern", "showcase"}),
        themes=frozenset({"light_trust_v1", "dark_tech_v1", "neutral_minimal_v1"}),
        complexity=3,
        slots=frozenset({"headline", "subheadline", "cta_text", "product_image_url", "features_preview"}),
        description="Product-focused hero with screenshot/mockup showcase",
    ),

    # ── TRUST ──
    TemplateMeta(
        scene_id="trust.authority_facts_rail.v1",
        file="trust_authority_facts_rail.html",
        section_type="trust",
        niches=frozenset({"legal", "finance", "medical", "real_estate", "education"}),
        styles=frozenset({"authoritative", "data-driven", "professional"}),
        themes=_ALL_THEMES,
        complexity=2,
        slots=frozenset({"facts"}),
        description="Horizontal rail of authority facts/credentials with animated counters",
    ),
    TemplateMeta(
        scene_id="trust.case_grid.v1",
        file="trust_case_grid.html",
        section_type="trust",
        niches=frozenset({"legal", "finance", "medical", "real_estate", "saas"}),
        styles=frozenset({"grid", "structured", "case-study"}),
        themes=_ALL_THEMES,
        complexity=2,
        slots=frozenset({"cases"}),
        description="Grid of case studies / success stories with metrics",
    ),
    TemplateMeta(
        scene_id="trust.comparison_block.v1",
        file="trust_comparison_block.html",
        section_type="trust",
        niches=frozenset({"fitness", "saas", "education", "legal"}),
        styles=frozenset({"comparison", "before-after", "persuasive"}),
        themes=_ALL_THEMES,
        complexity=2,
        slots=frozenset({"comparison_items"}),
        description="Before/after or us-vs-them comparison block",
    ),

    # ── FEATURES ──
    TemplateMeta(
        scene_id="features.bento_premium.v1",
        file="features_bento_premium.html",
        section_type="features",
        niches=frozenset({"saas", "fitness", "luxury_service", "education"}),
        styles=frozenset({"bento", "modern", "grid", "premium"}),
        themes=_ALL_THEMES,
        complexity=3,
        slots=frozenset({"headline", "features"}),
        description="Bento-grid layout with mixed card sizes and hover effects",
    ),
    TemplateMeta(
        scene_id="features.editorial_cards.v1",
        file="features_editorial_cards.html",
        section_type="features",
        niches=frozenset({"restaurant", "beauty", "hospitality", "medical", "education"}),
        styles=frozenset({"editorial", "cards", "clean"}),
        themes=_ALL_THEMES,
        complexity=2,
        slots=frozenset({"headline", "features"}),
        description="Editorial-style feature cards with icons and descriptions",
    ),
    TemplateMeta(
        scene_id="features.process_timeline.v1",
        file="features_process_timeline.html",
        section_type="features",
        niches=frozenset({"legal", "finance", "real_estate", "medical"}),
        styles=frozenset({"timeline", "process", "step-by-step"}),
        themes=_ALL_THEMES,
        complexity=2,
        slots=frozenset({"headline", "steps"}),
        description="Vertical timeline showing process steps with connectors",
    ),

    # ── PROOF ──
    TemplateMeta(
        scene_id="proof.stats_bar.v1",
        file="proof_stats_bar.html",
        section_type="proof",
        niches=_UNIVERSAL,
        styles=frozenset({"stats", "counters", "social-proof"}),
        themes=_ALL_THEMES,
        complexity=1,
        slots=frozenset({"stats"}),
        description="Horizontal stats bar with animated counters",
    ),

    # ── TESTIMONIALS ──
    TemplateMeta(
        scene_id="testimonials.quote_wall.v1",
        file="testimonials_quote_wall.html",
        section_type="testimonials",
        niches=frozenset({"legal", "finance", "medical", "real_estate", "education", "fitness"}),
        styles=frozenset({"quotes", "grid", "professional"}),
        themes=_ALL_THEMES,
        complexity=2,
        slots=frozenset({"testimonials"}),
        description="Grid of client testimonial cards with avatars and quotes",
    ),
    TemplateMeta(
        scene_id="testimonials.marquee.v1",
        file="testimonials_marquee.html",
        section_type="testimonials",
        niches=frozenset({"restaurant", "beauty", "hospitality", "luxury_service", "saas"}),
        styles=frozenset({"marquee", "scroll", "dynamic"}),
        themes=_ALL_THEMES,
        complexity=2,
        slots=frozenset({"testimonials"}),
        description="Auto-scrolling marquee of testimonial cards",
    ),

    # ── CTA ──
    TemplateMeta(
        scene_id="cta.executive_split.v1",
        file="cta_executive_split.html",
        section_type="cta",
        niches=_UNIVERSAL,
        styles=frozenset({"split", "executive", "bold"}),
        themes=_ALL_THEMES,
        complexity=2,
        slots=frozenset({"headline", "subheadline", "cta_primary_text", "cta_primary_href"}),
        description="Split-layout CTA with strong headline and action button",
    ),

    # ── FOOTER ──
    TemplateMeta(
        scene_id="footer.authority_contact.v1",
        file="footer_authority_contact.html",
        section_type="footer",
        niches=_UNIVERSAL,
        styles=frozenset({"authority", "contact", "professional"}),
        themes=_ALL_THEMES,
        complexity=2,
        slots=frozenset({"brand_name", "tagline", "phone", "email", "address"}),
        description="Professional footer with contact info, social links, and brand",
    ),

    # ── GALLERY ──
    TemplateMeta(
        scene_id="gallery.masonry_grid.v1",
        file="gallery_masonry_grid.html",
        section_type="gallery",
        niches=frozenset({"restaurant", "fitness", "beauty", "hospitality", "luxury_service", "real_estate"}),
        styles=frozenset({"masonry", "grid", "visual"}),
        themes=_ALL_THEMES,
        complexity=2,
        slots=frozenset({"images"}),
        description="Masonry-style image gallery with lightbox",
    ),

    # ── PRICING ──
    TemplateMeta(
        scene_id="pricing.cards.v1",
        file="pricing_cards.html",
        section_type="pricing",
        niches=frozenset({"saas", "fitness", "education", "restaurant", "beauty", "hospitality", "luxury_service"}),
        styles=frozenset({"cards", "pricing", "comparison"}),
        themes=_ALL_THEMES,
        complexity=2,
        slots=frozenset({"plans"}),
        description="Pricing cards with feature comparison and CTA buttons",
    ),

    # ── PARALLAX ──
    TemplateMeta(
        scene_id="parallax.quote.v1",
        file="parallax_quote.html",
        section_type="parallax",
        niches=_UNIVERSAL,
        styles=frozenset({"parallax", "quote", "cinematic"}),
        themes=_ALL_THEMES,
        complexity=1,
        slots=frozenset({"quote", "author"}),
        description="Parallax section with inspirational quote overlay",
    ),

    # ── ABOUT ──
    TemplateMeta(
        scene_id="about.split_image.v1",
        file="about_split_image.html",
        section_type="about",
        niches=_UNIVERSAL,
        styles=frozenset({"split", "image", "narrative"}),
        themes=_ALL_THEMES,
        complexity=2,
        slots=frozenset({"headline", "text", "image_url"}),
        description="Split-layout about section with image and narrative text",
    ),
)

# Build indexes for fast lookup
# Index by exact scene_id (e.g. "hero.cinematic_fullbleed.v1")
# AND by versionless alias (e.g. "hero.cinematic_fullbleed") for backward compat
_BY_SCENE_ID: dict[str, TemplateMeta] = {}
for _t in TEMPLATE_CATALOG:
    _BY_SCENE_ID[_t.scene_id] = _t
    # Strip version suffix (.v1, .v2, etc.) to create versionless alias
    _base = re.sub(r"\.v\d+$", "", _t.scene_id)
    if _base != _t.scene_id and _base not in _BY_SCENE_ID:
        _BY_SCENE_ID[_base] = _t
_BY_SECTION_TYPE: dict[str, list[TemplateMeta]] = {}
for _t in TEMPLATE_CATALOG:
    _BY_SECTION_TYPE.setdefault(_t.section_type, []).append(_t)


# ─────────────────────────────────────────────────────────────────
#  SCORING ENGINE
# ─────────────────────────────────────────────────────────────────
def _score_template(
    meta: TemplateMeta,
    *,
    niche: str = "",
    style_tags: Sequence[str] = (),
    theme: str = "",
) -> float:
    """
    Score a template against query criteria.
    Returns a float 0.0–1.0 where higher = better match.

    Scoring weights:
    - Niche match:  0.45  (exact match or universal)
    - Style match:  0.30  (intersection of style tags)
    - Theme match:  0.25  (compatible theme pack)
    """
    score = 0.0

    # Niche affinity (0.45)
    if "*" in meta.niches:
        score += 0.35  # universal gets partial credit
    elif niche and niche in meta.niches:
        score += 0.45  # exact niche match
    elif niche:
        score += 0.0   # no match

    # Style affinity (0.30)
    if style_tags:
        query_styles = set(style_tags)
        overlap = len(query_styles & meta.styles)
        if query_styles:
            score += 0.30 * (overlap / len(query_styles))
    else:
        score += 0.15  # no style preference = neutral

    # Theme compatibility (0.25)
    if theme:
        if theme in meta.themes:
            score += 0.25
        else:
            score += 0.05  # theme mismatch but still usable
    else:
        score += 0.15  # no theme preference = neutral

    return round(score, 3)


def retrieve_templates(
    section_type: str,
    *,
    niche: str = "",
    style_tags: Sequence[str] = (),
    theme: str = "",
    top_n: int = 1,
) -> list[tuple[TemplateMeta, float]]:
    """
    Retrieve top-N templates for a given section_type, ranked by affinity score.

    Args:
        section_type: Required. e.g. "hero", "features", "trust"
        niche: Optional niche filter. e.g. "fitness", "legal"
        style_tags: Optional style preferences. e.g. ["cinematic", "bold"]
        theme: Optional theme pack. e.g. "dark_premium_v1"
        top_n: Number of results to return (default 1)

    Returns:
        List of (TemplateMeta, score) tuples, sorted by score descending.
    """
    candidates = _BY_SECTION_TYPE.get(section_type, [])
    if not candidates:
        logger.warning(f"No templates found for section_type={section_type!r}")
        return []

    scored = [
        (meta, _score_template(meta, niche=niche, style_tags=style_tags, theme=theme))
        for meta in candidates
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    result = scored[:top_n]
    if result:
        logger.info(
            f"Retriever: section={section_type}, niche={niche}, "
            f"top={result[0][0].scene_id} (score={result[0][1]})"
        )
    return result


def retrieve_best(
    section_type: str,
    *,
    niche: str = "",
    style_tags: Sequence[str] = (),
    theme: str = "",
) -> Optional[TemplateMeta]:
    """Convenience: return the single best template or None."""
    results = retrieve_templates(
        section_type, niche=niche, style_tags=style_tags, theme=theme, top_n=1
    )
    return results[0][0] if results else None


# ─────────────────────────────────────────────────────────────────
#  TEMPLATE LOADING (backward-compatible API)
# ─────────────────────────────────────────────────────────────────
_template_cache: dict[str, str] = {}


def get_template(scene_id: str) -> Optional[str]:
    """
    Load and return the HTML template for a scene_id.
    Returns None if not found.

    This is the backward-compatible API used by scene_assembler.
    """
    if scene_id in _template_cache:
        return _template_cache[scene_id]

    meta = _BY_SCENE_ID.get(scene_id)
    if not meta:
        logger.warning(f"No catalog entry for scene_id: {scene_id!r}")
        return None

    template_path = TEMPLATES_BASE / meta.file
    if not template_path.exists():
        logger.warning(f"Template file not found: {template_path}")
        return None

    try:
        content = template_path.read_text(encoding="utf-8")
        _template_cache[scene_id] = content
        return content
    except Exception as e:
        logger.error(f"Failed to load template {template_path}: {e}")
        return None


def get_decorator_partial(partial_path: str) -> str:
    """Load a decorator partial HTML snippet."""
    if not partial_path:
        return ""
    if partial_path in _template_cache:
        return _template_cache[partial_path]

    full_path = TEMPLATES_BASE / partial_path
    if not full_path.exists():
        return ""

    try:
        content = full_path.read_text(encoding="utf-8")
        _template_cache[partial_path] = content
        return content
    except Exception:
        return ""


def get_template_meta(scene_id: str) -> Optional[TemplateMeta]:
    """Get metadata for a scene_id without loading the template."""
    return _BY_SCENE_ID.get(scene_id)


def list_available_scenes() -> list[str]:
    """Return list of scene_ids that have templates on disk."""
    return [
        meta.scene_id
        for meta in TEMPLATE_CATALOG
        if (TEMPLATES_BASE / meta.file).exists()
    ]


def list_section_types() -> list[str]:
    """Return all known section types."""
    return sorted(_BY_SECTION_TYPE.keys())


def clear_cache() -> None:
    """Clear the template cache (useful for hot-reload in development)."""
    _template_cache.clear()
