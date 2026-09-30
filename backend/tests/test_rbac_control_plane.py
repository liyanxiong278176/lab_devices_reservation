import pytest
from app.api.v2.rbac import _permissions_by_codes
from app.auth.security import Principal, get_current_principal
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_rbac_control_plane_cannot_be_delegated_to_a_custom_role(seeded) -> None:
    factory, _, _, student, *_ = seeded
    app = create_app(
        Settings(
            environment="test",
            cors_origins=[],
            enable_workers=False,
            rate_limit_enabled=False,
        )
    )

    async def override_db():
        async with factory() as session:
            yield session

    async def custom_role_with_rbac_code() -> Principal:
        return Principal(
            user_id=student.id,
            username=student.username,
            college_id=student.college_id,
            roles=("CUSTOM_OPERATOR",),
            token_type="access",
            token_id="custom-rbac-role-test",
            permissions=("rbac:manage",),
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = custom_role_with_rbac_code
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v2/rbac/roles")
            assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()

    async with factory() as session:
        for reserved_permission in ("rbac:manage", "user:manage", "organization:manage"):
            with pytest.raises(ApiError) as error:
                await _permissions_by_codes(session, [reserved_permission])
            assert error.value.code == "SYSTEM_PERMISSION_RESERVED"
