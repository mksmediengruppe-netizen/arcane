"""
ARCANE Search Worker
Web search capabilities for the agent.

Supports 4 search backends with type-based routing:
  1. Tavily  — AI-optimized, main provider ($0.003/req)
  2. Serper  — Budget Google results ($0.001/req)
  3. Exa     — Semantic/neural search ($0.005/req)
  4. Brave   — Independent index, fallback ($0.005/req)

Search types:
  - info:     General web information, articles, facts
  - api:      API documentation and code examples
  - news:     Recent news and announcements
  - image:    Image search
  - code:     Code examples, GitHub repos
  - research: Academic / deep semantic search
  - data:     Datasets and structured data
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Optional

from shared.utils.logger import get_logger

logger = get_logger("workers.search")

# ═══════════════════════════════════════════════════════════════════════════════
# SEARCH CACHE — avoid duplicate API calls for identical queries
# ═══════════════════════════════════════════════════════════════════════════════

_search_cache: dict[str, dict] = {}  # hash -> {result, timestamp}
CACHE_TTL = 3600  # 1 hour


# ═══════════════════════════════════════════════════════════════════════════════
# SEARCH TYPE → PROVIDER ROUTING
# For each search type, providers are tried in order until one succeeds.
# ═══════════════════════════════════════════════════════════════════════════════

SEARCH_TYPE_PROVIDERS: dict[str, list[str]] = {
    "info":     ["tavily", "serper", "brave"],
    "api":      ["tavily", "exa", "serper"],
    "news":     ["tavily", "serper", "brave"],
    "image":    ["serper", "brave"],
    "code":     ["exa", "tavily"],
    "research": ["exa", "tavily"],
    "data":     ["exa", "tavily", "serper"],
}


class SearchWorker:
    """
    Performs web searches using multiple backends with type-based routing
    and automatic fallback.
    """

    def __init__(
        self,
        tavily_api_key: str = "",
        serper_api_key: str = "",
        exa_api_key: str = "",
        brave_api_key: str = "",
    ):
        self._tavily_key = tavily_api_key or os.getenv("TAVILY_API_KEY", "")
        self._serper_key = serper_api_key or os.getenv("SERPER_API_KEY", "")
        self._exa_key = exa_api_key or os.getenv("EXA_API_KEY", "")
        self._brave_key = brave_api_key or os.getenv("BRAVE_API_KEY", "")

    # ───────────────────────────────────────────────────────────────────────
    # Public API
    # ───────────────────────────────────────────────────────────────────────

    async def search(
        self,
        queries: list[str],
        search_type: str = "info",
        max_results: int = 10,
    ) -> dict:
        """
        Search the web with multiple query variants.
        Routes to the best provider based on search_type.
        Returns combined, deduplicated results.
        Uses in-memory cache with 1-hour TTL to avoid duplicate API calls.
        """
        # Check cache first
        cache_key = hashlib.md5(json.dumps(
            {"q": sorted(queries), "t": search_type, "n": max_results},
            sort_keys=True,
        ).encode()).hexdigest()

        if cache_key in _search_cache:
            cached = _search_cache[cache_key]
            if time.time() - cached["timestamp"] < CACHE_TTL:
                logger.info(f"Search cache hit for '{queries[0][:50]}' (age: {int(time.time() - cached['timestamp'])}s)")
                return cached["result"]
            else:
                del _search_cache[cache_key]  # expired

        providers = SEARCH_TYPE_PROVIDERS.get(search_type, ["tavily", "serper", "brave"])
        all_results = []

        for query in queries[:3]:  # Max 3 query variants
            results = await self._search_with_routing(query, search_type, max_results, providers)
            if results:
                all_results.extend(results)

        # Deduplicate by URL
        seen_urls: set[str] = set()
        unique_results: list[dict] = []
        for r in all_results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(r)
            elif not url:
                # Keep items without URL (e.g. AI summaries)
                unique_results.append(r)

        result = {
            "query": queries[0] if queries else "",
            "results": unique_results[:max_results],
            "total": len(unique_results),
        }

        # Store in cache
        _search_cache[cache_key] = {"result": result, "timestamp": time.time()}

        # Evict old entries if cache grows too large (>200 entries)
        if len(_search_cache) > 200:
            oldest_key = min(_search_cache, key=lambda k: _search_cache[k]["timestamp"])
            del _search_cache[oldest_key]

        return result

    # ───────────────────────────────────────────────────────────────────────
    # Provider routing
    # ───────────────────────────────────────────────────────────────────────

    async def _search_with_routing(
        self, query: str, search_type: str, max_results: int, providers: list[str]
    ) -> Optional[list[dict]]:
        """Try providers in order until one succeeds."""
        provider_map = {
            "tavily": (self._tavily_key, self._search_tavily),
            "serper": (self._serper_key, self._search_serper),
            "exa":    (self._exa_key, self._search_exa),
            "brave":  (self._brave_key, self._search_brave),
        }

        for provider_name in providers:
            key, method = provider_map.get(provider_name, (None, None))
            if not key or not method:
                continue
            try:
                results = await method(query, search_type, max_results)
                if results:
                    logger.info(f"Search via {provider_name}: {len(results)} results for '{query[:50]}'")
                    return results
            except Exception as e:
                logger.warning(f"{provider_name} search failed: {e}")
                continue

        logger.warning(f"All search providers failed for query: {query[:80]}")
        return None

    # ───────────────────────────────────────────────────────────────────────
    # Tavily — main provider, AI-optimized
    # ───────────────────────────────────────────────────────────────────────

    async def _search_tavily(
        self, query: str, search_type: str, max_results: int
    ) -> Optional[list[dict]]:
        """Tavily — main provider. $0.003/request. Returns clean text for LLM."""
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._tavily_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "advanced" if search_type in ("research", "api", "data") else "basic",
                    "include_answer": True,
                    "include_raw_content": False,
                    "topic": "news" if search_type == "news" else "general",
                },
            )

            if response.status_code != 200:
                logger.warning(f"Tavily API error: {response.status_code}")
                return None

            data = response.json()
            results = []

            # Include AI-generated answer if available
            if data.get("answer"):
                results.append({
                    "title": "AI Summary",
                    "url": "",
                    "content": data["answer"],
                    "source": "tavily_answer",
                })

            for item in data.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),  # Full text, not truncated
                    "score": item.get("score", 0),
                    "source": "tavily",
                })

            return results

    # ───────────────────────────────────────────────────────────────────────
    # Serper — budget Google results
    # ───────────────────────────────────────────────────────────────────────

    async def _search_serper(
        self, query: str, search_type: str, max_results: int
    ) -> Optional[list[dict]]:
        """Serper — budget Google. $0.001/request."""
        import httpx

        endpoint = {
            "image": "https://google.serper.dev/images",
            "news": "https://google.serper.dev/news",
        }.get(search_type, "https://google.serper.dev/search")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                endpoint,
                json={"q": query, "num": max_results},
                headers={"X-API-KEY": self._serper_key},
            )

            if response.status_code != 200:
                logger.warning(f"Serper API error: {response.status_code}")
                return None

            data = response.json()
            organic = data.get("organic", data.get("images", data.get("news", [])))

            results = []
            for item in organic[:max_results]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "content": item.get("snippet", ""),
                    "source": "serper",
                })

            return results

    # ───────────────────────────────────────────────────────────────────────
    # Exa — semantic/neural search
    # ───────────────────────────────────────────────────────────────────────

    async def _search_exa(
        self, query: str, search_type: str, max_results: int
    ) -> Optional[list[dict]]:
        """Exa.ai — semantic search. $0.005/request. 94.9% accuracy."""
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.exa.ai/search",
                json={
                    "query": query,
                    "num_results": max_results,
                    "type": "neural",
                    "use_autoprompt": True,
                    "contents": {"text": {"max_characters": 2000}},
                },
                headers={"x-api-key": self._exa_key},
            )

            if response.status_code != 200:
                logger.warning(f"Exa API error: {response.status_code}")
                return None

            data = response.json()
            results = []
            for item in data.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("text", ""),
                    "score": item.get("score", 0),
                    "source": "exa",
                })

            return results

    # ───────────────────────────────────────────────────────────────────────
    # Brave — independent index, fallback
    # ───────────────────────────────────────────────────────────────────────

    async def _search_brave(
        self, query: str, search_type: str, max_results: int
    ) -> Optional[list[dict]]:
        """Brave Search — independent index. $0.005/request. Fallback."""
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results},
                headers={"X-Subscription-Token": self._brave_key},
            )

            if response.status_code != 200:
                logger.warning(f"Brave API error: {response.status_code}")
                return None

            data = response.json()
            results = []
            for item in data.get("web", {}).get("results", [])[:max_results]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("description", ""),
                    "source": "brave",
                })

            return results
