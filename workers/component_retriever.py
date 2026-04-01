"""
ComponentRetriever — Semantic Template Retrieval Engine
=======================================================

ARCANE Cutover v1 (2026-03-31)

Architecture:
  1. Pre-compute embeddings for all template descriptions at startup
  2. At query time: embed the query → cosine similarity → filter → rerank → return
  3. Embeddings cached in Redis for fast restart

Retrieval pipeline:
  embed(query) → cosine_sim(query_emb, catalog_embs)
    → filter(scene_type, niche_tags, forbidden_tags)
    → rerank(quality_tier, mobile_grade, anti_clone_penalty)
    → top_n results

Model: paraphrase-multilingual-MiniLM-L12-v2 (supports Russian + English)
Embedding dim: 384, ~120MB RAM
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

logger = logging.getLogger("arcane.component_retriever")

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
    description: str = ""      # human-readable description for embedding
    quality_tier: int = 3      # 1-5, higher = better quality template
    mobile_grade: str = "A"    # A/B/C — mobile responsiveness grade


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
        description="Split-layout hero with editorial typography, large image on one side, headline and CTA on the other. Clean professional aesthetic for business services.",
        quality_tier=4,
        mobile_grade="A",
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
        description="Authority-focused hero for professional services like law firms and financial advisors. Features credentials bar, formal typography, and trust indicators.",
        quality_tier=4,
        mobile_grade="A",
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
        description="Full-bleed cinematic hero with dramatic background image or video. Bold typography overlay, immersive experience for restaurants, gyms, beauty salons.",
        quality_tier=5,
        mobile_grade="A",
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
        description="Product-focused hero with screenshot or mockup showcase. Modern tech aesthetic for SaaS products and educational platforms.",
        quality_tier=4,
        mobile_grade="A",
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
        description="Horizontal rail of authority facts and credentials with animated counters. Shows years of experience, cases won, clients served. Professional data-driven trust builder.",
        quality_tier=4,
        mobile_grade="A",
    ),
    TemplateMeta(
        scene_id="trust.case_grid.v1",
        file="trust_case_grid.html",
        section_type="trust",
        niches=frozenset({"legal", "finance", "medical", "real_estate", "saas"}),
        styles=frozenset({"case-study", "grid", "authority"}),
        themes=frozenset({"light_trust_v1", "neutral_minimal_v1", "warm_editorial_v1"}),
        complexity=2,
        slots=frozenset({"cases"}),
        description="Grid of case studies or success stories with brief descriptions. Shows real results and outcomes for professional services.",
        quality_tier=3,
        mobile_grade="A",
    ),
    TemplateMeta(
        scene_id="trust.comparison_block.v1",
        file="trust_comparison_block.html",
        section_type="trust",
        niches=_UNIVERSAL,
        styles=frozenset({"comparison", "trust", "data-driven"}),
        themes=_ALL_THEMES,
        complexity=2,
        slots=frozenset({"comparisons"}),
        description="Comparison block showing before/after or us-vs-competitors. Trust-building section with visual comparison data.",
        quality_tier=3,
        mobile_grade="A",
    ),
    # ── FEATURES ──
    TemplateMeta(
        scene_id="features.bento_grid.v1",
        file="features_bento_premium.html",
        section_type="features",
        niches=frozenset({"saas", "education", "fitness", "medical"}),
        styles=frozenset({"bento", "modern", "structured"}),
        themes=frozenset({"light_trust_v1", "dark_tech_v1", "neutral_minimal_v1"}),
        complexity=3,
        slots=frozenset({"features"}),
        description="Bento grid layout for features or services. Modern structured cards with icons, varying sizes. Great for SaaS features or gym services.",
        quality_tier=4,
        mobile_grade="A",
    ),
    TemplateMeta(
        scene_id="features.timeline_process.v1",
        file="features_process_timeline.html",
        section_type="features",
        niches=frozenset({"legal", "medical", "real_estate", "education"}),
        styles=frozenset({"timeline", "step-by-step", "process"}),
        themes=frozenset({"light_trust_v1", "warm_editorial_v1", "neutral_minimal_v1"}),
        complexity=2,
        slots=frozenset({"steps"}),
        description="Vertical timeline showing step-by-step process or workflow. How it works section for legal consultations, medical procedures, real estate buying process.",
        quality_tier=4,
        mobile_grade="A",
    ),
    TemplateMeta(
        scene_id="features.editorial_cards.v1",
        file="features_editorial_cards.html",
        section_type="features",
        niches=frozenset({"fitness", "beauty", "restaurant", "hospitality"}),
        styles=frozenset({"editorial", "cards", "elegant", "visual"}),
        themes=frozenset({"dark_premium_v1", "warm_gold_v1", "dark_elegant_v1"}),
        complexity=2,
        slots=frozenset({"comparisons"}),
        description="Editorial-style feature cards with rich typography and visual hierarchy. Elegant presentation of services or capabilities.",
        quality_tier=4,
        mobile_grade="B",
    ),
    # ── PROOF ──
    TemplateMeta(
        scene_id="proof.stats_counters.v1",
        file="proof_stats_bar.html",
        section_type="proof",
        niches=_UNIVERSAL,
        styles=frozenset({"counters", "stats", "data-driven", "dynamic"}),
        themes=_ALL_THEMES,
        complexity=2,
        slots=frozenset({"stats"}),
        description="Animated statistics counters showing key metrics. Universal proof section with numbers that count up on scroll. Works for any niche.",
        quality_tier=3,
        mobile_grade="A",
    ),
    # ── TESTIMONIALS ──
    TemplateMeta(
        scene_id="testimonials.marquee.v1",
        file="testimonials_marquee.html",
        section_type="testimonials",
        niches=_UNIVERSAL,
        styles=frozenset({"marquee", "quotes", "social-proof"}),
        themes=_ALL_THEMES,
        complexity=2,
        slots=frozenset({"testimonials"}),
        description="Scrolling marquee of testimonial quotes. Continuous horizontal scroll of client reviews and social proof.",
        quality_tier=4,
        mobile_grade="A",
    ),
    TemplateMeta(
        scene_id="testimonials.quote_wall.v1",
        file="testimonials_quote_wall.html",
        section_type="testimonials",
        niches=frozenset({"legal", "finance", "medical", "real_estate", "saas"}),
        styles=frozenset({"executive", "quote", "premium"}),
        themes=frozenset({"light_trust_v1", "dark_elegant_v1", "warm_editorial_v1"}),
        complexity=2,
        slots=frozenset({"testimonials"}),
        description="Wall of testimonial quotes with large typography and professional styling. Premium look for high-end professional services.",
        quality_tier=5,
        mobile_grade="A",
    ),
    # ── CTA ──
    TemplateMeta(
        scene_id="cta.executive_split.v1",
        file="cta_executive_split.html",
        section_type="cta",
        niches=_UNIVERSAL,
        styles=frozenset({"bold", "persuasive", "dynamic"}),
        themes=_ALL_THEMES,
        complexity=1,
        slots=frozenset({"headline", "cta_text"}),
        description="Executive split-layout call-to-action with persuasive headline on one side and form or button on the other. Professional CTA section.",
        quality_tier=3,
        mobile_grade="A",
    ),
    # ── FOOTER ──
    TemplateMeta(
        scene_id="footer.authority_contact.v1",
        file="footer_authority_contact.html",
        section_type="footer",
        niches=_UNIVERSAL,
        styles=frozenset({"structured", "contact", "professional"}),
        themes=_ALL_THEMES,
        complexity=1,
        slots=frozenset({"company_name", "address", "phone", "email", "social_links"}),
        description="Authority footer with contact information, company details, and professional branding. Structured multi-column layout.",
        quality_tier=3,
        mobile_grade="A",
    ),
    # ── GALLERY ──
    TemplateMeta(
        scene_id="gallery.masonry_grid.v1",
        file="gallery_masonry_grid.html",
        section_type="gallery",
        niches=frozenset({"restaurant", "beauty", "fitness", "hospitality", "real_estate"}),
        styles=frozenset({"masonry", "image", "visual", "grid"}),
        themes=frozenset({"dark_premium_v1", "warm_gold_v1", "neutral_minimal_v1"}),
        complexity=3,
        slots=frozenset({"images"}),
        description="Masonry grid gallery with lightbox zoom. Visual portfolio showcase for restaurants, beauty salons, fitness transformations, real estate properties.",
        quality_tier=4,
        mobile_grade="B",
    ),
    # ── PRICING ──
    TemplateMeta(
        scene_id="pricing.cards.v1",
        file="pricing_cards.html",
        section_type="pricing",
        niches=frozenset({"saas", "fitness", "beauty", "education"}),
        styles=frozenset({"comparison", "pricing", "structured"}),
        themes=frozenset({"light_trust_v1", "dark_tech_v1", "neutral_minimal_v1"}),
        complexity=2,
        slots=frozenset({"plans"}),
        description="Pricing cards with plan comparison and highlighted recommended option. Clean card-based layout for subscription or membership tiers.",
        quality_tier=4,
        mobile_grade="A",
    ),
    # ── PARALLAX ──
    TemplateMeta(
        scene_id="parallax.quote.v1",
        file="parallax_quote.html",
        section_type="parallax",
        niches=_UNIVERSAL,
        styles=frozenset({"parallax", "image", "immersive", "scroll"}),
        themes=frozenset({"dark_premium_v1", "dark_elegant_v1", "warm_gold_v1"}),
        complexity=2,
        slots=frozenset({"bg_image_url", "overlay_text"}),
        description="Parallax section with inspirational quote overlay on background image. Creates visual depth between content sections.",
        quality_tier=3,
        mobile_grade="B",
    ),
    # ── ABOUT ──
    TemplateMeta(
        scene_id="about.split_image.v1",
        file="about_split_image.html",
        section_type="about",
        niches=_UNIVERSAL,
        styles=frozenset({"narrative", "split", "editorial"}),
        themes=frozenset({"light_trust_v1", "warm_editorial_v1", "neutral_minimal_v1"}),
        complexity=2,
        slots=frozenset({"headline", "story", "image_url"}),
        description="Split-layout about section with image on one side and company story on the other. Editorial style for company or founder narrative.",
        quality_tier=4,
        mobile_grade="A",
    ),
    # ── FAQ ──
    TemplateMeta(
        scene_id="faq.accordion.v1",
        file="faq_accordion.html",
        section_type="faq",
        niches=_UNIVERSAL,
        styles=frozenset({"clean", "professional", "minimal", "editorial"}),
        themes=_ALL_THEMES,
        complexity=1,
        slots=frozenset({"headline", "subheadline", "faq_items"}),
        description="FAQ accordion section with smooth expand/collapse animation. Clean design with plus icon toggle. Universal for all niches.",
        quality_tier=4,
        mobile_grade="A",
    ),
)


# ─────────────────────────────────────────────────────────────────
#  INDEXES (built at import time)
# ─────────────────────────────────────────────────────────────────
_BY_SCENE_ID: dict[str, TemplateMeta] = {m.scene_id: m for m in TEMPLATE_CATALOG}
_BY_SECTION_TYPE: dict[str, list[TemplateMeta]] = {}
for _m in TEMPLATE_CATALOG:
    _BY_SECTION_TYPE.setdefault(_m.section_type, []).append(_m)

TEMPLATES_BASE = Path(os.getenv(
    "ARCANE_TEMPLATES_DIR",
    str(Path(__file__).resolve().parent.parent / "templates" / "premium_scenes"),
))


# ─────────────────────────────────────────────────────────────────
#  SEMANTIC EMBEDDING ENGINE
# ─────────────────────────────────────────────────────────────────

_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_EMBEDDING_DIM = 384

# Lazy-loaded globals
_model = None
_catalog_embeddings: Optional[np.ndarray] = None  # shape: (N, 384)
_catalog_texts: list[str] = []  # parallel to _catalog_embeddings rows


def _get_model():
    """Lazy-load the sentence transformer model."""
    global _model
    if _model is None:
        t0 = time.time()
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_MODEL_NAME)
        logger.info(f"Loaded embedding model '{_MODEL_NAME}' in {time.time()-t0:.1f}s")
    return _model


def _build_template_text(meta: TemplateMeta) -> str:
    """Build a rich text representation of a template for embedding.
    
    Combines description, section_type, niches, and styles into a single
    string that captures the template's semantic identity.
    """
    parts = [
        meta.description or f"{meta.section_type} section template",
        f"Section type: {meta.section_type}",
        f"Niches: {', '.join(sorted(meta.niches))}",
        f"Styles: {', '.join(sorted(meta.styles))}",
        f"Content slots: {', '.join(sorted(meta.slots))}",
    ]
    return ". ".join(parts)


def _compute_catalog_embeddings() -> np.ndarray:
    """Compute embeddings for all templates in the catalog."""
    global _catalog_embeddings, _catalog_texts
    
    model = _get_model()
    _catalog_texts = [_build_template_text(m) for m in TEMPLATE_CATALOG]
    
    t0 = time.time()
    _catalog_embeddings = model.encode(
        _catalog_texts,
        normalize_embeddings=True,  # L2-normalize for cosine similarity via dot product
        show_progress_bar=False,
    )
    logger.info(
        f"Computed {len(TEMPLATE_CATALOG)} template embeddings "
        f"({_catalog_embeddings.shape}) in {time.time()-t0:.2f}s"
    )
    return _catalog_embeddings


def _try_load_cached_embeddings() -> bool:
    """Try to load pre-computed embeddings from Redis cache."""
    global _catalog_embeddings, _catalog_texts
    try:
        import redis
        port = int(os.getenv("REDIS_PORT", "6380"))
        db = int(os.getenv("REDIS_DB", "1"))
        r = redis.Redis(host="127.0.0.1", port=port, db=db)
        
        cached = r.get("arcane:embeddings:catalog_v2")
        if cached is None:
            return False
        
        data = json.loads(cached)
        # Verify catalog hasn't changed
        cached_ids = data.get("scene_ids", [])
        current_ids = [m.scene_id for m in TEMPLATE_CATALOG]
        if cached_ids != current_ids:
            logger.info("Cached embeddings stale (catalog changed), recomputing")
            return False
        
        _catalog_embeddings = np.array(data["embeddings"], dtype=np.float32)
        _catalog_texts = data.get("texts", [])
        logger.info(f"Loaded cached embeddings from Redis ({_catalog_embeddings.shape})")
        return True
    except Exception as e:
        logger.debug(f"Redis cache miss: {e}")
        return False


def _save_embeddings_to_cache(embeddings: np.ndarray) -> None:
    """Save computed embeddings to Redis cache."""
    try:
        import redis
        port = int(os.getenv("REDIS_PORT", "6380"))
        db = int(os.getenv("REDIS_DB", "1"))
        r = redis.Redis(host="127.0.0.1", port=port, db=db)
        
        data = {
            "scene_ids": [m.scene_id for m in TEMPLATE_CATALOG],
            "texts": _catalog_texts,
            "embeddings": embeddings.tolist(),
            "model": _MODEL_NAME,
            "computed_at": time.time(),
        }
        r.set("arcane:embeddings:catalog_v2", json.dumps(data), ex=86400 * 7)  # 7 day TTL
        logger.info("Saved embeddings to Redis cache")
    except Exception as e:
        logger.debug(f"Failed to cache embeddings: {e}")


def _ensure_embeddings() -> np.ndarray:
    """Ensure catalog embeddings are loaded (from cache or computed fresh)."""
    global _catalog_embeddings
    if _catalog_embeddings is not None:
        return _catalog_embeddings
    
    if _try_load_cached_embeddings():
        return _catalog_embeddings
    
    embs = _compute_catalog_embeddings()
    _save_embeddings_to_cache(embs)
    return embs


def _embed_query(query: str) -> np.ndarray:
    """Embed a user query string."""
    model = _get_model()
    return model.encode(
        [query],
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0]


# ─────────────────────────────────────────────────────────────────
#  SCORING & RERANKING
# ─────────────────────────────────────────────────────────────────

# Scoring weights
_W_SEMANTIC = 0.40    # Cosine similarity from embeddings
_W_NICHE = 0.25       # Niche match (exact, universal, or miss)
_W_STYLE = 0.15       # Style tag overlap
_W_QUALITY = 0.10     # Quality tier bonus
_W_MOBILE = 0.10      # Mobile grade bonus

_MOBILE_SCORES = {"A": 1.0, "B": 0.6, "C": 0.3}
_ANTI_CLONE_PENALTY = 0.25  # Penalty for reusing same scene_id


def _score_template(
    meta: TemplateMeta,
    *,
    semantic_sim: float = 0.0,
    niche: str = "",
    style_tags: Sequence[str] = (),
    theme: str = "",
    used_ids: frozenset[str] = frozenset(),
) -> float:
    """
    Compute a composite retrieval score for a template.
    
    Combines:
    - Semantic similarity (embedding cosine sim)
    - Niche affinity (exact match, universal, or miss)
    - Style overlap (intersection of requested vs available)
    - Quality tier (1-5 normalized)
    - Mobile grade (A/B/C)
    - Anti-clone penalty (if scene_id already used on this page)
    
    Returns a float 0.0–1.0 where higher = better match.
    """
    score = 0.0
    
    # 1. Semantic similarity (0.40)
    score += _W_SEMANTIC * max(0.0, semantic_sim)
    
    # 2. Niche affinity (0.25)
    if "*" in meta.niches:
        score += _W_NICHE * 0.7  # universal gets partial credit
    elif niche and niche in meta.niches:
        score += _W_NICHE * 1.0  # exact niche match
    elif niche:
        score += 0.0  # no match
    else:
        score += _W_NICHE * 0.5  # no preference = neutral
    
    # 3. Style affinity (0.15)
    if style_tags:
        query_styles = set(style_tags)
        overlap = len(query_styles & meta.styles)
        if query_styles:
            score += _W_STYLE * (overlap / len(query_styles))
    else:
        score += _W_STYLE * 0.5  # no preference = neutral
    
    # 4. Quality tier (0.10)
    score += _W_QUALITY * (meta.quality_tier / 5.0)
    
    # 5. Mobile grade (0.10)
    score += _W_MOBILE * _MOBILE_SCORES.get(meta.mobile_grade, 0.5)
    
    # 6. Theme compatibility bonus (additive, small)
    if theme and theme in meta.themes:
        score += 0.05
    
    # 7. Anti-clone penalty
    if meta.scene_id in used_ids:
        score -= _ANTI_CLONE_PENALTY
    
    return round(max(0.0, min(1.0, score)), 4)


# ─────────────────────────────────────────────────────────────────
#  PUBLIC RETRIEVAL API
# ─────────────────────────────────────────────────────────────────

def retrieve_templates(
    section_type: str,
    *,
    query: str = "",
    niche: str = "",
    style_tags: Sequence[str] = (),
    theme: str = "",
    forbidden_tags: Sequence[str] = (),
    used_ids: Sequence[str] = (),
    top_n: int = 1,
) -> list[tuple[TemplateMeta, float]]:
    """
    Retrieve top-N templates for a given section_type using semantic + metadata scoring.
    
    Args:
        section_type: Required. e.g. "hero", "features", "trust"
        query: Optional natural language query for semantic matching
        niche: Optional niche filter. e.g. "fitness", "legal"
        style_tags: Optional style preferences. e.g. ["cinematic", "bold"]
        theme: Optional theme pack. e.g. "dark_premium_v1"
        forbidden_tags: Tags that MUST NOT be present in the template
        used_ids: Scene IDs already used on this page (anti-clone)
        top_n: Number of results to return (default 1)
    
    Returns:
        List of (TemplateMeta, score) tuples, sorted by score descending.
    """
    candidates = _BY_SECTION_TYPE.get(section_type, [])
    if not candidates:
        logger.warning(f"No templates found for section_type={section_type!r}")
        return []
    
    # Filter by forbidden_tags
    if forbidden_tags:
        forbidden = set(forbidden_tags)
        candidates = [
            m for m in candidates
            if not (m.styles & forbidden) and not (m.niches & forbidden)
        ]
        if not candidates:
            logger.warning(f"All templates filtered out by forbidden_tags for {section_type}")
            return []
    
    # Compute semantic similarities if query provided
    semantic_sims: dict[str, float] = {}
    if query:
        try:
            catalog_embs = _ensure_embeddings()
            query_emb = _embed_query(query)
            
            # Compute cosine similarities (embeddings are L2-normalized, so dot product = cosine sim)
            all_sims = query_emb @ catalog_embs.T
            
            # Map scene_id → similarity
            for i, meta in enumerate(TEMPLATE_CATALOG):
                semantic_sims[meta.scene_id] = float(all_sims[i])
        except Exception as e:
            logger.warning(f"Semantic embedding failed: {e}, falling back to metadata-only scoring")
    
    # Score all candidates
    used_set = frozenset(used_ids)
    scored = [
        (
            meta,
            _score_template(
                meta,
                semantic_sim=semantic_sims.get(meta.scene_id, 0.0),
                niche=niche,
                style_tags=style_tags,
                theme=theme,
                used_ids=used_set,
            ),
        )
        for meta in candidates
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    result = scored[:top_n]
    
    if result:
        logger.info(
            f"Retriever: section={section_type}, niche={niche}, query={query[:40]!r}, "
            f"top={result[0][0].scene_id} (score={result[0][1]:.4f})"
        )
    return result


def retrieve_best(
    section_type: str,
    *,
    query: str = "",
    niche: str = "",
    style_tags: Sequence[str] = (),
    theme: str = "",
    forbidden_tags: Sequence[str] = (),
    used_ids: Sequence[str] = (),
) -> Optional[TemplateMeta]:
    """Convenience: return the single best template or None."""
    results = retrieve_templates(
        section_type,
        query=query,
        niche=niche,
        style_tags=style_tags,
        theme=theme,
        forbidden_tags=forbidden_tags,
        used_ids=used_ids,
        top_n=1,
    )
    return results[0][0] if results else None


# ─────────────────────────────────────────────────────────────────
#  BACKWARD-COMPATIBLE API (used by scene_assembler, scene_planner)
# ─────────────────────────────────────────────────────────────────

_template_cache: dict[str, str] = {}


def get_template(scene_id: str) -> Optional[str]:
    """
    Load and return the HTML template for a scene_id.
    Returns None if not found.
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
    """Clear the template cache and embeddings (useful for hot-reload)."""
    global _catalog_embeddings, _catalog_texts
    _template_cache.clear()
    _catalog_embeddings = None
    _catalog_texts = []


def warm_up() -> None:
    """Pre-load model and compute embeddings. Call at startup for fast first query."""
    try:
        _ensure_embeddings()
        logger.info("ComponentRetriever warmed up: model loaded, embeddings ready")
    except Exception as e:
        logger.warning(f"ComponentRetriever warm-up failed: {e}")
