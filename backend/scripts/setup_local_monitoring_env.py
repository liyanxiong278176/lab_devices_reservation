"""Create local-only credentials required by the development monitoring stack.

Existing values are preserved. The Prometheus scrape token is shared between
the root Compose .env file and backend/.env, while all other secrets are unique.
"""

from __future__ import annotations

import os
import re
import secrets
import socket
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROOT_ENV = ROOT / ".env"
BACKEND_ENV = ROOT / "backend" / ".env"


def find_available_grafana_port() -> str:
    for port in range(3000, 3101):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            try:
                candidate.bind(("127.0.0.1", port))
            except OSError:
                continue
            return str(port)
    raise OSError("No available localhost port found for Grafana in range 3000-3100")


def read_env(path: Path) -> tuple[list[str], dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Required local environment file is missing: {path}")

    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in values:
            raise ValueError(f"Duplicate environment key {key!r} in {path.name}")
        values[key] = value.strip().strip("\"'")
    return lines, values


def set_value(lines: list[str], values: dict[str, str], key: str, value: str) -> bool:
    if values.get(key):
        return False

    for index, line in enumerate(lines):
        if line.partition("=")[0].strip() == key:
            lines[index] = f"{key}={value}"
            values[key] = value
            return True

    if lines and lines[-1].strip():
        lines.append("")
    lines.append(f"{key}={value}")
    values[key] = value
    return True


def write_env(path: Path, lines: list[str]) -> None:
    content = "\n".join(lines).rstrip("\n") + "\n"
    original_mode = path.stat().st_mode
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.chmod(temporary_path, original_mode)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> None:
    root_lines, root_values = read_env(ROOT_ENV)
    backend_lines, backend_values = read_env(BACKEND_ENV)

    compose_token = root_values.get("PROMETHEUS_METRICS_TOKEN", "")
    backend_token = backend_values.get("LAB_METRICS_TOKEN", "")
    if compose_token and backend_token and compose_token != backend_token:
        raise ValueError(
            "PROMETHEUS_METRICS_TOKEN and LAB_METRICS_TOKEN already differ; "
            "resolve the local values manually instead of overwriting either one."
        )
    metrics_token = compose_token or backend_token or secrets.token_hex(32)
    if len(metrics_token) < 32:
        raise ValueError("The existing metrics token must contain at least 32 characters")

    grafana_password = root_values.get("GRAFANA_ADMIN_PASSWORD") or secrets.token_hex(32)
    if len(grafana_password) < 32:
        raise ValueError("The existing Grafana password must contain at least 32 characters")

    exporter_password = root_values.get("MYSQL_EXPORTER_PASSWORD") or secrets.token_hex(32)
    if not re.fullmatch(r"[a-fA-F0-9]{32,}", exporter_password):
        raise ValueError("MYSQL_EXPORTER_PASSWORD must be at least 32 hexadecimal characters")

    grafana_port = root_values.get("GRAFANA_PORT") or find_available_grafana_port()
    if not grafana_port.isdecimal() or not 1 <= int(grafana_port) <= 65535:
        raise ValueError("GRAFANA_PORT must be a valid TCP port number")

    changed_root: list[str] = []
    changed_backend: list[str] = []
    for key, value in (
        ("PROMETHEUS_METRICS_TOKEN", metrics_token),
        ("GRAFANA_ADMIN_USER", "admin"),
        ("GRAFANA_ADMIN_PASSWORD", grafana_password),
        ("GRAFANA_PORT", grafana_port),
        ("MYSQL_EXPORTER_PASSWORD", exporter_password),
    ):
        if set_value(root_lines, root_values, key, value):
            changed_root.append(key)

    if set_value(backend_lines, backend_values, "LAB_METRICS_TOKEN", metrics_token):
        changed_backend.append("LAB_METRICS_TOKEN")

    if changed_root:
        write_env(ROOT_ENV, root_lines)
    if changed_backend:
        write_env(BACKEND_ENV, backend_lines)

    print("Local monitoring credentials are ready; secret values were not displayed.")
    print(f"Updated root .env keys: {', '.join(changed_root) or 'none (already configured)'}")
    print(
        "Updated backend/.env keys: "
        f"{', '.join(changed_backend) or 'none (already configured)'}"
    )
    print("Grafana username: admin")
    print(f"Grafana localhost port: {root_values['GRAFANA_PORT']}")
    print("Grafana password: generated locally; retrieve it from root .env when needed.")


if __name__ == "__main__":
    main()
