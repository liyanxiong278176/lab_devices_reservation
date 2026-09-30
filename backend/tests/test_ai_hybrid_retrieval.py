import asyncio

import pytest
from app.ai.graph.harness import AgentHarness
from app.ai.rag.hybrid import _query_variants, hybrid_search
from app.ai.rag.qdrant_store import SearchHit
from app.auth.security import Principal
from app.infrastructure.db.models import (
    AiDomainTerm,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSection,
    Lab,
)


class StubStore:
    def __init__(self, hits: dict[str, list[SearchHit]]) -> None:
        self.hits = hits
        self.queries: list[str] = []
        self.role_filters: list[tuple[str, ...] | None] = []
        self.active_version_filters: list[dict[int, int] | None] = []

    async def search(
        self,
        query,
        college_id,
        limit=None,
        *,
        cross_college=False,
        allowed_roles=None,
        active_versions=None,
    ):
        self.queries.append(query)
        self.role_filters.append(tuple(allowed_roles) if allowed_roles is not None else None)
        self.active_version_filters.append(active_versions)
        return self.hits.get(query, [])

    async def search_sparse(
        self,
        query,
        college_id,
        limit=None,
        *,
        cross_college=False,
        allowed_roles=None,
        active_versions=None,
    ):
        self.role_filters.append(tuple(allowed_roles) if allowed_roles is not None else None)
        self.active_version_filters.append(active_versions)
        return self.hits.get(f"sparse:{query}", [])

    async def rerank(self, query, hits):
        return hits


@pytest.mark.asyncio
async def test_hybrid_retrieval_expands_terms_and_rechecks_live_tenant_scope(seeded) -> None:
    factory, college, other_college, user, _, *_ = seeded
    principal = Principal(
        user_id=user.id,
        username=user.username,
        college_id=college.id,
        roles=("STUDENT",),
        token_type="access",
        token_id="hybrid-retrieval-test",
        permissions=("ai:use", "device:read"),
    )
    async with factory() as session:
        own_document = KnowledgeDocument(
            college_id=college.id,
            title="电子显微镜预约说明",
            source_type="SOP",
            body="预约说明正文",
            version=1,
            status="PUBLISHED",
            created_by=user.id,
            checksum="a" * 64,
        )
        other_document = KnowledgeDocument(
            college_id=other_college.id,
            title="外学院说明",
            source_type="SOP",
            body="禁止跨学院读取",
            version=1,
            status="PUBLISHED",
            created_by=user.id,
            checksum="b" * 64,
        )
        restricted_document = KnowledgeDocument(
            college_id=college.id,
            title="负责人操作手册",
            source_type="SOP",
            body="仅负责人可以查阅这份操作说明。",
            version=1,
            status="PUBLISHED",
            created_by=user.id,
            checksum="c" * 64,
            allowed_roles=["LAB_ADMIN"],
        )
        wrong_lab = Lab(name="错误学院实验室", college_id=other_college.id)
        session.add_all([own_document, other_document, restricted_document, wrong_lab])
        await session.flush()
        wrong_scope_document = KnowledgeDocument(
            college_id=college.id,
            lab_id=wrong_lab.id,
            title="资源范围异常文档",
            source_type="SOP",
            body="该实验室并不属于文档所属学院。",
            version=1,
            status="PUBLISHED",
            created_by=user.id,
            checksum="d" * 64,
        )
        session.add(wrong_scope_document)
        await session.flush()
        own_section = KnowledgeSection(
            document_id=own_document.id,
            section_index=0,
            heading="预约要求",
            section_path="实验室安全 / 预约要求",
            content="预约前需要完成安全培训，并查看设备空闲日期。",
        )
        other_section = KnowledgeSection(
            document_id=other_document.id,
            section_index=0,
            heading="机密",
            section_path="机密",
            content="不得泄露给其他学院。",
        )
        restricted_section = KnowledgeSection(
            document_id=restricted_document.id,
            section_index=0,
            heading="负责人",
            section_path="负责人 / 操作",
            content="仅负责人可以查阅这份操作说明。",
        )
        wrong_scope_section = KnowledgeSection(
            document_id=wrong_scope_document.id,
            section_index=0,
            heading="实验室范围",
            section_path="实验室范围",
            content="该实验室并不属于文档所属学院。",
        )
        session.add_all([own_section, other_section, restricted_section, wrong_scope_section])
        await session.flush()
        session.add_all(
            [
                KnowledgeChunk(
                    document_id=own_document.id,
                    college_id=college.id,
                    point_id="own-point",
                    chunk_index=0,
                    content="预约前需要完成安全培训。",
                    metadata_json={"section_path": own_section.section_path},
                    parent_section_id=own_section.id,
                ),
                KnowledgeChunk(
                    document_id=other_document.id,
                    college_id=other_college.id,
                    point_id="foreign-point",
                    chunk_index=0,
                    content="不得泄露给其他学院。",
                    metadata_json={"section_path": other_section.section_path},
                    parent_section_id=other_section.id,
                ),
                KnowledgeChunk(
                    document_id=restricted_document.id,
                    college_id=college.id,
                    point_id="role-point",
                    chunk_index=0,
                    content="仅负责人可以查阅这份操作说明。",
                    metadata_json={"section_path": restricted_section.section_path},
                    parent_section_id=restricted_section.id,
                ),
                KnowledgeChunk(
                    document_id=wrong_scope_document.id,
                    college_id=college.id,
                    point_id="wrong-resource-point",
                    chunk_index=0,
                    content="该实验室并不属于文档所属学院。",
                    metadata_json={"section_path": wrong_scope_section.section_path},
                    parent_section_id=wrong_scope_section.id,
                ),
            ]
        )
        session.add_all(
            [
                AiDomainTerm(
                    college_id=college.id,
                    term="请问",
                    canonical=None,
                    kind="IGNORE",
                    status="APPROVED",
                    created_by=user.id,
                ),
                AiDomainTerm(
                    college_id=college.id,
                    term="电镜",
                    canonical="电子显微镜",
                    kind="SYNONYM",
                    status="APPROVED",
                    created_by=user.id,
                ),
            ]
        )
        await session.commit()

        variants = await _query_variants(session, "请问电镜预约", principal)
        own_hit = SearchHit(
            "own-point",
            own_document.id,
            own_document.title,
            "预约前需要完成安全培训。",
            0.9,
            "SOP",
            college.id,
        )
        foreign_hit = SearchHit(
            "foreign-point",
            other_document.id,
            other_document.title,
            "不得泄露给其他学院。",
            0.99,
            "SOP",
            other_college.id,
        )
        role_hit = SearchHit(
            "role-point",
            restricted_document.id,
            restricted_document.title,
            "仅负责人可以查阅这份操作说明。",
            0.98,
            "SOP",
            college.id,
        )
        wrong_scope_hit = SearchHit(
            "wrong-resource-point",
            wrong_scope_document.id,
            wrong_scope_document.title,
            "该实验室并不属于文档所属学院。",
            0.97,
            "SOP",
            college.id,
        )
        store = StubStore(
            {
                "请问电镜预约": [own_hit, foreign_hit, role_hit, wrong_scope_hit],
                "电镜预约": [own_hit],
                "电子显微镜预约": [own_hit],
                "sparse:电子显微镜预约": [own_hit],
            }
        )
        results = await hybrid_search(
            session,
            store,
            "请问电镜预约",
            principal,
            5,
            additional_queries=["电镜怎么预约"],
        )

    assert variants == ["请问电镜预约", "电镜预约", "电子显微镜预约"]
    assert "电镜怎么预约" in store.queries
    assert "请问电镜预约" in store.queries
    assert "电子显微镜预约" in store.queries
    assert store.role_filters and set(store.role_filters) == {("STUDENT",)}
    assert store.active_version_filters
    assert all(own_document.id in (versions or {}) for versions in store.active_version_filters)
    assert [hit.point_id for hit in results] == ["own-point"]
    assert results[0].section == "实验室安全 / 预约要求"
    assert "设备空闲日期" in results[0].parent_content


@pytest.mark.asyncio
async def test_harness_final_acl_rechecks_document_role_and_resource_scope(seeded) -> None:
    factory, college, other_college, user, _, _, *_ = seeded
    principal = Principal(
        user_id=user.id,
        username=user.username,
        college_id=college.id,
        roles=("STUDENT",),
        token_type="access",
        token_id="harness-acl-test",
        permissions=("ai:use",),
    )
    async with factory() as session:
        allowed = KnowledgeDocument(
            college_id=college.id,
            title="本学院公开文档",
            source_type="FAQ",
            body="公开内容足够长。",
            version=1,
            status="PUBLISHED",
            created_by=user.id,
            checksum="e" * 64,
        )
        denied_role = KnowledgeDocument(
            college_id=college.id,
            title="负责人文档",
            source_type="FAQ",
            body="负责人限定内容足够长。",
            version=1,
            status="PUBLISHED",
            created_by=user.id,
            checksum="f" * 64,
            allowed_roles=["LAB_ADMIN"],
        )
        invalid_lab = Lab(name="异院实验室", college_id=other_college.id)
        session.add_all([allowed, denied_role, invalid_lab])
        await session.flush()
        invalid_resource = KnowledgeDocument(
            college_id=college.id,
            lab_id=invalid_lab.id,
            title="资源隔离文档",
            source_type="FAQ",
            body="无效资源内容足够长。",
            version=1,
            status="PUBLISHED",
            created_by=user.id,
            checksum="1" * 64,
        )
        session.add(invalid_resource)
        await session.commit()
        harness = object.__new__(AgentHarness)
        harness.session = session
        harness.principal = principal

        authorized = await harness._authorized_document_ids(
            [allowed.id, denied_role.id, invalid_resource.id]
        )

    assert authorized == {allowed.id}


@pytest.mark.asyncio
async def test_hybrid_search_runs_independent_vector_lanes_concurrently(seeded) -> None:
    factory, college, _, user, _, *_ = seeded
    principal = Principal(
        user_id=user.id,
        username=user.username,
        college_id=college.id,
        roles=("STUDENT",),
        token_type="access",
        token_id="hybrid-concurrency-test",
        permissions=("ai:use",),
    )

    class DelayedStore(StubStore):
        def __init__(self) -> None:
            super().__init__({})
            self.active = 0
            self.maximum_active = 0

        async def _delayed(self):
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            await asyncio.sleep(0.05)
            self.active -= 1
            return []

        async def search(self, *args, **kwargs):
            return await self._delayed()

        async def search_sparse(self, *args, **kwargs):
            return await self._delayed()

    store = DelayedStore()
    async with factory() as session:
        await hybrid_search(session, store, "电镜预约", principal, 3)

    assert store.maximum_active == 2
