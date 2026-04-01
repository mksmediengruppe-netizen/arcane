"""
ARCANE Image Generation Worker — v2 (Manus-level quality)

Generates images using multiple providers with intelligent fallback:

Premium tier (highest quality, for hero/banner/key visuals):
  1. GPT-5 Image via OpenRouter — state-of-the-art, best prompt adherence
  2. Nano Banana 2 (Gemini 3.1 Flash) via OpenRouter — fast, good quality
  3. Nano Banana Pro (Gemini 3 Pro) via OpenRouter — reliable fallback

Standard tier (good quality, cost-effective):
  1. GPT-5 Image Mini via OpenRouter — great quality/cost ratio
  2. Nano Banana (Gemini 2.5 Flash) via OpenRouter — cheapest
  3. GPT Image 1.5 via OpenAI API — highest quality fallback (direct API)

Supports:
- Text-to-image generation with detailed style presets
- Multiple sizes (1024x1024, 1024x1792, 1792x1024)
- Premium mode toggle for higher quality models
- Automatic retry and fallback between providers
- Result storage in local filesystem
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import time
import uuid
from typing import Optional

import httpx

from shared.utils.logger import get_logger

logger = get_logger("workers.image_gen")

# Style presets that modify the prompt for better results
STYLE_PRESETS = {
    "photorealistic": "Ultra-realistic photograph, 8K resolution, professional lighting, sharp focus, shallow depth of field",
    "illustration": "Digital illustration, clean lines, vibrant colors, professional artwork, detailed",
    "3d": "3D rendered image, high quality, realistic materials, professional lighting, ray-traced",
    "pixel-art": "Pixel art style, retro game aesthetic, clean pixels",
    "watercolor": "Watercolor painting style, soft edges, artistic brushstrokes, delicate",
    "minimal": "Minimalist design, clean, simple, modern aesthetic, white space",
    "cinematic": "Cinematic shot, dramatic lighting, film grain, wide angle, anamorphic lens flare",
    "anime": "Anime art style, high quality, detailed, vibrant, studio quality",
    "sketch": "Pencil sketch, detailed line work, artistic, fine hatching",
    "logo": "Professional logo design, clean vector style, modern, scalable",
    "editorial": "Editorial photography, magazine quality, artistic composition, high fashion",
    "hero": "Hero section image, dramatic, high-impact, professional, wide format, 4K",
    "product": "Product photography, clean background, professional studio lighting, sharp detail",
}

# ── Premium model definitions ────────────────────────────────────────────────
# Models ordered by quality: GPT-5 Image > Nano Banana 2 > Nano Banana Pro
# All use OpenRouter chat completions API with image output.

PREMIUM_MODELS = [
    {
        "id": "openai/gpt-5-image",
        "name": "GPT-5 Image",
        "cost_per_image": 0.020,
        "api_type": "chat",
    },
    {
        "id": "google/gemini-3.1-flash-image-preview",
        "name": "Nano Banana 2",
        "cost_per_image": 0.005,
        "api_type": "chat",
    },
    {
        "id": "google/gemini-3-pro-image-preview",
        "name": "Nano Banana Pro",
        "cost_per_image": 0.020,
        "api_type": "chat",
    },
]

# Standard models: cost-effective, good quality
STANDARD_MODELS = [
    {
        "id": "openai/gpt-5-image-mini",
        "name": "GPT-5 Image Mini",
        "cost_per_image": 0.008,
        "api_type": "chat",
    },
    {
        "id": "google/gemini-2.5-flash-image",
        "name": "Nano Banana",
        "cost_per_image": 0.003,
        "api_type": "chat",
    },
]


class ImageGenerator:
    """Multi-provider image generation with automatic fallback."""

    def __init__(self, config=None):
        self._config = config
        self._openai_client: Optional[httpx.AsyncClient] = None
        self._output_dir = "/root/workspace/generated_images"
        os.makedirs(self._output_dir, exist_ok=True)

    async def _get_openai_client(self) -> httpx.AsyncClient:
        """Get or create OpenAI HTTP client."""
        if self._openai_client is None:
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
            self._openai_client = httpx.AsyncClient(
                base_url=base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(120.0),
            )
        return self._openai_client

    async def generate(
        self,
        prompt: str,
        style: str = "photorealistic",
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
        project_id: str = "",
        save_dir: Optional[str] = None,
        premium: bool = False,
    ) -> dict:
        """
        Generate an image from a text prompt.

        Args:
            prompt: Text description of the image
            style: Style preset name or custom style instruction
            size: Image size (1024x1024, 1024x1792, 1792x1024)
            quality: "standard" or "hd"
            n: Number of images to generate (1-4)
            project_id: Project ID for organizing outputs
            save_dir: Optional directory to save images
            premium: If True, use premium models (GPT-5 Image / Nano Banana 2)

        Returns:
            dict with: success, images (list of paths), provider, cost, elapsed_seconds
        """
        # Build enhanced prompt with style
        enhanced_prompt = self._enhance_prompt(prompt, style)
        openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")

        # ── Premium path: GPT-5 Image → Nano Banana 2 → Nano Banana Pro ──
        if premium and openrouter_key:
            for model_def in PREMIUM_MODELS:
                try:
                    result = await self._generate_via_openrouter(
                        enhanced_prompt, size, n, project_id, save_dir, model_def
                    )
                    if result["success"]:
                        logger.info(
                            f"Premium image generated via {model_def['name']} "
                            f"({model_def['id']}), cost=${result['cost']:.3f}"
                        )
                        return result
                except Exception as e:
                    logger.warning(
                        f"Premium {model_def['name']} generation failed: {e}"
                    )
                    continue

            # If all premium models failed, fall through to standard path
            logger.warning("All premium models failed, falling back to standard")

        # ── Standard path: GPT-5 Image Mini → Nano Banana → GPT Image 1.5 ─
        if openrouter_key:
            for model_def in STANDARD_MODELS:
                try:
                    result = await self._generate_via_openrouter(
                        enhanced_prompt, size, n, project_id, save_dir, model_def
                    )
                    if result["success"]:
                        logger.info(
                            f"Standard image generated via {model_def['name']} "
                            f"({model_def['id']}), cost=${result['cost']:.3f}"
                        )
                        return result
                except Exception as e:
                    logger.warning(f"Standard {model_def['name']} generation failed: {e}")
                    continue

        # ── Last resort: GPT Image 1.5 via direct OpenAI API ─────────────
        try:
            result = await self._generate_gpt_image(
                enhanced_prompt, size, quality, n, project_id, save_dir
            )
            if result["success"]:
                return result
        except Exception as e:
            logger.warning(f"GPT Image 1.5 generation failed: {e}")

        return {
            "success": False,
            "images": [],
            "provider": "none",
            "error": "All image generation providers failed",
            "cost": 0.0,
            "elapsed_seconds": 0,
        }

    def _enhance_prompt(self, prompt: str, style: str) -> str:
        """Enhance the prompt with style instructions."""
        style_instruction = STYLE_PRESETS.get(style, style)
        if style_instruction and style_instruction != prompt:
            return f"{prompt}. Style: {style_instruction}"
        return prompt

    # ── OpenRouter: GPT-5 Image / Nano Banana (chat completions API) ─────

    async def _generate_via_openrouter(
        self,
        prompt: str,
        size: str,
        n: int,
        project_id: str,
        save_dir: Optional[str],
        model_def: dict,
    ) -> dict:
        """Generate image via OpenRouter chat completions API.

        Works with GPT-5 Image, Nano Banana 2/Pro, and other chat-based
        image models that return images inline in the response content.
        """
        openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not openrouter_key:
            return {
                "success": False,
                "images": [],
                "provider": model_def["id"],
                "error": "OPENROUTER_API_KEY not configured",
                "cost": 0.0,
                "elapsed_seconds": 0,
            }

        start = time.monotonic()
        images = []
        total_cost = 0.0

        # Parse size for aspect ratio hint in prompt
        try:
            w, h = map(int, size.split("x"))
        except ValueError:
            w, h = 1024, 1024

        aspect_hint = ""
        if w > h:
            aspect_hint = " (landscape orientation, wide format)"
        elif h > w:
            aspect_hint = " (portrait orientation, tall format)"

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            for i in range(n):
                try:
                    # All models use chat completions API
                    resp = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {openrouter_key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://arcaneai.ru",
                            "X-Title": "ARCANE AI Workspace",
                        },
                        json={
                            "model": model_def["id"],
                            "messages": [
                                {
                                    "role": "user",
                                    "content": (
                                        f"Generate an image: {prompt}{aspect_hint}\n\n"
                                        "Output ONLY the image, no text explanation."
                                    ),
                                }
                            ],
                            "max_tokens": 4096,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    # Extract image from response
                    extracted = self._extract_image_from_chat_response(data)
                    if extracted:
                        filename = f"premium_{uuid.uuid4().hex[:8]}.png"
                        output_dir = save_dir or os.path.join(
                            self._output_dir, project_id or "default"
                        )
                        os.makedirs(output_dir, exist_ok=True)
                        filepath = os.path.join(output_dir, filename)

                        with open(filepath, "wb") as f:
                            f.write(extracted)

                        images.append({
                            "path": filepath,
                            "revised_prompt": prompt,
                            "size": size,
                        })
                        total_cost += model_def["cost_per_image"]
                    else:
                        logger.warning(
                            f"{model_def['name']} image {i+1}/{n}: "
                            "no image found in response"
                        )

                except httpx.HTTPStatusError as e:
                    logger.warning(
                        f"{model_def['name']} image {i+1}/{n} HTTP error: "
                        f"{e.response.status_code} — {e.response.text[:200]}"
                    )
                    continue
                except Exception as e:
                    logger.warning(
                        f"{model_def['name']} image {i+1}/{n} failed: {e}"
                    )
                    continue

        elapsed = time.monotonic() - start

        return {
            "success": len(images) > 0,
            "images": images,
            "provider": model_def["id"],
            "cost": total_cost,
            "elapsed_seconds": round(elapsed, 2),
        }

    def _extract_image_from_chat_response(self, data: dict) -> Optional[bytes]:
        """Extract base64 image data from a chat completion response.

        Supports multiple response formats:
        1. message.images[].image_url.url as data:image/png;base64,... (OpenRouter primary)
        2. content list parts with inline_data or image_url type (Gemini/GPT)
        3. content string with embedded base64 (fallback)
        """
        choices = data.get("choices", [])
        if not choices:
            return None

        message = choices[0].get("message", {})

        # Case 0 (PRIMARY): message.images[] — OpenRouter format
        images_list = message.get("images", [])
        if images_list:
            for img_entry in images_list:
                if isinstance(img_entry, dict):
                    url = ""
                    if img_entry.get("type") == "image_url":
                        url = img_entry.get("image_url", {}).get("url", "")
                    elif img_entry.get("url"):
                        url = img_entry["url"]
                    if url.startswith("data:image"):
                        b64_part = url.split(",", 1)[-1]
                        return base64.b64decode(b64_part)
                    elif url.startswith("http"):
                        # Download the image from URL
                        try:
                            import httpx as _httpx
                            with _httpx.Client(timeout=30.0) as dl:
                                resp = dl.get(url)
                                resp.raise_for_status()
                                return resp.content
                        except Exception as e:
                            logger.warning(f"Failed to download image from URL: {e}")
                            continue

        content = message.get("content", "")

        # Case 1: content is a list of parts (multimodal response)
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    # Check for inline_data (Gemini native format)
                    inline = part.get("inline_data", {})
                    if inline and inline.get("data"):
                        return base64.b64decode(inline["data"])

                    # Check for image_url type
                    if part.get("type") == "image_url":
                        url_data = part.get("image_url", {})
                        url = url_data.get("url", "")
                        if url.startswith("data:image"):
                            # data:image/png;base64,xxxxx
                            b64_part = url.split(",", 1)[-1]
                            return base64.b64decode(b64_part)

                    # Check for type "image" with base64
                    if part.get("type") == "image":
                        b64 = part.get("data", "") or part.get("base64", "")
                        if b64:
                            return base64.b64decode(b64)

                    # Check for source.data (Anthropic-style)
                    source = part.get("source", {})
                    if source.get("data"):
                        return base64.b64decode(source["data"])

        # Case 2: content is a string — check for embedded base64
        if isinstance(content, str) and len(content) > 500:
            # Look for base64-encoded image data
            import re
            b64_match = re.search(
                r'data:image/[a-z]+;base64,([A-Za-z0-9+/=]+)', content
            )
            if b64_match:
                return base64.b64decode(b64_match.group(1))

            # Try if the entire content is base64
            if content.replace("\n", "").replace(" ", "").replace("=", "").isalnum():
                try:
                    decoded = base64.b64decode(content)
                    # Check PNG magic bytes
                    if decoded[:4] == b'\x89PNG' or decoded[:2] == b'\xff\xd8':
                        return decoded
                except Exception:
                    pass

        return None

    # ── GPT Image 1.5 via direct OpenAI API ──────────────────────────────

    async def _generate_gpt_image(
        self,
        prompt: str,
        size: str,
        quality: str,
        n: int,
        project_id: str,
        save_dir: Optional[str],
    ) -> dict:
        """Generate image using GPT Image 1.5 via direct OpenAI API.

        GPT Image 1.5 is OpenAI's latest and most advanced image generation model.
        It offers superior instruction following, text rendering, and detailed editing.
        Replaces the deprecated DALL-E 3 as the primary OpenAI image model.
        """
        client = await self._get_openai_client()
        start = time.monotonic()

        images = []
        total_cost = 0.0

        # GPT Image 1.5 size mapping (supports: 1024x1024, 1536x1024, 1024x1536, auto)
        gpt_image_size = size
        size_map = {
            "1792x1024": "1536x1024",
            "1024x1792": "1024x1536",
        }
        gpt_image_size = size_map.get(size, size)

        # Quality mapping: "standard" → "medium", "hd" → "high"
        gpt_quality = "high" if quality == "hd" else "medium"

        for i in range(n):
            try:
                body = {
                    "model": "gpt-image-1.5",
                    "prompt": prompt,
                    "n": 1,
                    "size": gpt_image_size,
                    "quality": gpt_quality,
                }

                resp = await client.post("/images/generations", json=body)
                resp.raise_for_status()
                data = resp.json()

                for img_data in data.get("data", []):
                    b64 = img_data.get("b64_json", "")
                    revised_prompt = img_data.get("revised_prompt", prompt)
                    img_url = img_data.get("url", "")

                    if b64:
                        # Save base64 to file
                        filename = f"gpt_img_{uuid.uuid4().hex[:8]}.png"
                        output_dir = save_dir or os.path.join(
                            self._output_dir, project_id or "default"
                        )
                        os.makedirs(output_dir, exist_ok=True)
                        filepath = os.path.join(output_dir, filename)

                        with open(filepath, "wb") as f:
                            f.write(base64.b64decode(b64))

                        images.append({
                            "path": filepath,
                            "revised_prompt": revised_prompt,
                            "size": size,
                        })
                    elif img_url:
                        # Download from URL
                        try:
                            async with httpx.AsyncClient(timeout=30.0) as dl:
                                dl_resp = await dl.get(img_url)
                                dl_resp.raise_for_status()

                                filename = f"gpt_img_{uuid.uuid4().hex[:8]}.png"
                                output_dir = save_dir or os.path.join(
                                    self._output_dir, project_id or "default"
                                )
                                os.makedirs(output_dir, exist_ok=True)
                                filepath = os.path.join(output_dir, filename)

                                with open(filepath, "wb") as f:
                                    f.write(dl_resp.content)

                                images.append({
                                    "path": filepath,
                                    "revised_prompt": revised_prompt,
                                    "size": size,
                                })
                        except Exception as e:
                            logger.warning(f"Failed to download GPT Image URL: {e}")

                # Cost calculation for GPT Image 1.5
                # Pricing: low=$0.02, medium=$0.07, high=$0.19 (1024x1024)
                # Larger sizes: low=$0.04, medium=$0.14, high=$0.38
                is_large = gpt_image_size != "1024x1024"
                cost_table = {
                    "low": 0.04 if is_large else 0.02,
                    "medium": 0.14 if is_large else 0.07,
                    "high": 0.38 if is_large else 0.19,
                }
                total_cost += cost_table.get(gpt_quality, 0.07)

            except Exception as e:
                logger.warning(f"GPT Image 1.5 image {i+1}/{n} failed: {e}")
                continue

        elapsed = time.monotonic() - start

        if images:
            logger.info(
                f"GPT Image 1.5 generated {len(images)} images, cost=${total_cost:.3f}"
            )

        return {
            "success": len(images) > 0,
            "images": images,
            "provider": "openai/gpt-image-1.5",
            "cost": total_cost,
            "elapsed_seconds": round(elapsed, 2),
        }

    async def close(self):
        """Close HTTP clients."""
        if self._openai_client:
            await self._openai_client.aclose()
            self._openai_client = None


# Singleton instance
_generator: Optional[ImageGenerator] = None


def get_image_generator(config=None) -> ImageGenerator:
    """Get or create the singleton image generator."""
    global _generator
    if _generator is None:
        _generator = ImageGenerator(config)
    return _generator
