from types import SimpleNamespace

import pytest
from app.api.v2.catalog import (
    CollegeWriteRequest,
    LabWriteRequest,
    create_lab,
    list_labs,
    list_managers,
    update_college,
)
from app.auth.security import Principal
from app.core.errors import ApiError


def principal(user, *roles: str, college_id=None) -> Principal:
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=user.college_id if college_id is None else college_id,
        roles=roles,
        token_type="access",
        token_id=f"org-{user.id}",
    )


@pytest.mark.asyncio
async def test_system_admin_can_configure_college_lab_manager_and_scope(
    seeded,
    monkeypatch,
) -> None:
    factory, college, _, student, _, manager, _, _ = seeded

    async def no_op_cache_bump(_app, _college_id):
        return True

    monkeypatch.setattr("app.api.v2.catalog.sync_catalog_cache_bump", no_op_cache_bump)
    admin = principal(manager, "SYS_ADMIN", college_id=None)
    request = SimpleNamespace(app=SimpleNamespace())

    async with factory() as session:
        managers = await list_managers(college.id, admin, session)
        assert managers.data is not None
        assert [item.id for item in managers.data] == [manager.id]

        updated = await update_college(
            college.id,
            CollegeWriteRequest(code=college.code, name=college.name, manager_id=manager.id),
            request,
            admin,
            session,
        )
        assert updated.data is not None
        assert updated.data.manager_id == manager.id

        created = await create_lab(
            LabWriteRequest(
                college_id=college.id,
                name="新增材料实验室",
                location="南楼 201",
                manager_id=manager.id,
                description="用于组织配置回归测试",
            ),
            request,
            admin,
            session,
        )
        assert created.data is not None
        assert created.data.manager_id == manager.id

        labs = await list_labs(1, 100, admin, session)
        assert labs.data is not None
        assert any(row.name == "新增材料实验室" for row in labs.data["records"])

    # A student can still read business data through the normal scoped APIs,
    # but cannot change organization ownership.
    async with factory() as session:
        with pytest.raises(ApiError) as error:
            await update_college(
                college.id,
                CollegeWriteRequest(code=college.code, name=college.name, manager_id=manager.id),
                request,
                principal(student, "STUDENT"),
                session,
            )
        assert error.value.status_code == 403
