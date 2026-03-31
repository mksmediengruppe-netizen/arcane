"""
ARCANE Design Judge

Evaluates generated websites/landing pages using a Vision model.
Takes a screenshot of the page and sends it to GPT-5 (vision) or GPT-4.1 (vision)
for quality assessment.

Returns a structured score with actionable feedback.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Optional

import httpx

from shared.utils.logger import get_logger

logger = get_logger("workers.design_judge")

# Evaluation criteria and weights
CRITERIA = {
    "aesthetic": {
        "weight": 0.20,
        "description": "Beauty, color harmony, modern visual language",
    },
    "originality": {
        "weight": 0.15,
        "description": "Absence of AI cliches (glassmorphism, particles, generic gradients)",
    },
    "art_direction": {
        "weight": 0.15,
        "description": "Cohesive visual theme, clear mood and style",
    },
    "typography": {
        "weight": 0.15,
        "description": "Premium font choices, optical sizing, perfect hierarchy",
    },
    "composition": {
        "weight": 0.15,
        "description": "Grid usage, intentional whitespace, balance",
    },
    "conversion": {
        "weight": 0.10,
        "description": "Clear value prop, obvious CTA, logical flow",
    },
    "premium_feel": {
        "weight": 0.10,
        "description": "High-end polish, attention to detail, Awwwards-level quality",
    },
}

JUDGE_SYSTEM_PROMPT = """You are the ARCANE Multi-Judge Taste Engine, a panel of 7 elite design directors from top agencies (Pentagram, IDEO, MediaMonks).
You evaluate web pages with EXTREMELY HIGH standards. Your goal is to filter out generic AI-generated slop and only approve world-class, Awwwards-level designs.

You must evaluate the screenshot across 7 distinct dimensions (1-10 scale):

1. **Aesthetic Judge** (20%): Is it beautiful? Does it have a sophisticated color palette?
2. **Originality Judge** (15%): PENALIZE HEAVILY for AI cliches (glassmorphism, particles.js, generic purple/blue gradients, floating 3D blobs). Reward unique, editorial, or brutalist approaches.
3. **Art Direction Judge** (15%): Is there a clear, cohesive visual theme? Does it feel like a brand with a soul?
4. **Typography Judge** (15%): Are the fonts premium? Is the hierarchy perfect? Is there good contrast and optical sizing? (Penalize default system fonts or boring sans-serifs used poorly).
5. **Composition Judge** (15%): Is the whitespace intentional? Is the grid respected? Does it feel cramped or perfectly balanced?
6. **Conversion Judge** (10%): Is the value proposition instantly clear? Is the CTA obvious and frictionless?
7. **Premium Feel Judge** (10%): Does this look like a $50,000 website?

Scoring Guide:
- 9-10: World-class, Awwwards Site of the Day level.
- 7-8: Premium agency quality, highly professional.
- 5-6: Acceptable but generic (Bootstrap/Tailwind default feel).
- 1-4: Amateur, broken, or full of AI cliches.

Respond ONLY with valid JSON in this exact format:
{
    "scores": {
        "aesthetic": <1-10>,
        "originality": <1-10>,
        "art_direction": <1-10>,
        "typography": <1-10>,
        "composition": <1-10>,
        "conversion": <1-10>,
        "premium_feel": <1-10>
    },
    "overall_score": <weighted average 1-10>,
    "tier": "<TIER_S|TIER_A_PLUS|TIER_A|TIER_B|TIER_C>",
    "strengths": ["<strength 1>", "<strength 2>"],
    "issues": ["<issue 1>", "<issue 2>"],
    "suggestions": ["<specific actionable suggestion 1>", "<suggestion 2>"],
    "fix_instructions": [
        {
            "section": "<which section (hero/nav/footer/testimonials/etc)>",
            "problem": "<what exactly is wrong visually>",
            "fix": "<exact CSS/HTML change: e.g. 'Change .hero h1 { font-size: 4.5rem; letter-spacing: -0.04em; line-height: 0.92 }' or 'Replace background: linear-gradient(...) with background: #0A0A0A'>"
        }
    ]
}

CRITICAL RULES FOR FIX INSTRUCTIONS:
- Every fix_instruction MUST contain an exact CSS property, selector, or HTML change
- Do NOT give vague advice like "improve typography" — instead say "Change .hero h1 { font-size: 5rem; letter-spacing: -0.05em }"
- Do NOT give vague advice like "better colors" — instead say "Replace bg-blue-500 with bg-[#1a1a2e] for the hero section"
- Include at least 3 fix_instructions for any page scoring below 8.0
- Focus on the HIGHEST IMPACT changes first: hero section, typography scale, color palette, whitespace

Tier Definitions:
- TIER_S: Overall score >= 9.0
- TIER_A_PLUS: Overall score >= 8.0
- TIER_A: Overall score >= 7.0
- TIER_B: Overall score >= 5.0
- TIER_C: Overall score < 5.0
"""


class DesignJudge:
    """Evaluates generated web designs using Vision models."""

    def __init__(self, config=None):
        self._config = config
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client for OpenAI API."""
        if self._client is None:
            api_key = (
                self._config.openai.api_key
                if self._config
                else os.environ.get("OPENAI_API_KEY", "")
            )
            base_url = (
                self._config.openai.base_url
                if self._config
                else "https://api.openai.com/v1"
            )
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(60.0),
            )
        return self._client

    async def evaluate_screenshot(
        self,
        screenshot_path: str,
        context: str = "",
        model: str = "gpt-4.1-mini",
    ) -> dict:
        """
        Evaluate a website screenshot using a Vision model.

        Args:
            screenshot_path: Path to the screenshot image file
            context: Optional context about what the page should be
            model: Vision model to use

        Returns:
            dict with scores, tier, strengths, issues, suggestions
        """
        if not os.path.isfile(screenshot_path):
            return {
                "success": False,
                "error": f"Screenshot not found: {screenshot_path}",
            }

        # Read and encode the screenshot
        with open(screenshot_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Determine image format
        ext = os.path.splitext(screenshot_path)[1].lower()
        media_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(ext, "image/png")

        # Build the evaluation request
        user_content = []
        if context:
            user_content.append({
                "type": "text",
                "text": f"Context: {context}\n\nPlease evaluate this web page design:",
            })
        else:
            user_content.append({
                "type": "text",
                "text": "Please evaluate this web page design:",
            })

        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{media_type};base64,{image_data}",
                "detail": "high",
            },
        })

        client = await self._get_client()
        start = time.monotonic()

        try:
            resp = await client.post(
                "/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 2500,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            elapsed = time.monotonic() - start
            content = data["choices"][0]["message"]["content"]

            # Parse JSON response
            # Handle potential markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            result = json.loads(content.strip())
            result["success"] = True
            result["model_used"] = model
            result["elapsed_seconds"] = round(elapsed, 2)

            # Calculate cost (approximate for vision)
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            result["tokens"] = {
                "input": input_tokens,
                "output": output_tokens,
            }

            # Validate and recalculate overall score
            scores = result.get("scores", {})
            if scores:
                weighted_sum = sum(
                    scores.get(criterion, 5) * info["weight"]
                    for criterion, info in CRITERIA.items()
                )
                result["overall_score"] = round(weighted_sum, 1)

                # Set tier based on score
                if weighted_sum >= 9.0:
                    result["tier"] = "TIER_S"
                elif weighted_sum >= 8.0:
                    result["tier"] = "TIER_A_PLUS"
                elif weighted_sum >= 7.0:
                    result["tier"] = "TIER_A"
                elif weighted_sum >= 5.0:
                    result["tier"] = "TIER_B"
                else:
                    result["tier"] = "TIER_C"

            logger.info(
                f"Design evaluation complete: {result.get('tier', 'N/A')} "
                f"(score: {result.get('overall_score', 'N/A')})"
            )

            return result

        except json.JSONDecodeError as e:
            elapsed = time.monotonic() - start
            logger.warning(f"Failed to parse judge response as JSON, trying regex fallback: {e}")

            # Regex fallback: extract individual scores from text
            import re
            raw = content if 'content' in dir() else ""
            fallback_scores = {}
            for criterion in CRITERIA:
                # Match patterns like "aesthetic: 8" or "Aesthetic: 8/10"
                pattern = rf'{criterion}[:\s]*([\d.]+)'
                m = re.search(pattern, raw, re.IGNORECASE)
                if not m:
                    # Try human-readable name
                    human_name = criterion.replace('_', '[_ ]')
                    m = re.search(rf'{human_name}[:\s]*([\d.]+)', raw, re.IGNORECASE)
                if m:
                    score_val = float(m.group(1))
                    fallback_scores[criterion] = min(score_val, 10)

            if fallback_scores:
                weighted_sum = sum(
                    fallback_scores.get(c, 5) * info["weight"]
                    for c, info in CRITERIA.items()
                )
                tier = (
                    "TIER_S" if weighted_sum >= 9.0
                    else "TIER_A_PLUS" if weighted_sum >= 8.0
                    else "TIER_A" if weighted_sum >= 7.0
                    else "TIER_B" if weighted_sum >= 5.0
                    else "TIER_C"
                )
                return {
                    "success": True,
                    "scores": fallback_scores,
                    "overall_score": round(weighted_sum, 1),
                    "tier": tier,
                    "strengths": [],
                    "issues": ["Score extracted via regex fallback (LLM did not return valid JSON)"],
                    "suggestions": [],
                    "model_used": model,
                    "evaluation_method": "regex_fallback",
                    "elapsed_seconds": round(elapsed, 2),
                }

            # Last resort: try to find any overall score number
            score_match = re.search(r'(\d+)\s*/\s*100|overall[_\s]*score[:\s]*(\d+)', raw, re.IGNORECASE)
            if score_match:
                score = int(score_match.group(1) or score_match.group(2))
                # Convert 0-100 scale to 0-10
                score_10 = min(score / 10 if score > 10 else score, 10)
                tier = (
                    "TIER_S" if score_10 >= 9.0
                    else "TIER_A_PLUS" if score_10 >= 8.0
                    else "TIER_A" if score_10 >= 7.0
                    else "TIER_B" if score_10 >= 5.0
                    else "TIER_C"
                )
                return {
                    "success": True,
                    "overall_score": round(score_10, 1),
                    "tier": tier,
                    "model_used": model,
                    "evaluation_method": "regex_fallback_overall",
                    "elapsed_seconds": round(elapsed, 2),
                }

            return {
                "success": False,
                "error": f"Failed to parse evaluation response: {e}",
                "raw_content": raw[:1000],
                "elapsed_seconds": round(elapsed, 2),
            }
        except Exception as e:
            elapsed = time.monotonic() - start
            logger.error(f"Design evaluation failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "elapsed_seconds": round(elapsed, 2),
            }

    async def evaluate_html_file(
        self,
        html_path: str,
        context: str = "",
        model: str = "gpt-4.1-mini",
        viewport_width: int = 1440,
        viewport_height: int = 900,
    ) -> dict:
        """
        Evaluate an HTML file by taking a screenshot first.

        Requires a headless browser (Playwright/Puppeteer) to be available.
        Falls back to code-based evaluation if screenshot fails.
        """
        # Try to take a screenshot using playwright
        screenshot_path = f"/tmp/design_judge_{os.getpid()}.png"

        try:
            import asyncio
            proc = await asyncio.create_subprocess_shell(
                f'node -e "'
                f"const puppeteer = require('puppeteer');"
                f"(async () => {{"
                f"  const browser = await puppeteer.launch({{headless: true, args: ['--no-sandbox']}});"
                f"  const page = await browser.newPage();"
                f"  await page.setViewport({{width: {viewport_width}, height: {viewport_height}}});"
                f"  await page.goto('file://{html_path}', {{waitUntil: 'networkidle0'}});"
                f"  await page.screenshot({{path: '{screenshot_path}', fullPage: true}});"
                f"  await browser.close();"
                f"}})();"
                f'"',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)

            if os.path.isfile(screenshot_path):
                return await self.evaluate_screenshot(screenshot_path, context, model)
        except Exception as e:
            logger.warning(f"Screenshot failed, falling back to code review: {e}")

        # Fallback: evaluate the HTML code directly (no vision)
        return await self._evaluate_code(html_path, context, model)

    async def _evaluate_code(
        self,
        html_path: str,
        context: str,
        model: str,
    ) -> dict:
        """Fallback: evaluate HTML code without screenshot."""
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()[:15000]  # Limit to 15K chars
        except Exception as e:
            return {"success": False, "error": f"Cannot read HTML: {e}"}

        client = await self._get_client()
        start = time.monotonic()

        code_prompt = f"""Evaluate this HTML/CSS code for design quality.
Since you cannot see the rendered result, focus on:
- Code quality and structure
- CSS design patterns used
- Responsive design implementation
- Color scheme and typography choices in CSS
- Overall professionalism of the code

{f'Context: {context}' if context else ''}

HTML Code:
```html
{html_content}
```

{JUDGE_SYSTEM_PROMPT}"""

        try:
            resp = await client.post(
                "/chat/completions",
                json={
                    "model": model.replace("-vision", ""),
                    "messages": [
                        {"role": "user", "content": code_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 2500,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            elapsed = time.monotonic() - start
            content = data["choices"][0]["message"]["content"]

            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            result = json.loads(content.strip())
            result["success"] = True
            result["model_used"] = model
            result["evaluation_method"] = "code_review"
            result["elapsed_seconds"] = round(elapsed, 2)
            return result

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "elapsed_seconds": round(time.monotonic() - start, 2),
            }

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Singleton
_judge: Optional[DesignJudge] = None


def get_design_judge(config=None) -> DesignJudge:
    """Get or create the singleton design judge."""
    global _judge
    if _judge is None:
        _judge = DesignJudge(config)
    return _judge
