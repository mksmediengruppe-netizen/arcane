"""
ARCANE VisualRAG v2 — Screenshot-Enhanced Design Reference System

Extends the existing DesignRAGService with:
1. Screenshot retrieval — fetches actual screenshots of reference sites
2. Vision context builder — creates vision-ready messages with screenshot images
3. Style DNA extraction — uses vision LLM to extract design patterns from screenshots

The key insight: showing the LLM a screenshot of an award-winning site
is 10x more effective than describing it in text.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from typing import Any, Optional
from pathlib import Path

import aiohttp

from shared.utils.logger import get_logger

logger = get_logger("workers.visual_rag_v2")

# Screenshot cache directory
SCREENSHOT_CACHE_DIR = "/root/arcane/cache/screenshots"


class VisualRAGService:
    """
    Enhanced RAG service that provides visual references (screenshots)
    alongside text-based design metadata.
    """

    def __init__(
        self,
        qdrant_host: str = "",
        qdrant_port: int = 6333,
        openrouter_api_key: str = "",
        minio_endpoint: str = "",
        minio_bucket: str = "screenshots",
    ):
        self._qdrant_host = qdrant_host or os.getenv("QDRANT_HOST", "localhost")
        self._qdrant_port = qdrant_port or int(os.getenv("QDRANT_PORT", "6333"))
        self._openrouter_key = openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
        self._qdrant_base = f"http://{self._qdrant_host}:{self._qdrant_port}"
        self._minio_endpoint = minio_endpoint or os.getenv("MINIO_ENDPOINT", "http://172.23.0.4:9000")
        self._minio_bucket = minio_bucket

        # Ensure cache directory exists
        os.makedirs(SCREENSHOT_CACHE_DIR, exist_ok=True)

    async def get_visual_references(
        self,
        query: str,
        min_tier: str = "A",
        limit: int = 4,
        include_screenshots: bool = True,
    ) -> dict[str, Any]:
        """
        Get design references with optional screenshot images.

        Returns:
        {
            "references": [
                {
                    "title": "Site Name",
                    "design_style": "luxury",
                    "palette": {...},
                    "screenshot_url": "url or None",
                    "screenshot_base64": "base64 or None",
                    "style_analysis": "Visual analysis text",
                    ...
                }
            ],
            "vision_messages": [  # Ready-to-inject into LLM messages
                {"type": "text", "text": "Reference 1: ..."},
                {"type": "image_url", "image_url": {"url": "data:image/..."}},
            ],
            "style_summary": "Aggregated style analysis",
        }
        """
        # Step 1: Get text references from existing RAG
        from workers.design_rag import get_design_rag
        rag = get_design_rag()
        rag_results = await rag.search(
            query=query,
            min_tier=min_tier,
            limit=limit,
            diversity=True,
        )

        references = rag_results.get("references", [])
        if not references:
            return {
                "references": [],
                "vision_messages": [],
                "style_summary": "No references found.",
            }

        # Step 2: Fetch screenshots for top references (in parallel)
        if include_screenshots:
            screenshot_tasks = []
            for ref in references[:limit]:
                screenshot_url = ref.get("screenshot_url", "")
                if screenshot_url:
                    screenshot_tasks.append(
                        self._fetch_screenshot(screenshot_url, ref.get("title", "unknown"))
                    )
                else:
                    async def _noop():
                        return None
                    screenshot_tasks.append(_noop())

            screenshot_results = await asyncio.gather(*screenshot_tasks, return_exceptions=True)

            for i, result in enumerate(screenshot_results):
                if i < len(references) and isinstance(result, str) and result:
                    references[i]["screenshot_base64"] = result
                elif i < len(references):
                    references[i]["screenshot_base64"] = None

        # Step 3: Build vision-ready messages
        vision_messages = self._build_vision_messages(references)

        # Step 4: Create style summary
        style_summary = self._build_style_summary(references)

        return {
            "references": references,
            "vision_messages": vision_messages,
            "style_summary": style_summary,
            "suggested_blueprint": rag_results.get("suggested_blueprint", "clean_tech"),
        }

    async def _fetch_screenshot(self, url: str, title: str) -> Optional[str]:
        """
        Fetch a screenshot image and return as base64.
        Tries: 1) MinIO/S3 storage, 2) Direct URL, 3) Cache
        """
        # Check cache first
        safe_title = "".join(c if c.isalnum() else "_" for c in title)[:50]
        cache_path = Path(SCREENSHOT_CACHE_DIR) / f"{safe_title}.jpg"

        if cache_path.exists():
            try:
                with open(cache_path, "rb") as f:
                    data = f.read()
                if len(data) > 1000:  # Valid image
                    return base64.b64encode(data).decode("utf-8")
            except Exception:
                pass

        # Try to fetch from URL
        try:
            async with aiohttp.ClientSession() as session:
                # If URL is a MinIO path, construct full URL
                if url.startswith("/") or not url.startswith("http"):
                    fetch_url = f"{self._minio_endpoint}/{self._minio_bucket}/{url.lstrip('/')}"
                else:
                    fetch_url = url

                async with session.get(
                    fetch_url,
                    timeout=aiohttp.ClientTimeout(total=10),
                    headers={"User-Agent": "ARCANE/1.0"},
                ) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        if len(data) > 1000:
                            # Cache it
                            try:
                                with open(cache_path, "wb") as f:
                                    f.write(data)
                            except Exception:
                                pass

                            # Resize if too large (>500KB) to save tokens
                            if len(data) > 500_000:
                                data = await self._resize_image(data, max_width=800)

                            return base64.b64encode(data).decode("utf-8")
                    else:
                        logger.debug(f"Screenshot fetch failed for {title}: HTTP {resp.status}")

        except Exception as e:
            logger.debug(f"Screenshot fetch failed for {title}: {e}")

        return None

    async def _resize_image(self, image_data: bytes, max_width: int = 800) -> bytes:
        """Resize image to reduce token cost. Returns original if resize fails."""
        try:
            from PIL import Image
            import io

            img = Image.open(io.BytesIO(image_data))
            if img.width > max_width:
                ratio = max_width / img.width
                new_size = (max_width, int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)

            output = io.BytesIO()
            img.save(output, format="JPEG", quality=75)
            return output.getvalue()
        except Exception:
            return image_data

    def _build_vision_messages(self, references: list[dict]) -> list[dict]:
        """
        Build vision-ready content blocks for injection into LLM messages.
        Each reference becomes a text description + optional screenshot image.
        """
        messages = []

        for i, ref in enumerate(references):
            # Text description
            title = ref.get("title", "Unknown")
            style = ref.get("design_style", "?")
            mood = ref.get("mood", "?")
            palette_info = ""
            if ref.get("primary_colors"):
                palette_info = f", Colors: {ref['primary_colors']}"
            typo = ref.get("typography_style", "")
            hero = ref.get("hero_type", "")
            techniques = ref.get("notable_techniques", "")
            tier = ref.get("quality_tier", "?")

            text_block = (
                f"REFERENCE {i+1}: {title} (Tier {tier})\n"
                f"Style: {style} | Mood: {mood}{palette_info}\n"
                f"Typography: {typo} | Hero: {hero}\n"
                f"Notable: {techniques}"
            )

            messages.append({"type": "text", "text": text_block})

            # Screenshot image (if available)
            screenshot_b64 = ref.get("screenshot_base64")
            if screenshot_b64:
                messages.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{screenshot_b64}",
                        "detail": "low",  # Use low detail to save tokens
                    },
                })

        return messages

    def _build_style_summary(self, references: list[dict]) -> str:
        """
        Aggregate style patterns from references into a concise summary.
        """
        styles = set()
        moods = set()
        techniques = set()
        hero_types = set()
        palettes = []

        for ref in references:
            if ref.get("design_style"):
                styles.add(ref["design_style"])
            if ref.get("mood"):
                if isinstance(ref["mood"], list):
                    moods.update(ref["mood"])
                else:
                    moods.add(str(ref["mood"]))
            if ref.get("notable_techniques"):
                if isinstance(ref["notable_techniques"], list):
                    techniques.update(ref["notable_techniques"])
                else:
                    techniques.add(str(ref["notable_techniques"]))
            if ref.get("hero_type"):
                hero_types.add(ref["hero_type"])
            if ref.get("primary_colors"):
                pc = ref["primary_colors"]
                if isinstance(pc, list):
                    palettes.append(", ".join(str(c) for c in pc))
                else:
                    palettes.append(str(pc))

        summary_parts = []
        if styles:
            summary_parts.append(f"Dominant styles: {', '.join(styles)}")
        if moods:
            summary_parts.append(f"Mood keywords: {', '.join(list(moods)[:8])}")
        if hero_types:
            summary_parts.append(f"Hero types: {', '.join(hero_types)}")
        if techniques:
            summary_parts.append(f"Key techniques: {', '.join(list(techniques)[:6])}")
        if palettes:
            summary_parts.append(f"Color patterns: {'; '.join(palettes[:3])}")

        return "\n".join(summary_parts) if summary_parts else "No style patterns detected."


# ─────────────────────────────────────────────────────────────────
#  SINGLETON
# ─────────────────────────────────────────────────────────────────

_instance: Optional[VisualRAGService] = None


def get_visual_rag(config=None) -> VisualRAGService:
    """Get or create the singleton VisualRAGService."""
    global _instance
    if _instance is None:
        if config:
            _instance = VisualRAGService(
                qdrant_host=getattr(getattr(config, "qdrant", None), "host", ""),
                qdrant_port=getattr(getattr(config, "qdrant", None), "port", 6333),
                openrouter_api_key=getattr(getattr(config, "openrouter", None), "api_key", ""),
                minio_endpoint=getattr(getattr(config, "minio", None), "endpoint", ""),
            )
        else:
            _instance = VisualRAGService()
    return _instance
