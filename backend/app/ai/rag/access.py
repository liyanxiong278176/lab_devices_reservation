from __future__ import annotations

from sqlalchemy import or_, select

from app.auth.security import Principal
from app.infrastructure.db.models import Device, KnowledgeDocument, Lab


def document_scope_conditions(principal: Principal):
    """SQL guards shared by RAG retrieval and the harness' final ACL check."""

    conditions = []
    if not principal.is_system_admin:
        if principal.college_id is None:
            conditions.append(KnowledgeDocument.college_id.is_(None))
        else:
            conditions.append(
                or_(
                    KnowledgeDocument.college_id.is_(None),
                    KnowledgeDocument.college_id == principal.college_id,
                )
            )

    valid_lab = (
        select(Lab.id)
        .where(
            Lab.id == KnowledgeDocument.lab_id,
            Lab.college_id == KnowledgeDocument.college_id,
        )
        .exists()
    )
    conditions.append(
        or_(KnowledgeDocument.lab_id.is_(None), valid_lab)
    )

    valid_device_conditions = [
        Device.id == KnowledgeDocument.device_id,
        Device.college_id == KnowledgeDocument.college_id,
        or_(KnowledgeDocument.lab_id.is_(None), Device.lab_id == KnowledgeDocument.lab_id),
    ]
    valid_device = select(Device.id).where(*valid_device_conditions).exists()
    conditions.append(
        or_(KnowledgeDocument.device_id.is_(None), valid_device)
    )
    return conditions


def document_role_visible(allowed_roles: object, principal: Principal) -> bool:
    """Empty scope is public within tenant; system admins can audit all scopes."""

    if principal.is_system_admin or allowed_roles is None:
        return True
    if not isinstance(allowed_roles, (list, tuple, set)):
        return False
    if not allowed_roles:
        return True
    return bool(set(str(role) for role in allowed_roles) & set(principal.roles))
