from __future__ import annotations

import re

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.qdrant_store import QdrantKnowledgeStore, SearchHit
from app.auth.security import Principal
from app.infrastructure.db.models import KnowledgeChunk, KnowledgeDocument


def _tokens(query: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", query.lower())
    output: list[str] = []
    for term in terms:
        if len(term) <= 8:
            output.append(term)
        else:
            output.extend(term[index : index + 2] for index in range(len(term) - 1))
    if query.strip():
        output.append(query.strip()[:100])
    return list(dict.fromkeys(term for term in output if len(term) > 1))[:24]


async def _lexical_search(
    session: AsyncSession,
    query: str,
    principal: Principal,
    limit: int,
) -> list[SearchHit]:
    scope_filter = []
    if not principal.is_system_admin:
        if principal.college_id is None:
            scope_filter.append(KnowledgeDocument.college_id.is_(None))
        else:
            scope_filter.append(
                or_(
                    KnowledgeDocument.college_id.is_(None),
                    KnowledgeDocument.college_id == principal.college_id,
                )
            )
    base = (
        select(KnowledgeChunk, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .where(KnowledgeDocument.status == "PUBLISHED", *scope_filter)
    )
    if session.bind is not None and session.bind.dialect.name == "mysql":
        statement = text(
            "SELECT c.id AS chunk_id, c.document_id, c.college_id, c.point_id, "
            "c.chunk_index, c.content, d.title, d.source_type, "
            "MATCH(c.content) AGAINST (:query IN NATURAL LANGUAGE MODE) AS score "
            "FROM v2_knowledge_chunk c JOIN v2_knowledge_document d ON d.id=c.document_id "
            "WHERE d.status='PUBLISHED' AND "
            "(:is_admin=1 OR d.college_id IS NULL OR d.college_id=:college_id) "
            "AND MATCH(c.content) AGAINST (:query IN NATURAL LANGUAGE MODE) > 0 "
            "ORDER BY score DESC, c.id DESC LIMIT :limit"
        )
        rows = (
            (
                await session.execute(
                    statement,
                    {
                        "query": query[:500],
                        "is_admin": int(principal.is_system_admin),
                        "college_id": principal.college_id or 0,
                        "limit": limit,
                    },
                )
            )
            .mappings()
            .all()
        )
        return [
            SearchHit(
                point_id=str(row["point_id"]),
                document_id=int(row["document_id"]),
                title=str(row["title"]),
                content=str(row["content"]),
                score=float(row["score"] or 0),
                source_type=str(row["source_type"]),
                college_id=int(row["college_id"]) if row["college_id"] else None,
                section=f"片段 {int(row['chunk_index']) + 1}",
            )
            for row in rows
        ]

    tokens = _tokens(query)
    if not tokens:
        return []
    statement = base.where(or_(*(KnowledgeChunk.content.ilike(f"%{token}%") for token in tokens)))
    rows = list((await session.execute(statement.limit(limit * 3))).all())

    def lexical_score(row: tuple[KnowledgeChunk, KnowledgeDocument]) -> int:
        content = row[0].content.lower()
        return sum(content.count(token) for token in tokens)

    rows.sort(key=lambda row: (lexical_score(row), row[0].id), reverse=True)
    return [
        SearchHit(
            point_id=chunk.point_id,
            document_id=document.id,
            title=document.title,
            content=chunk.content,
            score=float(lexical_score((chunk, document))),
            source_type=document.source_type,
            college_id=document.college_id,
            section=f"片段 {chunk.chunk_index + 1}",
        )
        for chunk, document in rows[:limit]
    ]


async def hybrid_search(
    session: AsyncSession,
    store: QdrantKnowledgeStore,
    query: str,
    principal: Principal,
    limit: int,
) -> list[SearchHit]:
    candidates = max(limit * 4, 12)
    vector_hits = await store.search(
        query,
        principal.college_id,
        candidates,
        cross_college=principal.is_system_admin,
    )
    if vector_hits:
        point_conditions = [
            KnowledgeChunk.point_id.in_([hit.point_id for hit in vector_hits]),
            KnowledgeDocument.status == "PUBLISHED",
        ]
        if not principal.is_system_admin:
            if principal.college_id is None:
                point_conditions.append(KnowledgeDocument.college_id.is_(None))
            else:
                point_conditions.append(
                    or_(
                        KnowledgeDocument.college_id.is_(None),
                        KnowledgeDocument.college_id == principal.college_id,
                    )
                )
        current_points = set(
            await session.scalars(
                select(KnowledgeChunk.point_id)
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                .where(*point_conditions)
            )
        )
        vector_hits = [hit for hit in vector_hits if hit.point_id in current_points]
    lexical_hits = await _lexical_search(session, query, principal, candidates)
    by_id: dict[str, SearchHit] = {}
    scores: dict[str, float] = {}
    for rank, hit in enumerate(vector_hits, start=1):
        by_id[hit.point_id] = hit
        scores[hit.point_id] = scores.get(hit.point_id, 0.0) + 1 / (60 + rank)
    for rank, hit in enumerate(lexical_hits, start=1):
        by_id.setdefault(hit.point_id, hit)
        scores[hit.point_id] = scores.get(hit.point_id, 0.0) + 1 / (60 + rank)
    fused = [
        SearchHit(
            point_id=hit.point_id,
            document_id=hit.document_id,
            title=hit.title,
            content=hit.content,
            score=scores[point_id],
            source_type=hit.source_type,
            college_id=hit.college_id,
            section=hit.section,
        )
        for point_id, hit in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ]
    return (await store.rerank(query, fused))[:limit]
