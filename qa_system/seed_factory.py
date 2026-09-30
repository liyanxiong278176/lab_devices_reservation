"""Create uniquely named fixture rows and remove only recorded identifiers."""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa_system"
BACKEND = ROOT / "backend"
PRIVATE_STATE = QA / ".runtime-secrets.json"
ID_FILE = QA / "results" / "seed_ids.json"
ACCOUNTS_FILE = QA / "results" / "accounts.local.json"
sys.path.insert(0, str(BACKEND))


def load_state() -> dict[str, object]:
    if not PRIVATE_STATE.exists():
        raise RuntimeError("Run prepare_runtime.py before creating data")
    return json.loads(PRIVATE_STATE.read_text(encoding="utf-8"))


def record_created(table: str, identifier: int) -> None:
    current = json.loads(ID_FILE.read_text(encoding="utf-8")) if ID_FILE.exists() else {}
    values = set(int(item) for item in current.get(table, []))
    values.add(int(identifier))
    current[table] = sorted(values)
    ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    ID_FILE.write_text(json.dumps(current, indent=2), encoding="utf-8")


async def seed() -> None:
    from app.auth.security import hash_password
    from app.infrastructure.db.models import College, Device, Lab, Role, User

    state = load_state()
    suffix = str(state["suffix"])
    prefix = f"QAEVAL_{suffix}"
    password = secrets.token_urlsafe(20)
    engine = create_async_engine(str(state["mysql_dsn"]), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session, session.begin():
            roles = {
                role.role_code: role
                for role in (
                    await session.scalars(
                        select(Role).where(
                            Role.role_code.in_(["STUDENT", "LAB_ADMIN", "SYS_ADMIN"])
                        )
                    )
                ).all()
            }
            if "STUDENT" not in roles or "LAB_ADMIN" not in roles or "SYS_ADMIN" not in roles:
                raise RuntimeError("required default role rows are missing in the isolated schema")

            college_a = College(code=f"{prefix}_A", name=f"{prefix} College A", status=1)
            college_b = College(code=f"{prefix}_B", name=f"{prefix} College B", status=1)
            session.add_all([college_a, college_b])
            await session.flush()
            lab_a = Lab(
                college_id=college_a.id, name=f"{prefix} Lab A", location="QA location", status=1
            )
            lab_b = Lab(
                college_id=college_b.id, name=f"{prefix} Lab B", location="QA location", status=1
            )
            session.add_all([lab_a, lab_b])
            await session.flush()

            student_a = User(
                username=f"{prefix.lower()}_student_a",
                password_hash=hash_password(password),
                real_name=f"{prefix} Student A",
                user_type="STUDENT",
                college_id=college_a.id,
                status=1,
                roles=[roles["STUDENT"]],
            )
            student_b = User(
                username=f"{prefix.lower()}_student_b",
                password_hash=hash_password(password),
                real_name=f"{prefix} Student B",
                user_type="STUDENT",
                college_id=college_b.id,
                status=1,
                roles=[roles["STUDENT"]],
            )
            manager_a = User(
                username=f"{prefix.lower()}_manager_a",
                password_hash=hash_password(password),
                real_name=f"{prefix} Manager A",
                user_type="STAFF",
                college_id=college_a.id,
                status=1,
                roles=[roles["LAB_ADMIN"]],
            )
            session.add_all([student_a, student_b, manager_a])
            await session.flush()
            college_a.manager_id = manager_a.id
            lab_a.manager_id = manager_a.id

            device_a = Device(
                college_id=college_a.id,
                lab_id=lab_a.id,
                name=f"{prefix} approval device",
                brand="QAEVAL",
                model="QA-1",
                status="IDLE",
                need_approval=True,
                max_reservation_days=8,
                asset_code=f"{prefix}-ASSET-A",
                tags=["qaeval", "approval"],
                accessory_checklist=["case"],
            )
            device_b = Device(
                college_id=college_b.id,
                lab_id=lab_b.id,
                name=f"{prefix} direct device",
                brand="QAEVAL",
                model="QA-2",
                status="IDLE",
                need_approval=False,
                max_reservation_days=8,
                asset_code=f"{prefix}-ASSET-B",
                tags=["qaeval", "direct"],
                accessory_checklist=["case"],
            )
            session.add_all([device_a, device_b])
            await session.flush()
            ids = {
                "prefix": prefix,
                "college": [college_a.id, college_b.id],
                "lab": [lab_a.id, lab_b.id],
                "user": [student_a.id, student_b.id, manager_a.id],
                "device": [device_a.id, device_b.id],
            }
            ID_FILE.write_text(json.dumps(ids, indent=2), encoding="utf-8")
            accounts = {
                "admin": {"username": state["admin_username"], "password": state["admin_password"]},
                "student_a": {"username": student_a.username, "password": password},
                "student_b": {"username": student_b.username, "password": password},
                "manager_a": {"username": manager_a.username, "password": password},
            }
            ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2), encoding="utf-8")
    finally:
        await engine.dispose()


async def cleanup_recorded_rows() -> dict[str, int]:
    """Delete fixture roots and all rows linked to their exact recorded IDs."""

    from app.infrastructure.db.base import Base
    from app.infrastructure.db.models import College, Device, Lab, User

    state = load_state()
    if not ID_FILE.exists():
        return {}
    identifiers = json.loads(ID_FILE.read_text(encoding="utf-8"))
    target_ids = {
        "college": set(map(int, identifiers.get("college", []))),
        "lab": set(map(int, identifiers.get("lab", []))),
        "sys_user": set(map(int, identifiers.get("user", []))),
        "device": set(map(int, identifiers.get("device", []))),
    }
    for table_name, ids in identifiers.items():
        if table_name not in {"college", "lab", "user", "device", "prefix"}:
            target_ids[f"__pk__:{table_name}"] = set(map(int, ids))
    engine = create_async_engine(str(state["mysql_dsn"]), pool_pre_ping=True)
    deleted: dict[str, int] = defaultdict(int)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
            for table in reversed(list(Base.metadata.tables.values())):
                predicates = []
                primary_ids = target_ids.get(f"__pk__:{table.name}", set())
                if primary_ids and "id" in table.c:
                    predicates.append(table.c.id.in_(primary_ids))
                for column in table.c:
                    for foreign_key in column.foreign_keys:
                        referenced = foreign_key.column.table.name
                        values = target_ids.get(referenced, set())
                        if values:
                            predicates.append(column.in_(values))
                if predicates:
                    result = await connection.execute(delete(table).where(or_(*predicates)))
                    deleted[table.name] += max(result.rowcount or 0, 0)
            # The root rows have no incoming references after FK checks are disabled.
            for model, ids in (
                (Device, target_ids["device"]),
                (User, target_ids["sys_user"]),
                (Lab, target_ids["lab"]),
                (College, target_ids["college"]),
            ):
                if ids:
                    result = await connection.execute(delete(model).where(model.id.in_(ids)))
                    deleted[model.__tablename__] += max(result.rowcount or 0, 0)
            await connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")
    finally:
        await engine.dispose()
    return dict(deleted)


async def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--clean-recorded":
        print(json.dumps(await cleanup_recorded_rows(), sort_keys=True))
        return
    await seed()
    print("Created QAEVAL fixtures; exact identifiers are in qa_system/results/seed_ids.json")


if __name__ == "__main__":
    asyncio.run(main())
