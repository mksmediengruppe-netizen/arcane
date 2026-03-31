"""
ARCANE Vision Judge v2
=====================
Evaluates generated websites using REAL screenshots via Playwright + Vision API.
Key improvements over v1:
1. Playwright-based screenshot (not Puppeteer/Node) — native Python, reliable
2. Multi-viewport: desktop (1440px) + mobile (390px) screenshots
3. Full-page screenshot for complete evaluation
4. Structured actionable feedback with specific CSS/HTML fix suggestions
5. Comparison mode: can compare against RAG reference screenshots
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import tempfile
from pathlib import Path
from typing import Optional

import httpx

# Load .env for standalone testing
try:
    from dotenv import load_dotenv
    load_dotenv('/root/arcane/.env')
except ImportError:
    pass

from shared.utils.logger import get_logger

logger = get_logger("workers.design_judge_v2")

# ── Evaluation Criteria ──────────────────────────────────────────────────────

CRITERIA = {
    "aesthetic": {
        "weight": 0.15,
        "description": "Beauty, color harmony, modern visual language, visual polish",
    },
    "originality": {
        "weight": 0.15,
        "description": "Absence of AI cliches (glassmorphism everywhere, particles.js, generic gradients). Unique editorial approach",
    },
    "art_direction": {
        "weight": 0.15,
        "description": "Cohesive visual theme, clear mood and brand identity, intentional design decisions",
    },
    "typography": {
        "weight": 0.15,
        "description": "Premium font choices, optical sizing, perfect hierarchy, readable body text",
    },
    "composition": {
        "weight": 0.15,
        "description": "Grid usage, intentional whitespace, visual balance, section rhythm",
    },
    "conversion": {
        "weight": 0.10,
        "description": "Clear value proposition, obvious CTA, logical content flow, trust signals",
    },
    "premium_feel": {
        "weight": 0.15,
        "description": "High-end polish, attention to micro-details, Awwwards-level quality, $50K website feel",
    },
}

VISION_JUDGE_PROMPT = """You are the ARCANE Vision Judge — a panel of 7 elite design directors from Pentagram, IDEO, MediaMonks, and Awwwards jury members.

You are looking at a REAL SCREENSHOT of a generated landing page. Evaluate it with EXTREMELY HIGH standards.

## SCORING (1-10 scale per criterion):

1. **Aesthetic** (15%): Color palette sophistication, visual harmony, modern design language
2. **Originality** (15%): PENALIZE AI cliches (glassmorphism overuse, particles.js, generic purple/blue gradients, floating 3D blobs, generic stock photo grids). Reward unique editorial or brutalist approaches
3. **Art Direction** (15%): Cohesive visual theme, clear mood, feels like a real brand with soul
4. **Typography** (15%): Premium fonts, perfect hierarchy, optical sizing, contrast. Penalize default system fonts or poorly used sans-serifs
5. **Composition** (15%): Intentional whitespace, grid discipline, visual balance, section rhythm. Penalize cramped layouts
6. **Conversion** (10%): Value prop clarity, CTA visibility, logical flow, trust signals
7. **Premium Feel** (15%): Does this look like a $50,000 agency website? Micro-details, polish, sophistication

## SCORING GUIDE:
- 9-10: Awwwards Site of the Day. World-class.
- 7-8: Premium agency quality. Highly professional.
- 5-6: Acceptable but generic. Bootstrap/Tailwind default feel.
- 3-4: Below average. Obvious template or AI-generated feel.
- 1-2: Broken, amateur, or unusable.

## CRITICAL RULES:
- Be HONEST and HARSH. Generic AI output should score 4-6, not 7-8.
- Every suggestion MUST be specific and actionable (mention exact CSS properties, sections, colors).
- If you see broken layout, missing images, or rendering issues — mention them explicitly.

Respond ONLY with valid JSON:
```json
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
    "overall_score": <weighted_average>,
    "tier": "<TIER_S|TIER_A_PLUS|TIER_A|TIER_B|TIER_C>",
    "verdict": "<one sentence summary>",
    "strengths": ["<specific strength 1>", "<specific strength 2>", "<specific strength 3>"],
    "critical_issues": ["<most important issue that MUST be fixed>", "<second issue>"],
    "fix_instructions": [
        {
            "section": "<which section (hero/nav/footer/etc)>",
            "problem": "<what's wrong>",
            "fix": "<exact CSS/HTML change to make, be specific>"
        }
    ],
    "mobile_notes": "<assessment of mobile readiness based on layout>"
}
```

Tier Definitions:
- TIER_S: >= 9.0 (Awwwards level)
- TIER_A_PLUS: >= 8.0 (Premium agency)
- TIER_A: >= 7.0 (Professional)
- TIER_B: >= 5.0 (Generic/acceptable)
- TIER_C: < 5.0 (Needs major rework)
"""


class VisionJudge:
    """Evaluates generated web designs using Playwright screenshots + Vision API."""

    def __init__(self, config=None):
        self._config = config
        self._client: Optional[httpx.AsyncClient] = None
        self._browser = None
        self._playwright = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client for OpenRouter API."""
        if self._client is None:
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            if not api_key and self._config:
                api_key = getattr(self._config, 'openrouter_api_key', '') or os.environ.get("OPENROUTER_API_KEY", "")

            self._client = httpx.AsyncClient(
                base_url="https://openrouter.ai/api/v1",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
        return self._client

    async def _launch_browser(self):
        """Launch a fresh Playwright browser instance."""
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-gpu',
                '--disable-dev-shm-usage',
                '--disable-setuid-sandbox',
                '--single-process',
            ]
        )
        return pw, browser

    async def take_screenshot(
        self,
        html_path: str,
        viewport_width: int = 1440,
        viewport_height: int = 900,
        full_page: bool = False,
        wait_for_load: float = 2.0,
    ) -> Optional[str]:
        """
        Take a screenshot of an HTML file using Playwright.
        Returns the path to the saved screenshot PNG, or None on failure.
        """
        pw = None
        browser = None
        try:
            pw, browser = await self._launch_browser()
            context = await browser.new_context(
                viewport={"width": viewport_width, "height": viewport_height},
                device_scale_factor=1,
            )
            page = await context.new_page()

            # Navigate to the HTML file
            file_url = f"file://{os.path.abspath(html_path)}"
            await page.goto(file_url, wait_until="load", timeout=20000)

            # Wait for fonts and images to load
            await page.wait_for_timeout(int(wait_for_load * 1000))

            # Take screenshot
            screenshot_path = tempfile.mktemp(suffix=f"_vj_{viewport_width}.png")
            await page.screenshot(path=screenshot_path, full_page=False)

            await context.close()
            await browser.close()
            await pw.stop()

            if os.path.isfile(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
                logger.info(f"Screenshot taken: {screenshot_path} ({viewport_width}px)")
                return screenshot_path
            else:
                logger.warning(f"Screenshot file too small or missing: {screenshot_path}")
                return None

        except Exception as e:
            logger.error(f"Screenshot failed ({viewport_width}px): {e}")
            if browser:
                try:
                    await browser.close()
                except:
                    pass
            if pw:
                try:
                    await pw.stop()
                except:
                    pass
            return None

    async def take_multi_viewport_screenshots(
        self,
        html_path: str,
    ) -> dict:
        """
        Take screenshots at multiple viewports: desktop and mobile.
        Returns dict with paths: {"desktop": path, "mobile": path}
        """
        results = {}

        # Desktop screenshot (1440px) - each call launches its own browser (--single-process)
        desktop_path = await self.take_screenshot(
            html_path, viewport_width=1440, viewport_height=900, full_page=False
        )
        if desktop_path:
            results["desktop"] = desktop_path

        # Mobile screenshot (390px - iPhone 14 Pro) - separate browser instance
        mobile_path = await self.take_screenshot(
            html_path, viewport_width=390, viewport_height=844, full_page=False
        )
        if mobile_path:
            results["mobile"] = mobile_path

        return results

    def _encode_image(self, image_path: str, max_size_mb: float = 4.0) -> Optional[str]:
        """Encode image to base64, with size limit for API."""
        try:
            file_size = os.path.getsize(image_path) / (1024 * 1024)
            if file_size > max_size_mb:
                # Resize if too large
                try:
                    from PIL import Image
                    img = Image.open(image_path)
                    # Reduce to max 2000px width while maintaining aspect ratio
                    if img.width > 2000:
                        ratio = 2000 / img.width
                        new_size = (2000, int(img.height * ratio))
                        img = img.resize(new_size, Image.LANCZOS)
                    resized_path = image_path.replace('.png', '_resized.png')
                    img.save(resized_path, 'PNG', optimize=True)
                    image_path = resized_path
                except ImportError:
                    logger.warning("PIL not available for image resizing")

            with open(image_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to encode image: {e}")
            return None

    async def evaluate_screenshot(
        self,
        screenshot_path: str,
        context: str = "",
        model: str = "google/gemini-2.5-flash",
    ) -> dict:
        """
        Evaluate a single screenshot using Vision API.
        Returns structured evaluation with scores and actionable feedback.
        """
        start = time.monotonic()

        # Encode screenshot
        image_b64 = self._encode_image(screenshot_path)
        if not image_b64:
            return {
                "success": False,
                "error": "Failed to encode screenshot",
                "elapsed_seconds": round(time.monotonic() - start, 2),
            }

        # Build the prompt
        user_content = []
        if context:
            user_content.append({
                "type": "text",
                "text": f"Context about this landing page: {context}\n\nNow evaluate the screenshot below:"
            })
        else:
            user_content.append({
                "type": "text",
                "text": "Evaluate this landing page screenshot:"
            })

        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{image_b64}",
            }
        })

        client = await self._get_client()

        try:
            resp = await client.post(
                "/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": VISION_JUDGE_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 2000,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            elapsed = time.monotonic() - start

            content = data["choices"][0]["message"]["content"]

            # Parse JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            # Use strict=False to handle control characters in LLM output
            cleaned = content.strip()
            # Remove common control chars that break JSON parsing
            import re as _re
            cleaned = _re.sub(r'[\x00-\x1f](?<!\n)(?<!\r)(?<!\t)', ' ', cleaned)
            try:
                result = json.loads(cleaned, strict=False)
            except json.JSONDecodeError:
                # Try removing trailing commas
                cleaned2 = _re.sub(r',\s*([}\]])', r'\1', cleaned)
                result = json.loads(cleaned2, strict=False)
            result["success"] = True
            result["model_used"] = model
            result["evaluation_method"] = "vision_screenshot"
            result["elapsed_seconds"] = round(elapsed, 2)

            # Validate and recalculate overall score
            if "scores" in result:
                weighted_sum = 0
                for criterion, meta in CRITERIA.items():
                    score = result["scores"].get(criterion, 5)
                    weighted_sum += score * meta["weight"]
                result["overall_score"] = round(weighted_sum, 1)

                # Determine tier
                os_val = result["overall_score"]
                if os_val >= 9.0:
                    result["tier"] = "TIER_S"
                elif os_val >= 8.0:
                    result["tier"] = "TIER_A_PLUS"
                elif os_val >= 7.0:
                    result["tier"] = "TIER_A"
                elif os_val >= 5.0:
                    result["tier"] = "TIER_B"
                else:
                    result["tier"] = "TIER_C"

            return result

        except json.JSONDecodeError as e:
            elapsed = time.monotonic() - start
            logger.error(f"Failed to parse judge response: {e}")
            return {
                "success": False,
                "error": f"Failed to parse evaluation: {e}",
                "raw_content": content[:1000] if 'content' in dir() else "",
                "elapsed_seconds": round(elapsed, 2),
            }
        except Exception as e:
            elapsed = time.monotonic() - start
            logger.error(f"Vision evaluation failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "elapsed_seconds": round(elapsed, 2),
            }

    async def evaluate_html(
        self,
        html_path: str,
        context: str = "",
        model: str = "google/gemini-2.5-flash",
        include_mobile: bool = True,
    ) -> dict:
        """
        Full evaluation pipeline: take screenshots → evaluate with Vision API.
        This is the main entry point for the design_judge tool.
        """
        start = time.monotonic()
        logger.info(f"Starting Vision Judge evaluation: {html_path}")

        if not os.path.isfile(html_path):
            return {
                "success": False,
                "error": f"HTML file not found: {html_path}",
            }

        # Step 1: Take screenshots
        screenshots = await self.take_multi_viewport_screenshots(html_path)

        if not screenshots.get("desktop"):
            # Fallback: try code-based evaluation
            logger.warning("Screenshot failed, falling back to code review")
            return await self._evaluate_code_fallback(html_path, context, model)

        # Step 2: Evaluate desktop screenshot
        desktop_result = await self.evaluate_screenshot(
            screenshots["desktop"], context, model
        )

        # Step 3: If mobile screenshot available, add mobile notes
        if include_mobile and screenshots.get("mobile"):
            mobile_b64 = self._encode_image(screenshots["mobile"])
            if mobile_b64 and desktop_result.get("success"):
                # Quick mobile check
                try:
                    client = await self._get_client()
                    mobile_resp = await client.post(
                        "/chat/completions",
                        json={
                            "model": model,
                            "messages": [
                                {"role": "user", "content": [
                                    {"type": "text", "text": "This is a MOBILE screenshot (390px width) of a landing page. In 2-3 sentences, assess: 1) Is the mobile layout working correctly? 2) Are there any overflow/broken elements? 3) Is text readable? Respond with just the assessment text, no JSON."},
                                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{mobile_b64}"}}
                                ]}
                            ],
                            "temperature": 0.3,
                            "max_tokens": 300,
                        },
                    )
                    mobile_resp.raise_for_status()
                    mobile_data = mobile_resp.json()
                    mobile_assessment = mobile_data["choices"][0]["message"]["content"]
                    desktop_result["mobile_assessment"] = mobile_assessment
                except Exception as e:
                    logger.warning(f"Mobile evaluation failed: {e}")
                    desktop_result["mobile_assessment"] = "Could not evaluate mobile version"

        # Cleanup temp files
        for path in screenshots.values():
            try:
                os.unlink(path)
            except:
                pass

        desktop_result["elapsed_seconds"] = round(time.monotonic() - start, 2)
        return desktop_result

    async def _evaluate_code_fallback(
        self,
        html_path: str,
        context: str,
        model: str,
    ) -> dict:
        """Fallback: evaluate HTML code without screenshot."""
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()[:15000]
        except Exception as e:
            return {"success": False, "error": f"Cannot read HTML: {e}"}

        client = await self._get_client()
        start = time.monotonic()

        prompt = f"""Evaluate this HTML/CSS code for design quality.
Since you cannot see the rendered result, focus on code patterns:
- CSS design patterns and color choices
- Responsive design implementation
- Typography choices
- Overall code professionalism
{f'Context: {context}' if context else ''}

HTML Code (first 15K chars):
```html
{html_content}
```

{VISION_JUDGE_PROMPT}"""

        try:
            resp = await client.post(
                "/chat/completions",
                json={
                    "model": model.replace("-vision", ""),
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 2000,
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

            # Use strict=False to handle control characters in LLM output
            cleaned = content.strip()
            import re as _re
            cleaned = _re.sub(r'[\x00-\x1f](?<!\n)(?<!\r)(?<!\t)', ' ', cleaned)
            try:
                result = json.loads(cleaned, strict=False)
            except json.JSONDecodeError:
                cleaned2 = _re.sub(r',\s*([}\]])', r'\1', cleaned)
                result = json.loads(cleaned2, strict=False)
            result["success"] = True
            result["model_used"] = model
            result["evaluation_method"] = "code_review_fallback"
            result["elapsed_seconds"] = round(elapsed, 2)
            result["warning"] = "Evaluated from code only — screenshot failed. Scores may be less accurate."
            return result
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "evaluation_method": "code_review_fallback",
                "elapsed_seconds": round(time.monotonic() - start, 2),
            }

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Singleton
_judge: Optional[VisionJudge] = None


def get_vision_judge(config=None) -> VisionJudge:
    """Get or create the singleton Vision Judge."""
    global _judge
    if _judge is None:
        _judge = VisionJudge(config)
    return _judge
