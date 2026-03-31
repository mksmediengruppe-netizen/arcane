"""
ARCANE Memory Service
Long-term memory for the agent using vector storage (Qdrant).

Stores:
  - Solved tasks: task description → solution approach
  - Error-fix pairs: error pattern → successful fix
  - User preferences: per-user settings and patterns
  - Code snippets: reusable code patterns
  - Project context: per-project accumulated knowledge

Memory is used to:
  1. Skip known errors (instant fix from memory)
  2. Reuse successful approaches for similar tasks
  3. Remember user preferences across sessions
  4. Build a knowledge base that improves over time
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional

from shared.utils.logger import get_logger

logger = get_logger("workers.memory")


class MemoryService:
    """
    Vector-based long-term memory using Qdrant.
    Falls back to in-memory dict if Qdrant is unavailable.
    """

    def __init__(self, qdrant_url: str = "", qdrant_api_key: str = ""):
        self._qdrant_url = qdrant_url
        self._qdrant_key = qdrant_api_key
        self._client = None
        self._fallback: dict[str, list[dict]] = {
            "solved_tasks": [],
            "error_fixes": [],
            "preferences": [],
            "snippets": [],
        }
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize Qdrant connection."""
        if self._initialized:
            return

        if self._qdrant_url:
            try:
                from qdrant_client import AsyncQdrantClient
                from qdrant_client.models import Distance, VectorParams

                self._client = AsyncQdrantClient(
                    url=self._qdrant_url,
                    api_key=self._qdrant_key or None,
                )

                # Create collections if they don't exist
                collections = ["arcane_tasks", "arcane_errors", "arcane_preferences", "arcane_snippets"]
                existing = await self._client.get_collections()
                existing_names = [c.name for c in existing.collections]

                for collection in collections:
                    if collection not in existing_names:
                        await self._client.create_collection(
                            collection_name=collection,
                            vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
                        )
                        logger.info(f"Created Qdrant collection: {collection}")

                self._initialized = True
                logger.info("Memory service initialized with Qdrant")
                return

            except Exception as e:
                logger.warning(f"Qdrant unavailable, using fallback memory: {e}")

        self._initialized = True
        logger.info("Memory service initialized with in-memory fallback")

    async def store_solved_task(
        self,
        task_description: str,
        solution_approach: str,
        files_created: list[str] = None,
        technologies: list[str] = None,
        cost_usd: float = 0.0,
        user_id: str = "",
    ) -> None:
        """Store a successfully completed task for future reference."""
        await self.initialize()

        record = {
            "task": task_description,
            "solution": solution_approach,
            "files": files_created or [],
            "technologies": technologies or [],
            "cost_usd": cost_usd,
            "user_id": user_id,
            "timestamp": time.time(),
        }

        if self._client:
            try:
                embedding = await self._get_embedding(task_description)
                from qdrant_client.models import PointStruct
                import uuid

                await self._client.upsert(
                    collection_name="arcane_tasks",
                    points=[PointStruct(
                        id=str(uuid.uuid4()),
                        vector=embedding,
                        payload=record,
                    )],
                )
            except Exception as e:
                logger.warning(f"Failed to store task in Qdrant: {e}")
                self._fallback["solved_tasks"].append(record)
        else:
            self._fallback["solved_tasks"].append(record)

    async def store_error_fix(
        self,
        error_message: str,
        error_category: str,
        fix_applied: str,
        success: bool = True,
    ) -> None:
        """Store an error-fix pair for instant resolution of known errors."""
        await self.initialize()

        record = {
            "error": error_message[:500],
            "category": error_category,
            "fix": fix_applied,
            "success": success,
            "timestamp": time.time(),
        }

        if self._client:
            try:
                embedding = await self._get_embedding(error_message)
                from qdrant_client.models import PointStruct
                import uuid

                await self._client.upsert(
                    collection_name="arcane_errors",
                    points=[PointStruct(
                        id=str(uuid.uuid4()),
                        vector=embedding,
                        payload=record,
                    )],
                )
            except Exception as e:
                logger.warning(f"Failed to store error fix in Qdrant: {e}")
                self._fallback["error_fixes"].append(record)
        else:
            self._fallback["error_fixes"].append(record)

    async def find_similar_task(self, task_description: str, limit: int = 3) -> list[dict]:
        """Find similar previously solved tasks."""
        await self.initialize()

        if self._client:
            try:
                embedding = await self._get_embedding(task_description)
                # Qdrant >= 1.7: .search() removed, use .query_points()
                try:
                    qr = await self._client.query_points(
                        collection_name="arcane_tasks",
                        query=embedding,
                        limit=limit,
                        score_threshold=0.75,
                    )
                    results = qr.points if hasattr(qr, 'points') else qr
                except AttributeError:
                    results = await self._client.search(
                        collection_name="arcane_tasks",
                        query_vector=embedding,
                        limit=limit,
                        score_threshold=0.75,
                    )
                return [
                    {**r.payload, "similarity": r.score}
                    for r in results
                ]
            except Exception as e:
                logger.warning(f"Qdrant search failed: {e}")

        # Fallback: simple keyword matching
        matches = []
        keywords = set(task_description.lower().split())
        for record in self._fallback["solved_tasks"]:
            task_words = set(record["task"].lower().split())
            overlap = len(keywords & task_words) / max(len(keywords), 1)
            if overlap > 0.3:
                matches.append({**record, "similarity": overlap})

        matches.sort(key=lambda x: x["similarity"], reverse=True)
        return matches[:limit]

    async def find_error_fix(self, error_message: str) -> Optional[dict]:
        """Find a known fix for an error."""
        await self.initialize()

        if self._client:
            try:
                embedding = await self._get_embedding(error_message)
                # Qdrant >= 1.7: .search() removed, use .query_points()
                try:
                    qr = await self._client.query_points(
                        collection_name="arcane_errors",
                        query=embedding,
                        limit=1,
                        score_threshold=0.85,
                    )
                    results = qr.points if hasattr(qr, 'points') else qr
                except AttributeError:
                    results = await self._client.search(
                        collection_name="arcane_errors",
                        query_vector=embedding,
                        limit=1,
                        score_threshold=0.85,
                    )
                if results:
                    return {**results[0].payload, "similarity": results[0].score}
            except Exception as e:
                logger.warning(f"Qdrant error search failed: {e}")

        # Fallback
        error_hash = hashlib.md5(error_message[:200].encode()).hexdigest()
        for record in self._fallback["error_fixes"]:
            record_hash = hashlib.md5(record["error"][:200].encode()).hexdigest()
            if record_hash == error_hash and record["success"]:
                return record

        return None

    async def store_preference(self, user_id: str, key: str, value: Any) -> None:
        """Store a user preference."""
        await self.initialize()

        record = {
            "user_id": user_id,
            "key": key,
            "value": value,
            "timestamp": time.time(),
        }

        self._fallback["preferences"].append(record)

    async def get_preference(self, user_id: str, key: str, default: Any = None) -> Any:
        """Get a user preference."""
        for record in reversed(self._fallback["preferences"]):
            if record["user_id"] == user_id and record["key"] == key:
                return record["value"]
        return default

    async def _get_embedding(self, text: str) -> list[float]:
        """Get text embedding via OpenAI API."""
        try:
            import openai
            client = openai.AsyncOpenAI()
            response = await client.embeddings.create(
                model="text-embedding-3-small",
                input=text[:8000],
            )
            return response.data[0].embedding
        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            # Return zero vector as fallback
            return [0.0] * 1536
