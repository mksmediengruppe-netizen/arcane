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
5. Images must have descriptive search queries for Pexels (real photos only)
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
- gallery_grid: Photo gallery in masonry or grid layout
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
        "image_query": "pexels search query for background image (if type=image)",
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
            "image_query": "pexels search query (if section uses images)"
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

    def scene_plan_to_coder_prompt(self, scene_plan: dict) -> str:
        """DEPRECATED: No longer used in default flow since cutover v1 (2026-03-31).
        Kept for backward compatibility only. Will be removed in next release."""
        import warnings
        warnings.warn("scene_plan_to_coder_prompt is deprecated since cutover v1", DeprecationWarning, stacklevel=2)
        if "error" in scene_plan:
            return ""

        meta = scene_plan.get("meta", {})
        palette = scene_plan.get("palette", {})
        typo = scene_plan.get("typography", {})
        sections = scene_plan.get("sections", [])
        nav = scene_plan.get("navigation", {})
        footer = scene_plan.get("footer", {})
        responsive = scene_plan.get("responsive", {})

        prompt = f"""
═══════════════════════════════════════════════════════════════════
  SCENE PLAN — Follow this EXACTLY. Do NOT deviate.
═══════════════════════════════════════════════════════════════════

PROJECT: {meta.get('project_name', 'landing')}
LANGUAGE: {meta.get('language', 'en')}
MOOD: {', '.join(meta.get('mood', []))}
DESIGN FAMILY: {meta.get('design_family', 'clean_tech')}

── COLOR PALETTE (use these EXACT hex codes) ──
Background:       {palette.get('bg', '#FAFAF9')}
Background Alt:   {palette.get('bg_alt', '#F5F5F0')}
Surface:          {palette.get('surface', '#FFFFFF')}
Text Primary:     {palette.get('text_primary', '#1A1A1A')}
Text Secondary:   {palette.get('text_secondary', '#4A4A4A')}
Text Muted:       {palette.get('text_muted', '#8A8A8A')}
Accent:           {palette.get('accent', '#2563EB')}
Accent Hover:     {palette.get('accent_hover', '#1D4ED8')}
Border:           {palette.get('border', 'rgba(0,0,0,0.06)')}

── TYPOGRAPHY ──
Heading: {typo.get('heading_font', 'Inter')} (weights: {typo.get('heading_weights', [400, 600, 700])})
Body: {typo.get('body_font', 'Inter')} (weights: {typo.get('body_weights', [300, 400, 500])})
Google Fonts URL: {typo.get('google_fonts_url', '')}

Type Scale:
  Hero Title: {typo.get('scale', {}).get('hero_title', 'text-5xl md:text-7xl')}
  Section Title: {typo.get('scale', {}).get('section_title', 'text-3xl md:text-5xl')}
  Subtitle: {typo.get('scale', {}).get('subtitle', 'text-lg md:text-xl')}
  Body: {typo.get('scale', {}).get('body', 'text-base md:text-lg')}
  Kicker: {typo.get('scale', {}).get('kicker', 'text-xs uppercase tracking-[0.25em]')}

── NAVIGATION ──
Style: {nav.get('style', 'sticky_blur')}
Logo: {nav.get('logo_text', 'Brand')}
Links: {nav.get('links', [])}
CTA: {nav.get('cta_button', {}).get('text', 'Get Started')} ({nav.get('cta_button', {}).get('style', 'accent_filled')})

── SECTIONS (build these IN THIS EXACT ORDER) ──
"""
        for i, section in enumerate(sections, 1):
            prompt += f"\n{'─' * 60}\n"
            prompt += f"SECTION {i}: {section.get('id', f'section_{i}')} — Layout: {section.get('layout_type', '?')}\n"

            if section.get('min_height'):
                prompt += f"Min Height: {section['min_height']}\n"
            if section.get('padding'):
                prompt += f"Padding: {section['padding']}\n"
            if section.get('background_color'):
                prompt += f"Background: use palette.{section['background_color']}\n"

            bg = section.get('background', {})
            if bg:
                if bg.get('type') == 'image':
                    prompt += f"Background Image: search Pexels for \"{bg.get('image_query', '')}\"\n"
                    prompt += f"Overlay: {bg.get('overlay', 'bg-gradient-to-b from-black/50 to-black/20')}\n"
                elif bg.get('type') == 'gradient':
                    prompt += f"Background Gradient: {bg.get('gradient', '')}\n"

            content = section.get('content', {})
            if content:
                if content.get('kicker'):
                    prompt += f"Kicker: \"{content['kicker']}\"\n"
                if content.get('headline') or content.get('title'):
                    prompt += f"Title: \"{content.get('headline') or content.get('title', '')}\"\n"
                if content.get('subheadline') or content.get('subtitle'):
                    prompt += f"Subtitle: \"{content.get('subheadline') or content.get('subtitle', '')}\"\n"

                items = content.get('items', [])
                if items:
                    prompt += f"Items ({len(items)}):\n"
                    for j, item in enumerate(items, 1):
                        prompt += f"  {j}. {item.get('title', '?')}"
                        if item.get('icon'):
                            prompt += f" [icon: {item['icon']}]"
                        if item.get('image_query'):
                            prompt += f" [image: \"{item['image_query']}\"]"
                        prompt += f"\n     {item.get('description', '')}\n"

                cta_p = content.get('cta_primary', {})
                cta_s = content.get('cta_secondary', {})
                if cta_p:
                    prompt += f"CTA Primary: \"{cta_p.get('text', '')}\"\n"
                if cta_s:
                    prompt += f"CTA Secondary: \"{cta_s.get('text', '')}\"\n"

            anim = section.get('animation', {})
            if anim and anim.get('gsap'):
                prompt += f"Animation: {anim['gsap']}\n"

        # Footer
        prompt += f"\n{'─' * 60}\n"
        prompt += "FOOTER:\n"
        for col in footer.get('columns', []):
            prompt += f"  Column: {col.get('title', '?')}\n"
        prompt += f"  Copyright: {footer.get('copyright', '')}\n"

        # Responsive
        prompt += f"\n── RESPONSIVE ──\n"
        prompt += f"Mobile Nav: {responsive.get('mobile_nav', 'hamburger')}\n"
        prompt += f"Mobile Hero: {responsive.get('mobile_hero_height', 'min-h-[70vh]')}\n"

        prompt += f"""
{'═' * 60}
INSTRUCTIONS FOR CODER:
1. Follow this scene plan EXACTLY — do not add or remove sections
2. Use the EXACT hex codes from the palette
3. Use the EXACT Google Fonts from typography
4. Search Pexels for each image_query to get real photos
5. Implement all GSAP animations as specified
6. Build mobile-first with Tailwind CSS
7. The file should be a single HTML file with embedded CSS and JS
8. Use Tailwind CDN, GSAP CDN, Lucide Icons, and Swiper.js (if carousel needed)
{'═' * 60}
"""
        return prompt


def get_frontend_director(llm_client, router) -> FrontendDirector:
    """Factory function to create a FrontendDirector instance."""
    return FrontendDirector(llm_client, router)
