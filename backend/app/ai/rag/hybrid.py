from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.access import document_role_visible, document_scope_conditions
from app.ai.rag.qdrant_store import QdrantKnowledgeStore, SearchHit
from app.auth.security import Principal
from app.infrastructure.db.models import (
    AiDomainTerm,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSection,
)


def _decode_roles(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return ["__INVALID_SCOPE__"]
    return value if isinstance(value, list) else ["__INVALID_SCOPE__"]


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


async def _query_variants(
    session: AsyncSession,
    query: str,
    principal: Principal,
) -> list[str]:
    conditions = [AiDomainTerm.status == "APPROVED"]
    if not principal.is_system_admin:
        if principal.college_id is None:
            conditions.append(AiDomainTerm.college_id.is_(None))
        else:
            conditions.append(
                or_(
                    AiDomainTerm.college_id.is_(None),
                    AiDomainTerm.college_id == principal.college_id,
                )
            )
    terms = list((await session.scalars(select(AiDomainTerm).where(*conditions))).all())
    normalized = query.strip()
    for term in terms:
        if term.kind == "IGNORE":
            normalized = re.sub(
                re.escape(term.term),
                " ",
                normalized,
                flags=re.IGNORECASE,
            )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    variants = [query]
    if normalized and normalized.casefold() != query.strip().casefold():
        variants.append(normalized)
    for term in terms:
        if term.kind != "SYNONYM" or not term.canonical:
            continue
        if term.term.casefold() not in normalized.casefold():
            continue
        expanded = re.sub(
            re.escape(term.term),
            term.canonical,
            normalized,
            flags=re.IGNORECASE,
        )
        if expanded and expanded.casefold() not in {item.casefold() for item in variants}:
            variants.append(expanded)
    return variants[:4]


async def _lexical_search(
    session: AsyncSession,
    query: str,
    principal: Principal,
    limit: int,
) -> list[SearchHit]:
    scope_filter = document_scope_conditions(principal)
    base = (
        select(KnowledgeChunk, KnowledgeDocument, KnowledgeSection)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .outerjoin(KnowledgeSection, KnowledgeSection.id == KnowledgeChunk.parent_section_id)
        .where(
            KnowledgeDocument.status == "PUBLISHED",
            KnowledgeChunk.version
            == func.coalesce(KnowledgeDocument.active_version, KnowledgeDocument.version),
            *scope_filter,
        )
    )
    if session.bind is not None and session.bind.dialect.name == "mysql":
        role_predicates = [
            "d.allowed_roles IS NULL",
            "JSON_LENGTH(d.allowed_roles)=0",
        ]
        parameters: dict[str, object] = {
            "query": query[:500],
            "is_admin": int(principal.is_system_admin),
            "college_id": principal.college_id or 0,
            "candidate_limit": min(limit * 3, 300),
        }
        for role_index, role in enumerate(principal.roles):
            parameter_name = f"role_{role_index}"
            role_predicates.append(
                f"JSON_CONTAINS(d.allowed_roles, JSON_QUOTE(:{parameter_name}), '$')"
            )
            parameters[parameter_name] = role
        allowed_role_sql = " OR ".join(role_predicates)
        statement = text(
            "SELECT c.id AS chunk_id, c.document_id, c.college_id, c.point_id, "
            "c.chunk_index, c.content, c.metadata AS metadata_json, d.title, d.source_type, "
            "d.allowed_roles AS allowed_roles, "
            "s.id AS parent_section_id, s.content AS parent_content, "
            "s.section_path AS section_path, "
            "MATCH(c.content) AGAINST (:query IN NATURAL LANGUAGE MODE) AS score "
            "FROM v2_knowledge_chunk c JOIN v2_knowledge_document d ON d.id=c.document_id "
            "LEFT JOIN v2_knowledge_section s ON s.id=c.parent_section_id "
            "WHERE d.status='PUBLISHED' AND "
            "(:is_admin=1 OR d.college_id IS NULL OR d.college_id=:college_id) "
            "AND (d.lab_id IS NULL OR EXISTS (SELECT 1 FROM lab l "
            "WHERE l.id=d.lab_id AND l.college_id=d.college_id)) "
            "AND (d.device_id IS NULL OR EXISTS (SELECT 1 FROM device dv "
            "WHERE dv.id=d.device_id AND dv.college_id=d.college_id "
            "AND (d.lab_id IS NULL OR dv.lab_id=d.lab_id))) "
            f"AND (:is_admin=1 OR ({allowed_role_sql})) "
            "AND c.version=COALESCE(d.active_version,d.version) "
            "AND MATCH(c.content) AGAINST (:query IN NATURAL LANGUAGE MODE) > 0 "
            "ORDER BY score DESC, c.id DESC LIMIT :candidate_limit"
        )
        rows = (
            (
                await session.execute(
                    statement,
                    parameters,
                )
            )
            .mappings()
            .all()
        )
        if rows:
            hits = [
                SearchHit(
                    point_id=str(row["point_id"]),
                    document_id=int(row["document_id"]),
                    title=str(row["title"]),
                    content=str(row["content"]),
                    score=float(row["score"] or 0),
                    source_type=str(row["source_type"]),
                    college_id=int(row["college_id"]) if row["college_id"] else None,
                    section=str(
                        row["section_path"]
                        or (row["metadata_json"] or {}).get("section_path")
                        or f"片段 {int(row['chunk_index']) + 1}"
                    ),
                    parent_section_id=(
                        int(row["parent_section_id"])
                        if row["parent_section_id"] is not None
                        else None
                    ),
                    parent_content=str(row["parent_content"] or ""),
                )
                for row in rows
                if document_role_visible(_decode_roles(row["allowed_roles"]), principal)
            ]
            if hits:
                return hits[:limit]
        # MySQL's default FULLTEXT parser is poor at Chinese. If it returns no
        # candidates, use a bounded prepared LIKE/substring fallback over the
        # domain-aware character bigrams produced below.

    tokens = _tokens(query)
    if not tokens:
        return []
    statement = base.where(or_(*(KnowledgeChunk.content.ilike(f"%{token}%") for token in tokens)))
    rows = list((await session.execute(statement.limit(min(limit * 3, 300)))).all())
    rows = [row for row in rows if document_role_visible(row[1].allowed_roles, principal)]

    def lexical_score(
        row: tuple[KnowledgeChunk, KnowledgeDocument, KnowledgeSection | None],
    ) -> int:
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
            section=str(
                (section.section_path if section is not None else None)
                or (chunk.metadata_json or {}).get("section_path")
                or f"片段 {chunk.chunk_index + 1}"
            ),
            parent_section_id=section.id if section is not None else None,
            parent_content=section.content if section is not None else "",
        )
        for chunk, document, section in sorted(
            rows,
            key=lambda row: (lexical_score(row), row[0].id),
            reverse=True,
        )[:limit]
    ]


async def hybrid_search(
    session: AsyncSession,
    store: QdrantKnowledgeStore,
    query: str,
    principal: Principal,
    limit: int,
    additional_queries: list[str] | None = None,
) -> list[SearchHit]:
    candidates = max(limit * 4, 12)
    variants: list[str] = []
    for candidate in [query, *(additional_queries or [])]:
        candidate = candidate.strip()[:500]
        if not candidate:
            continue
        for variant in await _query_variants(session, candidate, principal):
            if variant.casefold() not in {item.casefold() for item in variants}:
                variants.append(variant)
            if len(variants) >= 8:
                break
        if len(variants) >= 8:
            break
    # Resolve currently published versions and all SQL-side resource/role scope
    # before asking Qdrant. This keeps staged builds and out-of-scope documents
    # out of the vector candidate set; SQL is still rechecked after retrieval.
    active_rows = (
        await session.execute(
            select(
                KnowledgeDocument.id,
                func.coalesce(KnowledgeDocument.active_version, KnowledgeDocument.version),
                KnowledgeDocument.allowed_roles,
            ).where(KnowledgeDocument.status == "PUBLISHED", *document_scope_conditions(principal))
        )
    ).all()
    active_versions = {
        int(document_id): int(version)
        for document_id, version, allowed_roles in active_rows
        if document_role_visible(allowed_roles, principal)
    }
    dense_lanes: list[list[SearchHit]] = []
    sparse_lanes: list[list[SearchHit]] = []
    lexical_lanes: list[list[SearchHit]] = []
    visible_roles = None if principal.is_system_admin else principal.roles

    ensure_collection = getattr(store, "ensure_collection", None)
    if ensure_collection is not None:
        await ensure_collection()
    vector_semaphore = asyncio.Semaphore(
        max(1, int(getattr(getattr(store, "settings", None), "ai_rag_query_concurrency", 4)))
    )

    async def vector_search(variant: str, *, sparse: bool) -> list[SearchHit]:
        async with vector_semaphore:
            try:
                search_method = store.search_sparse if sparse else store.search
                return await search_method(
                    variant,
                    principal.college_id,
                    candidates,
                    cross_college=principal.is_system_admin,
                    allowed_roles=visible_roles,
                    active_versions=active_versions,
                )
            except Exception:
                # Vector retrieval is one lane of hybrid search. A temporary
                # failure degrades that lane while lexical retrieval continues.
                return []

    vector_results = await asyncio.gather(
        *(vector_search(variant, sparse=sparse) for variant in variants for sparse in (False, True))
    )
    for index in range(len(variants)):
        dense_lanes.append(vector_results[index * 2])
        sparse_lanes.append(vector_results[index * 2 + 1])

    for variant in variants:
        lexical_lanes.append(await _lexical_search(session, variant, principal, candidates))

    dense_hits = [hit for lane in dense_lanes for hit in lane]
    sparse_hits = [hit for lane in sparse_lanes for hit in lane]
    all_hits = [hit for lane in (*dense_lanes, *sparse_lanes, *lexical_lanes) for hit in lane]
    point_ids = list({hit.point_id for hit in all_hits})
    live_sources: dict[str, tuple[int | None, str, str]] = {}
    if point_ids:
        point_conditions = [
            KnowledgeChunk.point_id.in_(point_ids),
            KnowledgeDocument.status == "PUBLISHED",
            KnowledgeChunk.version
            == func.coalesce(KnowledgeDocument.active_version, KnowledgeDocument.version),
            *document_scope_conditions(principal),
        ]
        source_rows = (
            await session.execute(
                select(
                    KnowledgeChunk.point_id,
                    KnowledgeSection.id,
                    KnowledgeSection.section_path,
                    KnowledgeSection.content,
                    KnowledgeDocument.allowed_roles,
                )
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                .outerjoin(
                    KnowledgeSection,
                    KnowledgeSection.id == KnowledgeChunk.parent_section_id,
                )
                .where(*point_conditions)
            )
        ).all()
        live_sources = {
            str(point_id): (
                int(section_id) if section_id is not None else None,
                str(section_path or ""),
                str(parent_content or ""),
            )
            for point_id, section_id, section_path, parent_content, allowed_roles in source_rows
            if document_role_visible(allowed_roles, principal)
        }
    allowed_vector_ids = {hit.point_id for hit in dense_hits + sparse_hits} & set(live_sources)

    scores: dict[str, float] = {}
    by_id: dict[str, SearchHit] = {}
    ranked_lanes = [(lane, True) for lane in dense_lanes]
    ranked_lanes.extend((lane, True) for lane in sparse_lanes)
    ranked_lanes.extend((lane, False) for lane in lexical_lanes)
    for lane, vector_lane in ranked_lanes:
        for rank, hit in enumerate(lane, start=1):
            if vector_lane and hit.point_id not in allowed_vector_ids:
                continue
            live_source = live_sources.get(hit.point_id)
            if live_source is not None:
                parent_id, section_path, parent_content = live_source
                hit = replace(
                    hit,
                    section=section_path or hit.section,
                    parent_section_id=parent_id,
                    parent_content=parent_content,
                )
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
            parent_section_id=hit.parent_section_id,
            parent_content=hit.parent_content,
        )
        for point_id, _score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        for hit in [by_id[point_id]]
    ]
    return (await store.rerank(query, fused))[:limit]
