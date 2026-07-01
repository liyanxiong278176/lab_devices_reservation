# 阶段1 设计规格：后端核心 MVP（高校实验室设备智能预约与管控平台）

- **状态**：已通过设计评审，待规格评审
- **日期**：2026-07-01
- **范围**：四阶段路线（方案A：后端垂直切片优先）中的**第 1 阶段**
- **协作模式**：用户为 Java/Spring 熟手，要求高效产出、可 review、可答辩

---

## 1. 背景与整体路线

本项目是毕业设计「高校实验室设备智能预约与管控平台」。整体分四阶段（方案A），本规格仅覆盖**阶段1**：

1. **阶段1（本规格）后端核心 MVP**：鉴权 + RBAC + 设备 + 预约（含 DB 层防超约）+ 审批 + 签到归还 + DB 通知。
2. 阶段2：四大亮点叠加 —— Redis 分布式锁并发预约、智能推荐、WebSocket 实时推送、ECharts 数据驾驶舱。
3. 阶段3：Vue3 + TS + Element Plus 三端前端。
4. 阶段4：RabbitMQ 异步通知 + Docker Compose 一键部署 + 论文素材（架构图、压测数据）。

**阶段1 的目标**：交付一个可独立运行、可演示、有单测与并发集成测试的后端系统，作为后续亮点与前端的基础。答辩技术核心（尤其防超约）在本阶段夯实。

---

## 2. 范围

### 2.1 纳入范围（In Scope）

- Spring Boot 3 项目骨架（包名 `com.lab.reservation`）
- MySQL 数据库 + Flyway 版本化迁移 + 种子数据
- Spring Security + JWT 鉴权（access + refresh）
- RBAC：3 角色（STUDENT / LAB_ADMIN / SYS_ADMIN）+ 权限表（阶段1以角色为主，权限表预留）
- 实验室、设备分类、设备 管理
- **预约核心**：混合槽模型、创建（含冲突检测）、取消、签到（check-in）、归还（check-out）、违规/爽约
- 审批流程（按实验室范围）
- 设备日历接口（返回某时段已占槽）
- DB 通知表 + 轮询接口
- 设备报修（最小版：提交/查看/状态流转 + 与设备 MAINTENANCE 状态联动）
- 统一响应 + 全局异常处理 + 参数校验
- Knife4j 接口文档
- 操作日志（AOP 切面，基础版）
- 单元测试 + 防超约并发集成测试（Testcontainers）

### 2.2 排除范围（Out of Scope，明确延后）

- Redis、RabbitMQ、WebSocket、ECharts —— 阶段2/3/4
- Vue3 前端 —— 阶段3
- Docker / Docker Compose —— 阶段4
- 智能推荐算法 —— 阶段2
- 数据驾驶舱的可视化（阶段1 仅返回统计数字，不含图表）
- 定时任务自动巡检（爽约自动判定等）—— 阶段1 用管理员手动操作，可留扩展点
- 第三方短信/邮件发送 —— 阶段4 用 MQ + 通知服务

> YAGNI 边界：阶段1 不引入任何未被上述业务需要的中间件。

---

## 3. 技术栈

| 层 | 选型 | 版本/说明 |
|---|---|---|
| 框架 | Spring Boot | 3.2.x |
| 语言 | Java | 17 |
| 构建 | Maven | - |
| ORM | MyBatis-Plus | 单表 CRUD 免 SQL |
| 数据库 | MySQL | 8.0 |
| 迁移 | Flyway | 版本化 SQL |
| 鉴权 | Spring Security + JWT | access 2h / refresh 7d |
| 校验 | Spring Validation | `@Validated` |
| 接口文档 | Knife4j | `/doc.html` |
| 工具 | Hutool、Lombok | - |
| 测试 | JUnit5 + Mockito + Testcontainers(MySQL) | - |

**依赖约束**：阶段1 仅运行时依赖 MySQL。无 Redis / MQ / WebSocket。

---

## 4. 架构与包结构

**经典 MVC 三层分包**（按层平铺，非按模块）。MyBatis-Plus 下数据访问层包名为 `mapper`（接口 `extends BaseMapper<T>`，等同传统 DAO/repository 层），数据模型层包名为 `entity`（等同 model/domain 层）。

```
com.lab.reservation
├── ReservationApplication.java        # 启动入口
│
├── controller                         # 控制器层：HTTP 请求、参数校验、调用 Service
│   ├── AuthController
│   ├── UserController
│   ├── LabController
│   ├── DeviceController / DeviceCategoryController
│   ├── ReservationController
│   ├── ApprovalController
│   ├── RepairReportController
│   ├── NotificationController
│   └── DashboardController
│
├── service                            # 业务逻辑层：核心业务规则、事务控制
│   ├── AuthService / UserService / LabService
│   ├── DeviceService / ReservationService / ApprovalService
│   ├── RepairReportService / NotificationService / DashboardService
│   ├── SlotCalculatorService          # 槽位计算（防超约核心，纯逻辑）
│   └── impl/                          # 各 Service 实现类
│
├── mapper                             # 数据访问层 (DAO)：MyBatis-Plus，extends BaseMapper<T>
│   ├── SysUserMapper / SysRoleMapper / SysPermissionMapper
│   ├── LabMapper / DeviceMapper / DeviceCategoryMapper
│   ├── ReservationMapper / ReservationItemMapper
│   ├── RepairReportMapper / NotificationMapper / OperationLogMapper
│
├── entity                             # 数据模型层：数据库表实体 (PO)
│   ├── SysUser / SysRole / SysUserRole / SysPermission
│   ├── Lab / DeviceCategory / Device
│   ├── Reservation / ReservationItem
│   ├── RepairReport / Notification / OperationLog
│   └── enums/                         # 枚举：DeviceStatus / ReservationStatus / RepairStatus / RoleType / UserType
│
├── dto                                # 数据传输对象：层间/前后端请求体
│   ├── auth/LoginDTO
│   ├── reservation/ReservationCreateDTO / ReservationQueryDTO
│   ├── repair/RepairCreateDTO ...
│
├── vo                                 # 视图对象：返回前端（剥离敏感信息）
│   ├── auth/LoginVO / UserInfoVO
│   ├── device/DeviceVO / DeviceCalendarVO
│   ├── reservation/ReservationVO
│   └── dashboard/DashboardSummaryVO ...
│
├── common                             # 公共：统一响应、结果码
│   └── result/Result / ResultCode
│
├── exception                          # 全局异常处理
│   ├── BusinessException
│   └── GlobalExceptionHandler
│
├── security                           # 鉴权：JWT 工具、过滤器、UserDetails
│   ├── JwtUtils
│   ├── JwtAuthenticationFilter
│   └── SecurityUserDetails
│
├── config                             # 配置类
│   └── SecurityConfig / MyBatisPlusConfig / Knife4jConfig / WebConfig
│
└── aspect                             # AOP：操作日志（@Log 注解 + OperationLogAspect）
    ├── Log
    └── OperationLogAspect
```

> 命名对照：`mapper` = 你模板里的 repository/dao（MyBatis-Plus 习惯名）；`entity` = model/domain。`security`、`aspect` 是为 JWT 鉴权与操作日志切面新增的标准包，其余与经典 MVC 模板一致。dto/vo 按业务子域分子包（auth/reservation/repair…），便于归类。

---

## 5. 数据模型

### 5.1 槽位（Slot）规则

- `slot_minutes = 15`（配置项 `lab.slot.minutes`，工作窗内整 15 分钟对齐）
- 工作窗 `[work_start, work_end]` 默认 `08:00–22:00`（配置项）
- 单日槽数 = 工作窗分钟数 / slot_minutes（默认 840/15 = **56 槽/天**）
- `slot_index` = 自当日工作窗起算的槽序号，取值 `0 .. (单日槽数-1)`
- 槽 `k` 覆盖区间 `[work_start + k*slot_minutes, work_start + (k+1)*slot_minutes)`

### 5.2 预约 = 1 条 reservation + N 条 reservation_item

> 混合模型：一次预约逻辑上是 1 条 `reservation`，物化为 N 条 `reservation_item`（每个占用槽一行）。

| 表 | 关键字段 | 说明 |
|---|---|---|
| `reservation` | id, user_id, device_id, purpose, start_time, end_time, slot_count, status, approver_id, approved_at, reject_reason, check_in_at, check_out_at, created_at, updated_at | 预约主记录 |
| `reservation_item` | id, reservation_id, **device_id, date, slot_index** | **`UNIQUE(device_id, date, slot_index)` = DB 原生唯一索引，硬防超约** |

**item 行的生命周期规则（关键，消除歧义）**：

- `reservation_item` 行**仅代表"当前被占用的槽"**，即预约处于活跃状态（PENDING / APPROVED / IN_USE）时存在。
- 预约转入任意**终态**（CANCELLED / REJECTED / COMPLETED / VIOLATED / NO_SHOW）时，**删除其全部 item 行**（释放槽）。
- `reservation` 主行**保留**（status + start/end 作为历史）。
- 因此唯一索引 `UNIQUE(device_id, date, slot_index)` 作用于"当前占用"，天然防双占，且终态后自动可再约。

### 5.3 预约状态机（ReservationStatus）

```
                 审批通过                 签到(到时间窗内)
PENDING ────────────────► APPROVED ────────────────► IN_USE ──归还──► COMPLETED
   │                         │                         │
   │ 拒绝                    │ 取消(开始前)            │ 爽约/违规(管理员)
   ▼                         ▼                         ▼
 REJECTED                CANCELLED            VIOLATED / NO_SHOW

设备无需审批时：创建直接 = APPROVED（跳过 PENDING）
```

**设备状态联动**：

- 签到 `APPROVED → IN_USE`：`device.status = IN_USE`
- 归还 `IN_USE → COMPLETED`：`device.status = IDLE`
- 取消/拒绝/违规/爽约：不改变设备状态（设备本应保持 IDLE，除非此前已签到）

### 5.4 全部实体

- `sys_user`：id, username(唯一), password(BCrypt), real_name, phone, email, user_type(STUDENT/TEACHER/STAFF), dept_name, status(0禁用/1正常), created_at, updated_at
- `sys_role`：id, role_code(STUDENT/LAB_ADMIN/SYS_ADMIN), role_name
- `sys_user_role`：user_id, role_id（一个用户可有多角色）
- `sys_permission`：id, perm_code(如 `device:manage`), name, type(MENU/BUTTON/API), parent_id
- `sys_role_permission`：role_id, permission_id
- `lab`：id, name, location, **manager_id(→sys_user.id)**, description, status, created_at
- `device_category`：id, name, parent_id（树形）
- `device`：id, name, category_id, lab_id, brand, model, specs, image_url, status(IDLE/IN_USE/MAINTENANCE), need_approval(bool), max_reservation_hours(decimal), price_per_hour(decimal), tags(JSON), description, created_at, updated_at
- `reservation` / `reservation_item`：见 5.2
- `notification`：id, user_id, type, title, content, related_id, related_type, is_read, created_at
- `operation_log`：id, user_id, username, action, method, params(JSON), ip, cost_ms, created_at
- `repair_report`：id, device_id, reporter_id(→sys_user), title, description, image_urls(JSON), status(PENDING/PROCESSING/RESOLVED/REJECTED), handler_id(→sys_user), resolution_note, created_at, updated_at, resolved_at

**索引**：

- `reservation`：(user_id, status)、(device_id, status)、(status, start_time)
- `reservation_item`：UNIQUE(device_id, date, slot_index)、INDEX(reservation_id)
- `sys_user`：UNIQUE(username)
- 其余外键字段常规索引

---

## 6. 核心业务规则与防超约（阶段1技术核心）

### 6.1 创建预约流程

```
@Transactional
create(CreateReq req, currentUser):
  1. 校验设备存在且可用（status != MAINTENANCE）
  2. 校验时段：
     - start < end，start 不早于 now
     - start/end 落在工作窗 [work_start, work_end] 内
     - start/end 对齐到 15 分钟槽边界（不对齐则拒绝，提示"须以15分钟为单位"）
  3. slots = SlotCalculator.compute(deviceId, start, end)   // List<(date, slot_index)>
  4. 校验 slot_count <= floor(max_reservation_hours × 60 / slot_minutes)（向下取整到槽粒度，如 max=2h、槽=15min → 上限 8 槽）
  5. INSERT reservation(status = device.need_approval ? PENDING : APPROVED, ...)
  6. 批量 INSERT reservation_item(slots)
       └─ 若抛 DuplicateKeyException：
            rollback（reservation 也回滚）
            抛 BusinessException(RESERVATION_CONFLICT, "该时段已被占用")
  7. 若直接 APPROVED，发通知
  8. 返回 reservation.id
```

**唯一索引让并发天然正确**：两个事务同时尝试占用同一槽 → 一个成功，另一个在批量 INSERT 时命中唯一索引拿到 `DuplicateKeyException` → 报冲突回滚。**无需显式行锁**。

> 阶段2 将在本流程第 5 步前增加 Redis `SETNX device:{date}:{slot_index}` 预抢，挡掉绝大多数并发、保护 DB，形成答辩「双层防线」故事。本阶段只实现 DB 唯一索引这一层。

### 6.2 SlotCalculator 纯逻辑（重点单测对象）

- 输入：`(start: datetime, end: datetime, workStart, workEnd, slotMinutes)`
- 输出：`List<SlotKey(device_id, date, slot_index)>`
- 规则：按日切分；每日取 `[max(start, date+workStart), min(end, date+workEnd))` 与槽网格的交集；要求起止对齐槽边界。
- 边界用例（必须测试）：
  - 跨天预约（如 22:00 前一天 → 次日 09:00）
  - 超出工作窗（拒绝）
  - 非整槽对齐（拒绝）
  - start == end（拒绝，0 槽）
  - 恰好整数槽、单槽、边界槽

### 6.3 取消 / 签到 / 归还 / 违规

| 操作 | 前置状态 | 转换 | 副作用 |
|---|---|---|---|
| 取消 cancel | PENDING / APPROVED（且未到 start） | → CANCELLED | 删除 item；发通知 |
| 审批通过 approve | PENDING | → APPROVED | 发通知（设备仍 IDLE） |
| 拒绝 reject | PENDING | → REJECTED | 删除 item；发通知 |
| 签到 checkIn | APPROVED 且 now ∈ [start−grace, end] | → IN_USE | device→IN_USE；记录 check_in_at |
| 归还 checkOut | IN_USE | → COMPLETED | device→IDLE；删除 item（清理，虽已过期）；记录 check_out_at |
| 爽约/违规 markNoShow/markViolated | APPROVED/IN_USE | → NO_SHOW/VIOLATED | device 若 IN_USE→IDLE；删除 item |

`grace`（签到宽限）默认 0，可配置。爽约/违规为管理员手动操作（阶段1），留 `@Scheduled` 巡检扩展点但不在阶段1实现。

### 6.4 报修状态与设备联动（最小版）

```
PENDING ──take(受理)──► PROCESSING ──resolve──► RESOLVED
            │                    │
            └──reject───────────► REJECTED
```

- 用户提交报修 → `PENDING`，设备状态不变。
- 管理员受理 `take` → `PROCESSING`，**设备置 `MAINTENANCE`**（此后该设备新预约被 §6.1 第 1 步拒绝）。`take` 不校验设备当前状态——若设备此时为 IN_USE，仍置 MAINTENANCE，其进行中的预约由管理员手动 cancel + 通知。
- 管理员解决 `resolve`（填 resolution_note）→ `RESOLVED`，**设备置回 `IDLE`**。
- 管理员驳回 `reject`（非真实故障）→ `REJECTED`，设备不变。
- 设备转入 `MAINTENANCE` 时，其上已有的活跃预约（PENDING/APPROVED）：阶段1 不自动取消，仅由管理员手动 cancel 并发通知（保持最小实现；自动取消留扩展点）。

---

## 7. 鉴权与 RBAC

- 密码：BCrypt。
- 登录：校验账号密码 → 签发 `accessToken`（2h，载荷含 userId/username/roles）+ `refreshToken`（7d）。
- 请求鉴权：`JwtAuthenticationFilter` 解析 `Authorization: Bearer <token>`，加载 `Authentication`（authorities 来自角色 + 权限 perm_code）。
- 方法级安全：`@PreAuthorize("hasRole('LAB_ADMIN')")` 或 `hasAuthority('device:manage')`。
- 三角色与职责：
  - **STUDENT**：浏览/预约/取消/查我的预约与通知/提交与查看我的报修。
  - **LAB_ADMIN**：管理本实验室设备、审批本实验室预约、签到归还、待审批列表、处理本实验室设备报修。
  - **SYS_ADMIN**：用户/角色/权限、实验室、系统级配置、操作日志。
- **权限加载**：登录返回的 `permissions` 为用户各角色经 `sys_role_permission` 映射出的 `perm_code` 列表（阶段1 已种基础权限数据，非空）；方法级安全同时支持 `hasRole(...)` 与 `hasAuthority(perm_code)`。
- **实验室范围（LAB_ADMIN 数据隔离）**：`lab.manager_id = admin.userId`。LAB_ADMIN 仅能管理/审批其所辖实验室的设备与预约。SYS_ADMIN 不受限。

---

## 8. API 设计（阶段1）

统一前缀 `/api`，统一响应 `Result<T>{code, msg, data}`。

### 8.1 auth
- `POST /auth/login` {username, password} → {accessToken, refreshToken, userInfo, roles, permissions}
- `POST /auth/register` {username, password, realName, ...}（学生自助注册，默认 STUDENT）
- `POST /auth/refresh` {refreshToken} → {accessToken}
- `POST /auth/logout`
- `GET /auth/me` → 当前用户 + 权限

### 8.2 user（管理员）
- `GET /users`（分页、搜索）｜`POST /users`｜`PUT /users/{id}`｜`DELETE /users/{id}`
- `PATCH /users/{id}/status` {status}（封禁/解封）

### 8.3 lab
- CRUD `/labs`（SYS_ADMIN / LAB_ADMIN 自辖）

### 8.4 device
- `GET /devices`（多条件：categoryId、labId、status、keyword、needApproval、minPrice/maxPrice，分页）
- `GET /devices/{id}`
- `GET /devices/{id}/calendar?from=&to=` → 该设备该区间已占槽 `[{date, slotIndex, reservationId, status}]`
- `POST/PUT/DELETE /devices`（LAB_ADMIN 自辖 / SYS_ADMIN）
- `PATCH /devices/{id}/status` {status}（维修/空闲）
- `GET /device-categories`（树）

### 8.5 reservation
- `POST /reservations` {deviceId, startTime, endTime, purpose}（含冲突检测）
- `POST /reservations/{id}/cancel`
- `POST /reservations/{id}/check-in`｜`POST /reservations/{id}/check-out`
- `GET /reservations/mine?status=&page=&size=`
- `GET /reservations/{id}`

### 8.6 approval（LAB_ADMIN）
- `GET /approvals/pending?page=`（按自辖实验室过滤）
- `POST /approvals/{reservationId}/approve`
- `POST /approvals/{reservationId}/reject` {reason}
- `POST /approvals/batch-approve` {ids[]}（可选）

### 8.7 notification
- `GET /notifications/mine?onlyUnread=&page=`
- `PATCH /notifications/{id}/read`｜`PATCH /notifications/read-all`

### 8.8 dashboard（阶段1 仅数字）
- `GET /dashboard/summary` → {totalDevices, idle, inUse, maintenance, todayReservations, pendingApprovals(按角色), weeklyReservationTrend: [{date,count}]}

### 8.9 repair-report（设备报修）
- 用户：`POST /repair-reports` {deviceId, title, description, imageUrls[]}｜`GET /repair-reports/mine`
- 管理员（LAB_ADMIN 自辖 / SYS_ADMIN）：`GET /repair-reports?status=&page=`｜`POST /repair-reports/{id}/take`（→PROCESSING，设备转 MAINTENANCE）｜`POST /repair-reports/{id}/resolve` {resolutionNote}（→RESOLVED，设备转 IDLE）｜`POST /repair-reports/{id}/reject` {note}（→REJECTED）

---

## 9. 错误处理与统一响应

- `Result<T>{code:int, msg:String, data:T}`；`Result.code` 为**业务码**：成功=200，失败=`ResultCode` 枚举值（其数值与 HTTP 语义对齐，仅作可读性约定，**不等于** HTTP 响应状态）。
- HTTP 响应状态：业务响应统一返回 **200**，前端以 `Result.code` 判断业务成败；鉴权失败（未带/无效 token、越权）由 Spring Security 入口点返回 HTTP **401/403** 并包 `Result` 体。
- `ResultCode` 枚举：SUCCESS、PARAM_INVALID、UNAUTHORIZED、FORBIDDEN、NOT_FOUND、USERNAME_OR_PASSWORD_ERROR、ACCOUNT_DISABLED、**RESERVATION_CONFLICT**、SLOT_OUT_OF_WORK_WINDOW、SLOT_NOT_ALIGNED、EXCEED_MAX_DURATION、DEVICE_UNAVAILABLE、STATUS_TRANSITION_INVALID、BUSINESS_ERROR 等。
- `GlobalExceptionHandler`（`@RestControllerAdvice`）统一捕获：
  - `BusinessException` → 对应 code
  - `MethodArgumentNotValidException` / `ConstraintViolationException` → PARAM_INVALID + 字段信息
  - `DuplicateKeyException` → RESERVATION_CONFLICT（兜底，正常路径已在 service 内捕获转译）
  - `AccessDeniedException` / `AuthenticationException` → FORBIDDEN / UNAUTHORIZED
  - 兜底 `Exception` → BUSINESS_ERROR + 记录日志

---

## 10. 测试策略

- **单元测试**（JUnit5 + Mockito）：
  - `SlotCalculator`：§6.2 全部边界用例。
  - `JwtUtils`：签发/解析/过期。
  - ReservationService 状态机转换的纯逻辑分支（用 mock mapper）。
- **集成测试**（Testcontainers MySQL）：
  - **防超约并发测试（亮点实证）**：两线程并发对同一设备同一时段创建预约 → 断言恰好 1 成功、1 抛 RESERVATION_CONFLICT；并断言 `reservation_item` 无重复、`reservation` 仅 1 条 APPROVED/PENDING。
  - 端到端关键链路：注册→登录→建预约→审批→签到→归还→状态与设备状态联动正确。

---

## 11. 配置与基础设施

- `application.yml`：
  - profile `dev`（本地 MySQL `lab_reservation`）与 `prod`（占位，阶段4 接 Docker）。
  - 配置项：`lab.slot.minutes`、`lab.slot.work-start`、`lab.slot.work-end`、`jwt.secret`、`jwt.access-ttl`、`jwt.refresh-ttl`。
- Flyway：`src/main/resources/db/migration/`
  - `V1__init_schema.sql`：全部建表 + 索引 + 唯一约束。
  - `V2__seed_data.sql`：3 角色、权限、默认 SYS_ADMIN 账号、示例实验室 + 设备分类 + 若干设备。
- Knife4j：`/doc.html`。
- 操作日志：AOP 切面拦截标注 `@Log("动作描述")` 的方法，异步写 `operation_log`（阶段1 简单同步写或 `@Async` 均可）。

---

## 12. 完成定义（Definition of Done）

1. `mvn spring-boot:run` 可启动（MySQL 已就绪）；Flyway 自动建表 + 灌种子数据。
2. Knife4j `/doc.html` 可见全部接口并可在线调试。
3. 登录获取 JWT → 受保护接口可调通；角色越权被拦截。
4. 学生路径：浏览设备 → 看设备日历 → 建预约（自动通过或待审批）→ 取消 → 查我的预约 → 查通知。
5. 管理员路径：管设备 → 待审批 → 通过/拒绝 → 签到 → 归还；设备状态正确联动。
6. **防超约**：脚本/测试并发提交相同时段 → 恰好一个成功（集成测试通过 + 可手动演示）。
7. **报修路径**：学生提交报修 → 管理员 take（设备转 MAINTENANCE，该设备新预约被拒）→ resolve（设备转 IDLE）。
8. 单元测试 + 集成测试全部通过；`mvn test` 绿。

---

## 13. 已确认决策（Resolved）

1. **设备报修**：阶段1 **纳入最小版**（`repair_report` 表 + §8.9 接口 + §6.4 状态联动），与设备 MAINTENANCE 状态闭环。
2. **dashboard 周趋势**：阶段1 返回近 7 天预约数数组，ECharts 渲染留到阶段3。
3. **批处理/巡检**：爽约自动判定等定时任务阶段1 不做，留 `@Scheduled` 扩展点。
4. **统一响应**：成功 code=200，业务错误 code 与 HTTP 语义对齐。
5. **权限加载**：登录返回 `perm_code` 列表（阶段1 已种数据，非空）。
6. **时长上限换算**：`max_reservation_hours` → 槽数按 `floor(hours×60/slot_minutes)` 向下取整。
