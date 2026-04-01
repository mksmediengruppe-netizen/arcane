"""
ARCANE FrontendDirectorWorker
Separates "creative direction" from "coding" in landing page generation.

The Director receives:
  - User's brief (what they want)
  - RAG references (from search_design_inspiration)
  - User preferences (from profile)

And produces a structured scene_plan — a JSON blueprint that the Coder
(orchestrator) follows exactly. This eliminates the "one LLM does everything"
problem where creative decisions and HTML coding compete for attention.

The scene_plan contains:
  - meta: project name, language, mood keywords
  - palette: exact hex codes for all design tokens
  - typography: Google Fonts families, weights, sizes
  - sections: ordered list of page sections with layout, content, images
  - animations: GSAP animation directives
  - responsive: breakpoint-specific overrides

Usage:
    from workers.frontend_director import FrontendDirector
    director = FrontendDirector(llm_client, router)
    scene_plan = await director.create_scene_plan(
        user_brief="Сделай лендинг для барбершопа в тёмном стиле",
        rag_references=[...],
        user_preferences={...},
    )
    # scene_plan is a dict that gets JSON-serialized and injected into the coder prompt
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from shared.utils.logger import get_logger

logger = get_logger("workers.frontend_director")

# ═══════════════════════════════════════════════════════════════════════════════
# DIRECTOR SYSTEM PROMPT — This is the "creative brain"
# ═══════════════════════════════════════════════════════════════════════════════

DIRECTOR_SYSTEM_PROMPT = """You are an elite Web Art Director at a top-tier design agency.
Your job is to create a detailed SCENE PLAN for a landing page — a structured JSON blueprint
that a frontend developer will follow EXACTLY to build the page.

You DO NOT write HTML/CSS/JS. You think ONLY about design: mood, colors, typography,
layout composition, section flow, image direction, animation choreography, and copy tone.

Your output quality determines the final website quality. Think like Pentagram, Sagmeister & Walsh,
or Collins. Every decision must be intentional and defensible.

RULES:
1. ALWAYS output valid JSON — no markdown, no comments, no explanation outside JSON
2. Use EXACT hex codes, not color names
3. Use EXACT Google Fonts names with weights
4. Every section must have a clear layout_type and content structure
5. Images must have DETAILED AI image generation prompts (50+ words each, unique per section). NOT search queries — full descriptions with subject, lighting, composition, mood, style.
6. Copy must be in the user's language (detect from their brief)
7. NEVER use pure white (#FFFFFF) or pure black (#000000) — use off-white and near-black
8. Sections must have VARIETY — never repeat the same layout consecutively
9. Hero section must be min 90vh with clear visual hierarchy
10. Include 6-10 sections for a complete landing page
11. Animation directives must be specific GSAP instructions, not vague descriptions

BANNED ELEMENTS (never include these):
- particles.js, three.js backgrounds
- Glassmorphism / frosted glass cards
- Dark gradient mesh backgrounds
- Floating orbs / blobs / rainbow gradients
- Lorem ipsum or placeholder text

AI IMAGE GENERATION RULES (CRITICAL):
- Every section that uses images MUST have a detailed image_prompt field (50+ words)
- image_prompt describes the DESIRED image for AI generation, NOT a search query
- Each image_prompt MUST be COMPLETELY UNIQUE — no two sections should have similar descriptions
- Include: subject, setting, composition, lighting, color palette, mood, camera angle, style
- End every prompt with "No text, no watermarks, no logos."
- GOOD: "A barista carefully pouring steamed milk into a ceramic cup creating latte art, shot from above at 45-degree angle, warm golden morning light streaming through large windows, rustic wooden counter with scattered coffee beans, shallow depth of field, editorial photography style. No text, no watermarks."
- BAD: "coffee shop interior" (too generic, no details)

SECTION LAYOUT TYPES (use these exact names):
- hero_fullscreen: Full viewport hero with bg image/video, overlay, headline, CTA
- hero_split: 50/50 split with text left, image right (or reversed)
- hero_minimal: Clean text-focused hero with subtle background
- two_column: Text + image side by side (alternating left/right)
- three_cards: 3 cards in a row (services, features, benefits)
- four_cards: 4 cards in a grid
- bento_grid: Asymmetric grid with mixed sizes (2x2, 1x2, 2x1)
- stats_counters: Horizontal row of 3-5 statistics with numbers
- testimonials_carousel: Client quotes with avatars
- testimonials_grid: 2-3 testimonials in a grid layout
- gallery_grid: Photo gallery in masonry or grid layout. MUST include 4-6 items, each with a UNIQUE image_prompt (50+ words)
- cta_banner: Full-width call-to-action section
- faq_accordion: Frequently asked questions with expand/collapse
- pricing_table: 2-3 pricing tiers side by side
- timeline: Vertical or horizontal timeline of steps/process
- team_grid: Team member cards with photos
- logo_strip: Client/partner logos in a horizontal strip
- text_block: Single column centered text (about, mission statement)
- footer_4col: 4-column footer with links, contact, social

OUTPUT SCHEMA (you MUST follow this exactly):
{
  "meta": {
    "project_name": "string — descriptive filename like 'luxe_barber_landing'",
    "language": "ru|en|de|etc",
    "mood": ["3-4 mood adjectives"],
    "design_family": "dark_luxury|warm_editorial|clean_tech|bold_energy|soft_wellness|elegant_minimal"
  },
  "palette": {
    "bg": "#hex — main background",
    "bg_alt": "#hex — alternate section background",
    "surface": "#hex — card/container background",
    "text_primary": "#hex — main text color",
    "text_secondary": "#hex — secondary text",
    "text_muted": "#hex — muted/caption text",
    "accent": "#hex — primary accent (CTA buttons, links)",
    "accent_hover": "#hex — accent hover state",
    "border": "#hex — subtle borders"
  },
  "typography": {
    "heading_font": "Google Font Name",
    "heading_weights": [400, 600, 700],
    "body_font": "Google Font Name",
    "body_weights": [300, 400, 500],
    "google_fonts_url": "full URL for <link> tag",
    "scale": {
      "hero_title": "text-5xl md:text-7xl lg:text-8xl",
      "section_title": "text-3xl md:text-5xl",
      "subtitle": "text-lg md:text-xl",
      "body": "text-base md:text-lg",
      "caption": "text-sm",
      "kicker": "text-xs uppercase tracking-[0.25em]"
    }
  },
  "sections": [
    {
      "id": "hero",
      "layout_type": "hero_fullscreen|hero_split|hero_minimal",
      "min_height": "90vh|100vh|80vh",
      "background": {
        "type": "image|color|gradient",
        "image_prompt": "DETAILED AI image generation prompt (50+ words) describing the desired background image with subject, composition, lighting, color palette, mood, camera angle. Must be unique.",
        "overlay": "bg-gradient-to-b from-black/60 to-black/30 (if type=image)",
        "color": "#hex (if type=color)",
        "gradient": "CSS gradient string (if type=gradient)"
      },
      "content": {
        "kicker": "Small caps text above headline (e.g., 'PREMIUM BARBERSHOP')",
        "headline": "Main headline text",
        "subheadline": "Supporting text under headline",
        "cta_primary": {"text": "Button text", "action": "scroll_to_section|link"},
        "cta_secondary": {"text": "Button text", "action": "scroll_to_section|link"}
      },
      "animation": {
        "type": "stagger_reveal",
        "elements": ["kicker", "headline", "subheadline", "cta"],
        "gsap": "gsap.from('.hero-element', {y:60, opacity:0, duration:1.2, stagger:0.2, ease:'power4.out'})"
      }
    },
    {
      "id": "unique_section_id",
      "layout_type": "one of the layout types above",
      "background_color": "bg|bg_alt|surface (reference palette key)",
      "padding": "py-24 md:py-32",
      "content": {
        "kicker": "optional small text",
        "title": "Section title",
        "subtitle": "Section description",
        "items": [
          {
            "title": "Item title",
            "description": "Item description",
            "icon": "lucide icon name (e.g., scissors, star, clock)",
            "image_prompt": "DETAILED AI image generation prompt (30+ words) for this specific item. Must be UNIQUE — different subject, angle, composition from other items."
          }
        ]
      },
      "animation": {
        "type": "fade_up|stagger_cards|counter|parallax|none",
        "gsap": "specific GSAP code"
      }
    }
  ],
  "navigation": {
    "style": "sticky_blur|sticky_solid|transparent_to_solid",
    "logo_text": "Brand name or null if logo image",
    "links": ["Section names for nav links"],
    "cta_button": {"text": "CTA text", "style": "accent_filled|accent_outline"}
  },
  "footer": {
    "layout_type": "footer_4col",
    "columns": [
      {"title": "Column title", "links": ["Link 1", "Link 2"]},
      {"title": "Contact", "content": "Address, phone, email"},
      {"title": "Social", "links": ["Instagram", "Telegram", "WhatsApp"]}
    ],
    "copyright": "© 2026 Brand Name. All rights reserved."
  },
  "responsive": {
    "mobile_nav": "hamburger|bottom_bar",
    "mobile_hero_height": "min-h-[70vh]",
    "mobile_font_scale": 0.75,
    "mobile_padding_scale": 0.6
  }
}"""


# ═══════════════════════════════════════════════════════════════════════════════
# DIRECTOR CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class FrontendDirector:
    """
    Creates structured scene plans for landing pages.
    Separates creative direction from code generation.
    """

    def __init__(self, llm_client, router):
        self._client = llm_client
        self._router = router

    async def create_scene_plan(
        self,
        user_brief: str,
        rag_references: list[dict] | None = None,
        user_preferences: dict | None = None,
        industry: str = "",
        mood: str = "",
    ) -> dict:
        """
        Generate a complete scene plan from user brief and references.

        Args:
            user_brief: The user's original request text
            rag_references: List of RAG reference dicts from search_design_inspiration
            user_preferences: User style preferences from profile
            industry: Detected industry/niche
            mood: Detected mood/style

        Returns:
            dict with the scene plan, or {"error": "..."} on failure
        """
        start = time.monotonic()

        # Build the user prompt with all available context
        user_prompt = self._build_user_prompt(
            user_brief, rag_references, user_preferences, industry, mood
        )

        try:
            # Use the highest-tier model for creative direction
            response = await self._router.route(
                messages=[
                    {"role": "system", "content": DIRECTOR_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                role="orchestrator",  # Use top-tier model for creative decisions
                user_id="system",
                project_id="director",
                worker="frontend_director",
            )

            raw = response.content or ""
            scene_plan = self._parse_scene_plan(raw)

            if "error" in scene_plan:
                logger.warning(f"Director failed to produce valid scene plan: {scene_plan['error']}")
                # Retry once with a simpler prompt
                scene_plan = await self._retry_simple(user_brief)

            elapsed = time.monotonic() - start
            logger.info(
                f"Director created scene plan in {elapsed:.1f}s: "
                f"{len(scene_plan.get('sections', []))} sections, "
                f"family={scene_plan.get('meta', {}).get('design_family', '?')}"
            )

            scene_plan["_meta"] = {
                "generated_by": "FrontendDirector",
                "generation_time_s": round(elapsed, 1),
                "model": response.model_id,
                "cost_usd": response.cost_usd,
            }

            return scene_plan

        except Exception as e:
            logger.error(f"Director error: {e}")
            return {"error": str(e)}

    def _build_user_prompt(
        self,
        user_brief: str,
        rag_references: list[dict] | None,
        user_preferences: dict | None,
        industry: str,
        mood: str,
    ) -> str:
        """Build the user prompt with all context for the Director."""
        parts = [f"USER BRIEF:\n{user_brief}"]

        if industry:
            parts.append(f"\nDETECTED INDUSTRY: {industry}")
        if mood:
            parts.append(f"\nDETECTED MOOD: {mood}")

        if rag_references:
            ref_text = "\nDESIGN REFERENCES (from our curated database — study these carefully):\n"
            for i, ref in enumerate(rag_references[:6], 1):
                ref_text += (
                    f"\n{i}. {ref.get('title', 'Unknown')}\n"
                    f"   Style: {ref.get('design_style', '?')}\n"
                    f"   Colors: {ref.get('primary_colors', [])}\n"
                    f"   Typography: {ref.get('typography_style', '?')}\n"
                    f"   Layout: {ref.get('layout_pattern', '?')}\n"
                    f"   Mood: {ref.get('mood', '?')}\n"
                    f"   Key techniques: {ref.get('key_techniques', '?')}\n"
                )
            parts.append(ref_text)

        if user_preferences:
            pref_text = "\nUSER STYLE PREFERENCES (from previous projects):\n"
            for k, v in user_preferences.items():
                if v:
                    pref_text += f"  - {k}: {v}\n"
            parts.append(pref_text)

        parts.append(
            "\n\nCreate a complete scene plan following the OUTPUT SCHEMA exactly. "
            "Output ONLY valid JSON — no markdown, no explanation."
        )

        return "\n".join(parts)

    def _parse_scene_plan(self, raw: str) -> dict:
        """Parse the LLM response into a scene plan dict."""
        # Strip markdown code blocks if present
        text = raw.strip()
        if text.startswith("```"):
            # Remove first line (```json or ```)
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            plan = json.loads(text)
        except json.JSONDecodeError as e:
            # Try to find JSON object in the response
            import re
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                try:
                    plan = json.loads(match.group())
                except json.JSONDecodeError:
                    return {"error": f"Invalid JSON from Director: {str(e)[:200]}"}
            else:
                return {"error": f"No JSON found in Director response: {text[:200]}"}

        # Validate required fields
        required = ["meta", "palette", "typography", "sections"]
        missing = [f for f in required if f not in plan]
        if missing:
            return {"error": f"Scene plan missing required fields: {missing}"}

        if not plan.get("sections") or len(plan["sections"]) < 3:
            return {"error": f"Scene plan has too few sections: {len(plan.get('sections', []))}"}

        return plan

    async def _retry_simple(self, user_brief: str) -> dict:
        """Retry with a simpler prompt if the first attempt failed."""
        simple_prompt = (
            f"Create a scene plan for this landing page request:\n{user_brief}\n\n"
            "Output ONLY valid JSON following the schema. Keep it simple but complete: "
            "8 sections, proper palette, typography, and content."
        )

        try:
            response = await self._router.route(
                messages=[
                    {"role": "system", "content": DIRECTOR_SYSTEM_PROMPT},
                    {"role": "user", "content": simple_prompt},
                ],
                role="orchestrator",
                user_id="system",
                project_id="director",
                worker="frontend_director",
            )
            return self._parse_scene_plan(response.content or "")
        except Exception as e:
            return {"error": f"Retry also failed: {e}"}


def get_frontend_director(llm_client, router) -> FrontendDirector:
    """Factory function to create a FrontendDirector instance."""
    return FrontendDirector(llm_client, router)
