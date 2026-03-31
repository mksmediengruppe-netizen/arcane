"""
ARCANE FrontendFinisherWorker — Final Polish & Fix Application

Takes the judge panel feedback and applies fixes to the HTML:
- PATCH mode: Apply targeted CSS fixes from judge instructions
- REFACTOR mode: Rewrite significant portions while keeping structure
- REBUILD mode: Signal agent to start over with a different approach

Also handles the "finishing touches" that separate 7/10 from 9/10:
- Micro-animations (hover states, transitions, scroll reveals)
- Typography refinements (optical kerning, proper line heights)
- Color polish (subtle gradients, surface differentiation)
- Mobile fine-tuning (touch targets, font size adjustments)
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from shared.llm.client import UnifiedLLMClient
from shared.llm.router import ModelRouter
from shared.models.schemas import LLMRequest
from shared.utils.logger import get_logger

logger = get_logger("workers.frontend_finisher")


FINISHER_SYSTEM_PROMPT = """You are a senior Frontend Developer specializing in pixel-perfect implementation.
You receive an HTML file and a list of specific CSS/HTML fixes from a design review panel.
Your job is to apply ALL fixes precisely and add finishing polish.

RULES:
1. Apply EVERY fix instruction exactly as specified (selector + property + value)
2. Do NOT change the overall design direction, layout, or content
3. Do NOT remove existing animations or features
4. Add these finishing touches if not already present:
   - Smooth scroll behavior (html { scroll-behavior: smooth })
   - Transition on interactive elements (a, button { transition: all 0.3s ease })
   - Subtle hover states on cards (transform: translateY(-4px) + box-shadow)
   - Focus-visible outlines for accessibility
   - Selection color matching the accent
5. Ensure all images have loading="lazy" and alt attributes
6. Ensure proper meta viewport tag exists
7. Return the COMPLETE modified HTML file — do not truncate or summarize

OUTPUT FORMAT:
Return ONLY the complete HTML file content, nothing else. No markdown code blocks, no explanation.
Start with <!DOCTYPE html> and end with </html>."""


REFACTOR_SYSTEM_PROMPT = """You are a senior Frontend Developer performing a major design refactor.
You receive an HTML file that scored poorly on design review. You must make SIGNIFICANT improvements
while keeping the same content and general purpose.

The design review panel found these critical issues. You MUST fix ALL of them:

{issues}

SPECIFIC FIX INSTRUCTIONS (apply ALL of these):
{fixes}

REFACTORING RULES:
1. Keep all text content, images, and links unchanged
2. Completely rework the CSS — new spacing, new visual rhythm
3. Apply every specific fix instruction from the judges
4. Improve typography hierarchy dramatically
5. Add proper section padding (80-120px vertical)
6. Ensure color palette is cohesive (no pure #000 or #fff)
7. Add micro-animations and hover states
8. Ensure full mobile responsiveness
9. Return the COMPLETE modified HTML file

OUTPUT FORMAT:
Return ONLY the complete HTML file content. Start with <!DOCTYPE html> and end with </html>."""


class FrontendFinisher:
    """
    Applies judge panel fixes to HTML and adds finishing polish.
    Supports three modes: PATCH, REFACTOR, REBUILD.
    """

    def __init__(self, llm_client: UnifiedLLMClient, router: ModelRouter):
        self._client = llm_client
        self._router = router

    async def apply_fixes(
        self,
        html_content: str,
        panel_result: dict,
        scene_plan: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Apply fixes based on judge panel evaluation.

        Args:
            html_content: Current HTML file content
            panel_result: Result from JudgePanel.evaluate()
            scene_plan: Original scene plan (used for REBUILD context)

        Returns:
            {
                "action_taken": "PATCH" | "REFACTOR" | "REBUILD",
                "html": "modified HTML content" | None (for REBUILD),
                "changes_summary": "What was changed",
                "rebuild_instructions": "..." (only for REBUILD),
            }
        """
        action = panel_result.get("action", "REFACTOR")
        score = panel_result.get("overall_score", 0)

        logger.info(f"FrontendFinisher: action={action}, score={score}/10")

        if action == "REBUILD":
            return await self._handle_rebuild(panel_result, scene_plan)
        elif action == "REFACTOR":
            return await self._handle_refactor(html_content, panel_result)
        else:  # PATCH
            return await self._handle_patch(html_content, panel_result)

    async def _handle_patch(self, html_content: str, panel_result: dict) -> dict:
        """Apply targeted CSS fixes — minimal changes."""
        fixes = panel_result.get("all_fix_instructions", [])
        top_fixes = panel_result.get("top_priority_fixes", [])

        # Build fix instructions text
        fix_text = self._format_fixes(fixes)

        try:
            _tier = self._router._resolve_tier("coder")
            _model_id = self._router._resolve_model_id("coder", _tier) or "gpt-4.1"

            request = LLMRequest(
                messages=[
                    {"role": "system", "content": FINISHER_SYSTEM_PROMPT},
                    {"role": "user", "content": (
                        f"Apply these fixes to the HTML file:\n\n"
                        f"FIX INSTRUCTIONS:\n{fix_text}\n\n"
                        f"CURRENT HTML:\n{html_content}"
                    )},
                ],
                model_id=_model_id,
                temperature=0.1,
                max_tokens=16000,
            )

            response = await self._client.complete(request)
            new_html = self._extract_html(response.content)

            if new_html and len(new_html) > len(html_content) * 0.5:
                logger.info(f"PATCH applied: {len(fixes)} fixes, {len(new_html)} chars")
                return {
                    "action_taken": "PATCH",
                    "html": new_html,
                    "changes_summary": f"Applied {len(fixes)} targeted fixes + finishing polish",
                }
            else:
                logger.warning("PATCH result too short, returning original")
                return {
                    "action_taken": "PATCH",
                    "html": html_content,
                    "changes_summary": "Patch failed, original preserved",
                }

        except Exception as e:
            logger.warning(f"PATCH failed: {e}")
            return {
                "action_taken": "PATCH",
                "html": html_content,
                "changes_summary": f"Patch failed: {e}",
            }

    async def _handle_refactor(self, html_content: str, panel_result: dict) -> dict:
        """Major CSS/layout rework while keeping content."""
        fixes = panel_result.get("all_fix_instructions", [])
        issues = panel_result.get("critical_issues_summary", "")

        fix_text = self._format_fixes(fixes)

        prompt = REFACTOR_SYSTEM_PROMPT.format(
            issues=issues,
            fixes=fix_text,
        )

        try:
            _tier = self._router._resolve_tier("coder")
            _model_id = self._router._resolve_model_id("coder", _tier) or "gpt-4.1"

            request = LLMRequest(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": (
                        f"REFACTOR this HTML file. Apply ALL judge fixes and dramatically improve the design.\n\n"
                        f"CURRENT HTML ({len(html_content)} chars):\n{html_content}"
                    )},
                ],
                model_id=_model_id,
                temperature=0.3,
                max_tokens=16000,
            )

            response = await self._client.complete(request)
            new_html = self._extract_html(response.content)

            if new_html and len(new_html) > len(html_content) * 0.4:
                logger.info(f"REFACTOR applied: {len(new_html)} chars (was {len(html_content)})")
                return {
                    "action_taken": "REFACTOR",
                    "html": new_html,
                    "changes_summary": f"Major refactor: {len(fixes)} fixes applied, CSS reworked, layout improved",
                }
            else:
                logger.warning("REFACTOR result too short, returning original")
                return {
                    "action_taken": "REFACTOR",
                    "html": html_content,
                    "changes_summary": "Refactor failed, original preserved",
                }

        except Exception as e:
            logger.warning(f"REFACTOR failed: {e}")
            return {
                "action_taken": "REFACTOR",
                "html": html_content,
                "changes_summary": f"Refactor failed: {e}",
            }

    async def _handle_rebuild(self, panel_result: dict, scene_plan: Optional[dict]) -> dict:
        """Signal that the design needs to be rebuilt from scratch."""
        issues = panel_result.get("critical_issues_summary", "")
        judges = panel_result.get("judges", {})

        # Build rebuild instructions
        worst_judges = sorted(
            judges.items(),
            key=lambda x: x[1].get("score", 10),
        )[:3]

        rebuild_focus = []
        for judge_name, jr in worst_judges:
            rebuild_focus.append(
                f"- {judge_name.upper()} ({jr.get('score', '?')}/10): "
                f"{jr.get('summary', 'No details')}"
            )

        rebuild_instructions = (
            "THE CURRENT DESIGN HAS FUNDAMENTAL PROBLEMS AND MUST BE REBUILT.\n\n"
            "WORST AREAS:\n"
            + "\n".join(rebuild_focus)
            + "\n\nCRITICAL ISSUES:\n"
            + issues
            + "\n\nREBUILD REQUIREMENTS:\n"
            "1. Start with a completely fresh HTML file\n"
            "2. Choose a DIFFERENT visual approach than the current one\n"
            "3. Focus on the worst-scoring areas listed above\n"
            "4. Use generous spacing (100px+ section padding)\n"
            "5. Implement proper typography hierarchy from the start\n"
            "6. Use a cohesive color palette (no pure black/white)\n"
            "7. Build mobile-first responsive layout\n"
        )

        if scene_plan:
            rebuild_instructions += (
                "\n8. Follow the original scene plan for content and structure, "
                "but use a DIFFERENT visual treatment.\n"
            )

        logger.info(f"REBUILD signaled: worst judges = {[j[0] for j in worst_judges]}")

        return {
            "action_taken": "REBUILD",
            "html": None,
            "changes_summary": "Design requires complete rebuild",
            "rebuild_instructions": rebuild_instructions,
        }

    def _format_fixes(self, fixes: list) -> str:
        """Format fix instructions into readable text."""
        if not fixes:
            return "No specific fixes provided."

        lines = []
        for i, fix in enumerate(fixes, 1):
            if isinstance(fix, dict):
                selector = fix.get("selector", "?")
                prop = fix.get("property", "")
                value = fix.get("value", "")
                reason = fix.get("reason", "")
                add_el = fix.get("add_element", "")

                if prop and value:
                    lines.append(f"{i}. {selector} {{ {prop}: {value}; }}  /* {reason} */")
                elif add_el:
                    lines.append(f"{i}. ADD to {selector}: {add_el}  /* {reason} */")
                else:
                    lines.append(f"{i}. {selector}: {reason}")
            else:
                lines.append(f"{i}. {fix}")

        return "\n".join(lines)

    def _extract_html(self, content: str) -> Optional[str]:
        """Extract HTML from LLM response, handling markdown code blocks."""
        if not content:
            return None

        # Try to find HTML in code blocks first
        code_block_match = re.search(
            r"```(?:html)?\s*\n(<!DOCTYPE.*?</html>)\s*```",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if code_block_match:
            return code_block_match.group(1).strip()

        # Try direct HTML
        html_match = re.search(
            r"(<!DOCTYPE.*?</html>)",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if html_match:
            return html_match.group(1).strip()

        # If content starts with < it might be HTML without doctype
        if content.strip().startswith("<"):
            return content.strip()

        return None


# ─────────────────────────────────────────────────────────────────
#  SINGLETON
# ─────────────────────────────────────────────────────────────────

_instance: Optional[FrontendFinisher] = None


def get_frontend_finisher(llm_client=None, router=None) -> Optional[FrontendFinisher]:
    """Get or create the singleton FrontendFinisher."""
    global _instance
    if _instance is None and llm_client and router:
        _instance = FrontendFinisher(llm_client, router)
    return _instance
