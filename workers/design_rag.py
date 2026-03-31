"""
ARCANE Design RAG (Retrieval-Augmented Generation) Service
Searches the curated design_inspiration Qdrant collection for relevant
reference websites based on business niche, style preferences, and mood.

Uses OpenRouter for embeddings (text-embedding-3-small, 1536 dim).
Qdrant collection: design_inspiration (515+ premium websites from Land-book,
Awwwards, Godly, SiteInspire, etc.)
"""

from __future__ import annotations

import gzip
import json
import os
from typing import Any, Optional

import aiohttp

from shared.utils.logger import get_logger

logger = get_logger("workers.design_rag")

# ── Constants ────────────────────────────────────────────────────────────────

EMBEDDING_MODEL = "openai/text-embedding-3-small"
EMBEDDING_DIM = 1536
COLLECTION_NAME = "design_inspiration"

# Payload fields we return to the agent
RETURN_FIELDS = [
    "title", "url", "original_url", "screenshot_url", "category", "source",
    "tags", "colors", "design_style", "color_theme", "primary_colors",
    "typography_style", "hero_type", "layout_pattern", "sections", "mood",
    "industry_fit", "notable_techniques", "quality_tier", "one_line_summary",
]

# Blueprint mapping: design_style → recommended blueprint template
STYLE_TO_BLUEPRINT = {
    "luxury": "dark_luxury",
    "dark-luxury": "dark_luxury",
    "dark-premium": "dark_luxury",
    "editorial": "warm_editorial",
    "warm-editorial": "warm_editorial",
    "tech-modern": "clean_tech",
    "clean-tech": "clean_tech",
    "saas": "clean_tech",
    "bold": "bold_energy",
    "energetic": "bold_energy",
    "wellness": "soft_wellness",
    "organic": "soft_wellness",
    "minimal": "japandi_minimal",
    "japandi": "japandi_minimal",
    "brutalist": "neobrutalist",
    "neobrutalist": "neobrutalist",
    "fashion": "editorial_couture",
    "couture": "editorial_couture",
    "cinematic": "cinematic_prestige",
    "prestige": "cinematic_prestige",
    "hospitality": "boutique_hospitality",
    "boutique": "boutique_hospitality",
}


class DesignRAGService:
    """
    Semantic search over curated design references.
    Combines vector similarity with optional payload filters for
    style, tier, mood, and industry.
    """

    def __init__(
        self,
        qdrant_host: str = "",
        qdrant_port: int = 6333,
        openrouter_api_key: str = "",
    ):
        self._qdrant_host = qdrant_host or os.getenv("QDRANT_HOST", "localhost")
        self._qdrant_port = qdrant_port or int(os.getenv("QDRANT_PORT", "6333"))
        self._openrouter_key = openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
        self._qdrant_base = f"http://{self._qdrant_host}:{self._qdrant_port}"

    # ── Public API ───────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        style: Optional[str] = None,
        mood: Optional[str] = None,
        industry: Optional[str] = None,
        min_tier: str = "A",
        limit: int = 8,
        diversity: bool = True,
    ) -> dict[str, Any]:
        """
        Search for design references matching the query.

        Args:
            query: Natural language description (e.g. "dark luxury hotel landing page")
            style: Filter by design_style (e.g. "luxury", "tech-modern", "editorial")
            mood: Filter by mood (e.g. "elegant sophisticated", "bold energetic")
            industry: Filter by industry_fit (e.g. "hospitality", "saas", "fashion")
            min_tier: Minimum quality tier: "S" (best), "A" (great), "B" (good). Default "A"
            limit: Max results (default 8)
            diversity: If True, deduplicate by design_style to ensure variety

        Returns:
            Dict with "references" list and "suggested_blueprint" string
        """
        try:
            # Step 1: Get embedding for the query
            embedding = await self._get_embedding(query)
            if not embedding or all(v == 0.0 for v in embedding[:10]):
                return {"error": "Failed to generate embedding", "references": []}

            # Step 2: Build Qdrant filter
            qdrant_filter = self._build_filter(style, mood, industry, min_tier)

            # Step 3: Search Qdrant
            search_body: dict[str, Any] = {
                "vector": embedding,
                "limit": limit * 3 if diversity else limit,  # over-fetch for diversity
                "with_payload": True,
                "score_threshold": 0.25,
            }
            if qdrant_filter:
                search_body["filter"] = qdrant_filter

            raw_results = await self._qdrant_search(search_body)

            if not raw_results and qdrant_filter:
                # Retry without filters
                logger.info("No results with filters, retrying without filters")
                search_body.pop("filter", None)
                search_body["limit"] = limit
                raw_results = await self._qdrant_search(search_body)

            # Step 4: Process and diversify results
            references = []
            seen_styles: dict[str, int] = {}
            for r in raw_results:
                payload = r.get("payload", {})
                ref = {"score": round(r.get("score", 0), 3)}
                for field in RETURN_FIELDS:
                    if field in payload:
                        ref[field] = payload[field]

                # Diversity: limit to 2 per design_style
                ds = payload.get("design_style", "unknown")
                if diversity:
                    count = seen_styles.get(ds, 0)
                    if count >= 2:
                        continue
                    seen_styles[ds] = count + 1

                references.append(ref)
                if len(references) >= limit:
                    break

            # Step 5: Suggest a blueprint based on dominant style
            suggested_blueprint = self._suggest_blueprint(references, query)

            return {
                "query": query,
                "total_found": len(raw_results),
                "returned": len(references),
                "suggested_blueprint": suggested_blueprint,
                "references": references,
            }

        except Exception as e:
            logger.error(f"Design RAG search failed: {e}", exc_info=True)
            return {"error": str(e), "references": []}

    async def get_stats(self) -> dict[str, Any]:
        """Get collection statistics."""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self._qdrant_base}/collections/{COLLECTION_NAME}"
                async with session.get(
                    url,
                    headers={"Accept-Encoding": "identity"},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result = data.get("result", {})
                        return {
                            "status": result.get("status", "unknown"),
                            "points_count": result.get("points_count", 0),
                            "indexed_vectors": result.get("indexed_vectors_count", 0),
                            "vector_dim": (
                                result.get("config", {})
                                .get("params", {})
                                .get("vectors", {})
                                .get("size", 0)
                            ),
                        }
                    return {"error": f"Status {resp.status}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Private helpers ──────────────────────────────────────────────────────

    async def _get_embedding(self, text: str) -> list[float]:
        """Get text embedding via OpenRouter API.
        
        Uses auto_decompress=False + Accept-Encoding: gzip to avoid
        brotli issues in some aiohttp versions.
        """
        if not self._openrouter_key:
            logger.error("No OpenRouter API key configured")
            return [0.0] * EMBEDDING_DIM

        try:
            async with aiohttp.ClientSession(auto_decompress=False) as session:
                async with session.post(
                    "https://openrouter.ai/api/v1/embeddings",
                    headers={
                        "Authorization": f"Bearer {self._openrouter_key}",
                        "Content-Type": "application/json",
                        "Accept-Encoding": "gzip, deflate",
                    },
                    json={
                        "model": EMBEDDING_MODEL,
                        "input": text[:8000],
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        raw = await resp.read()
                        ce = resp.headers.get("Content-Encoding", "")
                        if ce == "gzip":
                            raw = gzip.decompress(raw)
                        data = json.loads(raw)
                        return data["data"][0]["embedding"]
                    else:
                        text_err = await resp.text()
                        logger.error(f"Embedding API error ({resp.status}): {text_err}")
                        return [0.0] * EMBEDDING_DIM
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return [0.0] * EMBEDDING_DIM

    async def _qdrant_search(self, body: dict) -> list[dict]:
        """Execute a search against Qdrant."""
        url = f"{self._qdrant_base}/collections/{COLLECTION_NAME}/points/search"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=body,
                    headers={
                        "Content-Type": "application/json",
                        "Accept-Encoding": "identity",
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.error(f"Qdrant search failed ({resp.status}): {text}")
                        return []
                    data = await resp.json()
                    return data.get("result", [])
        except Exception as e:
            logger.error(f"Qdrant request failed: {e}")
            return []

    def _build_filter(
        self,
        style: Optional[str],
        mood: Optional[str],
        industry: Optional[str],
        min_tier: str,
    ) -> Optional[dict]:
        """Build Qdrant filter conditions."""
        must_conditions = []

        # Quality tier filter
        tier_order = {"S": 0, "A": 1, "B": 2, "C": 3}
        min_tier_idx = tier_order.get(min_tier.upper(), 1)
        allowed_tiers = [t for t, idx in tier_order.items() if idx <= min_tier_idx]
        if allowed_tiers and min_tier.upper() != "C":
            must_conditions.append({
                "key": "quality_tier",
                "match": {"any": allowed_tiers},
            })

        # Style filter
        if style:
            must_conditions.append({
                "key": "design_style",
                "match": {"value": style},
            })

        # Mood filter (keyword match)
        if mood:
            must_conditions.append({
                "key": "mood",
                "match": {"text": mood},
            })

        # Industry filter
        if industry:
            must_conditions.append({
                "key": "industry_fit",
                "match": {"any": [industry]},
            })

        if must_conditions:
            return {"must": must_conditions}
        return None

    def _suggest_blueprint(self, references: list[dict], query: str) -> str:
        """Suggest the best blueprint template based on search results and query."""
        # Count styles in results
        style_counts: dict[str, int] = {}
        for ref in references:
            ds = ref.get("design_style", "")
            if ds:
                style_counts[ds] = style_counts.get(ds, 0) + 1

        # Check query keywords for direct blueprint hints
        query_lower = query.lower()
        for keyword, blueprint in STYLE_TO_BLUEPRINT.items():
            if keyword in query_lower:
                return blueprint

        # Use dominant style from results
        if style_counts:
            dominant_style = max(style_counts, key=style_counts.get)
            if dominant_style in STYLE_TO_BLUEPRINT:
                return STYLE_TO_BLUEPRINT[dominant_style]

        # Default
        return "clean_tech"


# ── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[DesignRAGService] = None


def get_design_rag(config=None) -> DesignRAGService:
    """Get or create the singleton DesignRAGService."""
    global _instance
    if _instance is None:
        if config:
            _instance = DesignRAGService(
                qdrant_host=config.qdrant.host,
                qdrant_port=config.qdrant.port,
                openrouter_api_key=config.openrouter.api_key,
            )
        else:
            _instance = DesignRAGService()
    return _instance
