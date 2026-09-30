from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path

import httpx
from seed_factory import record_created

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / "qa_system"
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/b9sAAAAASUVORK5CYII="
)


def _fixture_ids() -> dict[str, object]:
    return json.loads((QA / "results" / "seed_ids.json").read_text(encoding="utf-8"))


async def _upload_evidence(client: httpx.AsyncClient, label: str) -> str:
    response = await client.post(
        "/repair-uploads",
        files={"file": (f"{label}.png", PNG_1PX, "image/png")},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["data"]["url"])


async def test_approval_handover_return_and_acceptance_state_machine(client_factory) -> None:
    ids = _fixture_ids()
    device_id = int(ids["device"][0])
    request_date = date.today().isoformat()
    run_prefix = json.loads((QA / "results" / "runtime.json").read_text())["run_prefix"]
    idempotency_key = f"qa-lifecycle-{run_prefix}"
    student = await client_factory("student_a")
    manager = await client_factory("manager_a")
    try:
        created = await student.post(
            "/reservations",
            json={
                "device_id": device_id,
                "purpose": "QAEVAL full lifecycle",
                "start_date": request_date,
                "end_date": request_date,
            },
            headers={"Idempotency-Key": idempotency_key},
        )
        assert created.status_code == 201, created.text
        reservation = created.json()["data"]["created"][0]
        reservation_id = int(reservation["id"])
        record_created("reservation", reservation_id)
        assert reservation["status"] == "PENDING"

        approved = await manager.post(
            f"/approvals/{reservation_id}/approve",
            json={"reason": "QAEVAL approval"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["status"] == "APPROVED"
        duplicate_approval = await manager.post(
            f"/approvals/{reservation_id}/approve",
            json={"reason": "duplicate"},
        )
        assert duplicate_approval.status_code == 409

        manager_evidence = await _upload_evidence(manager, "handover")
        handed_over = await manager.post(
            f"/reservations/{reservation_id}/handover",
            json={
                "condition": "NORMAL",
                "image_urls": [manager_evidence],
                "checklist": [{"name": "case", "condition": "NORMAL"}],
            },
        )
        assert handed_over.status_code == 200, handed_over.text
        assert handed_over.json()["data"]["status"] == "IN_USE"
        assert handed_over.json()["data"]["handover_status"] == "HANDED_OVER"

        returned = await student.post(
            f"/reservations/{reservation_id}/return",
            json={"condition": "NORMAL", "image_urls": [await _upload_evidence(student, "return")]},
        )
        assert returned.status_code == 200, returned.text
        assert returned.json()["data"]["status"] == "IN_USE"
        assert returned.json()["data"]["handover_status"] == "RETURN_PENDING"

        accepted = await manager.post(
            f"/reservations/{reservation_id}/accept-return",
            json={
                "condition": "NORMAL",
                "note": "QAEVAL inspected",
                "checklist": [{"name": "case", "condition": "NORMAL"}],
            },
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["data"]["status"] == "COMPLETED"
        duplicate_return = await manager.post(
            f"/reservations/{reservation_id}/accept-return",
            json={"condition": "NORMAL"},
        )
        assert duplicate_return.status_code == 409
    finally:
        await student.aclose()
        await manager.aclose()
