"""
ARCANE Image Generation Worker

Generates images using multiple providers:
1. FLUX Schnell via OpenRouter (default) — fast, cheap ($0.003)
2. OpenAI DALL-E 3 (fallback) — reliable ($0.04-0.12)
3. Nano Banana 2 via OpenRouter (premium) — #1 Arena T2I ($0.005)
4. Nano Banana Pro via OpenRouter (premium fallback) — #2-3 Arena ($0.02)

Supports:
- Text-to-image generation
- Style presets (photorealistic, illustration, 3d, pixel-art, etc.)
- Multiple sizes (1024x1024, 1024x1792, 1792x1024)
- Premium mode toggle for higher quality models
- Automatic retry and fallback between providers
- Result storage in MinIO/local filesystem
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
    "photorealistic": "Ultra-realistic photograph, 8K resolution, professional lighting, sharp focus",
    "illustration": "Digital illustration, clean lines, vibrant colors, professional artwork",
    "3d": "3D rendered image, high quality, realistic materials, professional lighting",
    "pixel-art": "Pixel art style, retro game aesthetic, clean pixels",
    "watercolor": "Watercolor painting style, soft edges, artistic brushstrokes",
    "minimal": "Minimalist design, clean, simple, modern aesthetic",
    "cinematic": "Cinematic shot, dramatic lighting, film grain, wide angle",
    "anime": "Anime art style, high quality, detailed, vibrant",
    "sketch": "Pencil sketch, detailed line work, artistic",
    "logo": "Professional logo design, clean vector style, modern",
}

# ── Premium model definitions ────────────────────────────────────────────────
# Nano Banana models use the OpenRouter chat completions API with image output,
# NOT the /images/generations endpoint. They accept text prompts and return
# inline images in the response.

PREMIUM_MODELS = [
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

STANDARD_MODELS = [
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
            premium: If True, use premium models (Nano Banana 2 / Pro)

        Returns:
            dict with: success, images (list of paths), provider, cost, elapsed_seconds
        """
        # Build enhanced prompt with style
        enhanced_prompt = self._enhance_prompt(prompt, style)
        openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")

        # ── Premium path: Nano Banana 2 → Nano Banana Pro ────────────────
        if premium and openrouter_key:
            for model_def in PREMIUM_MODELS:
                try:
                    result = await self._generate_nano_banana(
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

        # ── Standard path: Nano Banana → FLUX Schnell → DALL-E 3 ─────────
        if openrouter_key:
            # Try Nano Banana (standard) first — cheapest and reliable
            for model_def in STANDARD_MODELS:
                try:
                    result = await self._generate_nano_banana(
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

            # Legacy fallback: FLUX Schnell
            try:
                result = await self._generate_flux(
                    enhanced_prompt, size, n, project_id, save_dir
                )
                if result["success"]:
                    return result
            except Exception as e:
                logger.warning(f"FLUX image generation failed: {e}")

        # Last resort fallback: DALL-E 3 (requires direct OpenAI key)
        try:
            result = await self._generate_openai(
                enhanced_prompt, size, quality, n, project_id, save_dir
            )
            if result["success"]:
                return result
        except Exception as e:
            logger.warning(f"OpenAI DALL-E generation failed: {e}")

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

    # ── Premium: Nano Banana (Gemini image models via OpenRouter) ─────────

    async def _generate_nano_banana(
        self,
        prompt: str,
        size: str,
        n: int,
        project_id: str,
        save_dir: Optional[str],
        model_def: dict,
    ) -> dict:
        """Generate image using Nano Banana 2 or Pro via OpenRouter chat API.

        These Gemini-based models use the chat completions endpoint and return
        images inline as base64 data in the response content.
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
                    # Nano Banana models use chat completions API
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

        Gemini/Nano Banana models via OpenRouter return images in:
        1. message.images[].image_url.url as data:image/png;base64,... (primary)
        2. content list parts with inline_data or image_url type
        3. content string with embedded base64
        """
        choices = data.get("choices", [])
        if not choices:
            return None

        message = choices[0].get("message", {})

        # Case 0 (PRIMARY): message.images[] — OpenRouter Nano Banana format
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

    # ── Standard: DALL-E 3 ────────────────────────────────────────────────

    async def _generate_openai(
        self,
        prompt: str,
        size: str,
        quality: str,
        n: int,
        project_id: str,
        save_dir: Optional[str],
    ) -> dict:
        """Generate image using OpenAI DALL-E 3."""
        client = await self._get_openai_client()
        start = time.monotonic()

        # DALL-E 3 only supports n=1, so we loop
        images = []
        total_cost = 0.0

        for i in range(n):
            body = {
                "model": "dall-e-3",
                "prompt": prompt,
                "n": 1,
                "size": size,
                "quality": quality,
                "response_format": "b64_json",
            }

            resp = await client.post("/images/generations", json=body)
            resp.raise_for_status()
            data = resp.json()

            for img_data in data.get("data", []):
                b64 = img_data.get("b64_json", "")
                revised_prompt = img_data.get("revised_prompt", prompt)

                if b64:
                    # Save to file
                    filename = f"img_{uuid.uuid4().hex[:8]}.png"
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

            # Cost calculation for DALL-E 3
            if quality == "hd":
                if size == "1024x1024":
                    total_cost += 0.080
                else:
                    total_cost += 0.120
            else:
                if size == "1024x1024":
                    total_cost += 0.040
                else:
                    total_cost += 0.080

        elapsed = time.monotonic() - start

        logger.info(
            f"OpenAI DALL-E generated {len(images)} images, cost=${total_cost:.3f}"
        )

        return {
            "success": len(images) > 0,
            "images": images,
            "provider": "openai/dall-e-3",
            "cost": total_cost,
            "elapsed_seconds": round(elapsed, 2),
        }

    # ── Standard: FLUX Schnell ────────────────────────────────────────────

    async def _generate_flux(
        self,
        prompt: str,
        size: str,
        n: int,
        project_id: str,
        save_dir: Optional[str],
    ) -> dict:
        """Generate image using FLUX Schnell via OpenRouter.

        C1: FLUX Schnell is a fast diffusion model available through OpenRouter's
        image generation endpoint. Cost: ~$0.003 per image.
        """
        openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not openrouter_key:
            return {
                "success": False,
                "images": [],
                "provider": "flux-schnell",
                "error": "OPENROUTER_API_KEY not configured",
                "cost": 0.0,
                "elapsed_seconds": 0,
            }

        start = time.monotonic()

        # Parse size
        try:
            w, h = map(int, size.split("x"))
        except ValueError:
            w, h = 1024, 1024

        images = []
        total_cost = 0.0

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            for i in range(n):
                try:
                    resp = await client.post(
                        "https://openrouter.ai/api/v1/images/generations",
                        headers={
                            "Authorization": f"Bearer {openrouter_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "black-forest-labs/flux-schnell",
                            "prompt": prompt,
                            "n": 1,
                            "size": f"{w}x{h}",
                            "response_format": "b64_json",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    for img_data in data.get("data", []):
                        b64 = img_data.get("b64_json", "")
                        if b64:
                            filename = f"flux_{uuid.uuid4().hex[:8]}.png"
                            output_dir = save_dir or os.path.join(
                                self._output_dir, project_id or "default"
                            )
                            os.makedirs(output_dir, exist_ok=True)
                            filepath = os.path.join(output_dir, filename)

                            with open(filepath, "wb") as f:
                                f.write(base64.b64decode(b64))

                            images.append({
                                "path": filepath,
                                "revised_prompt": prompt,
                                "size": size,
                            })
                            total_cost += 0.003

                except Exception as e:
                    logger.warning(f"FLUX image {i+1}/{n} failed: {e}")
                    continue

        elapsed = time.monotonic() - start

        if images:
            logger.info(
                f"FLUX Schnell generated {len(images)} images, cost=${total_cost:.3f}"
            )

        return {
            "success": len(images) > 0,
            "images": images,
            "provider": "flux-schnell",
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
