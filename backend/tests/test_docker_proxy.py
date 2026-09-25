from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_docker_socket_proxy_is_disabled_by_default() -> None:
    script = Path(__file__).resolve().parents[2] / "docker-proxy.py"
    environment = os.environ.copy()
    environment.pop("DOCKER_PROXY_ENABLE", None)
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=5,
        check=False,
    )
    assert result.returncode != 0
    assert "disabled" in result.stderr or "disabled" in result.stdout


def test_compose_keeps_dev_dependencies_local_and_runtime_db_non_root() -> None:
    root = Path(__file__).resolve().parents[2]
    development = (root / "docker-compose.yml").read_text(encoding="utf-8")
    production = (root / "docker-compose.prod.yml").read_text(encoding="utf-8")
    nginx = (root / "frontend" / "nginx.conf").read_text(encoding="utf-8")

    assert "MYSQL_ROOT_PASSWORD: ${DB_ROOT_PASSWORD:?" in development
    assert '"127.0.0.1:3306:3306"' in development
    assert '"127.0.0.1:6379:6379"' in development
    assert "123456" not in development
    assert "MYSQL_USER: ${DB_APP_USER:?" in production
    assert "mysql+asyncmy://${DB_APP_USER:?" in production
    assert "mysql+asyncmy://root:" not in production
    assert nginx.count("location = /api/v2/ready { return 404; }") == 1
    assert nginx.count("location = /api/v2/metrics { return 404; }") == 1
