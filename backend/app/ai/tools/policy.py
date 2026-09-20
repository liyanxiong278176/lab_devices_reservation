from dataclasses import dataclass

from app.auth.security import Principal


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    description: str
    write: bool
    allowed_roles: tuple[str, ...] = ()

    def allowed(self, principal: Principal) -> bool:
        return (
            principal.is_system_admin
            or not self.allowed_roles
            or bool(set(self.allowed_roles).intersection(principal.roles))
        )


TOOL_POLICIES: dict[str, ToolPolicy] = {
    "search_devices": ToolPolicy(
        "search_devices",
        "查询当前用户所属学院可见的设备",
        write=False,
    ),
    "recommend_devices": ToolPolicy(
        "recommend_devices",
        "基于当前学院可见设备、用户偏好和近期热度生成可解释推荐",
        write=False,
    ),
    "check_availability": ToolPolicy(
        "check_availability",
        "查询当前学院设备在自然日期上的可用性",
        write=False,
    ),
    "my_reservations": ToolPolicy(
        "my_reservations",
        "查询当前用户自己的预约",
        write=False,
    ),
    "create_reservation": ToolPolicy(
        "create_reservation",
        "创建预约；只能先生成预览，必须经过用户确认",
        write=True,
    ),
    "cancel_reservation": ToolPolicy(
        "cancel_reservation",
        "取消当前用户自己的预约；必须经过用户确认",
        write=True,
    ),
    "submit_repair": ToolPolicy(
        "submit_repair",
        "提交设备报修；必须经过用户确认",
        write=True,
    ),
}
