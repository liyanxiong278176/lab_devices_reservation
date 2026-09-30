"""Add permission-backed authorization and retire legacy refresh rows.

Revision ID: 0029_cookie_auth_rbac
Revises: 0028_maintenance_retests
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_cookie_auth_rbac"
down_revision: str | None = "0028_maintenance_retests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = (
    ("dashboard:read", "查看仪表盘", "dashboard", "查看当前角色范围内的运营概览"),
    ("device:read", "查看设备", "device", "浏览授权学院范围内的设备"),
    ("device:manage", "管理设备", "device", "新增、编辑和维护设备档案"),
    ("device:documents:manage", "管理设备文档", "device", "上传和归档设备文档"),
    ("reservation:create", "创建预约", "reservation", "提交设备预约申请"),
    ("reservation:read:own", "查看个人预约", "reservation", "查看本人预约"),
    ("reservation:read:scope", "查看范围内预约", "reservation", "查看所负责范围的预约"),
    ("reservation:cancel", "取消预约", "reservation", "取消本人可取消的预约"),
    ("reservation:check-in", "预约签到", "reservation", "为本人预约签到"),
    ("reservation:return", "提交归还", "reservation", "为本人预约提交归还"),
    ("reservation:approve", "审批预约", "reservation", "审批所负责范围内的预约"),
    ("reservation:handover", "办理设备交接", "reservation", "办理领用交接"),
    ("reservation:accept-return", "验收设备归还", "reservation", "验收所负责范围内的设备归还"),
    ("notification:read:own", "查看个人通知", "notification", "查看本人通知"),
    ("repair:create", "提交报修", "repair", "提交设备故障报修"),
    ("repair:read:own", "查看个人报修", "repair", "查看本人报修工单"),
    ("repair:read:scope", "查看范围内报修", "repair", "查看所负责范围内的报修"),
    ("repair:handle", "处理报修", "repair", "受理并处理所负责范围内的报修"),
    ("repair:confirm", "确认报修结果", "repair", "确认本人报修的处理结果"),
    ("report:read", "查看运营报表", "report", "查看授权范围内的统计报表"),
    ("reservation-rule:manage", "管理预约规则", "reservation", "维护授权范围内的预约规则"),
    ("maintenance:manage", "管理设备维护", "maintenance", "维护校准计划和维护记录"),
    ("feedback:create", "提交设备评价", "feedback", "评价本人已完成的预约"),
    ("feedback:read:own", "查看个人评价", "feedback", "查看本人提交的设备评价"),
    ("feedback:read:scope", "查看范围内评价", "feedback", "查看所负责范围内的评价"),
    ("organization:manage", "管理组织", "organization", "管理学院、实验室及负责人"),
    ("organization:read", "查看组织", "organization", "查看授权范围内的学院和实验室"),
    ("user:manage", "管理用户", "user", "管理系统账号和角色分配"),
    ("rbac:manage", "管理角色权限", "rbac", "配置角色和角色权限"),
    ("ai:use", "使用 AI 工作台", "ai", "使用当前账号权限范围内的 AI 功能"),
    ("ai:knowledge:manage", "管理知识库", "ai", "维护授权范围内的知识库"),
    ("ai:usage:read:scope", "查看 AI 用量", "ai", "查看本人或授权范围内的 AI 用量"),
)

STUDENT_PERMISSIONS = (
    "dashboard:read",
    "device:read",
    "reservation:create",
    "reservation:read:own",
    "reservation:cancel",
    "reservation:check-in",
    "reservation:return",
    "notification:read:own",
    "repair:create",
    "repair:read:own",
    "repair:confirm",
    "feedback:create",
    "feedback:read:own",
    "ai:use",
)

LAB_ADMIN_PERMISSIONS = (
    "dashboard:read",
    "device:read",
    "device:manage",
    "device:documents:manage",
    "reservation:read:scope",
    "reservation:approve",
    "reservation:handover",
    "reservation:accept-return",
    "notification:read:own",
    "repair:read:scope",
    "repair:handle",
    "report:read",
    "reservation-rule:manage",
    "maintenance:manage",
    "feedback:read:scope",
    "organization:read",
    "ai:use",
    "ai:knowledge:manage",
    "ai:usage:read:scope",
)


def upgrade() -> None:
    op.add_column(
        "sys_role",
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        sa.text(
            "UPDATE sys_role SET is_system = 1 "
            "WHERE role_code IN ('STUDENT', 'LAB_ADMIN', 'SYS_ADMIN')"
        )
    )
    op.create_table(
        "sys_permission",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("permission_code", sa.String(length=100), nullable=False),
        sa.Column("permission_name", sa.String(length=100), nullable=False),
        sa.Column("module", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sys_permission_permission_code", "sys_permission", ["permission_code"], unique=True
    )
    op.create_index("ix_sys_permission_module", "sys_permission", ["module"])
    op.create_table(
        "sys_role_permission",
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("permission_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["permission_id"], ["sys_permission.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["sys_role.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )
    op.create_table(
        "v2_authz_version",
        # This is a singleton row whose primary key is always explicitly 1.
        # MySQL cannot reference an AUTO_INCREMENT column from a CHECK constraint.
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_v2_authz_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(sa.text("INSERT INTO v2_authz_version (id, version) VALUES (1, 1)"))

    permission_table = sa.table(
        "sys_permission",
        sa.column("permission_code", sa.String),
        sa.column("permission_name", sa.String),
        sa.column("module", sa.String),
        sa.column("description", sa.String),
    )
    op.bulk_insert(
        permission_table,
        [
            {
                "permission_code": code,
                "permission_name": name,
                "module": module,
                "description": description,
            }
            for code, name, module, description in PERMISSIONS
        ],
    )

    def assign(role_code: str, permission_codes: Sequence[str] | None = None) -> None:
        if permission_codes is None:
            predicate = "1 = 1"
        else:
            quoted = ", ".join(f"'{code}'" for code in permission_codes)
            predicate = f"p.permission_code IN ({quoted})"
        op.execute(
            sa.text(
                "INSERT INTO sys_role_permission (role_id, permission_id) "
                "SELECT r.id, p.id FROM sys_role r CROSS JOIN sys_permission p "
                f"WHERE r.role_code = '{role_code}' AND {predicate}"
            )
        )

    assign("STUDENT", STUDENT_PERMISSIONS)
    assign("LAB_ADMIN", LAB_ADMIN_PERMISSIONS)
    assign("SYS_ADMIN")

    # Old DB-backed refresh families are not accepted by the new cookie session
    # flow. Revoke them during the one-time authentication cutover.
    op.execute(
        sa.text(
            "UPDATE v2_refresh_session SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)"
        )
    )


def downgrade() -> None:
    op.drop_table("v2_authz_version")
    op.drop_table("sys_role_permission")
    op.drop_index("ix_sys_permission_module", table_name="sys_permission")
    op.drop_index("ix_sys_permission_permission_code", table_name="sys_permission")
    op.drop_table("sys_permission")
    op.drop_column("sys_role", "is_system")
