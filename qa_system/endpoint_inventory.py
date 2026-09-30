"""Create a route, authorization, AI tool, and settings inventory from source."""

from __future__ import annotations

import csv
import inspect
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OUTPUT = ROOT / "qa_system" / "results"
sys.path.insert(0, str(BACKEND))

PUBLIC_ROUTES = {
    ("GET", "/api/v2/auth/csrf"),
    ("GET", "/api/v2/auth/colleges"),
    ("POST", "/api/v2/auth/login"),
    ("POST", "/api/v2/auth/register"),
    ("GET", "/api/v2/live"),
    ("GET", "/api/v2/ready"),
}


def _dependency_names(dependant: Any) -> set[str]:
    names: set[str] = set()
    for dependency in dependant.dependencies:
        call = dependency.call
        if call is not None:
            names.add(getattr(call, "__name__", type(call).__name__))
        names.update(_dependency_names(dependency))
    return names


def _body_schema(operation: dict[str, Any]) -> str:
    body = operation.get("requestBody", {}).get("content", {})
    schema = next(iter(body.values()), {}).get("schema", {}) if body else {}
    reference = schema.get("$ref", "")
    return reference.rsplit("/", 1)[-1] if reference else json.dumps(schema, ensure_ascii=False)


def collect() -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    from app.ai.tools.policy import TOOL_POLICIES
    from app.core.settings import Settings
    from app.main import app

    spec = app.openapi()
    route_by_key: dict[tuple[str, str], Any] = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path and methods:
            for method in methods:
                route_by_key[(method.upper(), path)] = route

    routes: list[dict[str, str]] = []
    for path, path_item in sorted(spec["paths"].items()):
        for method, operation in sorted(path_item.items()):
            if method not in {"get", "post", "put", "patch", "delete", "head", "options"}:
                continue
            upper_method = method.upper()
            route = route_by_key.get((upper_method, path))
            dependencies = _dependency_names(route.dependant) if route else set()
            dependencies.update({"enforce_csrf"})
            public = (upper_method, path) in PUBLIC_ROUTES
            authentication = "public/session bootstrap" if public else "cookie session required"
            if "require_ai_access" in dependencies:
                authentication += "; require_ai_access"
            source = ""
            if route is not None:
                try:
                    source = inspect.getsource(route.endpoint)
                except (OSError, TypeError):
                    pass
            scope_evidence = []
            for marker, label in (
                ("college_id", "college scoped in endpoint/service"),
                ("require_college", "college access guard"),
                ("require_device", "device access guard"),
                ("is_system_admin", "system administrator bypass"),
            ):
                if marker in source:
                    scope_evidence.append(label)
            if "enforce_csrf" in dependencies and upper_method not in {"GET", "HEAD", "OPTIONS"}:
                csrf = "trusted Origin + double-submit CSRF"
            else:
                csrf = "not required by method"
            routes.append(
                {
                    "method": upper_method,
                    "path": path,
                    "tag": ",".join(operation.get("tags", [])),
                    "operation": operation.get("operationId", ""),
                    "request_schema": _body_schema(operation),
                    "responses": ",".join(sorted(operation.get("responses", {}).keys())),
                    "authentication": authentication,
                    "tenant_scope_evidence": "; ".join(scope_evidence)
                    or "review service/query path",
                    "csrf": csrf,
                    "dependencies": ",".join(sorted(dependencies)),
                }
            )

    tools = []
    for name, policy in sorted(TOOL_POLICIES.items()):
        tools.append(
            {
                "tool": name,
                "permission": policy.permission_code,
                "write": str(policy.write).lower(),
                "policy": policy.description,
                "confirmation": "required" if policy.write else "not required",
            }
        )

    config = []
    for name, field in sorted(Settings.model_fields.items()):
        sensitive = any(
            word in name.lower() for word in ("password", "secret", "token", "api_key", "dsn")
        )
        config.append(
            {
                "setting": name,
                "type": str(field.annotation),
                "sensitive_value": "never exported" if sensitive else "value omitted",
            }
        )
    return routes, tools, config


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    routes, tools, config = collect()
    with (OUTPUT / "endpoint-capability-inventory.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(routes[0]) if routes else [])
        writer.writeheader()
        writer.writerows(routes)
    with (OUTPUT / "ai-tools-and-settings.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = [{"section": "tool", **row} for row in tools]
        rows.extend({"section": "setting", **row} for row in config)
        columns = sorted({key for row in rows for key in row})
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    sections = [
        "# Endpoint and capability inventory",
        "",
        f"Routes: **{len(routes)}**. Source: FastAPI OpenAPI plus dependency inspection.",
        "Tenant scope is source evidence; API tests check cross-tenant behavior.",
        "Settings list names and types only; credential values are never serialized.",
        "",
        "## REST endpoints",
        "",
        "| Method | Path | Tag | Request schema | Auth | Tenant scope evidence | CSRF |",
        "|---|---|---|---|---|---|---|",
    ]
    sections.extend(
        (
            f"| {r['method']} | `{r['path']}` | {r['tag']} | `{r['request_schema']}` | "
            f"{r['authentication']} | {r['tenant_scope_evidence']} | {r['csrf']} |"
        )
        for r in routes
    )
    sections.extend(
        [
            "",
            "## AI tools and policy",
            "",
            "| Tool | Permission | Write | Confirmation | Policy |",
            "|---|---|---:|---|---|",
        ]
    )
    sections.extend(
        (
            f"| `{t['tool']}` | `{t['permission']}` | {t['write']} | "
            f"{t['confirmation']} | {t['policy']} |"
        )
        for t in tools
    )
    sections.extend(
        ["", "## Settings surface", "", "| Setting | Type | Value handling |", "|---|---|---|"]
    )
    sections.extend(
        f"| `{c['setting']}` | `{c['type']}` | {c['sensitive_value']} |" for c in config
    )
    (OUTPUT / "endpoint-capability-inventory.md").write_text(
        "\n".join(sections) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(routes)} routes, {len(tools)} AI tools, and {len(config)} setting names")


if __name__ == "__main__":
    main()
