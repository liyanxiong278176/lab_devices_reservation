import os
import secrets

import pytest
from app.ai.rag.access import document_role_visible
from app.ai.rag.hybrid import _lexical_search
from app.ai.rag.qdrant_store import QdrantKnowledgeStore
from app.auth.security import Principal
from app.core.settings import Settings
from app.infrastructure.db.models import College, KnowledgeChunk, KnowledgeDocument, Lab, User
from app.infrastructure.db.session import build_engine, build_session_factory
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from sqlalchemy import delete, select


def test_qdrant_filter_allows_matching_role_and_unrestricted_documents() -> None:
    query_filter = QdrantKnowledgeStore._scope_filter(
        7,
        cross_college=False,
        allowed_roles=("STUDENT",),
    )

    assert query_filter is not None
    serialized = query_filter.model_dump_json(exclude_none=True)
    assert "college_id" in serialized
    assert "STUDENT" in serialized
    assert "allowed_roles" in serialized
    assert "is_empty" in serialized


def test_qdrant_filter_with_no_roles_only_returns_unrestricted_documents() -> None:
    query_filter = QdrantKnowledgeStore._scope_filter(
        7,
        cross_college=True,
        allowed_roles=(),
    )

    assert query_filter is not None
    serialized = query_filter.model_dump_json(exclude_none=True)
    assert "allowed_roles" in serialized
    assert "is_empty" in serialized
    assert "STUDENT" not in serialized


def test_system_admin_can_query_all_role_scopes() -> None:
    assert (
        QdrantKnowledgeStore._scope_filter(
            None,
            cross_college=True,
            allowed_roles=None,
        )
        is None
    )


def test_malformed_role_scope_fails_closed() -> None:
    student = Principal(
        user_id=1,
        username="acl-test",
        college_id=7,
        roles=("STUDENT",),
        token_type="access",
        token_id="malformed-role-scope-test",
    )
    assert document_role_visible(None, student)
    assert document_role_visible([], student)
    assert not document_role_visible("not-json", student)


@pytest.mark.asyncio
async def test_live_qdrant_role_and_tenant_prefilter() -> None:
    if os.getenv("LAB_RUN_QDRANT_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_QDRANT_INTEGRATION=1 to use the configured Qdrant")

    settings = Settings()
    collection = f"ai_acl_probe_{secrets.token_hex(6)}"
    client = AsyncQdrantClient(
        url=settings.qdrant_url,
        timeout=settings.ai_qdrant_timeout_seconds,
        check_compatibility=False,
    )
    try:
        await client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(
                size=settings.ai_embedding_dimension,
                distance=models.Distance.COSINE,
            ),
        )
        vector = [1.0] + [0.0] * (settings.ai_embedding_dimension - 1)
        await client.upsert(
            collection_name=collection,
            wait=True,
            points=[
                models.PointStruct(
                    id="00000000-0000-4000-8000-000000000011",
                    vector=vector,
                    payload={"college_id": 11, "allowed_roles": ["STUDENT"]},
                ),
                models.PointStruct(
                    id="00000000-0000-4000-8000-000000000012",
                    vector=vector,
                    payload={"college_id": 11, "allowed_roles": ["LAB_ADMIN"]},
                ),
                models.PointStruct(
                    id="00000000-0000-4000-8000-000000000022",
                    vector=vector,
                    payload={"college_id": 22, "allowed_roles": ["STUDENT"]},
                ),
                models.PointStruct(
                    id="00000000-0000-4000-8000-000000000099",
                    vector=vector,
                    payload={"college_id": 0},
                ),
            ],
        )

        async def visible_ids(*, college_id: int | None, roles: tuple[str, ...] | None):
            result = await client.query_points(
                collection_name=collection,
                query=vector,
                query_filter=QdrantKnowledgeStore._scope_filter(
                    college_id,
                    cross_college=college_id is None,
                    allowed_roles=roles,
                ),
                limit=10,
                with_payload=True,
            )
            return {str(point.id) for point in result.points}

        assert await visible_ids(college_id=11, roles=("STUDENT",)) == {
            "00000000-0000-4000-8000-000000000011",
            "00000000-0000-4000-8000-000000000099",
        }
        assert await visible_ids(college_id=11, roles=("LAB_ADMIN",)) == {
            "00000000-0000-4000-8000-000000000012",
            "00000000-0000-4000-8000-000000000099",
        }
        assert await visible_ids(college_id=None, roles=None) == {
            "00000000-0000-4000-8000-000000000011",
            "00000000-0000-4000-8000-000000000012",
            "00000000-0000-4000-8000-000000000022",
            "00000000-0000-4000-8000-000000000099",
        }
    finally:
        if await client.collection_exists(collection):
            await client.delete_collection(collection_name=collection)
        await client.close()


@pytest.mark.asyncio
async def test_live_mysql_lexical_acl_filters_roles_and_resource_tenant() -> None:
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to use the configured MySQL")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("this test verifies the MySQL FULLTEXT and JSON ACL query path")

    engine = build_engine(settings)
    factory = build_session_factory(engine)
    token = f"aiaclverify{secrets.token_hex(8)}"
    test_lab_id: int | None = None
    try:
        async with factory() as session:
            college_ids = list(
                (
                    await session.scalars(
                        select(College.id).order_by(College.id).limit(2)
                    )
                ).all()
            )
            user_id = await session.scalar(select(User.id).order_by(User.id).limit(1))
            if len(college_ids) < 2 or user_id is None:
                pytest.skip("MySQL integration requires two Colleges and one User")
            own_college, other_college = college_ids
            foreign_lab = Lab(
                college_id=other_college,
                name=token[:40],
                status=1,
            )
            session.add(foreign_lab)
            await session.flush()
            test_lab_id = foreign_lab.id
            documents = [
                KnowledgeDocument(
                    college_id=own_college,
                    title=f"{token} student",
                    source_type="FAQ",
                    body=token,
                    version=1,
                    status="PUBLISHED",
                    created_by=user_id,
                    checksum=secrets.token_hex(32),
                    allowed_roles=["STUDENT"],
                ),
                KnowledgeDocument(
                    college_id=own_college,
                    title=f"{token} manager",
                    source_type="FAQ",
                    body=token,
                    version=1,
                    status="PUBLISHED",
                    created_by=user_id,
                    checksum=secrets.token_hex(32),
                    allowed_roles=["LAB_ADMIN"],
                ),
                KnowledgeDocument(
                    college_id=own_college,
                    title=f"{token} unrestricted",
                    source_type="FAQ",
                    body=token,
                    version=1,
                    status="PUBLISHED",
                    created_by=user_id,
                    checksum=secrets.token_hex(32),
                ),
                KnowledgeDocument(
                    college_id=other_college,
                    title=f"{token} foreign college",
                    source_type="FAQ",
                    body=token,
                    version=1,
                    status="PUBLISHED",
                    created_by=user_id,
                    checksum=secrets.token_hex(32),
                    allowed_roles=["STUDENT"],
                ),
                KnowledgeDocument(
                    college_id=own_college,
                    lab_id=test_lab_id,
                    title=f"{token} foreign lab",
                    source_type="FAQ",
                    body=token,
                    version=1,
                    status="PUBLISHED",
                    created_by=user_id,
                    checksum=secrets.token_hex(32),
                    allowed_roles=["STUDENT"],
                ),
            ]
            session.add_all(documents)
            await session.flush()
            expected_allowed_ids = {documents[0].id, documents[2].id}
            session.add_all(
                [
                    KnowledgeChunk(
                        document_id=document.id,
                        college_id=document.college_id,
                        point_id=f"mysql-acl-{token}-{index}",
                        chunk_index=0,
                        content=f"{token} 实验室预约权限隔离验证内容",
                    )
                    for index, document in enumerate(documents)
                ]
            )
            await session.commit()

            principal = Principal(
                user_id=user_id,
                username="mysql-acl-test",
                college_id=own_college,
                roles=("STUDENT",),
                token_type="access",
                token_id="mysql-lexical-acl-test",
                permissions=("ai:use",),
            )
            hits = await _lexical_search(session, token, principal, limit=20)
            assert {hit.document_id for hit in hits} == expected_allowed_ids
    finally:
        async with factory() as cleanup_session:
            cleanup_ids = list(
                (
                    await cleanup_session.scalars(
                        select(KnowledgeDocument.id).where(
                            KnowledgeDocument.title.like(f"{token}%")
                        )
                    )
                ).all()
            )
            if cleanup_ids:
                await cleanup_session.execute(
                    delete(KnowledgeChunk).where(
                        KnowledgeChunk.document_id.in_(cleanup_ids)
                    )
                )
                await cleanup_session.execute(
                    delete(KnowledgeDocument).where(
                        KnowledgeDocument.id.in_(cleanup_ids)
                    )
                )
            await cleanup_session.execute(delete(Lab).where(Lab.name == token[:40]))
            await cleanup_session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_knowledge_scope_rejects_wrong_college_resource_and_unknown_role(seeded) -> None:
    from app.api.v2.ai import _validate_knowledge_scope
    from app.core.errors import ApiError

    factory, college, _other_college, _user, _other_user, _manager, device, other_device = seeded
    async with factory() as session:
        roles = await _validate_knowledge_scope(
            session,
            college_id=college.id,
            lab_id=device.lab_id,
            device_id=device.id,
            allowed_roles=[" student ", "STUDENT"],
        )
        assert roles == ["STUDENT"]

        with pytest.raises(ApiError) as wrong_device:
            await _validate_knowledge_scope(
                session,
                college_id=college.id,
                lab_id=None,
                device_id=other_device.id,
                allowed_roles=[],
            )
        assert wrong_device.value.code == "KNOWLEDGE_SCOPE_INVALID"

        with pytest.raises(ApiError) as wrong_role:
            await _validate_knowledge_scope(
                session,
                college_id=college.id,
                lab_id=None,
                device_id=None,
                allowed_roles=["NON_EXISTENT_ROLE"],
            )
        assert wrong_role.value.code == "KNOWLEDGE_SCOPE_INVALID"

        with pytest.raises(ApiError) as global_resource:
            await _validate_knowledge_scope(
                session,
                college_id=None,
                lab_id=None,
                device_id=other_device.id,
                allowed_roles=[],
            )
        assert global_resource.value.code == "KNOWLEDGE_SCOPE_INVALID"


@pytest.mark.asyncio
async def test_knowledge_scope_role_options_include_custom_roles_for_managers(seeded) -> None:
    from app.api.v2.ai import list_knowledge_scope_roles
    from app.auth.security import Principal
    from app.infrastructure.db.models import Role

    factory, _college, _other_college, _user, _other_user, manager, *_ = seeded
    principal = Principal(
        user_id=manager.id,
        username=manager.username,
        college_id=manager.college_id,
        roles=("LAB_ADMIN",),
        token_type="access",
        token_id="knowledge-scope-role-options",
        permissions=("ai:use",),
    )
    async with factory() as session:
        session.add(Role(role_code="SAFETY_AUDITOR", role_name="安全审核员"))
        await session.flush()

        response = await list_knowledge_scope_roles(principal=principal, session=session)

    assert {role.code for role in response.data} >= {"STUDENT", "LAB_ADMIN", "SAFETY_AUDITOR"}


@pytest.mark.asyncio
async def test_knowledge_citation_hides_role_restricted_document_from_student(seeded) -> None:
    from app.api.v2.ai import get_knowledge_citation
    from app.auth.security import Principal
    from app.core.errors import ApiError
    from app.infrastructure.db.models import KnowledgeChunk, KnowledgeDocument

    factory, college, _other_college, user, *_ = seeded
    principal = Principal(
        user_id=user.id,
        username=user.username,
        college_id=college.id,
        roles=("STUDENT",),
        token_type="access",
        token_id="citation-role-acl-test",
        permissions=("ai:use",),
    )
    async with factory() as session:
        document = KnowledgeDocument(
            college_id=college.id,
            title="负责人专属资料",
            source_type="SOP",
            body="仅负责人可以查看。",
            version=1,
            status="PUBLISHED",
            created_by=user.id,
            checksum="a" * 64,
            allowed_roles=["LAB_ADMIN"],
        )
        session.add(document)
        await session.flush()
        session.add(
            KnowledgeChunk(
                document_id=document.id,
                college_id=college.id,
                point_id="role-private-citation",
                chunk_index=0,
                content="仅负责人可以查看。",
            )
        )
        await session.commit()

        with pytest.raises(ApiError) as denied:
            await get_knowledge_citation("role-private-citation", principal, session)

    assert denied.value.status_code == 404
