from typing import Final

ACTIVE_RESERVATION_STATUSES: Final[tuple[str, ...]] = ("PENDING", "APPROVED", "IN_USE")
TERMINAL_RESERVATION_STATUSES: Final[tuple[str, ...]] = (
    "COMPLETED",
    "CANCELLED",
    "REJECTED",
    "NO_SHOW",
    "VIOLATED",
)

RESERVATION_TRANSITIONS: Final[dict[str, tuple[str, ...]]] = {
    "PENDING": ("APPROVED", "CANCELLED"),
    "APPROVED": ("IN_USE", "CANCELLED", "NO_SHOW", "VIOLATED"),
    "IN_USE": ("COMPLETED", "VIOLATED"),
    "COMPLETED": (),
    "CANCELLED": (),
    "REJECTED": (),
    "NO_SHOW": (),
    "VIOLATED": (),
}
