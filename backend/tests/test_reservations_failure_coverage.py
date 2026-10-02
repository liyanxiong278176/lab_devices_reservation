from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from app.api.v2.schemas import ReservationCreateData, ReservationPlanRequest
from app.application.reservations import ReservationService, request_hash
from app.auth.security import Principal
from app.core.errors import ApiError
from app.infrastructure.db.models import (
    Device,
    DeviceCategory,
    DeviceDocument,
    DeviceDocumentAcknowledgement,
    DeviceHandover,
    DeviceMaintenancePlan,
    DeviceQualification,
    Reservation,
    ReservationBlackout,
    ReservationInspection,
    ReservationWaitlist,
    ReservationWaitlistOffer,
    UploadAsset,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload


def _principal(user, *roles: str, permissions: tuple[str, ...] = ()) -> Principal:
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=user.college_id,
        roles=roles,
        token_type="access",
        token_id="reservation-failure-coverage",
        permissions=permissions,
    )


def _service(session, user, *roles: str, permissions: tuple[str, ...] = ()) -> ReservationService:
    return ReservationService(
        session,
        _principal(user, *roles, permissions=permissions),
        max_days=5,
        advance_days=14,
    )


def _assert_api_error(error: pytest.ExceptionInfo[ApiError], code: str) -> None:
    assert error.value.code == code


def _reservation_stub(user, device, *, status="PENDING", handover_status="PENDING"):
    start = date.today() + timedelta(days=3)
    return SimpleNamespace(
        id=900,
        user_id=user.id,
        college_id=user.college_id,
        device_id=device.id,
        device=device,
        purpose="coverage reservation",
        purpose_category="OTHER",
        project_reference=None,
        status=status,
        handover_status=handover_status,
        start_date=start,
        end_date=start,
        batch_id=None,
        created_at=datetime.now(UTC).replace(tzinfo=None),
        check_in_at=None,
        check_out_at=None,
        reject_reason=None,
        safety_acknowledged_at=None,
        safety_document_version=None,
        user=None,
        days=[],
        inspections=[],
        handover=None,
        fault_repair=None,
    )


@pytest.mark.asyncio
async def test_device_catalog_permission_cache_fallback_and_manager_scope(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        denied = _service(session, student)
        with pytest.raises(ApiError) as error:
            await denied.list_devices()
        _assert_api_error(error, "FORBIDDEN")
        with pytest.raises(ApiError) as error:
            await denied.get_device(device.id)
        _assert_api_error(error, "FORBIDDEN")
        with pytest.raises(ApiError) as error:
            await denied.availability(device.id, date.today(), date.today())
        _assert_api_error(error, "FORBIDDEN")
        with pytest.raises(ApiError) as error:
            await denied.preflight(
                ReservationPlanRequest(
                    device_id=device.id,
                    start_date=date.today() + timedelta(days=1),
                    end_date=date.today() + timedelta(days=1),
                    purpose="permission guard",
                )
            )
        _assert_api_error(error, "FORBIDDEN")

        class BrokenCache:
            async def version(self, _scope):
                raise RuntimeError("redis unavailable")

        student_service = _service(
            session,
            student,
            "STUDENT",
            permissions=("device:read",),
        )
        student_service.cache = BrokenCache()
        items, total, pages, truncated = await student_service.list_devices(
            search="GPU",
            lab_id=device.lab_id,
            status="IDLE",
            include_meta=True,
        )
        assert total == 1 and pages == 1 and not truncated
        assert [item.id for item in items] == [device.id]

        manager_service = _service(
            session,
            manager,
            "LAB_ADMIN",
            permissions=("device:read",),
        )
        manager_items, manager_total = await manager_service.list_devices()
        assert manager_total == 1
        assert [item.id for item in manager_items] == [device.id]
        admin_service = _service(
            session,
            manager,
            "SYS_ADMIN",
            permissions=("device:read",),
        )
        await admin_service._list_devices_from_db(
            search=None,
            lab_id=None,
            status=None,
            page=1,
            page_size=20,
        )


@pytest.mark.asyncio
async def test_device_tenant_consistency_and_availability_validation(seeded) -> None:
    factory, _, other_college, student, _, _, device, _ = seeded
    async with factory() as session:
        loaded = await session.scalar(
            select(Device)
            .options(selectinload(Device.lab), selectinload(Device.college))
            .where(Device.id == device.id)
        )
        assert loaded is not None and loaded.lab is not None
        loaded.lab.college_id = other_college.id
        service = _service(
            session,
            student,
            "SYS_ADMIN",
            permissions=("device:read",),
        )
        with pytest.raises(ApiError) as error:
            await service._load_device(device.id)
        _assert_api_error(error, "TENANT_DATA_INVALID")

        service = _service(
            session,
            student,
            "STUDENT",
            permissions=("device:read",),
        )
        today = date.today()
        with pytest.raises(ApiError) as error:
            await service.availability(device.id, today + timedelta(days=1), today)
        _assert_api_error(error, "DATE_RANGE_INVALID")
        with pytest.raises(ApiError) as error:
            await service.availability(
                device.id,
                today,
                today + timedelta(days=service.max_days),
            )
        _assert_api_error(error, "DATE_RANGE_TOO_LARGE")
        with pytest.raises(ApiError) as error:
            await service.get_device(999999)
        _assert_api_error(error, "DEVICE_NOT_FOUND")


@pytest.mark.asyncio
async def test_handover_record_existing_row_refresh_and_missing_status_row(seeded) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    async with factory() as session:
        start = date.today() + timedelta(days=3)
        reservation = Reservation(
            college_id=student.college_id,
            user_id=student.id,
            device_id=device.id,
            purpose="handover helper",
            start_date=start,
            end_date=start,
            status="PENDING",
            handover_status="PENDING",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        reservation.device = device
        session.add(reservation)
        await session.flush()
        handover = DeviceHandover(
            reservation_id=reservation.id,
            device_id=device.id,
            user_id=student.id,
            college_id=student.college_id,
            status="PENDING",
            handover_note="old note",
            accessory_snapshot=None,
        )
        reservation.handover = handover
        session.add(handover)
        await session.flush()

        service = _service(session, student)
        updated_at = datetime(2026, 1, 2)
        result = await service._ensure_handover_record(
            reservation,
            status="HANDED_OVER",
            now=updated_at,
            note=None,
        )
        assert result is handover
        assert handover.status == "HANDED_OVER"
        assert handover.updated_at == updated_at
        assert handover.handover_note == "old note"
        assert handover.accessory_snapshot in (device.accessory_checklist, [])
        await service._ensure_handover_record(
            reservation,
            status="HANDED_OVER",
            now=updated_at,
            note="updated note",
        )
        assert handover.handover_note == "updated note"
        await service._set_handover_status(reservation, "RETURNED", now=updated_at)
        assert reservation.handover_status == "RETURNED"

        missing = SimpleNamespace(id=900001, handover_status="PENDING")
        await service._set_handover_status(missing, "CANCELLED", now=updated_at)
        assert missing.handover_status == "CANCELLED"


@pytest.mark.asyncio
async def test_access_snapshot_document_acknowledgement_and_qualification(seeded) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    async with factory() as session:
        loaded_device = await session.get(Device, device.id)
        assert loaded_device is not None
        loaded_device.requires_safety_ack = False
        loaded_device.requires_qualification = True
        loaded_device.risk_level = "HIGH"
        tokens = ["doc-access-snapshot-token-0000001", "doc-access-snapshot-token-0000002"]
        assets = [
            UploadAsset(
                asset_token=token,
                user_id=student.id,
                college_id=college.id,
                original_name=f"{index}.pdf",
                content_type="application/pdf",
                size_bytes=100,
                storage_path=f"memory://{token}",
            )
            for index, token in enumerate(tokens)
        ]
        session.add_all(assets)
        await session.flush()
        documents = [
            DeviceDocument(
                device_id=device.id,
                college_id=college.id,
                asset_id=asset.id,
                document_type="SAFETY",
                title=f"Safety {index}",
                version=f"v{index}",
                requires_ack=True,
                active=True,
                created_by=student.id,
            )
            for index, asset in enumerate(assets)
        ]
        session.add_all(documents)
        await session.commit()

        service = _service(session, student, "STUDENT")
        snapshot = await service._access_snapshot(
            loaded_device,
            coverage_until=date.today() + timedelta(days=2),
        )
        assert snapshot["safety_required"] is True
        assert snapshot["safety_acknowledged"] is False
        assert snapshot["qualification_required"] is True
        assert snapshot["qualification_approved"] is False

        latest = max(documents, key=lambda item: item.id)
        session.add(
            DeviceDocumentAcknowledgement(
                document_id=latest.id,
                device_id=device.id,
                user_id=student.id,
                college_id=college.id,
                document_version=latest.version,
            )
        )
        session.add(
            DeviceQualification(
                device_id=device.id,
                user_id=student.id,
                college_id=college.id,
                status="APPROVED",
                valid_until=None,
            )
        )
        await session.commit()
        snapshot = await service._access_snapshot(loaded_device)
        assert snapshot["safety_acknowledged"] is True
        assert snapshot["qualification_approved"] is True

        qualification = await session.scalar(
            select(DeviceQualification).where(DeviceQualification.device_id == device.id)
        )
        assert qualification is not None
        qualification.valid_until = date.today() - timedelta(days=1)
        await session.commit()
        snapshot = await service._access_snapshot(loaded_device)
        assert snapshot["qualification_approved"] is False


@pytest.mark.asyncio
async def test_date_validation_occupancy_and_suggestion_empty_edges(seeded) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    async with factory() as session:
        service = _service(session, student, "STUDENT")
        today = date.today()
        cases = [
            ([], [], "DATE_RANGE_EMPTY"),
            ([today], [[today] * 6], "DATE_RANGE_TOO_LARGE"),
            ([today - timedelta(days=1)], [[today - timedelta(days=1)]], "DATE_IN_PAST"),
            ([today + timedelta(days=15)], [[today + timedelta(days=15)]], "DATE_TOO_FAR"),
        ]
        for dates, segments, expected in cases:
            with pytest.raises(ApiError) as error:
                service._validate_dates(dates, 5, 14, segments)
            _assert_api_error(error, expected)
        assert await service._occupied(device.id, []) == {}
        admin_service = _service(session, student, "SYS_ADMIN")
        assert await admin_service._occupied(device.id, [today + timedelta(days=1)]) == {}
        assert await service._blocked_date_details(device, []) == {}
        assert (
            await service._blocked_dates_for_devices(
                {device.id: device},
                {device.id: set()},
            )
            == {}
        )
        assert await service._maintenance_warnings([]) == {}
        assert await service._reservation_suggestions(
            device,
            [],
            max_advance_days=14,
        ) == ([], [])


@pytest.mark.asyncio
async def test_blackout_and_maintenance_blocks_are_exposed(seeded) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    target = date.today() + timedelta(days=2)
    async with factory() as session:
        loaded_device = await session.get(Device, device.id)
        assert loaded_device is not None
        session.add_all(
            [
                ReservationBlackout(
                    scope_type="DEVICE",
                    scope_id=device.id,
                    blocked_date=target,
                    reason="device blackout",
                    active=True,
                    created_by=student.id,
                ),
                ReservationBlackout(
                    scope_type="LAB",
                    scope_id=device.lab_id,
                    blocked_date=target + timedelta(days=1),
                    reason="lab blackout",
                    active=True,
                    created_by=student.id,
                ),
                ReservationBlackout(
                    scope_type="COLLEGE",
                    scope_id=college.id,
                    blocked_date=target + timedelta(days=2),
                    reason="college blackout",
                    active=True,
                    created_by=student.id,
                ),
            ]
        )
        plan = DeviceMaintenancePlan(
            device_id=device.id,
            college_id=college.id,
            plan_type="CALIBRATION",
            title="Calibration",
            interval_value=1,
            interval_unit="YEAR",
            due_date=date.today() - timedelta(days=1),
            downtime_start=target + timedelta(days=3),
            downtime_end=target + timedelta(days=3),
            active=True,
            created_by=student.id,
            updated_by=student.id,
        )
        session.add(plan)
        await session.commit()
        service = _service(session, student, "STUDENT")
        details = await service._blocked_date_details(
            loaded_device,
            [target + timedelta(days=offset) for offset in range(4)],
        )
        assert len(details) == 4
        assert details[target].reason == "device blackout"
        assert details[target + timedelta(days=1)].reason == "lab blackout"
        assert details[target + timedelta(days=2)].reason == "college blackout"
        assert details[target + timedelta(days=3)].is_maintenance is True
        warnings = await service._maintenance_warnings([device.id])
        assert device.id in warnings


@pytest.mark.asyncio
async def test_suggestions_skip_blocked_candidates_and_stop_after_four(seeded, monkeypatch) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    target = date.today() + timedelta(days=2)
    async with factory() as session:
        category = DeviceCategory(name="Suggestion coverage", parent_id=0, sort=0)
        session.add(category)
        await session.flush()
        source = await session.get(Device, device.id)
        assert source is not None
        source.category_id = category.id
        candidates = [
            Device(
                name=f"Suggestion candidate {index}",
                college_id=college.id,
                category_id=category.id,
                status="IDLE",
                need_approval=False,
            )
            for index in range(1, 7)
        ]
        session.add_all(candidates)
        await session.commit()

        service = _service(session, student, "STUDENT")
        occupied_candidate = candidates[0].id
        blocked_candidate = candidates[1].id

        async def occupied(candidate_id, dates):
            if candidate_id == occupied_candidate:
                return {dates[0]: (123, "APPROVED")}
            return {}

        async def blocked(candidate, _dates):
            return {target: "candidate blocked"} if candidate.id == blocked_candidate else {}

        monkeypatch.setattr(service, "_occupied", occupied)
        monkeypatch.setattr(service, "_blocked_dates", blocked)
        date_suggestions, similar = await service._reservation_suggestions(
            source,
            [target],
            max_advance_days=14,
        )
        assert len(date_suggestions) == 3
        assert len(similar) == 4
        assert occupied_candidate not in {item.device_id for item in similar}
        assert blocked_candidate not in {item.device_id for item in similar}

        unavailable = SimpleNamespace(
            id=source.id,
            status="MAINTENANCE",
            category_id=None,
            college_id=college.id,
        )
        date_suggestions, similar = await service._reservation_suggestions(
            unavailable,
            [target],
            max_advance_days=1,
        )
        assert date_suggestions == []
        assert similar == []


@pytest.mark.asyncio
async def test_preflight_unavailable_device_overrides_date_conflicts(seeded, monkeypatch) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    target = date.today() + timedelta(days=2)
    async with factory() as session:
        loaded = await session.scalar(
            select(Device)
            .options(
                selectinload(Device.lab),
                selectinload(Device.college),
                selectinload(Device.category),
            )
            .where(Device.id == device.id)
        )
        assert loaded is not None
        loaded.status = "MAINTENANCE"
        service = _service(
            session,
            student,
            "STUDENT",
            permissions=("reservation:create",),
        )
        monkeypatch.setattr(service, "_load_device", AsyncMock(return_value=loaded))
        result = await service.preflight(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=target,
                end_date=target,
                purpose="unavailable preflight",
            )
        )
        assert result.conflicts[0].reason == "设备状态为 MAINTENANCE"
        assert result.available_dates == []


@pytest.mark.asyncio
async def test_evidence_validation_checklist_and_fault_report_edges(seeded) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    async with factory() as session:
        service = _service(session, student, "STUDENT")
        with pytest.raises(ApiError) as error:
            await service._validate_evidence_images(None, device)
        _assert_api_error(error, "EVIDENCE_REQUIRED")
        with pytest.raises(ApiError) as error:
            await service._validate_evidence_images(["/tmp/not-uploaded.png"], device)
        _assert_api_error(error, "EVIDENCE_INVALID")
        duplicated = "/repair-uploads/duplicate-evidence-token-000000001"
        with pytest.raises(ApiError) as error:
            await service._validate_evidence_images([duplicated, duplicated], device)
        _assert_api_error(error, "EVIDENCE_DUPLICATE")
        with pytest.raises(ApiError) as error:
            await service._validate_evidence_images(
                [f"/repair-uploads/{'x' * 21}"],
                device,
            )
        _assert_api_error(error, "EVIDENCE_FORBIDDEN")

        too_many = [f"/repair-uploads/{index:020d}" for index in range(7)]
        with pytest.raises(ApiError) as error:
            await service._validate_evidence_images(too_many, device)
        _assert_api_error(error, "EVIDENCE_REQUIRED")

        token = "invalid-content-token-0000000001"
        session.add(
            UploadAsset(
                asset_token=token,
                user_id=student.id,
                college_id=college.id,
                original_name="not-image.bin",
                content_type="application/octet-stream",
                size_bytes=64,
                storage_path=f"memory://{token}",
            )
        )
        await session.flush()
        with pytest.raises(ApiError) as error:
            await service._validate_evidence_images([f"/repair-uploads/{token}"], device)
        _assert_api_error(error, "EVIDENCE_INVALID")

        with pytest.raises(ApiError) as error:
            service._validated_checklist(["case", "cable"], [{"name": "case"}])
        _assert_api_error(error, "CHECKLIST_MISMATCH")
        clean = service._validated_checklist(
            ["case"],
            [{"name": " case ", "condition": "NORMAL", "note": " checked "}],
        )
        assert clean == [{"name": "case", "condition": "NORMAL", "note": "checked"}]
        assert service._effective_condition("NORMAL", clean) == "NORMAL"
        assert service._effective_condition(
            "NORMAL",
            [{"name": "case", "condition": "DAMAGED"}],
        ) == "DAMAGED"
        assert service._effective_condition(
            "DAMAGED",
            [{"name": "case", "condition": "MISSING"}],
        ) == "MISSING"

        existing = SimpleNamespace(id=55)
        service.session.scalar = AsyncMock(return_value=existing)
        report = await service._create_fault_repair(
            SimpleNamespace(id=7),
            phase="return",
            condition="DAMAGED",
            note=None,
            image_urls=[],
            checklist=[],
            now=datetime.now(),
        )
        assert report is existing


@pytest.mark.asyncio
async def test_waitlist_join_rejects_invalid_requests_and_reuses_cancelled_entry(
    seeded,
    monkeypatch,
) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    target = date.today() + timedelta(days=3)
    async with factory() as session:
        denied = _service(session, student)
        with pytest.raises(ApiError) as error:
            await denied.join_waitlist(
                device_id=device.id,
                reservation_date=target,
                purpose="no permission",
            )
        _assert_api_error(error, "FORBIDDEN")

        service = _service(
            session,
            student,
            "STUDENT",
            permissions=("reservation:create",),
        )
        monkeypatch.setattr(service, "_load_device", AsyncMock(return_value=device))
        with pytest.raises(ApiError) as error:
            await service.join_waitlist(
                device_id=device.id,
                reservation_date=date.today() - timedelta(days=1),
                purpose="past",
            )
        _assert_api_error(error, "DATE_IN_PAST")

        unavailable = SimpleNamespace(**device.__dict__)
        unavailable.status = "MAINTENANCE"
        monkeypatch.setattr(service, "_load_device", AsyncMock(return_value=unavailable))
        with pytest.raises(ApiError) as error:
            await service.join_waitlist(
                device_id=device.id,
                reservation_date=target,
                purpose="unavailable",
            )
        _assert_api_error(error, "DEVICE_UNAVAILABLE")

        monkeypatch.setattr(service, "_load_device", AsyncMock(return_value=device))
        monkeypatch.setattr(service, "_occupied", AsyncMock(return_value={}))
        with pytest.raises(ApiError) as error:
            await service.join_waitlist(
                device_id=device.id,
                reservation_date=target,
                purpose="not needed",
            )
        _assert_api_error(error, "WAITLIST_NOT_NEEDED")

        monkeypatch.setattr(
            service,
            "_occupied",
            AsyncMock(return_value={target: (10, "APPROVED")}),
        )
        monkeypatch.setattr(
            service,
            "_blocked_dates",
            AsyncMock(return_value={target: "scheduled blackout"}),
        )
        with pytest.raises(ApiError) as error:
            await service.join_waitlist(
                device_id=device.id,
                reservation_date=target,
                purpose="blocked",
            )
        _assert_api_error(error, "DATE_BLOCKED")

        monkeypatch.setattr(service, "_blocked_dates", AsyncMock(return_value={}))
        service.session.scalar = AsyncMock(return_value=SimpleNamespace(status="OFFERED"))
        with pytest.raises(ApiError) as error:
            await service.join_waitlist(
                device_id=device.id,
                reservation_date=target,
                purpose="already queued",
            )
        _assert_api_error(error, "WAITLIST_EXISTS")

        old_entry = SimpleNamespace(
            id=77,
            status="CANCELLED",
            purpose="old",
            purpose_category="OTHER",
            project_reference=None,
            notified_at=datetime.now(),
            created_at=datetime.now(),
            device_id=device.id,
            college_id=student.college_id,
            user_id=student.id,
            reservation_date=target,
        )
        service.session.scalar = AsyncMock(return_value=old_entry)
        service.session.add = Mock()
        service.session.flush = AsyncMock()
        service.session.commit = AsyncMock()
        result = await service.join_waitlist(
            device_id=device.id,
            reservation_date=target,
            purpose="  reuse entry  ",
            project_reference="  LAB-17  ",
        )
        assert result.id == old_entry.id
        assert result.purpose == "reuse entry"
        assert old_entry.status == "WAITING"
        assert old_entry.project_reference == "LAB-17"
        service.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_waitlist_join_integrity_conflict_rolls_back(seeded, monkeypatch) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    async with factory() as session:
        service = _service(
            session,
            student,
            "STUDENT",
            permissions=("reservation:create",),
        )
        target = date.today() + timedelta(days=4)
        monkeypatch.setattr(service, "_load_device", AsyncMock(return_value=device))
        monkeypatch.setattr(
            service,
            "_occupied",
            AsyncMock(return_value={target: (20, "APPROVED")}),
        )
        monkeypatch.setattr(service, "_blocked_dates", AsyncMock(return_value={}))
        session.scalar = AsyncMock(return_value=None)
        session.flush = AsyncMock(
            side_effect=IntegrityError("flush", {}, RuntimeError("duplicate waitlist"))
        )
        session.rollback = AsyncMock()
        with pytest.raises(ApiError) as error:
            await service.join_waitlist(
                device_id=device.id,
                reservation_date=target,
                purpose="racing duplicate",
            )
        _assert_api_error(error, "WAITLIST_EXISTS")
        session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_waitlist_list_cancel_and_confirmation_guard_paths(seeded, monkeypatch) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    async with factory() as session:
        denied = _service(session, student)
        with pytest.raises(ApiError) as error:
            await denied.list_waitlist()
        _assert_api_error(error, "FORBIDDEN")
        with pytest.raises(ApiError) as error:
            await denied.cancel_waitlist(1)
        _assert_api_error(error, "FORBIDDEN")
        with pytest.raises(ApiError) as error:
            await denied.confirm_waitlist_offer(1)
        _assert_api_error(error, "FORBIDDEN")

        service = _service(
            session,
            student,
            "STUDENT",
            permissions=("reservation:read:own", "reservation:cancel", "reservation:create"),
        )
        assert await service.list_waitlist() == []
        global_reader = _service(
            session,
            student,
            "SYS_ADMIN",
            permissions=("reservation:read:own",),
        )
        assert await global_reader.list_waitlist() == []

        cancel_service = _service(
            session,
            student,
            "STUDENT",
            permissions=("reservation:cancel",),
        )
        cancel_service.session.scalar = AsyncMock(return_value=None)
        with pytest.raises(ApiError) as error:
            await cancel_service.cancel_waitlist(101)
        _assert_api_error(error, "WAITLIST_NOT_FOUND")
        cancel_service.session.scalar = AsyncMock(
            return_value=SimpleNamespace(status="CONFIRMED")
        )
        with pytest.raises(ApiError) as error:
            await cancel_service.cancel_waitlist(102)
        _assert_api_error(error, "WAITLIST_NOT_FOUND")

        confirm = _service(
            session,
            student,
            "STUDENT",
            permissions=("reservation:create",),
        )
        confirm.session.scalar = AsyncMock(side_effect=[None, None])
        with pytest.raises(ApiError) as error:
            await confirm.confirm_waitlist_offer(103)
        _assert_api_error(error, "WAITLIST_OFFER_NOT_FOUND")

        entry = SimpleNamespace(
            id=104,
            status="OFFERED",
            device_id=device.id,
            college_id=college.id,
            reservation_date=date.today() + timedelta(days=2),
            purpose="offer",
            purpose_category="OTHER",
            project_reference=None,
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        expired_offer = SimpleNamespace(expires_at=now - timedelta(seconds=1))
        confirm.session.scalar = AsyncMock(side_effect=[entry, expired_offer])
        confirm.session.delete = AsyncMock()
        confirm.session.commit = AsyncMock()
        with pytest.raises(ApiError) as error:
            await confirm.confirm_waitlist_offer(entry.id)
        _assert_api_error(error, "WAITLIST_OFFER_EXPIRED")
        assert entry.status == "EXPIRED"
        confirm.session.commit.assert_awaited_once()

        past_entry = SimpleNamespace(
            **{
                **entry.__dict__,
                "id": 105,
                "status": "OFFERED",
                "reservation_date": date.today() - timedelta(days=1),
            }
        )
        future_offer = SimpleNamespace(expires_at=now + timedelta(hours=1))
        confirm.session.scalar = AsyncMock(side_effect=[past_entry, future_offer])
        with pytest.raises(ApiError) as error:
            await confirm.confirm_waitlist_offer(past_entry.id)
        _assert_api_error(error, "WAITLIST_OFFER_EXPIRED")
        assert past_entry.status == "SKIPPED"


@pytest.mark.asyncio
async def test_waitlist_offer_listing_cancellation_and_successful_confirmation(seeded) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    async with factory() as session:
        service = _service(
            session,
            student,
            "STUDENT",
            permissions=("reservation:read:own", "reservation:cancel", "reservation:create"),
        )
        target = date.today() + timedelta(days=5)
        listed = ReservationWaitlist(
            device_id=device.id,
            college_id=college.id,
            user_id=student.id,
            reservation_date=target,
            purpose="waitlist cancel",
            purpose_category="OTHER",
            status="OFFERED",
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(listed)
        await session.flush()
        listed_offer = ReservationWaitlistOffer(
            waitlist_id=listed.id,
            device_id=device.id,
            college_id=college.id,
            user_id=student.id,
            reservation_date=target,
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        )
        session.add(listed_offer)
        await session.commit()

        rows = await service.list_waitlist()
        assert len(rows) == 1
        assert rows[0].offered_until is not None
        await service.cancel_waitlist(listed.id)
        assert await session.get(ReservationWaitlistOffer, listed_offer.id) is None

        confirm_date = date.today() + timedelta(days=6)
        confirm_entry = ReservationWaitlist(
            device_id=device.id,
            college_id=college.id,
            user_id=student.id,
            reservation_date=confirm_date,
            purpose="waitlist confirmation",
            purpose_category="OTHER",
            status="OFFERED",
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(confirm_entry)
        await session.flush()
        session.add(
            ReservationWaitlistOffer(
                waitlist_id=confirm_entry.id,
                device_id=device.id,
                college_id=college.id,
                user_id=student.id,
                reservation_date=confirm_date,
                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            )
        )
        await session.commit()

        confirmation = await service.confirm_waitlist_offer(confirm_entry.id)
        assert confirmation.waitlist_id == confirm_entry.id
        assert confirmation.reservation.start_date == confirm_date
        assert confirmation.reservation.status == "APPROVED"


@pytest.mark.asyncio
async def test_waitlist_confirmation_rolls_back_failures_and_rejects_empty_create(
    seeded,
    monkeypatch,
) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    async with factory() as session:
        service = _service(
            session,
            student,
            "STUDENT",
            permissions=("reservation:create",),
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        entry = SimpleNamespace(
            id=880,
            status="OFFERED",
            device_id=device.id,
            college_id=college.id,
            reservation_date=date.today() + timedelta(days=3),
            purpose="retry offer",
            purpose_category="OTHER",
            project_reference=None,
        )
        offer = SimpleNamespace(expires_at=now + timedelta(hours=1))
        service.session.scalar = AsyncMock(side_effect=[entry, offer])
        service.session.delete = AsyncMock()
        service.session.flush = AsyncMock()
        service.session.rollback = AsyncMock()
        monkeypatch.setattr(service, "create", AsyncMock(side_effect=RuntimeError("create failed")))
        with pytest.raises(RuntimeError, match="create failed"):
            await service.confirm_waitlist_offer(entry.id)
        service.session.rollback.assert_awaited_once()

        entry.status = "OFFERED"
        service.session.scalar = AsyncMock(side_effect=[entry, offer])
        monkeypatch.setattr(service, "create", AsyncMock(return_value=SimpleNamespace(created=[])))
        with pytest.raises(ApiError) as error:
            await service.confirm_waitlist_offer(entry.id)
        _assert_api_error(error, "WAITLIST_CONFIRM_FAILED")


@pytest.mark.asyncio
async def test_create_permission_idempotency_user_and_policy_guards(seeded) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    plan = ReservationPlanRequest(
        device_id=device.id,
        start_date=date.today() + timedelta(days=3),
        end_date=date.today() + timedelta(days=3),
        purpose="create guard",
    )
    async with factory() as session:
        denied = _service(session, student)
        with pytest.raises(ApiError) as error:
            await denied.create(plan)
        _assert_api_error(error, "FORBIDDEN")

        service = _service(
            session,
            student,
            "STUDENT",
            permissions=("reservation:create",),
        )
        with pytest.raises(ApiError) as error:
            await service.create(plan, idempotency_key="x" * 129)
        _assert_api_error(error, "IDEMPOTENCY_KEY_INVALID")

        service.session.scalar = AsyncMock(
            side_effect=[
                student,
                SimpleNamespace(request_hash="different", response_body=None),
            ]
        )
        with pytest.raises(ApiError) as error:
            await service.create(plan, idempotency_key="already-used")
        _assert_api_error(error, "IDEMPOTENCY_REUSED")

        service.session.scalar = AsyncMock(
            side_effect=[
                student,
                SimpleNamespace(
                    request_hash=request_hash(plan),
                    response_body=None,
                ),
            ]
        )
        with pytest.raises(ApiError) as error:
            await service.create(plan, idempotency_key="in-progress")
        _assert_api_error(error, "REQUEST_IN_PROGRESS")

        service.session.scalar = AsyncMock(return_value=None)
        with pytest.raises(ApiError) as error:
            await service.create(plan)
        _assert_api_error(error, "USER_NOT_FOUND")

        disabled = SimpleNamespace(status=0, booking_blocked_until=None)
        service.session.scalar = AsyncMock(return_value=disabled)
        with pytest.raises(ApiError) as error:
            await service.create(plan)
        _assert_api_error(error, "USER_NOT_FOUND")

        restricted = SimpleNamespace(
            status=1,
            booking_blocked_until=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
        )
        service.session.scalar = AsyncMock(return_value=restricted)
        with pytest.raises(ApiError) as error:
            await service.create(plan)
        _assert_api_error(error, "BOOKING_RESTRICTED")

        service = _service(
            session,
            student,
            "STUDENT",
            permissions=("reservation:create",),
        )
        monkeypatch = pytest.MonkeyPatch()
        try:
            monkeypatch.setattr(service, "_load_device", AsyncMock(return_value=device))
            service.session.scalar = AsyncMock(side_effect=[student, None])
            with pytest.raises(ApiError) as error:
                await service.create(plan)
            _assert_api_error(error, "DEVICE_NOT_FOUND")
        finally:
            monkeypatch.undo()

        async def reject_with(preflight_values, *, request=plan):
            local = _service(
                session,
                student,
                "SYS_ADMIN",
                permissions=("reservation:create",),
            )
            local._load_device = AsyncMock(return_value=device)
            local.session.scalar = AsyncMock(side_effect=[student, device])
            local.preflight = AsyncMock(return_value=SimpleNamespace(**preflight_values))
            with pytest.raises(ApiError) as captured:
                await local.create(request)
            return captured.value

        common = {
            "conflicts": [],
            "available_dates": [plan.start_date],
            "safety_required": False,
            "safety_acknowledged": True,
            "qualification_required": False,
            "qualification_approved": True,
            "safety_document_version": None,
            "effective_policy": SimpleNamespace(approval_required=False),
            "model_dump": lambda **_kwargs: {},
        }
        conflict = await reject_with(
            {**common, "conflicts": [SimpleNamespace(date=plan.start_date)]}
        )
        assert conflict.code == "RESERVATION_CONFLICT"
        safety = await reject_with(
            {**common, "safety_required": True, "safety_acknowledged": False}
        )
        assert safety.code == "SAFETY_ACK_REQUIRED"
        qualification = await reject_with(
            {**common, "qualification_required": True, "qualification_approved": False}
        )
        assert qualification.code == "QUALIFICATION_REQUIRED"
        no_dates = await reject_with({**common, "available_dates": []})
        assert no_dates.code == "NO_AVAILABLE_DATE"


@pytest.mark.asyncio
async def test_create_integrity_conflict_and_idempotency_race_recovery(seeded, monkeypatch) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    plan = ReservationPlanRequest(
        device_id=device.id,
        start_date=date.today() + timedelta(days=4),
        end_date=date.today() + timedelta(days=4),
        purpose="integrity race",
    )
    success_shape = ReservationCreateData(created=[], skipped_conflicts=[]).model_dump(mode="json")
    base_preflight = SimpleNamespace(
        conflicts=[],
        available_dates=[plan.start_date],
        safety_required=False,
        safety_acknowledged=True,
        qualification_required=False,
        qualification_approved=True,
        safety_document_version=None,
        effective_policy=SimpleNamespace(approval_required=False),
        model_dump=lambda **_kwargs: {},
    )

    async def run_case(*, key: str | None, committed):
        async with factory() as session:
            service = _service(
                session,
                student,
                "STUDENT",
                permissions=("reservation:create",),
            )
            monkeypatch.setattr(service, "_load_device", AsyncMock(return_value=device))
            scalar_results = [student, device]
            if key:
                scalar_results.insert(1, None)
                scalar_results.append(committed)
            service.session.scalar = AsyncMock(side_effect=scalar_results)
            service.preflight = AsyncMock(return_value=base_preflight)
            service.session.flush = AsyncMock(
                side_effect=IntegrityError("insert", {}, RuntimeError("duplicate day"))
            )
            service.session.rollback = AsyncMock()
            if committed is not None and committed.response_body:
                committed.request_hash = request_hash(plan)
            try:
                result = await service.create(plan, idempotency_key=key)
            except ApiError as error:
                result = error
            service.session.rollback.assert_awaited_once()
            return result

    ordinary = await run_case(key=None, committed=None)
    assert isinstance(ordinary, ApiError) and ordinary.code == "RESERVATION_CONFLICT"

    in_progress = await run_case(
        key="race-pending",
        committed=SimpleNamespace(request_hash=request_hash(plan), response_body=None),
    )
    assert isinstance(in_progress, ApiError) and in_progress.code == "REQUEST_IN_PROGRESS"

    replaced = await run_case(
        key="race-replaced",
        committed=SimpleNamespace(request_hash="another-payload", response_body=None),
    )
    assert isinstance(replaced, ApiError) and replaced.code == "RESERVATION_CONFLICT"

    replayed = await run_case(
        key="race-committed",
        committed=SimpleNamespace(
            request_hash=request_hash(plan),
            response_body=success_shape,
        ),
    )
    assert isinstance(replayed, ReservationCreateData)
    assert replayed.created == []


@pytest.mark.asyncio
async def test_reservation_listing_visibility_and_manager_scope_matrix(seeded, monkeypatch) -> None:
    factory, _, other_college, student, other_student, manager, device, other_device = seeded
    async with factory() as session:
        denied = _service(session, student)
        with pytest.raises(ApiError) as error:
            await denied.list_mine()
        _assert_api_error(error, "FORBIDDEN")
        with pytest.raises(ApiError) as error:
            await denied._load_reservation(999999)
        _assert_api_error(error, "RESERVATION_NOT_FOUND")

        own = _reservation_stub(student, device)
        own_service = _service(
            session,
            student,
            "STUDENT",
            permissions=("reservation:read:own",),
        )
        assert await own_service._can_view(own) is True
        assert await own_service._can_view(
            SimpleNamespace(**{**own.__dict__, "college_id": other_college.id})
        ) is False

        manager_view = _reservation_stub(other_student, other_device)
        manager_service = _service(
            session,
            manager,
            "LAB_ADMIN",
            permissions=("reservation:read:scope",),
        )
        monkeypatch.setattr(manager_service, "_can_manage_device", AsyncMock(return_value=True))
        assert await manager_service._can_view(manager_view) is True
        monkeypatch.setattr(manager_service, "_can_manage_device", AsyncMock(return_value=False))
        assert await manager_service._can_view(manager_view) is False
        no_scope_read = _service(session, manager, "LAB_ADMIN")
        assert await no_scope_read._can_view(manager_view) is False

        admin = _service(session, manager, "SYS_ADMIN")
        assert await admin._can_view(manager_view) is True
        assert await admin._can_manage_device(device) is True

        ordinary = _service(session, student, "STUDENT")
        assert await ordinary._can_manage_device(device) is False
        lab_manager = _service(session, manager, "LAB_ADMIN")
        assert await lab_manager._can_manage_device(device) is True
        assert await lab_manager._can_manage_device(other_device) is False

        no_lab_device = SimpleNamespace(lab_id=None, college_id=device.college_id)
        lab_manager.session.scalar = AsyncMock(return_value=manager.id)
        assert await lab_manager._can_manage_device(no_lab_device) is True
        lab_manager.session.scalar = AsyncMock(return_value=None)
        assert await lab_manager._can_manage_device(no_lab_device) is False

        other_lab = SimpleNamespace(lab_id=999, college_id=device.college_id)
        lab_manager.session.scalar = AsyncMock(side_effect=[other_student.id, manager.id])
        assert await lab_manager._can_manage_device(other_lab) is True
        lab_manager.session.scalar = AsyncMock(side_effect=[other_student.id, other_student.id])
        assert await lab_manager._can_manage_device(other_lab) is False

        del session.scalar
        await own_service.list_mine(status="PENDING", handover_status="PENDING")
        await admin.list_mine(page=1, page_size=5)

        hidden = _service(session, other_student, "STUDENT", permissions=("reservation:read:own",))
        with pytest.raises(ApiError) as error:
            await hidden.get_reservation(999999)
        _assert_api_error(error, "RESERVATION_NOT_FOUND")
        monkeypatch.setattr(hidden, "_load_reservation", AsyncMock(return_value=own))
        monkeypatch.setattr(hidden, "_can_view", AsyncMock(return_value=False))
        with pytest.raises(ApiError) as error:
            await hidden.get_reservation(own.id)
        _assert_api_error(error, "RESERVATION_NOT_FOUND")


@pytest.mark.asyncio
async def test_reservation_cancel_and_handover_exception_compare_set_guards(
    seeded,
    monkeypatch,
) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        reservation = _reservation_stub(student, device)

        async def expect_cancel(principal, row, expected, *, visible=True, affected=1):
            service = ReservationService(session, principal)
            monkeypatch.setattr(service, "_load_reservation", AsyncMock(return_value=row))
            monkeypatch.setattr(service, "_can_view", AsyncMock(return_value=visible))
            service.session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=affected))
            with pytest.raises(ApiError) as error:
                await service.cancel(row.id)
            _assert_api_error(error, expected)

        student_principal = _principal(
            student,
            "STUDENT",
            permissions=("reservation:cancel",),
        )
        await expect_cancel(_principal(student), reservation, "FORBIDDEN")
        await expect_cancel(
            _principal(manager, "STUDENT", permissions=("reservation:cancel",)),
            reservation,
            "FORBIDDEN",
        )
        await expect_cancel(student_principal, reservation, "RESERVATION_NOT_FOUND", visible=False)
        await expect_cancel(
            student_principal,
            _reservation_stub(student, device, status="COMPLETED"),
            "INVALID_RESERVATION_STATE",
        )
        await expect_cancel(
            student_principal,
            _reservation_stub(student, device, status="IN_USE"),
            "INVALID_RESERVATION_STATE",
        )
        same_day = _reservation_stub(student, device)
        same_day.start_date = date.today()
        await expect_cancel(student_principal, same_day, "CANCEL_WINDOW_CLOSED")
        await expect_cancel(
            student_principal,
            reservation,
            "RESERVATION_STATE_CHANGED",
            affected=0,
        )

        admin_principal = _principal(
            manager,
            "LAB_ADMIN",
            permissions=("reservation:handover",),
        )

        async def expect_exception_cancel(principal, row, expected, *, manager_ok=True, affected=1):
            service = ReservationService(session, principal)
            monkeypatch.setattr(service, "_load_reservation", AsyncMock(return_value=row))
            monkeypatch.setattr(service, "_can_manage_device", AsyncMock(return_value=manager_ok))
            service.session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=affected))
            with pytest.raises(ApiError) as error:
                await service.cancel_handover_exception(row.id, "valid reason")
            _assert_api_error(error, expected)

        await expect_exception_cancel(_principal(manager), reservation, "FORBIDDEN")
        await expect_exception_cancel(admin_principal, reservation, "FORBIDDEN", manager_ok=False)
        invalid_state = _reservation_stub(
            student,
            device,
            status="APPROVED",
            handover_status="PENDING",
        )
        await expect_exception_cancel(admin_principal, invalid_state, "INVALID_RESERVATION_STATE")
        exception_row = _reservation_stub(
            student,
            device,
            status="APPROVED",
            handover_status="EXCEPTION",
        )
        service = ReservationService(session, admin_principal)
        monkeypatch.setattr(service, "_load_reservation", AsyncMock(return_value=exception_row))
        monkeypatch.setattr(service, "_can_manage_device", AsyncMock(return_value=True))
        with pytest.raises(ApiError) as error:
            await service.cancel_handover_exception(exception_row.id, "  ")
        _assert_api_error(error, "CANCEL_REASON_REQUIRED")
        await expect_exception_cancel(
            admin_principal,
            exception_row,
            "RESERVATION_STATE_CHANGED",
            affected=0,
        )


@pytest.mark.asyncio
async def test_single_approval_guards_and_approve_reject_transitions(seeded, monkeypatch) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        manager_principal = _principal(
            manager,
            "LAB_ADMIN",
            permissions=("reservation:approve",),
        )

        async def run_case(
            row,
            *,
            principal=manager_principal,
            manageable=True,
            blocked=None,
            affected=1,
        ):
            service = ReservationService(session, principal)
            monkeypatch.setattr(service, "_load_reservation", AsyncMock(return_value=row))
            monkeypatch.setattr(service, "_can_manage_device", AsyncMock(return_value=manageable))
            monkeypatch.setattr(service, "_blocked_dates", AsyncMock(return_value=blocked or {}))
            monkeypatch.setattr(service, "_ensure_handover_record", AsyncMock())
            monkeypatch.setattr(service, "_set_handover_status", AsyncMock())
            monkeypatch.setattr(service, "_enqueue_maintenance_impact_notifications", AsyncMock())
            service.session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=affected))
            service.session.commit = AsyncMock()
            return await service.approve(row.id, approve=True)

        row = _reservation_stub(student, device)
        with pytest.raises(ApiError) as error:
            await run_case(row, principal=_principal(manager))
        _assert_api_error(error, "FORBIDDEN")
        with pytest.raises(ApiError) as error:
            await run_case(row, manageable=False)
        _assert_api_error(error, "FORBIDDEN")
        with pytest.raises(ApiError) as error:
            await run_case(_reservation_stub(student, device, status="APPROVED"))
        _assert_api_error(error, "INVALID_RESERVATION_STATE")

        unavailable_device = SimpleNamespace(**device.__dict__)
        unavailable_device.status = "RETIRED"
        with pytest.raises(ApiError) as error:
            await run_case(_reservation_stub(student, unavailable_device))
        _assert_api_error(error, "DEVICE_UNAVAILABLE")

        with pytest.raises(ApiError) as error:
            await run_case(
                row,
                blocked={row.start_date: "maintenance downtime"},
            )
        _assert_api_error(error, "DEVICE_MAINTENANCE_RESTRICTION")
        with pytest.raises(ApiError) as error:
            await run_case(row, affected=0)
        _assert_api_error(error, "RESERVATION_STATE_CHANGED")

        approved = await run_case(row)
        assert approved.status == "APPROVED"

        rejected = _reservation_stub(student, device)
        service = ReservationService(session, manager_principal)
        monkeypatch.setattr(service, "_load_reservation", AsyncMock(return_value=rejected))
        monkeypatch.setattr(service, "_can_manage_device", AsyncMock(return_value=True))
        monkeypatch.setattr(service, "_set_handover_status", AsyncMock())
        monkeypatch.setattr(service, "_enqueue_waitlist_promotions", Mock())
        service.session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=1))
        service.session.commit = AsyncMock()
        result = await service.approve(rejected.id, approve=False, reason=None)
        assert result.status == "REJECTED"


@pytest.mark.asyncio
async def test_batch_approval_validates_scope_state_availability_and_maintenance(
    seeded,
    monkeypatch,
) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    principal = _principal(
        manager,
        "LAB_ADMIN",
        permissions=("reservation:approve",),
    )
    async with factory() as session:
        service = ReservationService(session, principal)
        with pytest.raises(ApiError) as error:
            await service.approve_many([])
        _assert_api_error(error, "APPROVAL_EMPTY")

        no_permission = ReservationService(session, _principal(manager))
        with pytest.raises(ApiError) as error:
            await no_permission.approve_many([1])
        _assert_api_error(error, "FORBIDDEN")

        async def expect_rows(rows, expected, *, manageable=True, blocked=None):
            local = ReservationService(session, principal)
            local.session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
            monkeypatch.setattr(
                local,
                "_can_manage_device",
                AsyncMock(return_value=manageable),
            )
            monkeypatch.setattr(
                local,
                "_blocked_dates_for_devices",
                AsyncMock(return_value=blocked or {}),
            )
            with pytest.raises(ApiError) as captured:
                await local.approve_many([row.id for row in rows] or [999])
            _assert_api_error(captured, expected)

        await expect_rows([], "RESERVATION_NOT_FOUND")
        await expect_rows(
            [_reservation_stub(student, device, status="APPROVED")],
            "INVALID_RESERVATION_STATE",
        )
        await expect_rows(
            [_reservation_stub(student, device)],
            "FORBIDDEN",
            manageable=False,
        )
        unavailable = SimpleNamespace(**device.__dict__)
        unavailable.status = "OFFLINE"
        await expect_rows(
            [_reservation_stub(student, unavailable)],
            "DEVICE_UNAVAILABLE",
        )
        blocked_row = _reservation_stub(student, device)
        await expect_rows(
            [blocked_row],
            "DEVICE_MAINTENANCE_RESTRICTION",
            blocked={device.id: {blocked_row.start_date: "calibration"}},
        )

        rows = [_reservation_stub(student, device), _reservation_stub(student, device)]
        rows[1].id = 901
        local = ReservationService(session, principal)
        local.session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
        monkeypatch.setattr(local, "_can_manage_device", AsyncMock(return_value=True))
        monkeypatch.setattr(local, "_blocked_dates_for_devices", AsyncMock(return_value={}))
        monkeypatch.setattr(local, "_ensure_handover_record", AsyncMock())
        monkeypatch.setattr(local, "_enqueue_maintenance_impact_notifications_many", AsyncMock())
        local.session.commit = AsyncMock()
        approved_count = await local.approve_many([rows[0].id, rows[1].id, rows[0].id])
        assert approved_count == 2
        assert all(row.status == "APPROVED" for row in rows)


@pytest.mark.asyncio
async def test_violation_guards_credit_penalty_and_missing_user(seeded, monkeypatch) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        principal = _principal(
            manager,
            "LAB_ADMIN",
            permissions=("reservation:approve",),
        )

        async def expect_violate(row, expected, *, permissioned=True, manageable=True, affected=1):
            actor = principal if permissioned else _principal(manager)
            service = ReservationService(session, actor, credit_block_threshold=90)
            monkeypatch.setattr(service, "_load_reservation", AsyncMock(return_value=row))
            monkeypatch.setattr(service, "_can_manage_device", AsyncMock(return_value=manageable))
            service.session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=affected))
            with pytest.raises(ApiError) as error:
                await service.violate(row.id, " violation reason ")
            _assert_api_error(error, expected)

        await expect_violate(_reservation_stub(student, device), "FORBIDDEN", permissioned=False)
        await expect_violate(_reservation_stub(student, device), "FORBIDDEN", manageable=False)
        await expect_violate(
            _reservation_stub(student, device, status="PENDING"),
            "INVALID_RESERVATION_STATE",
        )
        await expect_violate(
            _reservation_stub(student, device, status="APPROVED"),
            "RESERVATION_STATE_CHANGED",
            affected=0,
        )

        missing_user_row = _reservation_stub(student, device, status="APPROVED")
        service = ReservationService(session, principal)
        monkeypatch.setattr(service, "_load_reservation", AsyncMock(return_value=missing_user_row))
        monkeypatch.setattr(service, "_can_manage_device", AsyncMock(return_value=True))
        monkeypatch.setattr(service, "_set_handover_status", AsyncMock())
        service.session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=1))
        service.session.scalar = AsyncMock(return_value=None)
        service.session.commit = AsyncMock()
        result = await service.violate(missing_user_row.id, "missing account")
        assert result.status == "VIOLATED"

        student.credit_score = 95
        student.booking_blocked_until = None
        blocked_row = _reservation_stub(student, device, status="IN_USE")
        service = ReservationService(
            session,
            principal,
            credit_block_threshold=90,
            credit_block_days=2,
        )
        monkeypatch.setattr(service, "_load_reservation", AsyncMock(return_value=blocked_row))
        monkeypatch.setattr(service, "_can_manage_device", AsyncMock(return_value=True))
        monkeypatch.setattr(service, "_set_handover_status", AsyncMock())
        service.session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=1))
        service.session.scalar = AsyncMock(return_value=student)
        service.session.commit = AsyncMock()
        result = await service.violate(blocked_row.id, " repeated violation ")
        assert result.status == "VIOLATED"
        assert student.credit_score == 75
        assert student.booking_blocked_until is not None


@pytest.mark.asyncio
async def test_check_in_and_return_guards(seeded, monkeypatch) -> None:
    factory, _, _, student, other_student, _, device, _ = seeded
    async with factory() as session:
        row = _reservation_stub(student, device, status="IN_USE", handover_status="HANDED_OVER")

        def service_for(user, *permissions):
            service = _service(session, user, "STUDENT", permissions=tuple(permissions))
            monkeypatch.setattr(service, "_load_reservation", AsyncMock(return_value=row))
            return service

        with pytest.raises(ApiError) as error:
            await service_for(student).check_in(row.id)
        _assert_api_error(error, "FORBIDDEN")
        with pytest.raises(ApiError) as error:
            await service_for(student, "reservation:check-in").check_in(row.id)
        _assert_api_error(error, "HANDOVER_REQUIRED")
        row.user_id = other_student.id
        with pytest.raises(ApiError) as error:
            await service_for(student, "reservation:check-in").check_in(row.id)
        _assert_api_error(error, "FORBIDDEN")
        row.user_id = student.id

        async def expect_return(
            expected,
            *,
            permissioned=True,
            user=student,
            condition="NORMAL",
            **changes,
        ):
            current = _reservation_stub(
                student,
                device,
                status="IN_USE",
                handover_status="HANDED_OVER",
            )
            current.end_date = date.today()
            for key, value in changes.items():
                setattr(current, key, value)
            permissions = ("reservation:return",) if permissioned else ()
            service = _service(session, user, "STUDENT", permissions=permissions)
            monkeypatch.setattr(service, "_load_reservation", AsyncMock(return_value=current))
            monkeypatch.setattr(
                service,
                "_validate_evidence_images",
                AsyncMock(return_value=["/api/v2/repair-uploads/evidence-token-000000001"]),
            )
            service.session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=0))
            with pytest.raises(ApiError) as error:
                await service.return_device(
                    current.id,
                    condition=condition,
                    image_urls=["valid"],
                )
            _assert_api_error(error, expected)

        await expect_return("FORBIDDEN", permissioned=False)
        await expect_return("FORBIDDEN", user=other_student)
        await expect_return("INVALID_RESERVATION_STATE", status="APPROVED")
        await expect_return("INVALID_RESERVATION_STATE", handover_status="RETURN_PENDING")
        await expect_return("RETURN_DAY_INVALID", end_date=date.today() + timedelta(days=1))
        await expect_return("INSPECTION_INVALID", condition="UNKNOWN")
        unavailable = SimpleNamespace(**device.__dict__)
        unavailable.status = "DISABLED"
        await expect_return("DEVICE_UNAVAILABLE", device=unavailable)
        await expect_return("INVALID_RESERVATION_STATE", handover_status="PENDING")
        await expect_return("RESERVATION_STATE_CHANGED", end_date=date.today())


@pytest.mark.asyncio
async def test_handover_rejects_scope_state_device_maintenance_and_repair_conflicts(
    seeded,
    monkeypatch,
) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        manager_principal = _principal(
            manager,
            "LAB_ADMIN",
            permissions=("reservation:handover",),
        )

        async def expect_handover(expected, *, principal=manager_principal, manageable=True,
                                  row=None, scalar_values=None, blocked=None, condition="NORMAL",
                                  checklist=None, preserve_date=False):
            current = row or _reservation_stub(
                student,
                device,
                status="APPROVED",
                handover_status="PENDING",
            )
            if not preserve_date:
                current.start_date = date.today()
                current.end_date = date.today()
            service = ReservationService(session, principal)
            monkeypatch.setattr(service, "_load_reservation", AsyncMock(return_value=current))
            monkeypatch.setattr(service, "_can_manage_device", AsyncMock(return_value=manageable))
            monkeypatch.setattr(service, "_blocked_dates", AsyncMock(return_value=blocked or {}))
            monkeypatch.setattr(
                service,
                "_validate_evidence_images",
                AsyncMock(return_value=["/api/v2/repair-uploads/handover-evidence-000000001"]),
            )
            monkeypatch.setattr(service, "_ensure_handover_record", AsyncMock())
            service.session.scalar = AsyncMock(
                side_effect=scalar_values if scalar_values is not None else [device, 0]
            )
            service.session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=0))
            with pytest.raises(ApiError) as error:
                await service.handover(
                    current.id,
                    condition=condition,
                    image_urls=["valid"],
                    checklist=checklist or [],
                )
            _assert_api_error(error, expected)

        row = _reservation_stub(student, device, status="APPROVED", handover_status="PENDING")
        await expect_handover("FORBIDDEN", principal=_principal(manager), row=row)
        await expect_handover("FORBIDDEN", manageable=False, row=row)
        await expect_handover(
            "INVALID_RESERVATION_STATE",
            row=_reservation_stub(student, device, status="PENDING"),
        )
        wrong_day = _reservation_stub(student, device, status="APPROVED")
        wrong_day.start_date = date.today() + timedelta(days=1)
        await expect_handover("HANDOVER_DAY_INVALID", row=wrong_day, preserve_date=True)
        await expect_handover("DEVICE_UNAVAILABLE", scalar_values=[None], row=row)
        unavailable = SimpleNamespace(**device.__dict__)
        unavailable.status = "MAINTENANCE"
        await expect_handover("DEVICE_UNAVAILABLE", scalar_values=[unavailable], row=row)
        await expect_handover(
            "DEVICE_MAINTENANCE_RESTRICTION",
            blocked={date.today(): "planned downtime"},
            row=row,
        )
        await expect_handover("DEVICE_REPAIR_OPEN", scalar_values=[device, 1], row=row)
        await expect_handover(
            "HANDOVER_CONDITION_INVALID",
            scalar_values=[device, 0],
            condition="BROKEN",
            row=row,
        )

        mismatch = _reservation_stub(student, device, status="APPROVED", handover_status="PENDING")
        mismatch.start_date = date.today()
        mismatch.end_date = date.today()
        mismatch.device.accessory_checklist = ["case"]
        service = ReservationService(session, manager_principal)
        monkeypatch.setattr(service, "_load_reservation", AsyncMock(return_value=mismatch))
        monkeypatch.setattr(service, "_can_manage_device", AsyncMock(return_value=True))
        monkeypatch.setattr(service, "_blocked_dates", AsyncMock(return_value={}))
        monkeypatch.setattr(
            service,
            "_validate_evidence_images",
            AsyncMock(return_value=["valid"]),
        )
        service.session.scalar = AsyncMock(side_effect=[device, 0])
        with pytest.raises(ApiError) as error:
            await service.handover(mismatch.id, image_urls=["valid"], checklist=[])
        _assert_api_error(error, "CHECKLIST_MISMATCH")


@pytest.mark.asyncio
async def test_handover_normal_and_exception_success_paths(seeded, monkeypatch) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        principal = _principal(
            manager,
            "LAB_ADMIN",
            permissions=("reservation:handover",),
        )

        async def execute_handover(condition, *, already_in_use=False):
            row = _reservation_stub(
                student,
                device,
                status="APPROVED",
                handover_status="PENDING",
            )
            row.start_date = date.today()
            row.end_date = date.today()
            row.device.status = "IN_USE" if already_in_use else "IDLE"
            locked_device = SimpleNamespace(**device.__dict__)
            locked_device.status = "IDLE"
            handover = SimpleNamespace(
                status="PENDING",
                accessory_snapshot=[],
                handover_image_urls=None,
                return_image_urls=None,
                return_checklist=None,
                return_condition=None,
                return_note=None,
                returned_by=None,
                returned_at=None,
            )
            service = ReservationService(session, principal)
            monkeypatch.setattr(service, "_load_reservation", AsyncMock(return_value=row))
            monkeypatch.setattr(service, "_can_manage_device", AsyncMock(return_value=True))
            monkeypatch.setattr(service, "_blocked_dates", AsyncMock(return_value={}))
            monkeypatch.setattr(
                service,
                "_validate_evidence_images",
                AsyncMock(return_value=["/api/v2/repair-uploads/handover-success-token-001"]),
            )
            monkeypatch.setattr(
                service,
                "_ensure_handover_record",
                AsyncMock(return_value=handover),
            )
            monkeypatch.setattr(
                service,
                "_create_fault_repair",
                AsyncMock(return_value=SimpleNamespace(id=99)),
            )
            service.session.scalar = AsyncMock(side_effect=[locked_device, 0])
            service.session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=1))
            service.session.commit = AsyncMock()
            return await service.handover(
                row.id,
                condition=condition,
                image_urls=["valid"],
                checklist=[],
            )

        normal = await execute_handover("NORMAL")
        assert normal.status == "IN_USE"
        assert normal.handover_status == "HANDED_OVER"
        unchanged_status = await execute_handover("NORMAL", already_in_use=True)
        assert unchanged_status.status == "IN_USE"
        abnormal = await execute_handover("MISSING")
        assert abnormal.status == "APPROVED"
        assert abnormal.handover_status == "EXCEPTION"


@pytest.mark.asyncio
async def test_return_acceptance_guards_and_compare_set(seeded, monkeypatch) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        principal = _principal(
            manager,
            "LAB_ADMIN",
            permissions=("reservation:accept-return",),
        )

        async def expect_accept(expected, *, permissioned=True, manageable=True, row=None,
                                condition="NORMAL", handover=None, affected=1):
            current = row or _reservation_stub(
                student,
                device,
                status="IN_USE",
                handover_status="RETURN_PENDING",
            )
            service = ReservationService(
                session,
                principal if permissioned else _principal(manager),
            )
            monkeypatch.setattr(service, "_load_reservation", AsyncMock(return_value=current))
            monkeypatch.setattr(service, "_can_manage_device", AsyncMock(return_value=manageable))
            service.session.scalar = AsyncMock(
                side_effect=[handover] if handover is None else [handover, 0]
            )
            service.session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=affected))
            with pytest.raises(ApiError) as error:
                await service.accept_return(current.id, condition=condition, checklist=[])
            _assert_api_error(error, expected)

        row = _reservation_stub(student, device, status="IN_USE", handover_status="RETURN_PENDING")
        await expect_accept("FORBIDDEN", permissioned=False, row=row)
        await expect_accept("FORBIDDEN", manageable=False, row=row)
        await expect_accept("INVALID_RESERVATION_STATE", row=_reservation_stub(student, device))
        await expect_accept("INSPECTION_INVALID", row=row, condition="BROKEN")
        await expect_accept("RETURN_EVIDENCE_REQUIRED", row=row, handover=None)
        no_evidence = SimpleNamespace(accessory_snapshot=[], return_image_urls=[])
        await expect_accept("RETURN_EVIDENCE_REQUIRED", row=row, handover=no_evidence)
        mismatch = SimpleNamespace(accessory_snapshot=["case"], return_image_urls=["photo"])
        await expect_accept("CHECKLIST_MISMATCH", row=row, handover=mismatch)
        complete_handover = SimpleNamespace(
                    status="RETURN_PENDING",
                    accessory_snapshot=[],
                    handover_image_urls=[],
                    handover_checklist=[],
                    return_image_urls=["photo"],
            returned_by=None,
            returned_at=None,
            return_condition=None,
            return_note="old note",
            return_checklist=None,
            updated_at=None,
        )
        await expect_accept(
            "RESERVATION_STATE_CHANGED",
            row=row,
            handover=complete_handover,
            affected=0,
        )


@pytest.mark.asyncio
async def test_return_acceptance_normal_open_repair_and_fault_paths(seeded, monkeypatch) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        principal = _principal(
            manager,
            "LAB_ADMIN",
            permissions=("reservation:accept-return",),
        )

        async def accept(*, condition="NORMAL", open_repairs=0, note=None, device_status="IN_USE"):
            row = _reservation_stub(
                student,
                device,
                status="IN_USE",
                handover_status="RETURN_PENDING",
            )
            row.device.status = device_status
            row.inspections = []
            handover = SimpleNamespace(
                status="RETURN_PENDING",
                accessory_snapshot=[],
                handover_image_urls=[],
                handover_checklist=[],
                return_image_urls=["photo"],
                returned_by=None,
                returned_at=None,
                return_condition=None,
                return_note="previous note",
                return_checklist=None,
                updated_at=None,
            )
            service = ReservationService(session, principal)
            monkeypatch.setattr(service, "_load_reservation", AsyncMock(return_value=row))
            monkeypatch.setattr(service, "_can_manage_device", AsyncMock(return_value=True))
            monkeypatch.setattr(
                service,
                "_create_fault_repair",
                AsyncMock(return_value=SimpleNamespace(id=501)),
            )
            service.session.scalar = AsyncMock(side_effect=[handover, open_repairs])
            service.session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=1))
            service.session.commit = AsyncMock()
            service.session.add = Mock()
            result = await service.accept_return(
                row.id,
                condition=condition,
                note=note,
                checklist=[],
            )
            return result, row, handover, service

        normal, row, handover, normal_service = await accept()
        assert normal.status == "COMPLETED"
        assert row.inspections == []
        assert handover.return_note == "previous note"
        assert any(
            isinstance(call.args[0], ReservationInspection)
            for call in normal_service.session.add.call_args_list
        )

        maintenance, _, _, _ = await accept(open_repairs=1, note="repair remains open")
        assert maintenance.status == "COMPLETED"

        already_idle, _, _, _ = await accept(device_status="IDLE")
        assert already_idle.status == "COMPLETED"

        damaged, damaged_row, damaged_handover, service = await accept(
            condition="DAMAGED",
            note="cracked cover",
        )
        assert damaged.status == "COMPLETED"
        assert damaged.fault_repair_id == 501
        assert damaged_row.fault_repair.id == 501
        service._create_fault_repair.assert_awaited_once()


@pytest.mark.asyncio
async def test_maintenance_impact_notification_empty_due_and_dedup_paths(seeded) -> None:
    factory, _, _, student, _, manager, _, _ = seeded

    class Rows:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    async with factory() as session:
        service = _service(session, manager, "SYS_ADMIN")
        await service._enqueue_maintenance_impact_notifications_many([])

        target = date.today() + timedelta(days=5)
        reservation = SimpleNamespace(
            id=71,
            device_id=72,
            college_id=student.college_id,
            user_id=student.id,
            start_date=target,
            end_date=target,
            device=None,
        )
        no_notice = SimpleNamespace(
            id=73,
            device_id=72,
            due_date=target - timedelta(days=1),
            due_notice_sent_at=None,
            title="No prior reminder",
        )
        service.session.scalars = AsyncMock(return_value=Rows([no_notice]))
        service.session.add = Mock()
        await service._enqueue_maintenance_impact_notifications_many([reservation])
        service.session.add.assert_not_called()

        already_due = SimpleNamespace(
            id=74,
            device_id=72,
            due_date=target + timedelta(days=1),
            due_notice_sent_at=datetime.now(UTC).replace(tzinfo=None),
            title="Due after booking",
        )
        service.session.scalars = AsyncMock(return_value=Rows([already_due]))
        await service._enqueue_maintenance_impact_notifications_many([reservation])
        service.session.add.assert_not_called()

        overdue = SimpleNamespace(
            id=75,
            device_id=72,
            due_date=target - timedelta(days=1),
            due_notice_sent_at=datetime.now(UTC).replace(tzinfo=None),
            title="Already notified",
        )
        key = f"maintenance:impact:{overdue.id}:{reservation.id}:{overdue.due_date.isoformat()}"
        service.session.scalars = AsyncMock(side_effect=[Rows([overdue]), Rows([key])])
        await service._enqueue_maintenance_impact_notifications_many([reservation])
        service.session.add.assert_not_called()

        service.session.scalars = AsyncMock(side_effect=[Rows([overdue]), Rows([])])
        await service._enqueue_maintenance_impact_notifications_many([reservation])
        service.session.add.assert_called_once()
        generated = service.session.add.call_args.args[0]
        assert generated.task_key == key
        assert "#72" in generated.payload["content"]


@pytest.mark.asyncio
async def test_pending_approval_and_handover_views_cover_tenant_and_global_scopes(seeded) -> None:
    factory, _, _, student, _, manager, _, _ = seeded
    async with factory() as session:
        denied = _service(session, student, "STUDENT")
        with pytest.raises(ApiError) as error:
            await denied.pending_approvals()
        _assert_api_error(error, "FORBIDDEN")
        with pytest.raises(ApiError) as error:
            await denied.pending_handovers(status="INVALID")
        _assert_api_error(error, "HANDOVER_STATUS_INVALID")
        with pytest.raises(ApiError) as error:
            await denied.pending_handovers(status="PENDING")
        _assert_api_error(error, "FORBIDDEN")

        scoped_manager = _service(
            session,
            manager,
            "LAB_ADMIN",
            permissions=("reservation:approve", "reservation:handover"),
        )
        assert (await scoped_manager.pending_approvals()).total == 0
        assert (await scoped_manager.pending_handovers(status="PENDING")).total == 0
        assert (await scoped_manager.pending_handovers(status="EXCEPTION")).total == 0

        return_manager = _service(
            session,
            manager,
            "LAB_ADMIN",
            permissions=("reservation:accept-return",),
        )
        assert (await return_manager.pending_handovers(status="RETURN_PENDING")).total == 0

        global_manager = _service(
            session,
            manager,
            "SYS_ADMIN",
            permissions=("reservation:approve", "reservation:handover"),
        )
        assert (await global_manager.pending_approvals()).total == 0
        assert (await global_manager.pending_handovers(status="PENDING")).total == 0
