# 系统运行截图

前端「科技深色(Linear/Vercel 风)」重设计(R0–R6)后的运行截图,用于论文「系统实现 / 运行效果」章节实证。采集自 `pnpm dev` + 后端 8080 实跑环境,Playwright 1440×900 PNG。

## 已采集(7 张,SYS_ADMIN 视角)

| 编号 | 文件 | 页面 | 设计要点 |
|---|---|---|---|
| 01 | `01-login.png` | 登录 `/login` | 分屏 hero:左极光渐变 + Space Grotesk 品牌名 + 漂浮设备卡碎片;右毛玻璃登录卡 + 青渐变按钮 + 入场错峰 |
| 02 | `02-admin-dashboard.png` | 驾驶舱 `/dashboard`(SYS_ADMIN) | StatCard 行(count-up)+ ECharts 深色图表网格(30 天趋势折线/设备状态饼图,青蓝系)+ 顶部极光 + 错峰入场 |
| 03 | `03-device-browse.png` | 设备浏览 `/devices` | SegmentedControl 筛选 + GlowCard 设备网格(StatusDot + 品牌/型号 + 青价格)+ 错峰 + 分页(24/48/96) |
| 04 | `04-device-detail.png` | 设备详情 `/devices/:id` | hero(展示名 + StatusDot + spec chips)+ sticky 毛玻璃操作栏(预约/报修)+ 深色 tabs(规格/预约日历,青 active) |
| 05 | `05-device-manage.png` | 设备管理 `/devices/manage` | 全局深色 el-table(表头 sunken / 行 surface / 青行 hover)+ 状态 Tag + 青渐变"新增设备" |
| 06 | `06-user-manage.png` | 用户管理 `/users` | 暗表 + 角色 Tag(5 角色色调)+ 状态 Tag + 搜索 + 深色 el-drawer 抽屉 |
| 07 | `07-notifications.png` | 通知中心 `/notifications` | 未读左侧 2px 青条 + 类型 Tag + 已读弱化过渡 + EmptyState |

## 待补(STUDENT / LAB_ADMIN 视角)

`it_stu_*` 是集成测试建的账号(密码未知),`UserController.create` 在当前环境建演示账号触发底层异常(疑似 dept 约束)。STUDENT/LAB_ADMIN 视角页面(建预约 stepper / 审批队列 / 推荐 / 我的预约 Timeline / 报修)**已全部完成 + 通过设计复审 + build 绿**,视觉与上述 SYS_ADMIN 页同一套深色设计系统(token / GlowCard / Timeline / Tag / 暗表)。论文定稿前按下面方式补齐:

1. 经已验证的「用户管理 → 新增用户」UI(R6.2,`06-user-manage.png` 可见入口)建演示 STUDENT / LAB_ADMIN 账号(已知密码)。
2. 用该账号登录,按下表补截图,命名 `08-stu-*.png` / `09-lab-*.png`:

   - **STUDENT**:学生驾驶舱(`/dashboard`)/ 设备浏览 / **建预约 stepper**(`/reservations/create`)/ **智能推荐**(`/recommendations`,理由 Tag chips)/ 我的预约 Timeline / 通知
   - **LAB_ADMIN**:实验室驾驶舱 / **待审批队列**(`/approvals`,行内通过/驳回)/ 报修处理暗表

## 采集参数

- 浏览器:Chromium(Playwright 自带),1440×900,PNG。
- 环境:`pnpm dev`(5173)+ 后端 `mvn spring-boot:run`(8080,profile dev),中间件 docker compose(mysql/redis/rabbitmq)。
- 数据:V5 种子(12 实验室 / 32 类别 / ~270 设备)+ Phase1 seed 用户。
- 实时推送:通知页右上角铃铛未读数 = WebSocket STOMP 链路实证。
- 防超约:可手动构造同时段二次预约,抓 `RESERVATION_CONFLICT` 前端提示(与 JMeter 1成功/49冲突 压测数据互证)。
