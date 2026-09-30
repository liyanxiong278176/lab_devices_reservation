"""Read-only list of QA-prefixed MySQL schemas/users; never outputs credentials."""

from __future__ import annotations

import sys

from mysql_admin import execute


def main() -> None:
    schemas = execute(
        "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
        "WHERE SCHEMA_NAME LIKE 'lab_reservation_qa_%';"
    )
    users = execute("SELECT User FROM mysql.user WHERE User LIKE 'qaeval_%';")
    print("QA-prefixed schemas and service accounts (names only):")
    print("Schemas:")
    print(schemas or "(none)")
    print("Accounts:")
    print(users or "(none)")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Read-only MySQL audit failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
