"""Use local MySQL container admin credentials in memory, without logging them."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def _secret_candidates() -> list[str]:
    candidates: list[str] = []
    docker = shutil.which("docker")
    if docker:
        inspected = subprocess.run(
            [
                docker,
                "inspect",
                "--format",
                "{{range .Config.Env}}{{println .}}{{end}}",
                "lab-mysql",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if inspected.returncode == 0:
            for line in inspected.stdout.splitlines():
                if line.startswith("MYSQL_ROOT_PASSWORD="):
                    candidates.append(line.split("=", 1)[1])
                    break
    if os.environ.get("DB_ROOT_PASSWORD"):
        candidates.append(os.environ["DB_ROOT_PASSWORD"])
    for path in (ROOT / ".env",):
        if path.exists():
            value = dotenv_values(path).get("DB_ROOT_PASSWORD")
            if value:
                candidates.append(value)
    return list(dict.fromkeys(candidates))


def execute(sql: str) -> str:
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("Docker client is missing; refusing MySQL administration")
    last_exit = 0
    for password in _secret_candidates():
        env = os.environ.copy()
        env["MYSQL_PWD"] = password
        result = subprocess.run(
            [
                docker,
                "exec",
                "-i",
                "--env",
                "MYSQL_PWD",
                "lab-mysql",
                "mysql",
                "--user=root",
                "--batch",
                "--skip-column-names",
            ],
            input=sql,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        last_exit = result.returncode
    raise RuntimeError(f"MySQL administration failed (exit {last_exit})")
