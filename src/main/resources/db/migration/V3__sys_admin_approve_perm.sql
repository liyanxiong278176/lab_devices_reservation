-- V3__sys_admin_approve_perm.sql
-- 补授 SYS_ADMIN 以 device:approve / repair:handle / reservation:create 权限。
--
-- V2 种子数据中 SYS_ADMIN 仅持有 device:manage/user:manage/system:manage，
-- 缺失 device:approve（§8.6 审批接口要求 LAB_ADMIN 与 SYS_ADMIN 均可审批），
-- 以及 repair:handle / reservation:create。SYS_ADMIN 作为系统超级管理员，
-- 应当具备全量业务权限。本迁移补齐这三条映射，幂等（INSERT ... SELECT ... WHERE NOT EXISTS）。
INSERT INTO sys_role_permission(role_id, permission_id)
 SELECT r.id, p.id
 FROM sys_role r, sys_permission p
 WHERE r.role_code='SYS_ADMIN'
   AND p.perm_code IN ('device:approve','repair:handle','reservation:create')
   AND NOT EXISTS (
       SELECT 1 FROM sys_role_permission rp
       WHERE rp.role_id = r.id AND rp.permission_id = p.id
   );
