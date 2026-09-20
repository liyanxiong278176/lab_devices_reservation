from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.ai.config import AiRuntimeConfig
from app.core.settings import Settings


@dataclass(frozen=True)
class SearchHit:
    point_id: str
    document_id: int
    title: str
    content: str
    score: float
    source_type: str
    college_id: int | None


def split_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(normalized) <= chunk_size:
        return [normalized] if normalized else []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + chunk_size)
        if end < len(normalized):
            boundary = normalized.rfind("\n", start + chunk_size // 2, end)
            if boundary > start:
                end = boundary
        chunks.append(normalized[start:end].strip())
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


class EmbeddingProvider:
    def __init__(self, settings: Settings, runtime: AiRuntimeConfig | None = None) -> None:
        self.settings = settings
        self.runtime = runtime
        self._embedder = None
        if runtime and runtime.api_key:
            from langchain_openai import OpenAIEmbeddings

            self._embedder = OpenAIEmbeddings(
                model=settings.ai_embedding_model,
                api_key=runtime.api_key,
                base_url=runtime.base_url,
            )

    async def embed(self, text: str) -> list[float]:
        if self._embedder is not None:
            return list(await self._embedder.aembed_query(text))
        return self._deterministic(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._embedder is not None:
            return [list(vector) for vector in await self._embedder.aembed_documents(texts)]
        return [self._deterministic(text) for text in texts]

    def _deterministic(self, text: str) -> list[float]:
        """Offline fallback for local/test; production should configure embeddings."""

        dimension = self.settings.ai_embedding_dimension
        values = [0.0] * dimension
        encoded = text.encode("utf-8") or b"_"
        for index in range(0, dimension, 4):
            digest = hashlib.blake2b(encoded + index.to_bytes(4, "big"), digest_size=8).digest()
            value = int.from_bytes(digest, "big") / 2**64
            values[index] = value * 2 - 1
        norm = math.sqrt(sum(value * value for value in values)) or 1
        return [value / norm for value in values]


class QdrantKnowledgeStore:
    def __init__(self, settings: Settings, runtime: AiRuntimeConfig | None = None) -> None:
        self.settings = settings
        self.client = AsyncQdrantClient(
            url=settings.qdrant_url,
            timeout=settings.ai_qdrant_timeout_seconds,
            check_compatibility=False,
        )
        self.embeddings = EmbeddingProvider(settings, runtime)
        self.collection = settings.ai_qdrant_collection
        self._collection_ready = False

    async def ensure_collection(self) -> None:
        if self._collection_ready:
            return
        if not await self.client.collection_exists(self.collection):
            try:
                await self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(
                        size=self.settings.ai_embedding_dimension,
                        distance=models.Distance.COSINE,
                    ),
                )
            except Exception:
                # Multiple API workers may initialize the same collection at
                # once. Treat an already-created collection as success, but
                # preserve genuine Qdrant outages for the caller to degrade.
                if not await self.client.collection_exists(self.collection):
                    raise
        self._collection_ready = True

    async def upsert_chunks(
        self,
        *,
        document_id: int,
        title: str,
        source_type: str,
        college_id: int | None,
        chunks: list[str],
    ) -> list[str]:
        await self.ensure_collection()
        # Re-publishing a document must remove old chunks; otherwise stale
        # vectors remain searchable after the MySQL metadata was replaced.
        await self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
            wait=True,
        )
        point_ids: list[str] = []
        points: list[models.PointStruct] = []
        vectors = await self.embeddings.embed_documents(chunks)
        for index, (content, vector) in enumerate(zip(chunks, vectors, strict=True)):
            point_id = str(uuid5(NAMESPACE_URL, f"lab-knowledge:{document_id}:{index}"))
            point_ids.append(point_id)
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "document_id": document_id,
                        "title": title,
                        "source_type": source_type,
                        "college_id": college_id or 0,
                        "content": content,
                        "chunk_index": index,
                    },
                )
            )
        if points:
            await self.client.upsert(self.collection, points=points, wait=True)
        return point_ids

    async def search(
        self,
        query: str,
        college_id: int | None,
        limit: int | None = None,
    ) -> list[SearchHit]:
        await self.ensure_collection()
        query_filter = None
        if college_id is not None:
            query_filter = models.Filter(
                should=[
                    models.FieldCondition(key="college_id", match=models.MatchValue(value=0)),
                    models.FieldCondition(
                        key="college_id",
                        match=models.MatchValue(value=college_id),
                    ),
                ],
                min_should=1,
            )
        response = await self.client.query_points(
            collection_name=self.collection,
            query=await self.embeddings.embed(query),
            query_filter=query_filter,
            limit=limit or self.settings.ai_max_context_documents,
            with_payload=True,
        )
        hits: list[SearchHit] = []
        for point in response.points:
            payload = point.payload or {}
            hits.append(
                SearchHit(
                    point_id=str(point.id),
                    document_id=int(payload.get("document_id", 0)),
                    title=str(payload.get("title", "知识库")),
                    content=str(payload.get("content", "")),
                    score=float(point.score or 0),
                    source_type=str(payload.get("source_type", "FAQ")),
                    college_id=(int(payload["college_id"]) or None)
                    if payload.get("college_id") is not None
                    else None,
                )
            )
        return hits

    async def close(self) -> None:
        await self.client.close()
