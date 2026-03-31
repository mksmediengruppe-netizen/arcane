"""
ARCANE MultiConceptGenerator + DesignRanker
Generates multiple design concepts for a landing page and ranks them
to select the best one before coding begins.

Flow:
1. MultiConceptGenerator creates 3 distinct scene plans (different palettes, layouts, moods)
2. DesignRanker evaluates all 3 and picks the winner based on:
   - Relevance to user brief
   - Visual distinctiveness
   - Conversion potential
   - Originality (not template-like)
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Optional

from shared.llm.client import UnifiedLLMClient
from shared.llm.router import ModelRouter
from shared.models.schemas import LLMRequest, Tier
from shared.utils.logger import get_logger

logger = get_logger("workers.multi_concept")


# ─────────────────────────────────────────────────────────────────
#  CONCEPT GENERATION PROMPT
# ─────────────────────────────────────────────────────────────────

# NOTE: Uses __CONCEPT_NUM__ placeholder instead of {concept_number}
# because the JSON example contains curly braces that break Python .format()
CONCEPT_SYSTEM_PROMPT = """You are a world-class Web Art Director. You create DISTINCT design concepts for landing pages.

You will receive a user brief and optionally RAG references from award-winning sites.
Your job: generate ONE unique design concept as a JSON scene plan.

IMPORTANT CONSTRAINTS for concept #__CONCEPT_NUM__ of 3:
- Concept 1: SAFE — use the most natural palette/layout for this niche. Classic, proven, high-conversion.
- Concept 2: BOLD — unexpected palette or layout. Break conventions. Surprise the viewer.
- Concept 3: EDITORIAL — magazine-style, asymmetric, heavy typography, minimal images.

Each concept MUST differ in:
- Color palette (completely different hex values)
- Typography pairing (different font families)
- Hero section type (different layout approach)
- Overall mood (different adjectives)

Return ONLY valid JSON with this exact structure:
{
  "meta": {
    "concept_name": "Short creative name for this concept",
    "design_family": "dark_luxury|warm_editorial|clean_tech|bold_energy|soft_wellness|elegant_minimal",
    "mood": ["adjective1", "adjective2", "adjective3"],
    "rationale": "Why this concept works for the brief (2-3 sentences)"
  },
  "palette": {
    "bg": "#hex",
    "surface": "#hex",
    "text": "#hex",
    "muted": "#hex",
    "accent": "#hex",
    "accent_light": "#hex"
  },
  "typography": {
    "heading_font": "Font Name",
    "heading_weights": "400,600,700",
    "body_font": "Font Name",
    "body_weights": "300,400,500",
    "style_note": "How to use these fonts"
  },
  "hero": {
    "type": "full_viewport|split_screen|minimal_text|bento|magazine|parallax",
    "headline": "Main headline text",
    "subheadline": "Supporting text",
    "kicker": "Small text above headline",
    "cta_primary": "Button text",
    "cta_secondary": "Secondary button text or null",
    "visual_description": "What the hero image/visual should be",
    "photo_search_query": "Pexels search query for hero image"
  },
  "sections": [
    {
      "id": "section_id",
      "type": "features|services|about|testimonials|gallery|stats|cta|pricing|faq|team|process",
      "layout": "2_col_grid|3_col_cards|bento_grid|single_column|alternating_rows|stats_bar|full_width",
      "title": "Section title",
      "kicker": "Small text above title",
      "content_description": "What content goes here",
      "items_count": 3,
      "photo_search_query": "Pexels search query or null"
    }
  ],
  "animations": {
    "hero_entrance": "Description of hero animation",
    "scroll_reveals": "How sections appear on scroll",
    "micro_interactions": "Hover effects, transitions"
  },
  "footer": {
    "columns": ["About", "Links", "Contact", "Social"],
    "style": "minimal|detailed|dark_contrast"
  }
}"""


RANKER_SYSTEM_PROMPT = """You are a senior Design Director evaluating design concepts for a client project.

You will receive 3 design concepts (scene plans) for the same brief.
Evaluate each on these criteria (1-10 scale):

1. **Brief Alignment** (weight 0.30) — How well does it match what the client asked for?
2. **Visual Impact** (weight 0.25) — Will this design make a strong first impression?
3. **Conversion Potential** (weight 0.20) — Will visitors take action (buy, sign up, contact)?
4. **Originality** (weight 0.15) — Does it feel fresh and unique, not template-like?
5. **Feasibility** (weight 0.10) — Can this be built as a single HTML file with high quality?

Return ONLY valid JSON:
{
  "evaluations": [
    {
      "concept_index": 0,
      "concept_name": "Name from concept",
      "scores": {
        "brief_alignment": 8,
        "visual_impact": 7,
        "conversion_potential": 9,
        "originality": 6,
        "feasibility": 8
      },
      "weighted_score": 7.8,
      "strengths": ["strength1", "strength2"],
      "weaknesses": ["weakness1"]
    }
  ],
  "winner_index": 0,
  "winner_rationale": "Why this concept is the best choice (2-3 sentences)"
}"""


def _safe_parse_json(text: str) -> dict:
    """
    Robustly parse JSON from LLM output.
    Handles common issues: markdown fences, trailing commas, BOM, etc.
    """
    if not text:
        raise json.JSONDecodeError("Empty response", text, 0)

    # Strip BOM and whitespace
    text = text.strip().lstrip("\ufeff")

    # Remove markdown code fences if present
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        # Remove closing fence
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text
    # Look for first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        json_str = text[start:end + 1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # Last resort: try removing trailing commas before } or ]
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    return json.loads(cleaned)


class MultiConceptGenerator:
    """Generates multiple distinct design concepts for a landing page."""

    def __init__(self, llm_client: UnifiedLLMClient, router: ModelRouter):
        self._client = llm_client
        self._router = router

    async def generate_concepts(
        self,
        user_brief: str,
        rag_references: list[dict] = None,
        user_preferences: dict = None,
        num_concepts: int = 3,
    ) -> list[dict]:
        """
        Generate N distinct design concepts in parallel.
        Returns a list of scene plan dicts.
        """
        rag_references = rag_references or []
        user_preferences = user_preferences or {}

        # Build RAG context
        rag_context = ""
        if rag_references:
            rag_lines = []
            for ref in rag_references[:6]:
                if isinstance(ref, dict):
                    name = ref.get("name", "Unknown")
                    style = ref.get("style", "")
                    palette = ref.get("palette", "")
                    rag_lines.append(f"- {name}: {style}. Palette: {palette}")
                elif isinstance(ref, str):
                    rag_lines.append(f"- {ref}")
                else:
                    rag_lines.append(f"- {str(ref)}")
            rag_context = "\n\nAWARD-WINNING REFERENCES (study these for inspiration):\n" + "\n".join(rag_lines)

        # Preference context
        pref_context = ""
        if user_preferences:
            pref_parts = []
            if isinstance(user_preferences, dict):
                if user_preferences.get("preferred_style"):
                    pref_parts.append(f"Preferred style: {user_preferences['preferred_style']}")
                if user_preferences.get("brand_colors"):
                    pref_parts.append(f"Brand colors: {user_preferences['brand_colors']}")
            if pref_parts:
                pref_context = "\n\nUSER PREFERENCES:\n" + "\n".join(pref_parts)

        # Generate concepts in parallel
        tasks = []
        for i in range(num_concepts):
            tasks.append(self._generate_single_concept(
                concept_number=i + 1,
                user_brief=user_brief,
                rag_context=rag_context,
                pref_context=pref_context,
            ))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        concepts = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"Concept {i+1} generation failed: {type(result).__name__}: {result}")
                continue
            if result:
                concepts.append(result)

        logger.info(f"MultiConcept: generated {len(concepts)}/{num_concepts} concepts")
        return concepts

    async def _generate_single_concept(
        self,
        concept_number: int,
        user_brief: str,
        rag_context: str,
        pref_context: str,
    ) -> Optional[dict]:
        """Generate a single design concept."""
        # Use str.replace() instead of .format() to avoid KeyError on JSON curly braces
        system_prompt = CONCEPT_SYSTEM_PROMPT.replace("__CONCEPT_NUM__", str(concept_number))

        user_content = f"""CLIENT BRIEF:
{user_brief}
{rag_context}
{pref_context}

Generate concept #{concept_number} of 3. Remember:
- Concept 1 = SAFE (proven, classic for this niche)
- Concept 2 = BOLD (unexpected, convention-breaking)
- Concept 3 = EDITORIAL (magazine-style, typography-heavy)

Return ONLY the JSON scene plan."""

        try:
            # Use router.route() which handles model resolution, fallback, and LLM call
            response = await self._router.route(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                role="orchestrator",
                temperature=0.85 + (concept_number * 0.05),  # Slightly more creative for each concept
                max_tokens=3000,
                worker="multi_concept",
            )
            content = response.content.strip()

            # Parse JSON with robust parser
            concept = _safe_parse_json(content)
            if not isinstance(concept, dict):
                logger.warning(f"Concept {concept_number}: LLM returned {type(concept).__name__} instead of dict")
                return None

            # Validate required fields
            required = ["meta", "palette", "typography", "hero", "sections"]
            missing = [f for f in required if f not in concept]
            if missing:
                logger.warning(f"Concept {concept_number} missing fields: {missing}")
                return None

            concept["_concept_number"] = concept_number
            logger.info(
                f"Concept {concept_number}: "
                f"{concept.get('meta', {}).get('concept_name', '?')} — "
                f"{concept.get('meta', {}).get('design_family', '?')}"
            )
            return concept

        except json.JSONDecodeError as e:
            logger.warning(f"Concept {concept_number} JSON parse failed: {e}")
            # Log first 200 chars of response for debugging
            if 'content' in dir():
                logger.debug(f"Concept {concept_number} raw response (first 200): {content[:200]}")
            return None
        except Exception as e:
            logger.warning(f"Concept {concept_number} generation failed: {type(e).__name__}: {e}")
            return None


class DesignRanker:
    """Evaluates and ranks multiple design concepts to select the best one."""

    def __init__(self, llm_client: UnifiedLLMClient, router: ModelRouter):
        self._client = llm_client
        self._router = router

    async def rank_concepts(
        self,
        concepts: list[dict],
        user_brief: str,
    ) -> dict:
        """
        Rank concepts and return the winner with evaluation details.
        Returns: {
            "winner": <scene_plan dict>,
            "winner_index": int,
            "evaluations": [...],
            "rationale": str,
        }
        """
        if not concepts:
            return {"error": "No concepts to rank"}

        if len(concepts) == 1:
            return {
                "winner": concepts[0],
                "winner_index": 0,
                "evaluations": [],
                "rationale": "Only one concept generated, using it by default.",
            }

        # Build concepts summary for the ranker
        concepts_text = ""
        for i, concept in enumerate(concepts):
            if not isinstance(concept, dict):
                continue
            meta = concept.get("meta", {})
            palette = concept.get("palette", {})
            typo = concept.get("typography", {})
            hero = concept.get("hero", {})
            sections = concept.get("sections", [])

            concepts_text += f"""
═══ CONCEPT {i+1}: {meta.get('concept_name', 'Unnamed')} ═══
Design Family: {meta.get('design_family', '?')}
Mood: {', '.join(meta.get('mood', []))}
Rationale: {meta.get('rationale', '?')}
Palette: bg={palette.get('bg')}, accent={palette.get('accent')}, text={palette.get('text')}
Typography: {typo.get('heading_font', '?')} + {typo.get('body_font', '?')}
Hero Type: {hero.get('type', '?')} — "{hero.get('headline', '?')}"
Sections ({len(sections)}): {', '.join(s.get('type', '?') for s in sections)}
"""

        try:
            response = await self._router.route(
                messages=[
                    {"role": "system", "content": RANKER_SYSTEM_PROMPT},
                    {"role": "user", "content": f"CLIENT BRIEF:\n{user_brief}\n\n{concepts_text}\n\nEvaluate all concepts and pick the winner. Return JSON only."},
                ],
                role="orchestrator",
                temperature=0.3,  # Low temperature for consistent evaluation
                max_tokens=2000,
                worker="design_ranker",
            )
            result = _safe_parse_json(response.content.strip())

            winner_index = result.get("winner_index", 0)
            if winner_index < 0 or winner_index >= len(concepts):
                winner_index = 0

            return {
                "winner": concepts[winner_index],
                "winner_index": winner_index,
                "evaluations": result.get("evaluations", []),
                "rationale": result.get("winner_rationale", "Selected by ranker."),
            }

        except Exception as e:
            logger.warning(f"DesignRanker failed: {e}, falling back to concept 1")
            return {
                "winner": concepts[0],
                "winner_index": 0,
                "evaluations": [],
                "rationale": f"Ranker failed ({e}), defaulting to first concept.",
            }


# ─────────────────────────────────────────────────────────────────
#  CONVENIENCE FUNCTIONS
# ─────────────────────────────────────────────────────────────────

async def generate_and_rank(
    llm_client: UnifiedLLMClient,
    router: ModelRouter,
    user_brief: str,
    rag_references: list[dict] = None,
    user_preferences: dict = None,
    num_concepts: int = 3,
) -> dict:
    """
    Full pipeline: generate N concepts, rank them, return the winner.
    Returns: {
        "winner": <best scene_plan>,
        "all_concepts": [<all generated concepts>],
        "evaluations": [...],
        "rationale": str,
    }
    """
    generator = MultiConceptGenerator(llm_client, router)
    ranker = DesignRanker(llm_client, router)

    t0 = time.monotonic()

    # Generate concepts
    concepts = await generator.generate_concepts(
        user_brief=user_brief,
        rag_references=rag_references,
        user_preferences=user_preferences,
        num_concepts=num_concepts,
    )

    if not concepts:
        return {"error": "Failed to generate any concepts"}

    # Rank them
    ranking = await ranker.rank_concepts(concepts, user_brief)

    elapsed = time.monotonic() - t0
    logger.info(
        f"MultiConcept pipeline: {len(concepts)} concepts generated, "
        f"winner=#{ranking.get('winner_index', 0)+1}, "
        f"elapsed={elapsed:.1f}s"
    )

    return {
        "winner": ranking["winner"],
        "all_concepts": concepts,
        "winner_index": ranking.get("winner_index", 0),
        "evaluations": ranking.get("evaluations", []),
        "rationale": ranking.get("rationale", ""),
        "elapsed_seconds": round(elapsed, 1),
    }
