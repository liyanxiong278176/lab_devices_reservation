-- V2__seed_data.sql
INSERT INTO sys_role(role_code, role_name) VALUES ('STUDENT','学生'),('LAB_ADMIN','实验室管理员'),('SYS_ADMIN','系统管理员');

INSERT INTO sys_permission(perm_code,name,type) VALUES
 ('device:manage','设备管理','MENU'),('device:approve','预约审批','MENU'),
 ('user:manage','用户管理','MENU'),('system:manage','系统管理','MENU'),
 ('repair:handle','报修处理','MENU'),('reservation:create','创建预约','BUTTON');

INSERT INTO sys_role_permission(role_id, permission_id)
 SELECT r.id, p.id FROM sys_role r, sys_permission p
 WHERE r.role_code='LAB_ADMIN' AND p.perm_code IN ('device:manage','device:approve','repair:handle');
INSERT INTO sys_role_permission(role_id, permission_id)
 SELECT r.id, p.id FROM sys_role r, sys_permission p
 WHERE r.role_code='SYS_ADMIN' AND p.perm_code IN ('device:manage','user:manage','system:manage');
INSERT INTO sys_role_permission(role_id, permission_id)
 SELECT r.id, p.id FROM sys_role r, sys_permission p
 WHERE r.role_code='STUDENT' AND p.perm_code='reservation:create';

INSERT INTO device_category(name, parent_id, sort) VALUES ('显微成像',0,1),('光谱分析',0,2),('电子测量',0,3);
INSERT INTO device_category(name, parent_id, sort) VALUES ('光学显微镜',1,1),('电子显微镜',1,2);

INSERT INTO lab(name, location, manager_id, description) VALUES ('材料科学实验室','理科楼A301',NULL,'显微与光谱设备');
INSERT INTO device(name, category_id, lab_id, brand, model, status, need_approval, max_reservation_hours, price_per_hour, tags, description)
 VALUES
 ('奥林巴斯BX53显微镜',4,1,'Olympus','BX53','IDLE',1,4.00,0.00,'["显微镜","光学","高精度"]','常用光学显微镜'),
 ('场发射电镜',5,1,'ZEISS','Sigma300','IDLE',1,2.00,20.00,'["电镜","高精度","昂贵"]','需培训后方可使用'),
 ('紫外可见分光光度计',(SELECT id FROM device_category WHERE name='光谱分析'),1,'Shimadzu','UV-2600','IDLE',0,8.00,5.00,'["光谱","通用"]','通用分析设备');
