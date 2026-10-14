# 前端流程截图册

2026-10-14 · 14 条流程 · 24 张关键截图

## 1. 管理员菜单页面正常显示，设备、用户和实验室 CRUD 可闭环

![管理员菜单页面正常显示，设备、用户和实验室 CRUD 可闭环 · 结果核对 · admin-dashboard](images/0001.png)

![管理员菜单页面正常显示，设备、用户和实验室 CRUD 可闭环 · 结果核对 · organization-lab-management](images/0002.png)

## 2. 不可预约日期会阻止用户提交，解除后恢复预约；同步与异步报表可下载

![不可预约日期会阻止用户提交，解除后恢复预约；同步与异步报表可下载 · 结果核对 · operations-reports](images/0003.png)

![不可预约日期会阻止用户提交，解除后恢复预约；同步与异步报表可下载 · 结果核对 · reservation-rules-released-user](images/0004.png)

## 3. 两个标签页并发提交时使用共享令牌并成功通过 CSRF 校验

![两个标签页并发提交时使用共享令牌并成功通过 CSRF 校验 · 打开页面](images/0005.png)

## 4. 交接发现配件损坏会阻止启用、生成报修并等待负责人处置

![交接发现配件损坏会阻止启用、生成报修并等待负责人处置 · 结果核对 · handover-damage-repair-workorder](images/0006.png)

## 5. 报修被退回后可重新处理，管理员驳回分支也可闭环

![报修被退回后可重新处理，管理员驳回分支也可闭环 · 点击 · 提交报修](images/0007.png)

![报修被退回后可重新处理，管理员驳回分支也可闭环 · 点击 · 确认处理](images/0008.png)

## 6. 损坏归还验收会完成预约并将设备转入维护状态

![损坏归还验收会完成预约并将设备转入维护状态 · 结果核对 · damaged-device-maintenance-admin](images/0009.png)

![损坏归还验收会完成预约并将设备转入维护状态 · 结果核对 · damaged-return-completed-user](images/0010.png)

## 7. 管理员可驳回待受理报修，用户端可查看驳回状态

![管理员可驳回待受理报修，用户端可查看驳回状态 · 结果核对 · repair-rejected-admin](images/0011.png)

![管理员可驳回待受理报修，用户端可查看驳回状态 · 结果核对 · repair-rejected-user](images/0012.png)

## 8. 预约审批、报修处理和菜单隔离均通过页面完成

![预约审批、报修处理和菜单隔离均通过页面完成 · 结果核对 · handover-queue-completed-admin](images/0013.png)

![预约审批、报修处理和菜单隔离均通过页面完成 · 结果核对 · reservation-completed-user](images/0014.png)

## 9. 驳回、取消与候补递补都能通过实际页面闭环

![驳回、取消与候补递补都能通过实际页面闭环 · 结果核对 · reservation-rejected-and-cancelled-user](images/0015.png)

![驳回、取消与候补递补都能通过实际页面闭环 · 结果核对 · waitlist-notified-user](images/0016.png)

## 10. 两个用户并发预约同一设备，管理员审批唯一成功申请

![两个用户并发预约同一设备，管理员审批唯一成功申请 · 结果核对 · 01-user-one-ready-to-submit](images/0017.png)

![两个用户并发预约同一设备，管理员审批唯一成功申请 · 结果核对 · 07-admin-approval-complete](images/0018.png)

## 11. HTTP 连接中断后同一 EventSource 按 Last-Event-ID 补发通知

![HTTP 连接中断后同一 EventSource 按 Last-Event-ID 补发通知 · 点击 · 我的通知](images/0019.png)

## 12. 一个标签页标记已读后同步更新同账号的另一个标签页

![一个标签页标记已读后同步更新同账号的另一个标签页 · 点击控件](images/0020.png)

## 13. 非 AI 菜单页面、预约与报修协作链路及预期错误状态均截图验证

![非 AI 菜单页面、预约与报修协作链路及预期错误状态均截图验证 · 结果核对 · admin-approvals-pending](images/0021.png)

![非 AI 菜单页面、预约与报修协作链路及预期错误状态均截图验证 · 结果核对 · user-reservations](images/0022.png)

## 14. 跨学院设备、预约和审批不可见；本学院负责人及系统管理员范围正确

![跨学院设备、预约和审批不可见；本学院负责人及系统管理员范围正确 · 结果核对 · cross-college-user-empty-device-list](images/0023.png)

![跨学院设备、预约和审批不可见；本学院负责人及系统管理员范围正确 · 结果核对 · system-admin-cross-college-device-management](images/0024.png)
