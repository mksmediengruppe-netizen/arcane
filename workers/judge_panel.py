"""
ARCANE Judge Panel v3 — 5 Specialized Design Judges

Instead of one generic Vision Judge, this module runs 5 specialized judges
in parallel, each focusing on a specific aspect of design quality:

1. TypographyJudge — font choices, hierarchy, spacing, readability
2. ColorJudge — palette harmony, contrast, brand consistency
3. LayoutJudge — spacing, alignment, visual rhythm, section flow
4. MobileJudge — responsive behavior, touch targets, mobile UX
5. ConversionJudge — CTA clarity, trust signals, user flow

Each judge returns:
- score (1-10)
- critical_issues (list of specific problems)
- fix_instructions (concrete CSS/HTML fixes)
- verdict: PASS / NEEDS_FIX / REBUILD

The panel aggregates scores and determines the overall action:
- PATCH: score >= 7.5, minor fixes only
- REFACTOR: score 5.0-7.4, significant changes needed
- REBUILD: score < 5.0, start over with different approach
"""

from __future__ import annotations

import asyncio
import json
import time
import base64
from typing import Any, Optional

from shared.utils.logger import get_logger

logger = get_logger("workers.judge_panel")


# ─────────────────────────────────────────────────────────────────
#  JUDGE DEFINITIONS
# ─────────────────────────────────────────────────────────────────

JUDGES = {
    "typography": {
        "weight": 0.20,
        "prompt": """You are a Typography Expert Judge. Evaluate ONLY typography quality in this web page screenshot.

Score 1-10 on these criteria:
- Font pairing quality (do heading + body fonts complement each other?)
- Visual hierarchy (is there clear h1 > h2 > h3 > body progression?)
- Line height and letter spacing (comfortable reading?)
- Font sizes (hero headline >= 48px? body >= 16px?)
- Text contrast against background (WCAG AA minimum)
- Kicker/label typography (small caps, tracking, weight?)
- Consistency across sections

CRITICAL RED FLAGS (auto-deduct 2 points each):
- Default system fonts (Arial, Times New Roman, sans-serif without specific font)
- All text same size (no hierarchy)
- Line height < 1.4 for body text
- Hero headline smaller than 40px
- White text on light background or dark text on dark background

Return JSON:
{
  "judge": "typography",
  "score": 7,
  "critical_issues": ["Issue 1 with specific element", "Issue 2"],
  "fix_instructions": [
    {"selector": ".hero h1", "property": "font-size", "value": "clamp(3rem, 6vw, 5rem)", "reason": "Hero headline too small"},
    {"selector": "body", "property": "line-height", "value": "1.7", "reason": "Body text cramped"}
  ],
  "verdict": "NEEDS_FIX",
  "summary": "One sentence summary"
}""",
    },
    "color": {
        "weight": 0.20,
        "prompt": """You are a Color & Visual Design Expert Judge. Evaluate ONLY color and visual quality.

Score 1-10 on these criteria:
- Palette cohesion (do all colors work together harmoniously?)
- Accent color usage (is there a clear accent that draws attention to CTAs?)
- Background variety (not all sections same background color?)
- Gradient and overlay quality (subtle, not garish?)
- Dark/light balance (appropriate for the brand mood?)
- Surface differentiation (cards vs background vs sections)
- No pure #000000 or #FFFFFF (use near-black/near-white instead)

CRITICAL RED FLAGS (auto-deduct 2 points each):
- Pure white (#fff/#ffffff) background with no texture or warmth
- Pure black (#000/#000000) text
- More than 3 competing accent colors
- Clashing color combinations
- No visual distinction between sections
- CTA button same color as background

Return JSON:
{
  "judge": "color",
  "score": 7,
  "critical_issues": ["Issue 1", "Issue 2"],
  "fix_instructions": [
    {"selector": "body", "property": "background-color", "value": "#0a0a0f", "reason": "Pure white too harsh"},
    {"selector": ".cta-btn", "property": "background", "value": "linear-gradient(135deg, #6366f1, #8b5cf6)", "reason": "CTA needs gradient accent"}
  ],
  "verdict": "NEEDS_FIX",
  "summary": "One sentence summary"
}""",
    },
    "layout": {
        "weight": 0.25,
        "prompt": """You are a Layout & Spacing Expert Judge. Evaluate ONLY layout, spacing, and visual rhythm.

Score 1-10 on these criteria:
- Section padding (each section should have generous vertical padding, 80-120px)
- Content max-width (text content should not exceed 1200px, hero text ~800px)
- Grid alignment (are elements properly aligned on a grid?)
- White space usage (enough breathing room between elements?)
- Visual rhythm (consistent spacing pattern throughout?)
- Section variety (not all sections look the same layout)
- Hero section impact (does it fill the viewport? Is it commanding?)
- Card/feature spacing (gap between cards, internal padding)

CRITICAL RED FLAGS (auto-deduct 2 points each):
- Content touching edges (no padding)
- Sections with less than 60px vertical padding
- Text lines longer than 75 characters
- No max-width constraint (text stretches full viewport)
- All sections identical layout (monotonous)
- Hero section less than 80vh height
- Cramped cards with insufficient internal padding

Return JSON:
{
  "judge": "layout",
  "score": 7,
  "critical_issues": ["Issue 1", "Issue 2"],
  "fix_instructions": [
    {"selector": "section", "property": "padding", "value": "100px 0", "reason": "Sections need more vertical breathing room"},
    {"selector": ".container", "property": "max-width", "value": "1200px", "reason": "Content too wide"}
  ],
  "verdict": "NEEDS_FIX",
  "summary": "One sentence summary"
}""",
    },
    "mobile": {
        "weight": 0.15,
        "prompt": """You are a Mobile & Responsive Design Expert Judge. Evaluate ONLY mobile responsiveness.

You will receive TWO screenshots: desktop (1440px) and mobile (390px).
Focus primarily on the MOBILE screenshot.

Score 1-10 on these criteria:
- Text readability on mobile (font sizes appropriate? Not too small?)
- Touch targets (buttons at least 44px tall?)
- Horizontal overflow (nothing overflows the viewport?)
- Image scaling (images resize properly?)
- Navigation (hamburger menu or appropriate mobile nav?)
- Content stacking (multi-column layouts stack to single column?)
- Hero section on mobile (still impactful? Text not tiny?)
- Card layouts on mobile (single column? Readable?)

CRITICAL RED FLAGS (auto-deduct 2 points each):
- Horizontal scroll on mobile
- Text smaller than 14px on mobile
- Buttons smaller than 44px touch target
- Multi-column layout not collapsing on mobile
- Fixed-width elements breaking mobile layout
- Navigation items too small to tap

Return JSON:
{
  "judge": "mobile",
  "score": 7,
  "critical_issues": ["Issue 1", "Issue 2"],
  "fix_instructions": [
    {"selector": ".hero h1", "property": "font-size", "value": "clamp(2rem, 8vw, 3.5rem)", "reason": "Hero text too large on mobile"},
    {"selector": "@media (max-width: 768px) .grid", "property": "grid-template-columns", "value": "1fr", "reason": "Grid not stacking on mobile"}
  ],
  "verdict": "NEEDS_FIX",
  "summary": "One sentence summary"
}""",
    },
    "conversion": {
        "weight": 0.20,
        "prompt": """You are a Conversion & UX Expert Judge. Evaluate ONLY conversion optimization and user experience.

Score 1-10 on these criteria:
- CTA visibility (is the primary CTA immediately visible and compelling?)
- CTA copy (action-oriented text, not generic "Submit" or "Click here"?)
- Trust signals (testimonials, logos, stats, guarantees?)
- Value proposition clarity (can visitor understand the offer in 5 seconds?)
- Visual hierarchy for scanning (can user scan the page quickly?)
- Social proof placement (near CTAs?)
- Urgency/scarcity elements (if appropriate for the niche)
- Form simplicity (if forms exist, are they minimal?)
- Navigation clarity (can user find what they need?)

CRITICAL RED FLAGS (auto-deduct 2 points each):
- No visible CTA above the fold
- CTA blends into background (low contrast)
- Generic CTA text ("Submit", "Click Here", "Learn More" without context)
- No social proof anywhere on the page
- Value proposition unclear or buried
- Too many competing CTAs confusing the user

Return JSON:
{
  "judge": "conversion",
  "score": 7,
  "critical_issues": ["Issue 1", "Issue 2"],
  "fix_instructions": [
    {"selector": ".cta-primary", "property": "font-size", "value": "1.125rem", "reason": "CTA text too small"},
    {"selector": ".hero", "add_element": "<div class='trust-bar'>Trusted by 500+ companies</div>", "reason": "No trust signals above fold"}
  ],
  "verdict": "NEEDS_FIX",
  "summary": "One sentence summary"
}""",
    },
}


# ─────────────────────────────────────────────────────────────────
#  JUDGE PANEL
# ─────────────────────────────────────────────────────────────────

class JudgePanel:
    """
    Runs 5 specialized judges in parallel and aggregates results
    into a unified evaluation with an overall action decision.
    """

    def __init__(self, openrouter_api_key: str = "", model: str = ""):
        import os
        self._api_key = openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
        self._model = model or os.getenv("VISION_JUDGE_MODEL", "google/gemini-2.5-flash")
        self._base_url = "https://openrouter.ai/api/v1"

    async def evaluate(
        self,
        desktop_screenshot_b64: str,
        mobile_screenshot_b64: Optional[str] = None,
        html_content: Optional[str] = None,
        user_brief: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Run all 5 judges in parallel and aggregate results.

        Returns:
        {
            "overall_score": 7.2,
            "action": "REFACTOR",  # PATCH / REFACTOR / REBUILD
            "judges": {
                "typography": {"score": 7, "critical_issues": [...], ...},
                "color": {"score": 8, ...},
                ...
            },
            "all_fix_instructions": [...],  # Merged from all judges
            "critical_issues_summary": "...",
            "top_priority_fixes": [...],  # Top 5 most impactful fixes
        }
        """
        t0 = time.monotonic()

        # Run all judges in parallel
        tasks = {}
        for judge_name, judge_config in JUDGES.items():
            tasks[judge_name] = self._run_single_judge(
                judge_name=judge_name,
                judge_prompt=judge_config["prompt"],
                desktop_b64=desktop_screenshot_b64,
                mobile_b64=mobile_screenshot_b64 if judge_name == "mobile" else None,
                html_content=html_content[:3000] if html_content and judge_name == "conversion" else None,
                user_brief=user_brief,
            )

        # Gather results
        results_list = await asyncio.gather(*tasks.values(), return_exceptions=True)
        judge_results = {}
        for judge_name, result in zip(tasks.keys(), results_list):
            if isinstance(result, Exception):
                logger.warning(f"Judge {judge_name} failed: {result}")
                judge_results[judge_name] = {
                    "score": 5.0,
                    "critical_issues": [f"Judge failed: {result}"],
                    "fix_instructions": [],
                    "verdict": "NEEDS_FIX",
                    "summary": "Judge evaluation failed",
                }
            elif result:
                judge_results[judge_name] = result
            else:
                judge_results[judge_name] = {
                    "score": 5.0,
                    "critical_issues": ["Judge returned empty result"],
                    "fix_instructions": [],
                    "verdict": "NEEDS_FIX",
                    "summary": "No evaluation available",
                }

        # Calculate weighted overall score
        overall_score = 0.0
        total_weight = 0.0
        for judge_name, judge_config in JUDGES.items():
            if judge_name in judge_results:
                weight = judge_config["weight"]
                score = judge_results[judge_name].get("score", 5.0)
                overall_score += score * weight
                total_weight += weight

        if total_weight > 0:
            overall_score = round(overall_score / total_weight, 1)

        # Determine action
        if overall_score >= 7.5:
            action = "PATCH"
        elif overall_score >= 5.0:
            action = "REFACTOR"
        else:
            action = "REBUILD"

        # Check if any single judge says REBUILD
        for jr in judge_results.values():
            if jr.get("verdict") == "REBUILD":
                action = "REBUILD"
                break

        # Merge all fix instructions
        all_fixes = []
        for jr in judge_results.values():
            fixes = jr.get("fix_instructions", [])
            if isinstance(fixes, list):
                all_fixes.extend(fixes)

        # Collect all critical issues
        all_issues = []
        for judge_name, jr in judge_results.items():
            issues = jr.get("critical_issues", [])
            if isinstance(issues, list):
                for issue in issues:
                    all_issues.append(f"[{judge_name.upper()}] {issue}")

        # Top priority fixes (first 5)
        top_fixes = all_fixes[:5]

        elapsed = time.monotonic() - t0

        result = {
            "overall_score": overall_score,
            "action": action,
            "judges": judge_results,
            "all_fix_instructions": all_fixes,
            "critical_issues_summary": "\n".join(all_issues) if all_issues else "No critical issues found.",
            "top_priority_fixes": top_fixes,
            "elapsed_seconds": round(elapsed, 1),
        }

        judges_str = ', '.join(f'{k}={v.get("score", "?")}/10' for k, v in judge_results.items())
        logger.info(
            f"JudgePanel: overall={overall_score}/10, action={action}, "
            f"judges={judges_str}, "
            f"fixes={len(all_fixes)}, elapsed={elapsed:.1f}s"
        )

        return result

    async def _run_single_judge(
        self,
        judge_name: str,
        judge_prompt: str,
        desktop_b64: str,
        mobile_b64: Optional[str] = None,
        html_content: Optional[str] = None,
        user_brief: Optional[str] = None,
    ) -> Optional[dict]:
        """Run a single specialized judge."""
        import aiohttp

        # Build message content
        content_parts = []

        # Add user brief context if available
        if user_brief:
            content_parts.append({
                "type": "text",
                "text": f"CLIENT BRIEF: {user_brief[:500]}",
            })

        content_parts.append({
            "type": "text",
            "text": f"Evaluate this web page. Focus ONLY on {judge_name} quality.",
        })

        # Desktop screenshot
        content_parts.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{desktop_b64}",
                "detail": "high",
            },
        })

        # Mobile screenshot (for mobile judge)
        if mobile_b64 and judge_name == "mobile":
            content_parts.append({
                "type": "text",
                "text": "MOBILE VERSION (390px viewport):",
            })
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{mobile_b64}",
                    "detail": "high",
                },
            })

        # HTML snippet (for conversion judge)
        if html_content:
            content_parts.append({
                "type": "text",
                "text": f"HTML STRUCTURE (first 3000 chars):\n```html\n{html_content}\n```",
            })

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": judge_prompt},
                            {"role": "user", "content": content_parts},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 1500,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=aiohttp.ClientTimeout(total=45),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.warning(f"Judge {judge_name} API error ({resp.status}): {error_text[:200]}")
                        return None

                    data = await resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                    # Parse JSON response
                    result = json.loads(content)

                    # Validate required fields
                    if "score" not in result:
                        result["score"] = 5.0
                    result["score"] = max(1.0, min(10.0, float(result["score"])))

                    if "critical_issues" not in result:
                        result["critical_issues"] = []
                    if "fix_instructions" not in result:
                        result["fix_instructions"] = []
                    if "verdict" not in result:
                        if result["score"] >= 7.5:
                            result["verdict"] = "PASS"
                        elif result["score"] >= 4.0:
                            result["verdict"] = "NEEDS_FIX"
                        else:
                            result["verdict"] = "REBUILD"

                    return result

        except json.JSONDecodeError as e:
            logger.warning(f"Judge {judge_name} JSON parse failed: {e}")
            return None
        except Exception as e:
            logger.warning(f"Judge {judge_name} failed: {e}")
            return None

    def format_feedback_for_agent(self, panel_result: dict) -> str:
        """
        Convert panel results into a clear, actionable feedback message
        that can be injected into the agent's conversation.
        """
        action = panel_result.get("action", "REFACTOR")
        score = panel_result.get("overall_score", 0)
        judges = panel_result.get("judges", {})

        lines = []
        lines.append(f"{'='*60}")
        lines.append(f"DESIGN JUDGE PANEL EVALUATION — Score: {score}/10 — Action: {action}")
        lines.append(f"{'='*60}")
        lines.append("")

        # Per-judge scores
        lines.append("JUDGE SCORES:")
        for judge_name, jr in judges.items():
            emoji = "✓" if jr.get("score", 0) >= 7.5 else "✗" if jr.get("score", 0) < 5 else "△"
            lines.append(f"  {emoji} {judge_name.upper()}: {jr.get('score', '?')}/10 — {jr.get('summary', '')}")
        lines.append("")

        # Critical issues
        issues = panel_result.get("critical_issues_summary", "")
        if issues and issues != "No critical issues found.":
            lines.append("CRITICAL ISSUES:")
            for issue_line in issues.split("\n")[:10]:
                lines.append(f"  • {issue_line}")
            lines.append("")

        # Top priority fixes
        top_fixes = panel_result.get("top_priority_fixes", [])
        if top_fixes:
            lines.append("TOP PRIORITY FIXES (apply these first):")
            for i, fix in enumerate(top_fixes[:5], 1):
                selector = fix.get("selector", "?")
                prop = fix.get("property", "")
                value = fix.get("value", "")
                reason = fix.get("reason", "")
                if prop and value:
                    lines.append(f"  {i}. {selector} {{ {prop}: {value}; }}  /* {reason} */")
                elif fix.get("add_element"):
                    lines.append(f"  {i}. ADD to {selector}: {fix['add_element']}  /* {reason} */")
            lines.append("")

        # Action instruction
        if action == "REBUILD":
            lines.append("ACTION: REBUILD — The current design has fundamental problems.")
            lines.append("Delete the current HTML and start fresh with a completely different approach.")
            lines.append("Focus on: proper typography hierarchy, cohesive color palette, generous spacing.")
        elif action == "REFACTOR":
            lines.append("ACTION: REFACTOR — Significant improvements needed.")
            lines.append("Apply ALL fix instructions above. Do NOT just tweak — make substantial changes.")
            lines.append("After fixes, the score must improve by at least 1.5 points.")
        else:
            lines.append("ACTION: PATCH — Minor polish needed.")
            lines.append("Apply the fix instructions above for final refinement.")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
#  SCREENSHOT HELPER
# ─────────────────────────────────────────────────────────────────

async def take_screenshots(html_path: str) -> dict[str, Optional[str]]:
    """
    Take desktop and mobile screenshots of an HTML file using Playwright.
    Returns {"desktop": base64_str, "mobile": base64_str}
    """
    try:
        from playwright.async_api import async_playwright

        screenshots = {"desktop": None, "mobile": None}

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
            )

            # Desktop screenshot (1440x900)
            try:
                page = await browser.new_page(viewport={"width": 1440, "height": 900})
                await page.goto(f"file://{html_path}", wait_until="networkidle", timeout=15000)
                await page.wait_for_timeout(2000)  # Wait for animations
                desktop_bytes = await page.screenshot(full_page=True, type="png")
                screenshots["desktop"] = base64.b64encode(desktop_bytes).decode("utf-8")
                await page.close()
            except Exception as e:
                logger.warning(f"Desktop screenshot failed: {e}")

            # Mobile screenshot (390x844)
            try:
                page = await browser.new_page(viewport={"width": 390, "height": 844})
                await page.goto(f"file://{html_path}", wait_until="networkidle", timeout=15000)
                await page.wait_for_timeout(2000)
                mobile_bytes = await page.screenshot(full_page=True, type="png")
                screenshots["mobile"] = base64.b64encode(mobile_bytes).decode("utf-8")
                await page.close()
            except Exception as e:
                logger.warning(f"Mobile screenshot failed: {e}")

            await browser.close()

        return screenshots

    except ImportError:
        logger.warning("Playwright not available, trying Puppeteer fallback")
        return await _puppeteer_screenshots(html_path)
    except Exception as e:
        logger.warning(f"Screenshot capture failed: {e}")
        return {"desktop": None, "mobile": None}


async def _puppeteer_screenshots(html_path: str) -> dict[str, Optional[str]]:
    """Fallback: use Puppeteer (Node.js) for screenshots."""
    import subprocess
    import tempfile

    screenshots = {"desktop": None, "mobile": None}

    for viewport_name, width, height in [("desktop", 1440, 900), ("mobile", 390, 844)]:
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                output_path = tmp.name

            js_code = f"""
const puppeteer = require('puppeteer');
(async () => {{
    const browser = await puppeteer.launch({{headless: 'new', args: ['--no-sandbox']}});
    const page = await browser.newPage();
    await page.setViewport({{width: {width}, height: {height}}});
    await page.goto('file://{html_path}', {{waitUntil: 'networkidle0', timeout: 15000}});
    await page.waitForTimeout(2000);
    await page.screenshot({{path: '{output_path}', fullPage: true}});
    await browser.close();
}})();
"""
            result = subprocess.run(
                ["node", "-e", js_code],
                capture_output=True,
                timeout=30,
            )

            if result.returncode == 0:
                import os
                if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    with open(output_path, "rb") as f:
                        screenshots[viewport_name] = base64.b64encode(f.read()).decode("utf-8")
                os.unlink(output_path)

        except Exception as e:
            logger.warning(f"Puppeteer {viewport_name} screenshot failed: {e}")

    return screenshots


# ─────────────────────────────────────────────────────────────────
#  SINGLETON
# ─────────────────────────────────────────────────────────────────

_instance: Optional[JudgePanel] = None


def get_judge_panel(config=None) -> JudgePanel:
    """Get or create the singleton JudgePanel."""
    global _instance
    if _instance is None:
        if config:
            _instance = JudgePanel(
                openrouter_api_key=getattr(getattr(config, "openrouter", None), "api_key", ""),
            )
        else:
            _instance = JudgePanel()
    return _instance
