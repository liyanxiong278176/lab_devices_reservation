from dataclasses import dataclass

from app.auth.security import Principal


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    description: str
    write: bool
    permission_code: str

    def allowed(self, principal: Principal) -> bool:
        return principal.has_permission(self.permission_code)


TOOL_POLICIES: dict[str, ToolPolicy] = {
    "search_devices": ToolPolicy(
        "search_devices",
        "查询当前用户所属学院可见的设备",
        write=False,
        permission_code="device:read",
    ),
    "recommend_devices": ToolPolicy(
        "recommend_devices",
        "基于当前学院可见设备、用户偏好和近期热度生成可解释推荐",
        write=False,
        permission_code="device:read",
    ),
    "check_availability": ToolPolicy(
        "check_availability",
        "查询当前学院设备在自然日期上的可用性",
        write=False,
        permission_code="device:read",
    ),
    "my_reservations": ToolPolicy(
        "my_reservations",
        "查询当前用户自己的预约",
        write=False,
        permission_code="reservation:read:own",
    ),
    "create_reservation": ToolPolicy(
        "create_reservation",
        "创建预约；只能先生成预览，必须经过用户确认",
        write=True,
        permission_code="reservation:create",
    ),
    "cancel_reservation": ToolPolicy(
        "cancel_reservation",
        "取消当前用户自己的预约；必须经过用户确认",
        write=True,
        permission_code="reservation:cancel",
    ),
    "submit_repair": ToolPolicy(
        "submit_repair",
        "提交设备报修；必须经过用户确认",
        write=True,
        permission_code="repair:create",
    ),
}
