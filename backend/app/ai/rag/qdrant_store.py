from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

import httpx
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.ai.config import AiRuntimeConfig
from app.ai.dlp import redact_text
from app.core.errors import ApiError
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
    section: str = ""
    parent_section_id: int | None = None
    parent_content: str = ""


@dataclass(frozen=True)
class SectionPlan:
    index: int
    parent_index: int | None
    heading: str
    section_path: str
    content: str


@dataclass(frozen=True)
class ChildChunkPlan:
    index: int
    section_index: int
    section_path: str
    content: str


def parent_context_excerpt(parent_content: str, child_content: str, limit: int = 6000) -> str:
    if len(parent_content) <= limit:
        return parent_content
    needle = child_content[:120]
    match_at = parent_content.find(needle) if needle else -1
    start = max(0, match_at - limit // 3) if match_at >= 0 else 0
    end = min(len(parent_content), start + limit)
    if end == len(parent_content):
        start = max(0, end - limit)
    return parent_content[start:end]


def split_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(normalized) <= chunk_size:
        return [normalized] if normalized else []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + chunk_size)
        if end < len(normalized):
            search_from = start + chunk_size // 2
            for separator in ("\n\n", "\n", "。", "！", "？", "；", "，", " "):
                boundary = normalized.rfind(separator, search_from, end)
                if boundary > start:
                    end = boundary + len(separator)
                    break
        chunks.append(normalized[start:end].strip())
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


def split_document_sections(
    text: str,
    *,
    chunk_size: int = 900,
    overlap: int = 120,
) -> tuple[list[SectionPlan], list[ChildChunkPlan]]:
    """Keep Markdown heading ancestry, then recursively split each section body.

    The persisted section rows form the heading tree; child chunks remain small
    enough for embedding and point to their source section for retrieval context.
    Documents without headings get a synthetic whole-document section.
    """

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    heading_pattern = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
    sections: list[dict[str, object]] = []
    stack: list[tuple[int, int, str]] = []
    current_index: int | None = None
    body: list[str] = []
    saw_heading = False

    def flush_body() -> None:
        nonlocal body
        content = "\n".join(body).strip()
        if content and current_index is not None:
            existing = str(sections[current_index]["content"])
            sections[current_index]["content"] = f"{existing}\n{content}".strip()
        body = []

    for line in normalized.splitlines():
        match = heading_pattern.match(line)
        if match:
            flush_body()
            saw_heading = True
            level = len(match.group(1))
            heading = match.group(2).strip()[:500]
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent_index = stack[-1][1] if stack else None
            path = " / ".join([item[2] for item in stack] + [heading])
            current_index = len(sections)
            sections.append(
                {
                    "index": current_index,
                    "parent_index": parent_index,
                    "heading": heading,
                    "section_path": path[:2000],
                    "content": "",
                }
            )
            stack.append((level, current_index, heading))
        else:
            if not saw_heading and current_index is None and line.strip():
                current_index = len(sections)
                sections.append(
                    {
                        "index": current_index,
                        "parent_index": None,
                        "heading": "全文",
                        "section_path": "全文",
                        "content": "",
                    }
                )
            body.append(line)
    flush_body()

    if not sections:
        content = normalized.strip()
        if content:
            sections.append(
                {
                    "index": 0,
                    "parent_index": None,
                    "heading": "全文",
                    "section_path": "全文",
                    "content": content,
                }
            )

    section_plans = [SectionPlan(**section) for section in sections]
    child_plans: list[ChildChunkPlan] = []
    for section in section_plans:
        for content in split_text(section.content, chunk_size=chunk_size, overlap=overlap):
            child_plans.append(
                ChildChunkPlan(
                    index=len(child_plans),
                    section_index=section.index,
                    section_path=section.section_path,
                    content=content,
                )
            )
    return section_plans, child_plans


class EmbeddingProvider:
    def __init__(self, settings: Settings, runtime: AiRuntimeConfig | None = None) -> None:
        self.settings = settings
        self.runtime = runtime
        self._embedder = None
        if runtime and runtime.api_key:
            from langchain_openai import OpenAIEmbeddings

            self._embedder = OpenAIEmbeddings(
                model=runtime.model,
                api_key=runtime.api_key,
                base_url=runtime.base_url,
                timeout=settings.ai_provider_timeout_seconds,
                max_retries=2,
                # Ollama's OpenAI-compatible embeddings endpoint accepts text
                # strings, but not LangChain's token-ID arrays.
                check_embedding_ctx_length=runtime.provider.lower() != "ollama",
            )
        elif settings.environment == "prod":
            raise ApiError("AI_EMBEDDING_NOT_CONFIGURED", "Embedding 服务尚未配置", 503)

    async def embed(self, text: str) -> list[float]:
        if self._embedder is not None:
            vector = list(await self._embedder.aembed_query(text))
            if len(vector) != self.settings.ai_embedding_dimension:
                raise ApiError(
                    "AI_EMBEDDING_DIMENSION_MISMATCH", "Embedding 向量维度与索引不一致", 503
                )
            return vector
        return self._deterministic(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._embedder is not None:
            vectors = [list(vector) for vector in await self._embedder.aembed_documents(texts)]
            if any(len(vector) != self.settings.ai_embedding_dimension for vector in vectors):
                raise ApiError(
                    "AI_EMBEDDING_DIMENSION_MISMATCH", "Embedding 向量维度与索引不一致", 503
                )
            return vectors
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
    def __init__(
        self,
        settings: Settings,
        runtime: AiRuntimeConfig | None = None,
        *,
        embeddings_required: bool = True,
    ) -> None:
        self.settings = settings
        self.client = AsyncQdrantClient(
            url=settings.qdrant_url,
            timeout=settings.ai_qdrant_timeout_seconds,
            check_compatibility=False,
        )
        self.embeddings = EmbeddingProvider(settings, runtime) if embeddings_required else None
        self.collection = (
            runtime.collection_name if runtime else None
        ) or settings.ai_qdrant_collection
        self._collection_ready = False
        self._named_dense = False
        self._bm25_ready = False

    @staticmethod
    def _scope_filter(
        college_id: int | None,
        *,
        cross_college: bool,
        allowed_roles: list[str] | tuple[str, ...] | None,
    ):
        visible_roles = sorted(set(allowed_roles or ()))
        role_conditions = []
        if allowed_roles is not None:
            if visible_roles:
                role_conditions.append(
                    models.FieldCondition(
                        key="allowed_roles",
                        match=models.MatchAny(any=visible_roles),
                    )
                )
            role_conditions.append(
                models.IsEmptyCondition(is_empty=models.PayloadField(key="allowed_roles"))
            )
        if cross_college:
            return (
                models.Filter(min_should=models.MinShould(conditions=role_conditions, min_count=1))
                if role_conditions
                else None
            )
        visible_scopes = [models.FieldCondition(key="college_id", match=models.MatchValue(value=0))]
        if college_id is not None:
            visible_scopes.append(
                models.FieldCondition(
                    key="college_id",
                    match=models.MatchValue(value=college_id),
                )
            )
        college_filter = models.Filter(
            min_should=models.MinShould(conditions=visible_scopes, min_count=1)
        )
        if not role_conditions:
            return college_filter
        return models.Filter(
            must=[college_filter],
            min_should=models.MinShould(conditions=role_conditions, min_count=1),
        )

    @staticmethod
    def _with_active_versions(
        scope_filter,
        active_versions: Mapping[int, int] | None,
    ):
        if active_versions is None:
            return scope_filter
        if not active_versions:
            return models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=-1),
                    )
                ]
            )
        active_filter = models.Filter(
            min_should=models.MinShould(
                conditions=[
                    models.Filter(
                        must=[
                            models.FieldCondition(
                                key="document_id",
                                match=models.MatchValue(value=document_id),
                            ),
                            models.FieldCondition(
                                key="version",
                                match=models.MatchValue(value=version),
                            ),
                        ]
                    )
                    for document_id, version in active_versions.items()
                ],
                min_count=1,
            )
        )
        if scope_filter is None:
            return active_filter
        return models.Filter(must=[scope_filter, active_filter])

    async def ensure_collection(self) -> None:
        if self._collection_ready:
            return
        if not await self.client.collection_exists(self.collection):
            try:
                await self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config={
                        "dense": models.VectorParams(
                            size=self.settings.ai_embedding_dimension,
                            distance=models.Distance.COSINE,
                        )
                    },
                    sparse_vectors_config={
                        "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)
                    },
                )
            except Exception:
                # Multiple API workers may initialize the same collection at
                # once. Treat an already-created collection as success, but
                # preserve genuine Qdrant outages for the caller to degrade.
                if not await self.client.collection_exists(self.collection):
                    raise
        info = await self.client.get_collection(self.collection)
        payload_schema = info.payload_schema or {}
        for field_name, field_schema in (
            ("college_id", models.PayloadSchemaType.INTEGER),
            ("document_id", models.PayloadSchemaType.INTEGER),
            ("version", models.PayloadSchemaType.INTEGER),
            ("allowed_roles", models.PayloadSchemaType.KEYWORD),
            ("lab_id", models.PayloadSchemaType.INTEGER),
            ("device_id", models.PayloadSchemaType.INTEGER),
        ):
            if field_name in payload_schema:
                continue
            try:
                await self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field_name,
                    field_schema=field_schema,
                    wait=True,
                )
            except Exception:
                # Another API/Worker process may create the same index while
                # this process initializes the shared collection.
                refreshed = await self.client.get_collection(self.collection)
                if field_name not in (refreshed.payload_schema or {}):
                    raise
        info = await self.client.get_collection(self.collection)
        params = info.config.params
        vector_config = params.vectors
        sparse_config = params.sparse_vectors or {}
        self._named_dense = isinstance(vector_config, dict) and "dense" in vector_config
        self._bm25_ready = self._named_dense and "bm25" in sparse_config
        self._collection_ready = True

    async def upsert_chunks(
        self,
        *,
        document_id: int,
        title: str,
        source_type: str,
        college_id: int | None,
        chunks: list[str],
        version: int = 1,
        chunk_indices: list[int] | None = None,
        section_paths: list[str] | None = None,
        parent_section_ids: list[int | None] | None = None,
        allowed_roles: list[str] | None = None,
        lab_ids: list[int | None] | None = None,
        device_ids: list[int | None] | None = None,
        index_metadata: dict[str, object] | None = None,
    ) -> list[str]:
        await self.ensure_collection()
        point_ids: list[str] = []
        points: list[models.PointStruct] = []
        if self.embeddings is None:
            raise RuntimeError("Embedding provider is unavailable for this operation")
        safe_chunks = [redact_text(chunk).text for chunk in chunks]
        vectors = await self.embeddings.embed_documents(safe_chunks)
        indices = chunk_indices or list(range(len(chunks)))
        if len(indices) != len(chunks):
            raise ValueError("chunk index count must match chunk count")
        paths = section_paths or [""] * len(chunks)
        parents = parent_section_ids or [None] * len(chunks)
        roles = allowed_roles or [[] for _ in chunks]
        labs = lab_ids or [None] * len(chunks)
        devices = device_ids or [None] * len(chunks)
        if any(len(values) != len(chunks) for values in (paths, parents, roles, labs, devices)):
            raise ValueError("section metadata count must match chunk count")
        extra_metadata = index_metadata or {}
        for index, content, vector, section_path, parent_id, role_scope, lab_id, device_id in zip(
            indices,
            safe_chunks,
            vectors,
            paths,
            parents,
            roles,
            labs,
            devices,
            strict=True,
        ):
            point_id = str(uuid5(NAMESPACE_URL, f"lab-knowledge:{document_id}:v{version}:{index}"))
            point_ids.append(point_id)
            if self._named_dense:
                vector_payload: dict[str, object] = {"dense": vector}
                if self._bm25_ready:
                    vector_payload["bm25"] = models.Document(
                        text=content,
                        model="qdrant/bm25",
                        options={"tokenizer": "multilingual"},
                    )
            else:
                vector_payload = vector
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=vector_payload,
                    payload={
                        "document_id": document_id,
                        "title": title,
                        "source_type": source_type,
                        "college_id": college_id or 0,
                        "content": content,
                        "chunk_index": index,
                        "version": version,
                        "section_path": section_path,
                        "parent_section_id": parent_id,
                        "allowed_roles": sorted(set(role_scope)),
                        "lab_id": lab_id,
                        "device_id": device_id,
                        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        "embedding_model": (
                            self.embeddings.runtime.model
                            if self.embeddings.runtime is not None
                            else "deterministic-test"
                        ),
                        "index_generation": self.collection,
                        **extra_metadata,
                    },
                )
            )
        if points:
            await self.client.upsert(self.collection, points=points, wait=True)
        return point_ids

    async def delete_old_document_versions(self, document_id: int, keep_version: int) -> None:
        await self.ensure_collection()
        await self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        )
                    ],
                    must_not=[
                        models.FieldCondition(
                            key="version",
                            match=models.MatchValue(value=keep_version),
                        )
                    ],
                )
            ),
            wait=True,
        )

    async def delete_document(self, document_id: int) -> None:
        await self.ensure_collection()
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

    async def search(
        self,
        query: str,
        college_id: int | None,
        limit: int | None = None,
        *,
        cross_college: bool = False,
        allowed_roles: list[str] | tuple[str, ...] | None = None,
        active_versions: Mapping[int, int] | None = None,
    ) -> list[SearchHit]:
        if active_versions is not None and not active_versions:
            return []
        await self.ensure_collection()
        query_filter = self._with_active_versions(
            self._scope_filter(
                college_id,
                cross_college=cross_college,
                allowed_roles=allowed_roles,
            ),
            active_versions,
        )
        if self.embeddings is None:
            raise RuntimeError("Embedding provider is unavailable for this operation")
        kwargs: dict[str, object] = {}
        if self._named_dense:
            kwargs["using"] = "dense"
        response = await self.client.query_points(
            collection_name=self.collection,
            query=await self.embeddings.embed(redact_text(query).text),
            query_filter=query_filter,
            limit=limit or self.settings.ai_max_context_documents,
            with_payload=True,
            **kwargs,
        )
        return self._search_hits(response.points)

    async def search_sparse(
        self,
        query: str,
        college_id: int | None,
        limit: int | None = None,
        *,
        cross_college: bool = False,
        allowed_roles: list[str] | tuple[str, ...] | None = None,
        active_versions: Mapping[int, int] | None = None,
    ) -> list[SearchHit]:
        if active_versions is not None and not active_versions:
            return []
        await self.ensure_collection()
        if not self._bm25_ready:
            return []
        query_filter = self._with_active_versions(
            self._scope_filter(
                college_id,
                cross_college=cross_college,
                allowed_roles=allowed_roles,
            ),
            active_versions,
        )
        response = await self.client.query_points(
            collection_name=self.collection,
            query=models.Document(
                text=redact_text(query).text,
                model="qdrant/bm25",
                options={"tokenizer": "multilingual"},
            ),
            using="bm25",
            query_filter=query_filter,
            limit=limit or self.settings.ai_max_context_documents,
            with_payload=True,
        )
        return self._search_hits(response.points)

    @staticmethod
    def _search_hits(points: list[models.ScoredPoint]) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for point in points:
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
                    section=str(
                        payload.get("section_path")
                        or f"片段 {int(payload.get('chunk_index', 0)) + 1}"
                    ),
                    parent_section_id=(
                        int(payload["parent_section_id"])
                        if payload.get("parent_section_id") is not None
                        else None
                    ),
                )
            )
        return hits

    async def rerank(self, query: str, hits: list[SearchHit]) -> list[SearchHit]:
        if (
            not hits
            or self.embeddings is None
            or self.embeddings.runtime is None
            or not self.embeddings.runtime.api_key
        ):
            return hits
        runtime = self.embeddings.runtime
        endpoint = (runtime.base_url or "https://api.siliconflow.cn/v1").rstrip("/") + "/rerank"
        safe_query = redact_text(query).text
        safe_documents = [
            redact_text(hit.parent_content or hit.content).text[:6000] for hit in hits
        ]
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.ai_provider_timeout_seconds
            ) as client:
                response = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {runtime.api_key}"},
                    json={
                        "model": self.settings.ai_reranker_model,
                        "query": safe_query,
                        "documents": safe_documents,
                        "top_n": min(len(hits), self.settings.ai_max_context_documents),
                    },
                )
                response.raise_for_status()
                results = response.json().get("results", [])
            reranked: list[SearchHit] = []
            for result in results:
                index = int(result.get("index", -1))
                if 0 <= index < len(hits):
                    hit = hits[index]
                    reranked.append(
                        SearchHit(
                            point_id=hit.point_id,
                            document_id=hit.document_id,
                            title=hit.title,
                            content=hit.content,
                            score=float(result.get("relevance_score", hit.score)),
                            source_type=hit.source_type,
                            college_id=hit.college_id,
                            section=hit.section,
                            parent_section_id=hit.parent_section_id,
                            parent_content=hit.parent_content,
                        )
                    )
            return reranked or hits
        except Exception:
            # Rerank is best-effort; vector and lexical ranking remain available.
            return hits

    async def close(self) -> None:
        await self.client.close()
