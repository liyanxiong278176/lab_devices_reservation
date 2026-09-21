from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, TimestampMixin

BIGINT = BigInteger().with_variant(Integer, "sqlite")

user_roles = Table(
    "sys_user_role",
    Base.metadata,
    Column("user_id", BIGINT, ForeignKey("sys_user.id"), primary_key=True),
    Column("role_id", BIGINT, ForeignKey("sys_role.id"), primary_key=True),
)


class College(TimestampMixin, Base):
    __tablename__ = "college"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    manager_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)

    users: Mapped[list["User"]] = relationship(
        back_populates="college",
        foreign_keys="User.college_id",
    )
    labs: Mapped[list["Lab"]] = relationship(back_populates="college")
    devices: Mapped[list["Device"]] = relationship(back_populates="college")


class Role(Base):
    __tablename__ = "sys_role"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    role_code: Mapped[str] = mapped_column(String(50), unique=True)
    role_name: Mapped[str] = mapped_column(String(50))

    users: Mapped[list["User"]] = relationship(
        secondary=user_roles,
        back_populates="roles",
    )


class User(TimestampMixin, Base):
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column("password", String(255))
    real_name: Mapped[str | None] = mapped_column(String(50))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(100))
    user_type: Mapped[str] = mapped_column(String(20), default="STUDENT")
    college_id: Mapped[int | None] = mapped_column(
        BIGINT,
        ForeignKey("college.id"),
        index=True,
    )
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    credit_score: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    booking_blocked_until: Mapped[datetime | None] = mapped_column(DateTime)

    college: Mapped[College | None] = relationship(
        back_populates="users",
        foreign_keys=[college_id],
    )
    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles,
        back_populates="users",
    )
    reservations: Mapped[list["Reservation"]] = relationship(
        back_populates="user",
        foreign_keys="Reservation.user_id",
    )


class Lab(TimestampMixin, Base):
    __tablename__ = "lab"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    college_id: Mapped[int | None] = mapped_column(
        BIGINT,
        ForeignKey("college.id"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(200))
    manager_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    description: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    college: Mapped[College | None] = relationship(back_populates="labs")
    manager: Mapped[User | None] = relationship(foreign_keys=[manager_id])
    devices: Mapped[list["Device"]] = relationship(back_populates="lab")


class DeviceCategory(Base):
    __tablename__ = "device_category"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[int] = mapped_column(BIGINT, default=0)
    sort: Mapped[int] = mapped_column(Integer, default=0)

    devices: Mapped[list["Device"]] = relationship(back_populates="category")


class Device(TimestampMixin, Base):
    __tablename__ = "device"
    __table_args__ = (
        Index("idx_device_college_status_id_v2", "college_id", "status", "id"),
        Index("idx_device_college_lab_id_v2", "college_id", "lab_id", "id"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    college_id: Mapped[int | None] = mapped_column(
        BIGINT,
        ForeignKey("college.id"),
        index=True,
    )
    lab_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("lab.id"), index=True)
    category_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("device_category.id"))
    name: Mapped[str] = mapped_column(String(100), index=True)
    brand: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    specs: Mapped[str | None] = mapped_column(String(500))
    image_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="IDLE", index=True)
    need_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_reservation_days: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str] | None] = mapped_column(JSON)

    lab: Mapped[Lab | None] = relationship(back_populates="devices")
    college: Mapped[College | None] = relationship(back_populates="devices")
    category: Mapped[DeviceCategory | None] = relationship(back_populates="devices")
    reservations: Mapped[list["Reservation"]] = relationship(back_populates="device")
    reservation_days: Mapped[list["ReservationItem"]] = relationship(back_populates="device")
    status_history: Mapped[list["DeviceStatusHistory"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
    )


class Reservation(TimestampMixin, Base):
    __tablename__ = "reservation"
    __table_args__ = (
        Index("idx_reservation_user_id_v2", "user_id", "id"),
        Index("idx_reservation_college_status_id_v2", "college_id", "status", "id"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    device_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("device.id"), index=True)
    purpose: Mapped[str | None] = mapped_column(String(500))
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date, index=True)
    # Legacy columns remain nullable during migration from the old time-slot model.
    start_time: Mapped[datetime | None] = mapped_column(DateTime)
    end_time: Mapped[datetime | None] = mapped_column(DateTime)
    slot_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    approver_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    reject_reason: Mapped[str | None] = mapped_column(String(500))
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped[User] = relationship(back_populates="reservations", foreign_keys=[user_id])
    device: Mapped[Device] = relationship(back_populates="reservations")
    days: Mapped[list["ReservationItem"]] = relationship(
        back_populates="reservation",
        cascade="all, delete-orphan",
    )
    inspections: Mapped[list["ReservationInspection"]] = relationship(
        back_populates="reservation",
        cascade="all, delete-orphan",
    )
    feedback: Mapped["ReservationFeedback | None"] = relationship(
        back_populates="reservation",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ReservationFeedback(Base):
    """One post-use satisfaction record for a completed reservation."""

    __tablename__ = "v2_reservation_feedback"
    __table_args__ = (
        UniqueConstraint("reservation_id", name="uk_v2_feedback_reservation"),
        Index("idx_v2_feedback_device_created", "device_id", "created_at"),
        Index("idx_v2_feedback_college_created", "college_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    reservation_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("reservation.id", ondelete="CASCADE"),
    )
    device_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("device.id"), index=True)
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    reservation: Mapped[Reservation] = relationship(back_populates="feedback")


class ReservationItem(Base):
    """One occupied device-day; old minute-slot rows remain untouched."""

    __tablename__ = "v2_reservation_day"
    __table_args__ = (
        UniqueConstraint("device_id", "date", name="uk_device_date_v2"),
        Index("idx_device_date_v2", "device_id", "date"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    reservation_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("reservation.id", ondelete="CASCADE"),
        index=True,
    )
    device_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("device.id"), index=True)
    reservation_date: Mapped[date] = mapped_column("date", Date, index=True)
    slot_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    reservation: Mapped[Reservation] = relationship(back_populates="days")
    device: Mapped[Device] = relationship(back_populates="reservation_days")


class DeviceStatusHistory(Base):
    """Auditable device lifecycle transition."""

    __tablename__ = "v2_device_status_history"
    __table_args__ = (
        Index("idx_v2_device_status_history_device_created", "device_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("device.id", ondelete="CASCADE"),
        index=True,
    )
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    old_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(500))
    operator_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    device: Mapped[Device] = relationship(back_populates="status_history")


class ReservationInspection(Base):
    """Daily reservation return acceptance record."""

    __tablename__ = "v2_reservation_inspection"
    __table_args__ = (
        UniqueConstraint("reservation_id", name="uk_v2_reservation_inspection_reservation"),
        Index("idx_v2_reservation_inspection_device", "device_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    reservation_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("reservation.id", ondelete="CASCADE"),
    )
    device_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("device.id"), index=True)
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    condition: Mapped[str] = mapped_column(String(20), default="NORMAL")
    note: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    reservation: Mapped[Reservation] = relationship(back_populates="inspections")


class ReservationWaitlist(Base):
    """One waiting request for a device on one natural day."""

    __tablename__ = "v2_reservation_waitlist"
    __table_args__ = (
        UniqueConstraint(
            "device_id",
            "reservation_date",
            "user_id",
            name="uk_v2_waitlist_device_date_user",
        ),
        Index("idx_v2_waitlist_device_date_status", "device_id", "reservation_date", "status"),
        Index("idx_v2_waitlist_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("device.id"), index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    reservation_date: Mapped[date] = mapped_column(Date)
    purpose: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="WAITING", index=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReservationBlackout(Base):
    """Configured non-bookable natural day at college/lab/device scope."""

    __tablename__ = "v2_reservation_blackout"
    __table_args__ = (
        UniqueConstraint(
            "scope_type",
            "scope_id",
            "blocked_date",
            name="uk_v2_blackout_scope_date",
        ),
        Index("idx_v2_blackout_scope_date", "scope_type", "scope_id", "blocked_date"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String(20))
    scope_id: Mapped[int] = mapped_column(BIGINT)
    blocked_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CreditEvent(Base):
    """Immutable user credit change caused by a reservation event."""

    __tablename__ = "v2_credit_event"
    __table_args__ = (Index("idx_v2_credit_event_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    reservation_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("reservation.id"))
    event_type: Mapped[str] = mapped_column(String(40))
    points: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    operator_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RefreshSession(Base):
    """Rotatable refresh-token family record."""

    __tablename__ = "v2_refresh_session"
    __table_args__ = (
        UniqueConstraint("token_id", name="uk_v2_refresh_token_id"),
        Index("idx_v2_refresh_user_active", "user_id", "revoked_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    token_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    replaced_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    """Small append-only audit record for non-AI business mutations."""

    __tablename__ = "v2_audit_log"
    __table_args__ = (
        Index("idx_v2_audit_scope_created", "college_id", "created_at"),
        Index("idx_v2_audit_target_created", "target_type", "target_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[int | None] = mapped_column(BIGINT)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UploadAsset(Base):
    """Validated private upload referenced by a non-AI business record."""

    __tablename__ = "v2_upload_asset"
    __table_args__ = (
        UniqueConstraint("asset_token", name="uk_v2_upload_asset_token"),
        Index("idx_v2_upload_asset_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    asset_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OutboxTask(Base):
    __tablename__ = "v2_outbox_task"
    __table_args__ = (
        UniqueConstraint("task_key", name="uk_v2_outbox_task_key"),
        Index("idx_v2_outbox_status_execute", "status", "execute_at", "id"),
        Index("idx_v2_outbox_aggregate_status", "aggregate_key", "status", "id"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    task_key: Mapped[str] = mapped_column(String(128))
    task_type: Mapped[str] = mapped_column(String(64), index=True)
    aggregate_key: Mapped[str | None] = mapped_column(String(128), index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    execute_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)


class IdempotencyKey(Base):
    __tablename__ = "v2_idempotency_key"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uk_v2_idempotency_user_key"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT, index=True)
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(128))
    response_code: Mapped[str | None] = mapped_column(String(32))
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Notification(TimestampMixin, Base):
    __tablename__ = "notification"
    __table_args__ = (Index("idx_notification_user_read_id_v2", "user_id", "is_read", "id"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT, index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(String(1000))
    related_id: Mapped[int | None] = mapped_column(BIGINT)
    related_type: Mapped[str | None] = mapped_column(String(50))
    source_task_key: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class RepairReport(TimestampMixin, Base):
    """Tenant-scoped repair ticket used by both the web UI and AI write previews."""

    __tablename__ = "v2_repair_report"
    __table_args__ = (
        Index("idx_v2_repair_scope_status", "college_id", "status", "created_at"),
        Index("idx_v2_repair_reporter", "reporter_id", "created_at"),
        Index("idx_v2_repair_device_status", "device_id", "status"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("college.id"), index=True)
    device_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("device.id"), index=True)
    reporter_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    image_urls: Mapped[list[str] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    handler_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    resolution_note: Mapped[str | None] = mapped_column(String(1000))
    taken_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)

    device: Mapped["Device"] = relationship(foreign_keys=[device_id])
    reporter: Mapped["User"] = relationship(foreign_keys=[reporter_id])
    handler: Mapped["User | None"] = relationship(foreign_keys=[handler_id])


class AiProviderConfig(TimestampMixin, Base):
    __tablename__ = "v2_ai_provider_config"
    __table_args__ = (UniqueConstraint("scope_key", name="uk_v2_ai_provider_scope"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    scope_key: Mapped[str] = mapped_column(String(80), default="global")
    college_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("college.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="openai")
    model: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str | None] = mapped_column(String(500))
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    daily_quota: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AiConversation(TimestampMixin, Base):
    __tablename__ = "v2_ai_conversation"
    __table_args__ = (
        Index("idx_v2_ai_conversation_user_updated", "user_id", "updated_at"),
        Index("idx_v2_ai_conversation_college", "college_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    graph_thread_id: Mapped[str] = mapped_column(String(80), unique=True)


class AiMessage(Base):
    __tablename__ = "v2_ai_message"
    __table_args__ = (
        Index("idx_v2_ai_message_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("v2_ai_conversation.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class AiRun(Base):
    __tablename__ = "v2_ai_run"
    __table_args__ = (
        UniqueConstraint("run_key", name="uk_v2_ai_run_key"),
        Index("idx_v2_ai_run_conversation", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    run_key: Mapped[str] = mapped_column(String(100))
    conversation_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("v2_ai_conversation.id"))
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING", index=True)
    input_text: Mapped[str] = mapped_column(Text)
    output_text: Mapped[str | None] = mapped_column(Text)
    state_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    citations_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class AiConfirmation(Base):
    __tablename__ = "v2_ai_confirmation"
    __table_args__ = (Index("idx_v2_ai_confirmation_user_status", "user_id", "status"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("v2_ai_run.id", ondelete="CASCADE"))
    conversation_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("v2_ai_conversation.id"))
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    tool_name: Mapped[str] = mapped_column(String(80))
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    preview_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class KnowledgeDocument(TimestampMixin, Base):
    __tablename__ = "v2_knowledge_document"
    __table_args__ = (Index("idx_v2_knowledge_scope_status", "college_id", "status"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    title: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(40), default="FAQ")
    body: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    created_by: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    checksum: Mapped[str] = mapped_column(String(64))


class KnowledgeChunk(Base):
    __tablename__ = "v2_knowledge_chunk"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uk_v2_knowledge_chunk_order"),
        UniqueConstraint("point_id", name="uk_v2_knowledge_chunk_point"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("v2_knowledge_document.id", ondelete="CASCADE"),
        index=True,
    )
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    point_id: Mapped[str] = mapped_column(String(100))
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON)
