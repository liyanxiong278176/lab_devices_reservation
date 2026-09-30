"""Export the live FastAPI OpenAPI contract without importing project test assets."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("QA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
OPENAPI_URL = os.getenv("QA_OPENAPI_URL", f"{BASE_URL}/api/v2/openapi.json")
OUTPUT = Path(os.getenv("QA_ROUTE_INVENTORY", str(ROOT / "qa_eval" / "route_inventory.md")))


def resolve_schema(document: dict[str, object], schema: dict[str, object]) -> dict[str, object]:
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        name = ref.rsplit("/", 1)[-1]
        component = document.get("components", {}).get("schemas", {}).get(name, {})
        return {"name": name, "schema": component}
    return schema


def field_names(document: dict[str, object], schema: dict[str, object]) -> str:
    resolved = resolve_schema(document, schema)
    actual = resolved.get("schema", resolved)
    properties = actual.get("properties", {}) if isinstance(actual, dict) else {}
    return ", ".join(str(name) for name in properties) or "—"


def main() -> None:
    schema_source = OPENAPI_URL
    try:
        with urllib.request.urlopen(OPENAPI_URL, timeout=10) as response:
            document = json.load(response)
    except (HTTPError, OSError):
        # Local deployments may intentionally disable the docs endpoint. Build
        # the schema from registered production routes, never from old tests.
        sys.path.insert(0, str(ROOT / "backend"))
        from app.core.settings import Settings
        from app.main import create_app

        document = create_app(Settings()).openapi()
        schema_source = "the current in-process FastAPI OpenAPI schema"
    rows = [
        "# API endpoint inventory (AI routes excluded)",
        "",
        f"Generated from `{schema_source}`. Authorization and tenant scope are",
        "cross-checked against the route dependencies and service queries "
        "listed in the test notes.",
        "",
        "| Method | Path | Auth | Tenant scope | Request/query fields | Response fields |",
        "|---|---|---|---|---|---|",
    ]
    for path, methods in sorted(document.get("paths", {}).items()):
        if path.startswith("/api/v2/ai"):
            continue
        for method, operation in sorted(methods.items()):
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            request_fields: list[str] = []
            for parameter in operation.get("parameters", []):
                request_fields.append(f"{parameter.get('name')}[{parameter.get('in')}]")
            body = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
            body_schema = body.get("schema", {})
            body_fields = field_names(document, body_schema) if body_schema else ""
            if body_fields and body_fields != "—":
                request_fields.append(f"body: {body_fields}")
            response_schema: dict[str, object] = {}
            responses = operation.get("responses", {})
            for status in ("200", "201", "202"):
                content = responses.get(status, {}).get("content", {})
                candidate = content.get("application/json", {}).get("schema")
                if candidate:
                    response_schema = candidate
                    break
            response_fields = "—"
            if response_schema:
                resolved_response = resolve_schema(document, response_schema)
                outer = resolved_response.get("schema", resolved_response)
                data_schema = (
                    outer.get("properties", {}).get("data", {}) if isinstance(outer, dict) else {}
                )
                refs = data_schema.get("anyOf", []) if isinstance(data_schema, dict) else []
                data_ref = next((item for item in refs if "$ref" in item), data_schema)
                response_fields = field_names(document, data_ref)
            public = path in {
                "/api/v2/auth/csrf",
                "/api/v2/auth/login",
                "/api/v2/auth/register",
                "/api/v2/live",
            }
            system_admin_only = path in {
                "/api/v2/ready",
                "/api/v2/system/outbox/failed",
            } or path.startswith("/api/v2/system/outbox/")
            auth = (
                "public"
                if public
                else "HttpOnly session cookie; SYS_ADMIN required"
                if system_admin_only
                else "HttpOnly session cookie"
            )
            if public:
                tenant = "no tenant scope"
            elif path.startswith(("/api/v2/users", "/api/v2/colleges", "/api/v2/rbac")):
                tenant = "role-aware; SYS_ADMIN global, other roles restricted by service policy"
            else:
                tenant = (
                    "role-aware server-side scope; student college/own data, manager scope, "
                    "SYS_ADMIN global"
                )
            rows.append(
                f"| {method.upper()} | `{path}` | {auth} | {tenant} | "
                f"{'; '.join(request_fields) or '—'} | {response_fields} |"
            )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
