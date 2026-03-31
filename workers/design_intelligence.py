"""
ARCANE Design Intelligence — Scene Library + Anti-Clone Memory + Trust Engine

Three subsystems that improve design quality over time:

1. PremiumSceneLibrary — Curated library of proven section patterns
   with exact CSS, ready to inject into scene plans.

2. AntiCloneMemory — Tracks recently generated designs to prevent
   repetitive outputs. Stores palette + layout fingerprints.

3. TrustEngine — Tracks model performance per task type and
   automatically selects the best-performing model for each role.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Optional
from pathlib import Path

from shared.utils.logger import get_logger

logger = get_logger("workers.design_intelligence")


# ─────────────────────────────────────────────────────────────────
#  1. PREMIUM SCENE LIBRARY
# ─────────────────────────────────────────────────────────────────

PREMIUM_SECTIONS = {
    "hero_cinematic": {
        "name": "Cinematic Hero",
        "type": "hero",
        "description": "Full-viewport hero with gradient overlay, large headline, and floating CTA",
        "css_pattern": """
.hero {
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    overflow: hidden;
    background: linear-gradient(135deg, var(--bg) 0%, var(--surface) 100%);
}
.hero::before {
    content: '';
    position: absolute;
    inset: 0;
    background: radial-gradient(ellipse at 30% 50%, rgba(var(--accent-rgb), 0.15), transparent 70%);
    pointer-events: none;
}
.hero-content {
    text-align: center;
    max-width: 800px;
    padding: 2rem;
    z-index: 1;
}
.hero h1 {
    font-size: clamp(3rem, 7vw, 6rem);
    font-weight: 700;
    line-height: 1.05;
    letter-spacing: -0.03em;
    margin-bottom: 1.5rem;
}
.hero .kicker {
    font-size: 0.875rem;
    text-transform: uppercase;
    letter-spacing: 0.2em;
    color: var(--accent);
    margin-bottom: 1rem;
    font-weight: 500;
}
.hero p {
    font-size: clamp(1.125rem, 2vw, 1.375rem);
    color: var(--muted);
    max-width: 600px;
    margin: 0 auto 2.5rem;
    line-height: 1.7;
}
""",
        "html_skeleton": """
<section class="hero">
    <div class="hero-content">
        <span class="kicker">{kicker}</span>
        <h1>{headline}</h1>
        <p>{subheadline}</p>
        <div class="hero-cta">
            <a href="#" class="btn btn-primary">{cta_primary}</a>
            <a href="#" class="btn btn-ghost">{cta_secondary}</a>
        </div>
    </div>
</section>
""",
        "compatible_families": ["dark_luxury", "cinematic_prestige", "clean_tech"],
    },

    "hero_split": {
        "name": "Split Hero",
        "type": "hero",
        "description": "50/50 split with text left, visual right",
        "css_pattern": """
.hero {
    min-height: 100vh;
    display: grid;
    grid-template-columns: 1fr 1fr;
    align-items: center;
    gap: 4rem;
    padding: 0 clamp(2rem, 5vw, 6rem);
}
.hero-text { max-width: 560px; }
.hero-text .kicker {
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.25em;
    color: var(--accent);
    margin-bottom: 1.5rem;
    display: block;
}
.hero-text h1 {
    font-size: clamp(2.5rem, 5vw, 4.5rem);
    font-weight: 700;
    line-height: 1.1;
    letter-spacing: -0.02em;
    margin-bottom: 1.5rem;
}
.hero-visual {
    position: relative;
    border-radius: 1.5rem;
    overflow: hidden;
    aspect-ratio: 4/5;
}
.hero-visual img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}
@media (max-width: 768px) {
    .hero { grid-template-columns: 1fr; min-height: auto; padding: 6rem 1.5rem 3rem; }
    .hero-visual { aspect-ratio: 16/9; }
}
""",
        "html_skeleton": """
<section class="hero">
    <div class="hero-text">
        <span class="kicker">{kicker}</span>
        <h1>{headline}</h1>
        <p>{subheadline}</p>
        <a href="#" class="btn btn-primary">{cta_primary}</a>
    </div>
    <div class="hero-visual">
        <img src="{image_url}" alt="{image_alt}" loading="eager">
    </div>
</section>
""",
        "compatible_families": ["warm_editorial", "soft_wellness", "boutique_hospitality"],
    },

    "features_bento": {
        "name": "Bento Grid Features",
        "type": "features",
        "description": "Apple-style bento grid with mixed card sizes",
        "css_pattern": """
.features-bento {
    padding: 100px clamp(1.5rem, 5vw, 6rem);
}
.bento-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    grid-auto-rows: minmax(250px, auto);
    gap: 1.25rem;
    max-width: 1200px;
    margin: 0 auto;
}
.bento-card {
    background: var(--surface);
    border-radius: 1.25rem;
    padding: 2.5rem;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    position: relative;
    overflow: hidden;
    transition: transform 0.4s ease, box-shadow 0.4s ease;
}
.bento-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 20px 60px rgba(0,0,0,0.15);
}
.bento-card.large { grid-column: span 2; }
.bento-card.tall { grid-row: span 2; }
.bento-card h3 {
    font-size: 1.375rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
}
.bento-card p {
    color: var(--muted);
    font-size: 0.95rem;
    line-height: 1.6;
}
@media (max-width: 768px) {
    .bento-grid { grid-template-columns: 1fr; }
    .bento-card.large, .bento-card.tall { grid-column: span 1; grid-row: span 1; }
}
""",
        "html_skeleton": """
<section class="features-bento">
    <div class="section-header">
        <span class="kicker">{kicker}</span>
        <h2>{title}</h2>
    </div>
    <div class="bento-grid">
        <div class="bento-card large">
            <h3>{feature_1_title}</h3>
            <p>{feature_1_desc}</p>
        </div>
        <div class="bento-card">
            <h3>{feature_2_title}</h3>
            <p>{feature_2_desc}</p>
        </div>
        <div class="bento-card tall">
            <h3>{feature_3_title}</h3>
            <p>{feature_3_desc}</p>
        </div>
        <div class="bento-card">
            <h3>{feature_4_title}</h3>
            <p>{feature_4_desc}</p>
        </div>
    </div>
</section>
""",
        "compatible_families": ["clean_tech", "dark_luxury", "bold_energy"],
    },

    "stats_counters": {
        "name": "Stats Bar",
        "type": "stats",
        "description": "Horizontal stats strip with large numbers and labels",
        "css_pattern": """
.stats-bar {
    padding: 60px clamp(1.5rem, 5vw, 6rem);
    background: var(--surface);
    border-top: 1px solid rgba(255,255,255,0.06);
    border-bottom: 1px solid rgba(255,255,255,0.06);
}
.stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 2rem;
    max-width: 1100px;
    margin: 0 auto;
    text-align: center;
}
.stat-item .stat-number {
    font-size: clamp(2.5rem, 4vw, 3.5rem);
    font-weight: 700;
    letter-spacing: -0.02em;
    color: var(--accent);
    line-height: 1.2;
}
.stat-item .stat-label {
    font-size: 0.875rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-top: 0.5rem;
}
@media (max-width: 768px) {
    .stats-grid { grid-template-columns: repeat(2, 1fr); }
}
""",
        "html_skeleton": """
<section class="stats-bar">
    <div class="stats-grid">
        <div class="stat-item">
            <div class="stat-number">{stat_1_value}</div>
            <div class="stat-label">{stat_1_label}</div>
        </div>
        <div class="stat-item">
            <div class="stat-number">{stat_2_value}</div>
            <div class="stat-label">{stat_2_label}</div>
        </div>
        <div class="stat-item">
            <div class="stat-number">{stat_3_value}</div>
            <div class="stat-label">{stat_3_label}</div>
        </div>
        <div class="stat-item">
            <div class="stat-number">{stat_4_value}</div>
            <div class="stat-label">{stat_4_label}</div>
        </div>
    </div>
</section>
""",
        "compatible_families": ["*"],
    },

    "testimonials_cards": {
        "name": "Testimonial Cards",
        "type": "testimonials",
        "description": "Clean testimonial cards with avatar, quote, and attribution",
        "css_pattern": """
.testimonials {
    padding: 100px clamp(1.5rem, 5vw, 6rem);
}
.testimonials-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 2rem;
    max-width: 1200px;
    margin: 0 auto;
}
.testimonial-card {
    background: var(--surface);
    border-radius: 1.25rem;
    padding: 2.5rem;
    position: relative;
    transition: transform 0.3s ease;
}
.testimonial-card:hover { transform: translateY(-2px); }
.testimonial-card .stars {
    color: var(--accent);
    font-size: 1rem;
    margin-bottom: 1.25rem;
}
.testimonial-card blockquote {
    font-size: 1rem;
    line-height: 1.7;
    color: var(--text);
    margin-bottom: 1.5rem;
    font-style: normal;
}
.testimonial-author {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}
.testimonial-author img {
    width: 44px;
    height: 44px;
    border-radius: 50%;
    object-fit: cover;
}
.testimonial-author .name { font-weight: 600; font-size: 0.9rem; }
.testimonial-author .role { color: var(--muted); font-size: 0.8rem; }
@media (max-width: 768px) {
    .testimonials-grid { grid-template-columns: 1fr; }
}
""",
        "html_skeleton": """
<section class="testimonials">
    <div class="section-header">
        <span class="kicker">{kicker}</span>
        <h2>{title}</h2>
    </div>
    <div class="testimonials-grid">
        <!-- Repeat for each testimonial -->
        <div class="testimonial-card">
            <div class="stars">★★★★★</div>
            <blockquote>{quote}</blockquote>
            <div class="testimonial-author">
                <img src="{avatar_url}" alt="{name}">
                <div>
                    <div class="name">{name}</div>
                    <div class="role">{role}</div>
                </div>
            </div>
        </div>
    </div>
</section>
""",
        "compatible_families": ["*"],
    },

    "cta_gradient": {
        "name": "Gradient CTA Section",
        "type": "cta",
        "description": "Full-width CTA with gradient background and centered content",
        "css_pattern": """
.cta-section {
    padding: 100px clamp(1.5rem, 5vw, 6rem);
    text-align: center;
    position: relative;
    overflow: hidden;
}
.cta-section::before {
    content: '';
    position: absolute;
    inset: 0;
    background: radial-gradient(ellipse at center, rgba(var(--accent-rgb), 0.12), transparent 70%);
    pointer-events: none;
}
.cta-content {
    max-width: 700px;
    margin: 0 auto;
    position: relative;
    z-index: 1;
}
.cta-content h2 {
    font-size: clamp(2rem, 4vw, 3.5rem);
    font-weight: 700;
    letter-spacing: -0.02em;
    margin-bottom: 1rem;
}
.cta-content p {
    font-size: 1.125rem;
    color: var(--muted);
    margin-bottom: 2.5rem;
    line-height: 1.7;
}
""",
        "html_skeleton": """
<section class="cta-section">
    <div class="cta-content">
        <h2>{headline}</h2>
        <p>{description}</p>
        <a href="#" class="btn btn-primary btn-lg">{cta_text}</a>
    </div>
</section>
""",
        "compatible_families": ["*"],
    },
}


class PremiumSceneLibrary:
    """
    Curated library of proven section patterns.
    Returns CSS + HTML skeletons for scene plan sections.
    """

    def get_section_patterns(
        self,
        section_type: str,
        design_family: str = "",
    ) -> list[dict]:
        """Get matching section patterns for a given type and family."""
        matches = []
        for key, pattern in PREMIUM_SECTIONS.items():
            if pattern["type"] == section_type:
                families = pattern.get("compatible_families", ["*"])
                if "*" in families or design_family in families or not design_family:
                    matches.append({
                        "key": key,
                        "name": pattern["name"],
                        "description": pattern["description"],
                        "css_pattern": pattern["css_pattern"],
                        "html_skeleton": pattern["html_skeleton"],
                    })
        return matches

    def get_all_css_patterns(self) -> str:
        """Get all premium CSS patterns concatenated for injection into prompts."""
        patterns = []
        for key, pattern in PREMIUM_SECTIONS.items():
            patterns.append(f"/* === {pattern['name']} ({pattern['type']}) === */")
            patterns.append(pattern["css_pattern"])
        return "\n".join(patterns)

    def get_pattern_by_key(self, key: str) -> Optional[dict]:
        """Get a specific pattern by its key."""
        return PREMIUM_SECTIONS.get(key)


# ─────────────────────────────────────────────────────────────────
#  2. ANTI-CLONE MEMORY
# ─────────────────────────────────────────────────────────────────

MEMORY_FILE = "/root/arcane/data/design_memory.json"


class AntiCloneMemory:
    """
    Tracks recently generated designs to prevent repetitive outputs.
    Stores fingerprints of palette + layout + font combinations.
    """

    def __init__(self, memory_file: str = MEMORY_FILE, max_entries: int = 100):
        self._memory_file = memory_file
        self._max_entries = max_entries
        self._entries: list[dict] = []
        self._load()

    def _load(self):
        """Load memory from disk."""
        try:
            if os.path.exists(self._memory_file):
                with open(self._memory_file, "r") as f:
                    self._entries = json.load(f)
        except Exception as e:
            logger.warning(f"AntiCloneMemory load failed: {e}")
            self._entries = []

    def _save(self):
        """Save memory to disk."""
        try:
            os.makedirs(os.path.dirname(self._memory_file), exist_ok=True)
            with open(self._memory_file, "w") as f:
                json.dump(self._entries[-self._max_entries:], f, indent=2)
        except Exception as e:
            logger.warning(f"AntiCloneMemory save failed: {e}")

    def fingerprint(self, scene_plan: dict) -> str:
        """Generate a fingerprint for a scene plan."""
        parts = []

        # Palette
        palette = scene_plan.get("palette", {})
        parts.append(palette.get("bg", ""))
        parts.append(palette.get("accent", ""))

        # Typography
        typo = scene_plan.get("typography", {})
        parts.append(typo.get("heading_font", ""))
        parts.append(typo.get("body_font", ""))

        # Layout structure
        sections = scene_plan.get("sections", [])
        section_types = [s.get("type", "") for s in sections]
        parts.append(",".join(section_types))

        # Hero type
        hero = scene_plan.get("hero", {})
        parts.append(hero.get("type", ""))

        # Design family
        meta = scene_plan.get("meta", {})
        parts.append(meta.get("design_family", ""))

        raw = "|".join(parts)
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def is_too_similar(self, scene_plan: dict, threshold: float = 0.7) -> tuple[bool, Optional[str]]:
        """
        Check if a scene plan is too similar to recent designs.
        Returns (is_similar, reason_or_None).
        """
        fp = self.fingerprint(scene_plan)

        # Exact match
        for entry in self._entries[-20:]:
            if entry.get("fingerprint") == fp:
                return True, f"Exact duplicate of design from {entry.get('timestamp', '?')}"

        # Palette similarity
        palette = scene_plan.get("palette", {})
        new_bg = palette.get("bg", "").lower()
        new_accent = palette.get("accent", "").lower()

        similar_count = 0
        for entry in self._entries[-10:]:
            old_palette = entry.get("palette", {})
            if old_palette.get("bg", "").lower() == new_bg and old_palette.get("accent", "").lower() == new_accent:
                similar_count += 1

        if similar_count >= 2:
            return True, f"Same bg+accent palette used {similar_count} times recently"

        # Font similarity
        typo = scene_plan.get("typography", {})
        new_heading = typo.get("heading_font", "").lower()
        font_count = sum(
            1 for e in self._entries[-10:]
            if e.get("typography", {}).get("heading_font", "").lower() == new_heading
        )
        if font_count >= 3:
            return True, f"Heading font '{new_heading}' used {font_count} times recently"

        return False, None

    def record(self, scene_plan: dict, score: float = 0, user_id: str = ""):
        """Record a generated design in memory."""
        entry = {
            "fingerprint": self.fingerprint(scene_plan),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "palette": scene_plan.get("palette", {}),
            "typography": scene_plan.get("typography", {}),
            "design_family": scene_plan.get("meta", {}).get("design_family", ""),
            "hero_type": scene_plan.get("hero", {}).get("type", ""),
            "section_types": [s.get("type", "") for s in scene_plan.get("sections", [])],
            "score": score,
            "user_id": user_id,
        }
        self._entries.append(entry)
        self._save()
        logger.info(f"AntiClone: recorded design fp={entry['fingerprint']}, total={len(self._entries)}")

    def get_avoidance_prompt(self) -> str:
        """
        Generate a prompt snippet telling the model what to avoid.
        """
        if not self._entries:
            return ""

        recent = self._entries[-5:]
        avoid_parts = ["AVOID THESE RECENTLY USED COMBINATIONS:"]
        for e in recent:
            palette = e.get("palette", {})
            typo = e.get("typography", {})
            avoid_parts.append(
                f"- bg={palette.get('bg', '?')}, accent={palette.get('accent', '?')}, "
                f"font={typo.get('heading_font', '?')}, family={e.get('design_family', '?')}"
            )
        avoid_parts.append("Choose DIFFERENT colors, fonts, and layout approaches.")
        return "\n".join(avoid_parts)


# ─────────────────────────────────────────────────────────────────
#  3. TRUST ENGINE
# ─────────────────────────────────────────────────────────────────

TRUST_FILE = "/root/arcane/data/trust_scores.json"


class TrustEngine:
    """
    Tracks model performance per task type and role.
    Automatically recommends the best model based on historical scores.
    """

    def __init__(self, trust_file: str = TRUST_FILE):
        self._trust_file = trust_file
        self._scores: dict[str, list[dict]] = {}
        self._load()

    def _load(self):
        """Load trust scores from disk."""
        try:
            if os.path.exists(self._trust_file):
                with open(self._trust_file, "r") as f:
                    self._scores = json.load(f)
        except Exception as e:
            logger.warning(f"TrustEngine load failed: {e}")
            self._scores = {}

    def _save(self):
        """Save trust scores to disk."""
        try:
            os.makedirs(os.path.dirname(self._trust_file), exist_ok=True)
            with open(self._trust_file, "w") as f:
                json.dump(self._scores, f, indent=2)
        except Exception as e:
            logger.warning(f"TrustEngine save failed: {e}")

    def record_result(
        self,
        model_id: str,
        role: str,
        task_type: str,
        score: float,
        metadata: dict = None,
    ):
        """Record a model's performance on a task."""
        key = f"{role}:{task_type}"
        if key not in self._scores:
            self._scores[key] = []

        entry = {
            "model_id": model_id,
            "score": score,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "metadata": metadata or {},
        }
        self._scores[key].append(entry)

        # Keep only last 50 entries per key
        if len(self._scores[key]) > 50:
            self._scores[key] = self._scores[key][-50:]

        self._save()
        logger.info(f"TrustEngine: recorded {model_id} on {key} = {score}/10")

    def get_best_model(self, role: str, task_type: str) -> Optional[str]:
        """
        Get the best-performing model for a given role and task type.
        Returns model_id or None if insufficient data.
        """
        key = f"{role}:{task_type}"
        entries = self._scores.get(key, [])

        if len(entries) < 3:
            return None  # Not enough data

        # Group by model and calculate average score
        model_scores: dict[str, list[float]] = {}
        for entry in entries[-20:]:  # Last 20 entries
            mid = entry.get("model_id", "")
            if mid:
                if mid not in model_scores:
                    model_scores[mid] = []
                model_scores[mid].append(entry.get("score", 0))

        if not model_scores:
            return None

        # Find best average
        best_model = None
        best_avg = 0
        for mid, scores in model_scores.items():
            avg = sum(scores) / len(scores)
            if avg > best_avg:
                best_avg = avg
                best_model = mid

        if best_model and best_avg > 6.0:
            logger.info(f"TrustEngine: recommending {best_model} for {key} (avg={best_avg:.1f})")
            return best_model

        return None

    def get_stats(self) -> dict[str, Any]:
        """Get trust engine statistics."""
        stats = {}
        for key, entries in self._scores.items():
            if entries:
                model_scores: dict[str, list[float]] = {}
                for e in entries[-20:]:
                    mid = e.get("model_id", "")
                    if mid:
                        if mid not in model_scores:
                            model_scores[mid] = []
                        model_scores[mid].append(e.get("score", 0))

                stats[key] = {
                    "total_entries": len(entries),
                    "models": {
                        mid: {"avg": round(sum(s)/len(s), 1), "count": len(s)}
                        for mid, s in model_scores.items()
                    },
                }
        return stats


# ─────────────────────────────────────────────────────────────────
#  SINGLETONS
# ─────────────────────────────────────────────────────────────────

_scene_library: Optional[PremiumSceneLibrary] = None
_anti_clone: Optional[AntiCloneMemory] = None
_trust_engine: Optional[TrustEngine] = None


def get_scene_library() -> PremiumSceneLibrary:
    global _scene_library
    if _scene_library is None:
        _scene_library = PremiumSceneLibrary()
    return _scene_library


def get_anti_clone() -> AntiCloneMemory:
    global _anti_clone
    if _anti_clone is None:
        _anti_clone = AntiCloneMemory()
    return _anti_clone


def get_trust_engine() -> TrustEngine:
    global _trust_engine
    if _trust_engine is None:
        _trust_engine = TrustEngine()
    return _trust_engine
