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
    Column(
        "user_id",
        BIGINT,
        ForeignKey("sys_user.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        BIGINT,
        ForeignKey("sys_role.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

role_permissions = Table(
    "sys_role_permission",
    Base.metadata,
    Column(
        "role_id",
        BIGINT,
        ForeignKey("sys_role.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        BIGINT,
        ForeignKey("sys_permission.id", ondelete="CASCADE"),
        primary_key=True,
    ),
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
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    users: Mapped[list["User"]] = relationship(
        secondary=user_roles,
        back_populates="roles",
    )
    permissions: Mapped[list["Permission"]] = relationship(
        secondary=role_permissions,
        back_populates="roles",
    )


class Permission(Base):
    __tablename__ = "sys_permission"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    permission_code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    permission_name: Mapped[str] = mapped_column(String(100))
    module: Mapped[str] = mapped_column(String(50), index=True)
    description: Mapped[str | None] = mapped_column(String(255))

    roles: Mapped[list[Role]] = relationship(
        secondary=role_permissions,
        back_populates="permissions",
    )


class AuthorizationVersion(Base):
    __tablename__ = "v2_authz_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
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


class DevicePool(TimestampMixin, Base):
    """A user-facing group of interchangeable physical device records."""

    __tablename__ = "v2_device_pool"
    __table_args__ = (Index("idx_v2_device_pool_college_lab_id", "college_id", "lab_id", "id"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    college_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("college.id"), index=True)
    lab_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("lab.id"), index=True)

    devices: Mapped[list["Device"]] = relationship(back_populates="pool")


class Device(TimestampMixin, Base):
    __tablename__ = "device"
    __table_args__ = (
        Index("idx_device_college_status_id_v2", "college_id", "status", "id"),
        Index("idx_device_college_lab_id_v2", "college_id", "lab_id", "id"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    pool_id: Mapped[int | None] = mapped_column(
        BIGINT,
        ForeignKey("v2_device_pool.id"),
        index=True,
    )
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
    accessory_checklist: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    asset_code: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)
    serial_number: Mapped[str | None] = mapped_column(String(120), index=True)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    warranty_until: Mapped[date | None] = mapped_column(Date)
    allow_external_loan: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="STANDARD", nullable=False)
    requires_safety_ack: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_qualification: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_advance_days: Mapped[int | None] = mapped_column(Integer)

    lab: Mapped[Lab | None] = relationship(back_populates="devices")
    college: Mapped[College | None] = relationship(back_populates="devices")
    category: Mapped[DeviceCategory | None] = relationship(back_populates="devices")
    pool: Mapped[DevicePool | None] = relationship(back_populates="devices")
    reservations: Mapped[list["Reservation"]] = relationship(back_populates="device")
    reservation_days: Mapped[list["ReservationItem"]] = relationship(back_populates="device")
    status_history: Mapped[list["DeviceStatusHistory"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list["DeviceDocument"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
    )
    handovers: Mapped[list["DeviceHandover"]] = relationship(
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
    purpose_category: Mapped[str] = mapped_column(String(40), default="OTHER", nullable=False)
    project_reference: Mapped[str | None] = mapped_column(String(160))
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
    handover_status: Mapped[str] = mapped_column(String(24), default="NOT_REQUIRED", nullable=False)
    safety_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    safety_document_version: Mapped[str | None] = mapped_column(String(40))

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
    handover: Mapped["DeviceHandover | None"] = relationship(
        back_populates="reservation",
        uselist=False,
        cascade="all, delete-orphan",
    )
    fault_repair: Mapped["RepairReport | None"] = relationship(
        back_populates="reservation",
        uselist=False,
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
    image_urls: Mapped[list[str] | None] = mapped_column(JSON)
    checklist: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
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
    purpose_category: Mapped[str] = mapped_column(String(40), default="OTHER", nullable=False)
    project_reference: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="WAITING", index=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReservationWaitlistOffer(Base):
    """Exclusive, expiring hold for the current head of a device-day queue."""

    __tablename__ = "v2_reservation_waitlist_offer"
    __table_args__ = (
        UniqueConstraint("device_id", "reservation_date", name="uk_v2_waitlist_offer_device_day"),
        UniqueConstraint("waitlist_id", name="uk_v2_waitlist_offer_entry"),
        Index("idx_v2_waitlist_offer_expiry", "expires_at", "id"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    waitlist_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("v2_reservation_waitlist.id", ondelete="CASCADE"),
    )
    device_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("device.id", ondelete="CASCADE"))
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id", ondelete="CASCADE"))
    reservation_date: Mapped[date] = mapped_column(Date)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
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


class ReservationRule(TimestampMixin, Base):
    """Booking constraints scoped by user category and organization/resource."""

    __tablename__ = "v2_reservation_rule"
    __table_args__ = (
        UniqueConstraint(
            "scope_type",
            "scope_id",
            "user_category",
            name="uk_v2_reservation_rule_scope_category",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[int] = mapped_column(BIGINT, default=0, nullable=False)
    user_category: Mapped[str] = mapped_column(String(20), default="ALL", nullable=False)
    max_booking_days: Mapped[int | None] = mapped_column(Integer)
    max_advance_days: Mapped[int | None] = mapped_column(Integer)
    approval_required: Mapped[bool | None] = mapped_column(Boolean)
    created_by: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    updated_by: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"))


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


class CollegeCreditAccount(Base):
    """Per-college credit balance; credit history remains in CreditEvent."""

    __tablename__ = "v2_college_credit_account"
    __table_args__ = (
        UniqueConstraint("user_id", "college_id", name="uk_v2_college_credit_user_college"),
        Index("idx_v2_college_credit_college_points", "college_id", "points"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("college.id"), index=True)
    points: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PenaltyRuleVersion(Base):
    """Immutable college-wide violation rules, versioned by effective time."""

    __tablename__ = "v2_penalty_rule_version"
    __table_args__ = (
        UniqueConstraint("college_id", "version", name="uk_v2_penalty_rule_college_version"),
        Index("idx_v2_penalty_rule_effective", "college_id", "effective_at", "version"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    college_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("college.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    grace_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tiers: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PenaltyCase(Base):
    """One confirmed violation and its immutable initial penalty snapshot."""

    __tablename__ = "v2_penalty_case"
    __table_args__ = (
        UniqueConstraint("reservation_id", "violation_type", name="uk_v2_penalty_reservation_type"),
        Index("idx_v2_penalty_user_college_event", "user_id", "college_id", "event_at"),
        Index("idx_v2_penalty_college_status", "college_id", "status", "applied_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    reservation_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("reservation.id"), index=True)
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("college.id"), index=True)
    lab_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("lab.id"), index=True)
    device_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("device.id"), index=True)
    violation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    rule_version_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("v2_penalty_rule_version.id")
    )
    occurrence_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    points_delta: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reservation_block_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False, index=True)
    confirmed_by: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    applied_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReservationOverdue(Base):
    """Return deadline, follow-up, and escalation state for an overdue reservation."""

    __tablename__ = "v2_reservation_overdue"
    __table_args__ = (
        UniqueConstraint("reservation_id", name="uk_v2_reservation_overdue_reservation"),
        Index(
            "idx_v2_reservation_overdue_scope_status",
            "college_id",
            "status",
            "grace_deadline_at",
        ),
        Index("idx_v2_reservation_overdue_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    reservation_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("reservation.id"), index=True)
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("college.id"), index=True)
    lab_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("lab.id"), index=True)
    device_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("device.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    grace_deadline_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    rule_version_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("v2_penalty_rule_version.id")
    )
    penalty_case_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("v2_penalty_case.id"))
    status: Mapped[str] = mapped_column(String(24), default="GRACE", nullable=False, index=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime)
    escalated_by: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    escalation_reason: Mapped[str | None] = mapped_column(String(1000))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReservationOverdueFollowUp(Base):
    """Append-only manager contact log for one overdue equipment case."""

    __tablename__ = "v2_reservation_overdue_followup"
    __table_args__ = (Index("idx_v2_overdue_followup_case_time", "overdue_id", "contacted_at"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    overdue_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("v2_reservation_overdue.id", ondelete="CASCADE"), index=True
    )
    operator_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    contacted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    result: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReservationBookingRestriction(Base):
    """Active reservation or handover hold created by a penalty/escalation."""

    __tablename__ = "v2_reservation_booking_restriction"
    __table_args__ = (
        UniqueConstraint("penalty_case_id", name="uk_v2_booking_restriction_penalty"),
        UniqueConstraint("overdue_id", name="uk_v2_booking_restriction_overdue"),
        Index(
            "idx_v2_booking_restriction_user_scope",
            "user_id",
            "college_id",
            "scope_type",
            "scope_id",
            "ends_at",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("college.id"), index=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    penalty_case_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("v2_penalty_case.id", ondelete="SET NULL")
    )
    overdue_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("v2_reservation_overdue.id", ondelete="SET NULL")
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime)
    release_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PenaltyAppeal(Base):
    """A user's appeal and its manager's auditable disposition."""

    __tablename__ = "v2_penalty_appeal"
    __table_args__ = (
        UniqueConstraint("penalty_case_id", "attempt_number", name="uk_v2_penalty_appeal_attempt"),
        Index("idx_v2_penalty_appeal_college_status", "college_id", "status", "submitted_at"),
        Index("idx_v2_penalty_appeal_user", "user_id", "submitted_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    penalty_case_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("v2_penalty_case.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("college.id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    evidence: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False, index=True)
    reviewer_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    result: Mapped[str | None] = mapped_column(String(20))
    result_reason: Mapped[str | None] = mapped_column(String(2000))
    adjusted_points_delta: Mapped[int | None] = mapped_column(Integer)
    adjusted_block_days: Mapped[int | None] = mapped_column(Integer)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PenaltyGraceBounds(Base):
    """School-wide configurable lower/upper bounds for college grace periods."""

    __tablename__ = "v2_penalty_grace_bounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    minimum_days: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_days: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RefreshSession(Base):
    """Rotatable refresh-token family record."""

    __tablename__ = "v2_refresh_session"
    __table_args__ = (
        UniqueConstraint("token_id", name="uk_v2_refresh_token_id"),
        Index("idx_v2_refresh_user_active", "user_id", "revoked_at", "expires_at"),
        Index("idx_v2_refresh_family_active", "family_id", "revoked_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    token_id: Mapped[str] = mapped_column(String(64))
    family_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("sys_user.id", ondelete="CASCADE"),
        index=True,
    )
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
    user_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("sys_user.id", ondelete="CASCADE"),
        index=True,
    )
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UploadQuotaBucket(Base):
    """Cross-process byte counters serialized by row locks during upload."""

    __tablename__ = "v2_upload_quota_bucket"
    __table_args__ = (UniqueConstraint("scope_type", "scope_id", name="uk_v2_upload_quota_scope"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[int] = mapped_column(BIGINT, default=0)
    used_bytes: Mapped[int] = mapped_column(BIGINT, default=0, nullable=False)


class DeviceDocument(Base):
    """Published device manual/SOP metadata backed by a private upload asset."""

    __tablename__ = "v2_device_document"
    __table_args__ = (
        Index("idx_v2_device_document_device_active", "device_id", "active", "created_at"),
        Index("idx_v2_device_document_college_active", "college_id", "active", "created_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("device.id", ondelete="CASCADE"),
        index=True,
    )
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    asset_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("v2_upload_asset.id", ondelete="CASCADE"),
        index=True,
    )
    document_type: Mapped[str] = mapped_column(String(20), default="MANUAL")
    title: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(40), default="1.0", nullable=False)
    requires_ack: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime)

    device: Mapped[Device] = relationship(back_populates="documents")
    asset: Mapped[UploadAsset] = relationship()


class DeviceDocumentAcknowledgement(Base):
    """Records which user acknowledged which published device document."""

    __tablename__ = "v2_device_document_ack"
    __table_args__ = (
        UniqueConstraint("document_id", "user_id", name="uk_v2_device_document_ack_user"),
        Index("idx_v2_device_document_ack_user", "user_id", "acknowledged_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("v2_device_document.id", ondelete="CASCADE"),
        index=True,
    )
    device_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("device.id"), index=True)
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    reservation_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("reservation.id"))
    document_version: Mapped[str] = mapped_column(String(40))
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DeviceQualification(TimestampMixin, Base):
    """User qualification for a controlled or high-risk device."""

    __tablename__ = "v2_device_qualification"
    __table_args__ = (
        UniqueConstraint("device_id", "user_id", name="uk_v2_device_qualification_user"),
        Index("idx_v2_device_qualification_scope_status", "college_id", "status", "valid_until"),
        Index("idx_v2_device_qualification_user_status", "user_id", "status", "valid_until"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("device.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False, index=True)
    qualification_type: Mapped[str] = mapped_column(String(80), default="TRAINING")
    asset_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("v2_upload_asset.id"))
    valid_until: Mapped[date | None] = mapped_column(Date)
    reviewed_by: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(String(500))


class DeviceHandover(TimestampMixin, Base):
    """Physical handover and return evidence for a reservation."""

    __tablename__ = "v2_device_handover"
    __table_args__ = (
        UniqueConstraint("reservation_id", name="uk_v2_device_handover_reservation"),
        Index("idx_v2_device_handover_device_status", "device_id", "status", "created_at"),
        Index("idx_v2_device_handover_scope_status", "college_id", "status"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    reservation_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("reservation.id", ondelete="CASCADE"),
    )
    device_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("device.id"), index=True)
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False, index=True)
    handover_by: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    handover_at: Mapped[datetime | None] = mapped_column(DateTime)
    handover_condition: Mapped[str | None] = mapped_column(String(20))
    handover_note: Mapped[str | None] = mapped_column(String(1000))
    accessory_snapshot: Mapped[list[str] | None] = mapped_column(JSON)
    handover_checklist: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    handover_image_urls: Mapped[list[str] | None] = mapped_column(JSON)
    returned_by: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    returned_at: Mapped[datetime | None] = mapped_column(DateTime)
    return_condition: Mapped[str | None] = mapped_column(String(20))
    return_note: Mapped[str | None] = mapped_column(String(1000))
    return_checklist: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    return_image_urls: Mapped[list[str] | None] = mapped_column(JSON)

    reservation: Mapped[Reservation] = relationship(back_populates="handover")
    device: Mapped[Device] = relationship(back_populates="handovers")


class RepairWorklog(Base):
    """Append-only repair processing timeline entry."""

    __tablename__ = "v2_repair_worklog"
    __table_args__ = (Index("idx_v2_repair_worklog_report_created", "report_id", "created_at"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("v2_repair_report.id", ondelete="CASCADE"),
        index=True,
    )
    operator_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    status: Mapped[str] = mapped_column(String(24))
    content: Mapped[str] = mapped_column(String(2000))
    image_urls: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ExportTask(TimestampMixin, Base):
    """Durable asynchronous CSV/Excel export request."""

    __tablename__ = "v2_export_task"
    __table_args__ = (
        Index("idx_v2_export_task_user_status_created", "requester_id", "status", "created_at"),
        Index("idx_v2_export_task_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    requester_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    export_type: Mapped[str] = mapped_column(String(40))
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False, index=True)
    file_token: Mapped[str | None] = mapped_column(String(96), unique=True, index=True)
    file_path: Mapped[str | None] = mapped_column(String(500))
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(String(1000))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


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
    __table_args__ = (
        Index("idx_notification_user_read_id_v2", "user_id", "is_read", "id"),
        Index(
            "uq_notification_user_delivery_sequence", "user_id", "delivery_sequence", unique=True
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    college_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(String(1000))
    related_id: Mapped[int | None] = mapped_column(BIGINT)
    related_type: Mapped[str | None] = mapped_column(String(50))
    source_task_key: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    delivery_sequence: Mapped[int] = mapped_column(BIGINT, nullable=False)


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
    reservation_id: Mapped[int | None] = mapped_column(
        BIGINT,
        ForeignKey("reservation.id", ondelete="SET NULL"),
        unique=True,
    )
    reporter_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    image_urls: Mapped[list[str] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    handler_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("sys_user.id"))
    priority: Mapped[str] = mapped_column(String(20), default="NORMAL", nullable=False, index=True)
    response_due_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    resolve_due_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    resolution_note: Mapped[str | None] = mapped_column(String(1000))
    taken_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    user_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    user_confirmation_note: Mapped[str | None] = mapped_column(String(500))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)

    device: Mapped["Device"] = relationship(foreign_keys=[device_id])
    reporter: Mapped["User"] = relationship(foreign_keys=[reporter_id])
    handler: Mapped["User | None"] = relationship(foreign_keys=[handler_id])
    reservation: Mapped["Reservation | None"] = relationship(back_populates="fault_repair")
    worklogs: Mapped[list["RepairWorklog"]] = relationship(
        cascade="all, delete-orphan",
        primaryjoin="RepairReport.id == foreign(RepairWorklog.report_id)",
    )


class DeviceMaintenancePlan(TimestampMixin, Base):
    """One recurring maintenance, calibration or safety-check schedule."""

    __tablename__ = "v2_device_maintenance_plan"
    __table_args__ = (
        Index("idx_v2_maintenance_device_active", "device_id", "active"),
        Index("idx_v2_maintenance_due_active", "active", "due_date", "plan_type"),
        Index("idx_v2_maintenance_scope", "college_id", "active", "id"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("device.id", ondelete="CASCADE"),
        nullable=False,
    )
    college_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("college.id"))
    plan_type: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    interval_value: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_unit: Mapped[str] = mapped_column(String(12), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    downtime_start: Mapped[date | None] = mapped_column(Date)
    downtime_end: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    due_notice_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), nullable=False)
    updated_by: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), nullable=False)

    device: Mapped[Device] = relationship()
    records: Mapped[list["DeviceMaintenanceRecord"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="DeviceMaintenanceRecord.id.desc()",
    )


class DeviceMaintenanceRecord(Base):
    """Auditable result for a single completed maintenance cycle."""

    __tablename__ = "v2_device_maintenance_record"
    __table_args__ = (
        UniqueConstraint("plan_id", "idempotency_key", name="uk_v2_maintenance_record_request"),
        Index("idx_v2_maintenance_record_plan_date", "plan_id", "cycle_due_date", "id"),
        Index("idx_v2_maintenance_record_device_date", "device_id", "completed_date", "id"),
        Index("ix_v2_device_maintenance_record_evidence_asset_id", "evidence_asset_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("v2_device_maintenance_plan.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("device.id", ondelete="CASCADE"),
        nullable=False,
    )
    college_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("college.id"), index=True)
    cycle_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed_date: Mapped[date] = mapped_column(Date, nullable=False)
    downtime_start: Mapped[date | None] = mapped_column(Date)
    downtime_end: Mapped[date | None] = mapped_column(Date)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(2000))
    performed_by: Mapped[int] = mapped_column(BIGINT, ForeignKey("sys_user.id"), nullable=False)
    evidence_asset_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("v2_upload_asset.id"))
    repair_report_id: Mapped[int | None] = mapped_column(
        BIGINT,
        ForeignKey("v2_repair_report.id", ondelete="SET NULL"),
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    plan: Mapped[DeviceMaintenancePlan] = relationship(back_populates="records")
    evidence_asset: Mapped[UploadAsset | None] = relationship()
    repair_report: Mapped[RepairReport | None] = relationship()
    performer: Mapped[User] = relationship(foreign_keys=[performed_by])
