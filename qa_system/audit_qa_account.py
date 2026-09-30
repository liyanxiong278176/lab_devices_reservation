"""Read-only QA account metadata; never queries authentication hash columns."""

from __future__ import annotations

import json
from pathlib import Path

from mysql_admin import execute

ROOT = Path(__file__).resolve().parents[1]
STATE = json.loads((ROOT / "qa_system" / ".runtime-secrets.json").read_text(encoding="utf-8"))
USER = str(STATE["mysql_user"])


def main() -> None:
    print(execute(f"SELECT User,Host,plugin FROM mysql.user WHERE User='{USER}';"))
    print(execute(f"SHOW GRANTS FOR '{USER}'@'%';"))


if __name__ == "__main__":
    main()
