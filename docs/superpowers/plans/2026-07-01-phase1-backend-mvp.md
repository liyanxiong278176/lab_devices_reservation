# 阶段1 后端核心 MVP 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个可运行、可演示、有单测与并发集成测试的高校实验室设备预约后端（鉴权 + RBAC + 设备 + 混合槽模型预约(含唯一索引硬防超约) + 审批 + 签到归还 + 报修 + DB 通知 + 操作日志）。

**Architecture:** 经典平铺 MVC 三层（controller/service(+impl)/mapper/entity/dto/vo）。预约采用"混合槽模型"：1 条 `reservation` + N 条 `reservation_item`，靠 `UNIQUE(device_id, date, slot_index)` 唯一索引在数据库层硬防超约；并发下重复占用抛 `DuplicateKeyException` 转译为业务冲突。纯逻辑（槽位计算、状态机）走严格 TDD。

**Tech Stack:** Spring Boot 3.2.5 / Java 17 / MyBatis-Plus 3.5.5 / MySQL 8 / Flyway / Spring Security + JWT(jjwt 0.12.5) / Knife4j 4.5.0 / Hutool / Lombok / Testcontainers 1.19.7。详见 spec §3.1。

**Spec:** `docs/superpowers/specs/2026-07-01-phase1-backend-mvp-design.md`

---

## 前置环境（执行前确认）

- JDK 17、Maven 3.8+、本地 MySQL 8（建库 `lab_reservation`，UTF-8 `utf8mb4`）。
- **Docker 运行中**（Testcontainers 集成测试需要）。若无 Docker：集成测试改用本地 MySQL 测试库（见 Task 9 备选说明）。
- IDE：IntelliJ IDEA。

---

## 文件结构（落地清单）

```
src/main/
├── java/com/lab/reservation/
│   ├── ReservationApplication.java
│   ├── common/
│   │   └── result/{Result.java, ResultCode.java}
│   ├── exception/{BusinessException.java, GlobalExceptionHandler.java}
│   ├── entity/                         # 13 个实体 + enums/
│   │   └── enums/{DeviceStatus,ReservationStatus,RepairStatus,RoleType,UserType,UserStatus}.java
│   ├── mapper/                         # 13 个 Mapper 接口
│   ├── dto/                            # auth/, reservation/, repair/, device/, user/, query/
│   ├── vo/                             # auth/, device/, reservation/, dashboard/
│   ├── security/{JwtProperties,JwtUtils,SecurityUserDetails,JwtAuthenticationFilter}
│   ├── config/{SecurityConfig,MyBatisPlusConfig,Knife4jConfig,WebConfig}
│   ├── aspect/{Log.java,OperationLogAspect.java}
│   ├── controller/                     # 11 个 Controller（含 UserController）
│   ├── service/                        # 10 个 Service 接口 + impl/
│   │   └── SlotCalculatorService.java  # 纯逻辑
│   └── init/DataInitializer.java       # 启动时种默认管理员
├── resources/
│   ├── application.yml
│   ├── application-dev.yml
│   └── db/migration/{V1__init_schema.sql, V2__seed_data.sql}
src/test/java/com/lab/reservation/
├── service/SlotCalculatorServiceTest.java
├── security/JwtUtilsTest.java
├── service/ReservationLifecycleTest.java
└── reservation/ReservationConcurrencyIT.java   # 防超约亮点测试
```

---

## 任务依赖图

```
T1 骨架/pom/yml ─► T2 Flyway建表 ─► T3 Result/异常/枚举 ─► T4 实体+Mapper+MP配置
   ─► T5 JwtUtils+Security基础 ─► T6 Auth(login/register/me) + DataInitializer
   ─► T7 SlotCalculator(TDD) ─► T9 Reservation创建+防超约(TDD+并发)
T6 ─► T8 Lab/Device/Category(CRUD+检索+日历) ─► T9
T6 ─► T11 用户管理(CRUD)
T9 ─► T10 预约生命周期 ─► T12 审批 ─► T13 报修 ─► T14 通知 ─► T15 Dashboard ─► T16 操作日志AOP ─► T17 Knife4j+收尾DoD
```

---

## Task 1: 项目骨架 + pom.xml + 配置 + 启动验证

**Files:**
- Modify: `pom.xml`（整体重写）
- Create: `src/main/java/com/lab/reservation/ReservationApplication.java`
- Delete: `src/main/java/org/example/Main.java`
- Create: `src/main/resources/application.yml`
- Create: `src/main/resources/application-dev.yml`

- [ ] **Step 1: 重写 pom.xml**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.2.5</version>
        <relativePath/>
    </parent>

    <groupId>com.lab</groupId>
    <artifactId>lab-devices-reservation</artifactId>
    <version>1.0-SNAPSHOT</version>
    <name>lab-devices-reservation</name>

    <properties>
        <java.version>17</java.version>
        <mybatis-plus.version>3.5.5</mybatis-plus.version>
        <knife4j.version>4.5.0</knife4j.version>
        <jjwt.version>0.12.5</jjwt.version>
        <hutool.version>5.8.27</hutool.version>
        <testcontainers.version>1.19.7</testcontainers.version>
    </properties>

    <dependencies>
        <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency>
        <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-security</artifactId></dependency>
        <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-validation</artifactId></dependency>

        <dependency><groupId>com.baomidou</groupId><artifactId>mybatis-plus-spring-boot3-starter</artifactId><version>${mybatis-plus.version}</version></dependency>
        <dependency><groupId>com.mysql</groupId><artifactId>mysql-connector-j</artifactId><scope>runtime</scope></dependency>
        <dependency><groupId>org.flywaydb</groupId><artifactId>flyway-core</artifactId></dependency>
        <dependency><groupId>org.flywaydb</groupId><artifactId>flyway-mysql</artifactId></dependency>

        <dependency><groupId>com.github.xiaoymin</groupId><artifactId>knife4j-openapi3-jakarta-spring-boot-starter</artifactId><version>${knife4j.version}</version></dependency>

        <dependency><groupId>io.jsonwebtoken</groupId><artifactId>jjwt-api</artifactId><version>${jjwt.version}</version></dependency>
        <dependency><groupId>io.jsonwebtoken</groupId><artifactId>jjwt-impl</artifactId><version>${jjwt.version}</version><scope>runtime</scope></dependency>
        <dependency><groupId>io.jsonwebtoken</groupId><artifactId>jjwt-jackson</artifactId><version>${jjwt.version}</version><scope>runtime</scope></dependency>

        <dependency><groupId>cn.hutool</groupId><artifactId>hutool-all</artifactId><version>${hutool.version}</version></dependency>

        <dependency><groupId>org.projectlombok</groupId><artifactId>lombok</artifactId><optional>true</optional></dependency>

        <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-test</artifactId><scope>test</scope></dependency>
        <dependency><groupId>org.springframework.security</groupId><artifactId>spring-security-test</artifactId><scope>test</scope></dependency>
        <dependency><groupId>org.testcontainers</groupId><artifactId>junit-jupiter</artifactId><version>${testcontainers.version}</version><scope>test</scope></dependency>
        <dependency><groupId>org.testcontainers</groupId><artifactId>mysql</artifactId><version>${testcontainers.version}</version><scope>test</scope></dependency>
    </dependencies>

    <build>
        <plugins>
            <plugin><groupId>org.springframework.boot</groupId><artifactId>spring-boot-maven-plugin</artifactId>
                <configuration><excludes><exclude><groupId>org.projectlombok</groupId><artifactId>lombok</artifactId></exclude></excludes></configuration>
            </plugin>
        </plugins>
    </build>
</project>
```

- [ ] **Step 2: 新建启动类 `ReservationApplication.java`**

```java
package com.lab.reservation;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;

@SpringBootApplication
@MapperScan("com.lab.reservation.mapper")
@EnableAsync
public class ReservationApplication {
    public static void main(String[] args) {
        SpringApplication.run(ReservationApplication.class, args);
    }
}
```

- [ ] **Step 3: 删除旧 `src/main/java/org/example/Main.java` 及空目录**

- [ ] **Step 4: 新建 `application.yml`**

```yaml
spring:
  profiles:
    active: dev
  application:
    name: lab-devices-reservation
  jackson:
    date-format: yyyy-MM-dd HH:mm:ss
    time-zone: Asia/Shanghai
server:
  port: 8080
  servlet:
    context-path: /api
mybatis-plus:
  configuration:
    map-underscore-to-camel-case: true
    log-impl: org.apache.ibatis.logging.stdout.StdOutImpl
  global-config:
    db-config:
      id-type: auto
      logic-delete-field: deleted
lab:
  slot:
    minutes: 15
    work-start: "08:00"
    work-end: "22:00"
    check-in-grace-minutes: 0
jwt:
  secret: "change-me-please-this-is-a-dev-secret-key-at-least-32-bytes-long!!"
  access-ttl: 7200        # 秒，2h
  refresh-ttl: 604800     # 秒，7d
```

- [ ] **Step 5: 新建 `application-dev.yml`**（本地 MySQL，需先建库 `lab_reservation`）

```yaml
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/lab_reservation?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai&useSSL=false&allowPublicKeyRetrieval=true
    username: root
    password: root
    driver-class-name: com.mysql.cj.jdbc.Driver
  flyway:
    enabled: true
    baseline-on-migrate: true
    locations: classpath:db/migration
logging:
  level:
    com.lab.reservation: debug
```

- [ ] **Step 6: 验证可编译**

Run: `mvn -q -DskipTests compile`
Expected: BUILD SUCCESS（依赖全部下载成功）。

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: 项目骨架(pom/yml/启动类)"
```

---

## Task 2: Flyway 建表 + 种子数据

**Files:**
- Create: `src/main/resources/db/migration/V1__init_schema.sql`
- Create: `src/main/resources/db/migration/V2__seed_data.sql`

- [ ] **Step 1: V1 建表脚本（含唯一索引 = 防超约核心）**

```sql
-- V1__init_schema.sql
CREATE TABLE sys_user (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(64) NOT NULL UNIQUE,
  password VARCHAR(100) NOT NULL,
  real_name VARCHAR(50),
  phone VARCHAR(20), email VARCHAR(100),
  user_type VARCHAR(20) DEFAULT 'STUDENT',
  dept_name VARCHAR(100),
  status TINYINT DEFAULT 1 COMMENT '0禁用 1正常',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE sys_role (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  role_code VARCHAR(50) NOT NULL UNIQUE,
  role_name VARCHAR(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE sys_user_role (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL, role_id BIGINT NOT NULL,
  UNIQUE KEY uk_user_role (user_id, role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE sys_permission (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  perm_code VARCHAR(100) NOT NULL UNIQUE,
  name VARCHAR(100), type VARCHAR(20), parent_id BIGINT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE sys_role_permission (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  role_id BIGINT NOT NULL, permission_id BIGINT NOT NULL,
  UNIQUE KEY uk_role_perm (role_id, permission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE lab (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL, location VARCHAR(200),
  manager_id BIGINT, description VARCHAR(500),
  status TINYINT DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE device_category (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL, parent_id BIGINT DEFAULT 0, sort INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE device (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL, category_id BIGINT, lab_id BIGINT,
  brand VARCHAR(100), model VARCHAR(100), specs VARCHAR(500), image_url VARCHAR(500),
  status VARCHAR(20) DEFAULT 'IDLE' COMMENT 'IDLE/IN_USE/MAINTENANCE',
  need_approval TINYINT DEFAULT 0,
  max_reservation_hours DECIMAL(5,2) DEFAULT 8.00,
  price_per_hour DECIMAL(10,2) DEFAULT 0.00,
  tags JSON, description TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_lab (lab_id), KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE reservation (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL, device_id BIGINT NOT NULL,
  purpose VARCHAR(500),
  start_time DATETIME NOT NULL, end_time DATETIME NOT NULL,
  slot_count INT NOT NULL,
  status VARCHAR(20) NOT NULL COMMENT 'PENDING/APPROVED/IN_USE/COMPLETED/REJECTED/CANCELLED/VIOLATED/NO_SHOW',
  approver_id BIGINT, approved_at DATETIME, reject_reason VARCHAR(500),
  check_in_at DATETIME, check_out_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_user_status (user_id, status),
  KEY idx_device_status (device_id, status),
  KEY idx_status_start (status, start_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE reservation_item (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  reservation_id BIGINT NOT NULL,
  device_id BIGINT NOT NULL,
  date DATE NOT NULL,
  slot_index INT NOT NULL,
  UNIQUE KEY uk_device_date_slot (device_id, date, slot_index) COMMENT '硬防超约',
  KEY idx_reservation (reservation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE repair_report (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  device_id BIGINT NOT NULL, reporter_id BIGINT NOT NULL,
  title VARCHAR(200), description TEXT, image_urls JSON,
  status VARCHAR(20) DEFAULT 'PENDING' COMMENT 'PENDING/PROCESSING/RESOLVED/REJECTED',
  handler_id BIGINT, resolution_note VARCHAR(500),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  resolved_at DATETIME,
  KEY idx_device (device_id), KEY idx_reporter (reporter_id), KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE notification (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL, type VARCHAR(50),
  title VARCHAR(200), content VARCHAR(1000),
  related_id BIGINT, related_type VARCHAR(50),
  is_read TINYINT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_user_read (user_id, is_read)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE operation_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT, username VARCHAR(64),
  action VARCHAR(200), method VARCHAR(200), params TEXT,
  ip VARCHAR(50), cost_ms BIGINT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_user (user_id), KEY idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- [ ] **Step 2: V2 种子数据（角色/权限/映射/示例数据，不含 admin 密码哈希——admin 由 Java 初始化器种）**

```sql
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
```

- [ ] **Step 3: 启动验证迁移成功**

本地先建库：`mysql -uroot -proot -e "CREATE DATABASE IF NOT EXISTS lab_reservation DEFAULT CHARSET utf8mb4;"`
Run: `mvn spring-boot:run`
Expected: 日志出现 `Flyway ... Migrating schema ... Successfully applied 2 migrations`，无报错（此时无 Web 接口，404 属正常）。Ctrl+C 停止。

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(db): Flyway 建表脚本+种子数据"
```

---

## Task 3: 公共基础设施（Result/异常/枚举）

**Files:**
- Create: `common/result/Result.java`, `common/result/ResultCode.java`
- Create: `exception/BusinessException.java`, `exception/GlobalExceptionHandler.java`
- Test: `common/result/ResultTest.java`

- [ ] **Step 1: `ResultCode` 枚举**

```java
package com.lab.reservation.common.result;

import lombok.Getter;

@Getter
public enum ResultCode {
    SUCCESS(200,"成功"),
    PARAM_INVALID(400,"参数校验失败"),
    UNAUTHORIZED(401,"未认证或登录失效"),
    FORBIDDEN(403,"无权限"),
    NOT_FOUND(404,"资源不存在"),
    RESERVATION_CONFLICT(409,"该时段已被占用"),
    USERNAME_OR_PASSWORD_ERROR(1001,"用户名或密码错误"),
    ACCOUNT_DISABLED(1002,"账号已禁用"),
    USERNAME_EXISTS(1003,"用户名已存在"),
    SLOT_OUT_OF_WORK_WINDOW(2001,"不在可预约工作时段内"),
    SLOT_NOT_ALIGNED(2002,"起止时间须以15分钟为单位"),
    EXCEED_MAX_DURATION(2003,"超过单次最大可预约时长"),
    DEVICE_UNAVAILABLE(2004,"设备当前不可预约"),
    STATUS_TRANSITION_INVALID(2005,"预约状态不允许该操作"),
    BUSINESS_ERROR(5000,"业务异常");

    private final int code; private final String msg;
    ResultCode(int code,String msg){this.code=code;this.msg=msg;}
}
```

- [ ] **Step 2: `Result<T>`**

```java
package com.lab.reservation.common.result;
import lombok.Data;
@Data
public class Result<T> {
    private int code; private String msg; private T data;
    public static <T> Result<T> ok(T data){ Result<T> r=new Result<>(); r.code=ResultCode.SUCCESS.getCode(); r.msg=ResultCode.SUCCESS.getMsg(); r.data=data; return r;}
    public static <T> Result<T> ok(){ return ok(null);}
    public static <T> Result<T> fail(ResultCode rc){ Result<T> r=new Result<>(); r.code=rc.getCode(); r.msg=rc.getMsg(); return r;}
    public static <T> Result<T> fail(int code,String msg){ Result<T> r=new Result<>(); r.code=code; r.msg=msg; return r;}
}
```

- [ ] **Step 3: 写 `ResultTest`（最小校验）**

```java
package com.lab.reservation.common.result;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ResultTest {
    @Test void ok_sets_success_code_and_data(){
        Result<String> r = Result.ok("hi");
        assertEquals(200, r.getCode());
        assertEquals("hi", r.getData());
    }
    @Test void fail_sets_error_code(){
        assertEquals(409, Result.fail(ResultCode.RESERVATION_CONFLICT).getCode());
    }
}
```

- [ ] **Step 4: 跑测试验证通过**

Run: `mvn -q test -Dtest=ResultTest`
Expected: PASS。

- [ ] **Step 5: `BusinessException`**

```java
package com.lab.reservation.exception;
import com.lab.reservation.common.result.ResultCode;
import lombok.Getter;

@Getter
public class BusinessException extends RuntimeException {
    private final int code;
    public BusinessException(ResultCode rc){ super(rc.getMsg()); this.code=rc.getCode(); }
    public BusinessException(int code,String msg){ super(msg); this.code=code; }
}
```

- [ ] **Step 6: `GlobalExceptionHandler`**

```java
package com.lab.reservation.exception;
import com.lab.reservation.common.result.Result;
import com.lab.reservation.common.result.ResultCode;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {
    @ExceptionHandler(BusinessException.class)
    public Result<?> biz(BusinessException e){ return Result.fail(e.getCode(), e.getMessage()); }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public Result<?> invalid(MethodArgumentNotValidException e){
        FieldError fe = e.getBindingResult().getFieldError();
        return Result.fail(ResultCode.PARAM_INVALID.getCode(), fe!=null? fe.getDefaultMessage():ResultCode.PARAM_INVALID.getMsg());
    }

    @ExceptionHandler(DuplicateKeyException.class)
    public Result<?> dup(DuplicateKeyException e){ return Result.fail(ResultCode.RESERVATION_CONFLICT); }

    @ExceptionHandler(AuthenticationException.class)
    public Result<?> auth(AuthenticationException e){ return Result.fail(ResultCode.UNAUTHORIZED); }

    @ExceptionHandler(AccessDeniedException.class)
    public Result<?> denied(AccessDeniedException e){ return Result.fail(ResultCode.FORBIDDEN); }

    @ExceptionHandler(Exception.class)
    public Result<?> all(Exception e){ e.printStackTrace(); return Result.fail(ResultCode.BUSINESS_ERROR); }
}
```

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat(common): Result/ResultCode/BusinessException/全局异常"
```

---

## Task 4: 实体层 + Mapper + MyBatis-Plus 配置

**Files:**
- Create: `entity/enums/*.java`（6 个枚举）
- Create: `entity/*.java`（13 实体）
- Create: `mapper/*.java`（13 Mapper）
- Create: `config/MyBatisPlusConfig.java`

- [ ] **Step 1: 枚举（示例 2 个，其余同理）**

```java
package com.lab.reservation.entity.enums;
public enum DeviceStatus { IDLE, IN_USE, MAINTENANCE }
```
```java
package com.lab.reservation.entity.enums;
public enum ReservationStatus { PENDING, APPROVED, IN_USE, COMPLETED, REJECTED, CANCELLED, VIOLATED, NO_SHOW }
```
其余：`RepairStatus{PENDING,PROCESSING,RESOLVED,REJECTED}`、`RoleType{STUDENT,LAB_ADMIN,SYS_ADMIN}`、`UserType{STUDENT,TEACHER,STAFF}`、`UserStatus{NORMAL,DISABLED}`。

- [ ] **Step 2: 实体基类 + 典型实体**

```java
package com.lab.reservation.entity;
import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;
import java.time.LocalDateTime;

@Data
public class BaseEntity {
    @TableId(type = IdType.AUTO) private Long id;
    @TableField(fill = FieldFill.INSERT) private LocalDateTime createdAt;
    @TableField(fill = FieldFill.INSERT_UPDATE) private LocalDateTime updatedAt;
}
```

```java
package com.lab.reservation.entity;
import com.baomidou.mybatisplus.annotation.*;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.Data; import lombok.EqualsAndHashCode;
import java.math.BigDecimal; import java.util.List;

@Data @EqualsAndHashCode(callSuper = true)
@TableName(value = "device", autoResultMap = true)
public class Device extends BaseEntity {
    private String name; private Long categoryId; private Long labId;
    private String brand; private String model; private String specs; private String imageUrl;
    private String status;            // DeviceStatus name
    private Integer needApproval;
    private BigDecimal maxReservationHours;
    private BigDecimal pricePerHour;
    @TableField(typeHandler = JacksonTypeHandler.class) private List<String> tags;
    private String description;
}
```

其余实体按 §5.4 字段逐个建（SysUser/SysRole/SysUserRole/SysPermission/SysRolePermission/Lab/DeviceCategory/Reservation/ReservationItem/RepairReport/Notification/OperationLog），均 `extends BaseEntity`（无 created_at 的角色/权限/映射表可不继承，自定义字段）。`ReservationItem` 含 `reservationId, deviceId, date(LocalDate), slotIndex`。`RepairReport.imageUrls` 同 tags 用 JacksonTypeHandler。

**Notification 与 OperationLog 不继承 BaseEntity**（与 V1 建表对齐，只有 created_at、无 updated_at）：
```java
@Data @TableName("notification")
public class Notification {
    @TableId(type = IdType.AUTO) private Long id;
    private Long userId; private String type; private String title; private String content;
    private Long relatedId; private String relatedType; private Integer isRead;
    @TableField(fill = FieldFill.INSERT) private LocalDateTime createdAt;
}
@Data @TableName("operation_log")
public class OperationLog {
    @TableId(type = IdType.AUTO) private Long id;
    private Long userId; private String username; private String action;
    private String method; private String params; private String ip; private Long costMs;
    @TableField(fill = FieldFill.INSERT) private LocalDateTime createdAt;
}
```
（`SysRole`/`SysPermission`/`SysUserRole`/`SysRolePermission`/`DeviceCategory` 同理自定义字段，按 V1 列定义即可。）

- [ ] **Step 3: Mapper 接口（13 个，模式一致）**

```java
package com.lab.reservation.mapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.lab.reservation.entity.Device;
import org.apache.ibatis.annotations.Mapper;

@Mapper public interface DeviceMapper extends BaseMapper<Device> {}
```
为 13 张表各建一个：`SysUserMapper, SysRoleMapper, SysUserRoleMapper, SysPermissionMapper, SysRolePermissionMapper, LabMapper, DeviceCategoryMapper, DeviceMapper, ReservationMapper, ReservationItemMapper, RepairReportMapper, NotificationMapper, OperationLogMapper`。

- [ ] **Step 4: `MyBatisPlusConfig`（分页插件 + 自动填充）**

```java
package com.lab.reservation.config;
import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.core.handlers.MetaObjectHandler;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.PaginationInnerInterceptor;
import org.apache.ibatis.reflection.MetaObject;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import java.time.LocalDateTime;

@Configuration
public class MyBatisPlusConfig {
    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor(){
        MybatisPlusInterceptor i = new MybatisPlusInterceptor();
        i.addInnerInterceptor(new PaginationInnerInterceptor());
        return i;
    }
    @Bean
    public MetaObjectHandler metaObjectHandler(){
        return new MetaObjectHandler(){
            @Override public void insertFill(MetaObject m){ strictInsertFill(m,"createdAt", LocalDateTime.class, LocalDateTime.now()); strictInsertFill(m,"updatedAt", LocalDateTime.class, LocalDateTime.now()); }
            @Override public void updateFill(MetaObject m){ strictUpdateFill(m,"updatedAt", LocalDateTime.class, LocalDateTime.now()); }
        };
    }
}
```

- [ ] **Step 5: 验证编译**

Run: `mvn -q -DskipTests compile`
Expected: BUILD SUCCESS。

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(entity): 13实体+枚举+Mapper+MP配置"
```

---

## Task 5: JWT 工具 + 安全基础（TDD on JwtUtils）

**Files:**
- Create: `security/JwtProperties.java`, `security/JwtUtils.java`
- Test: `security/JwtUtilsTest.java`

- [ ] **Step 1: 先写失败测试 `JwtUtilsTest`**

```java
package com.lab.reservation.security;
import io.jsonwebtoken.Claims;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class JwtUtilsTest {
    private JwtUtils jwt;
    @BeforeEach void setup(){
        JwtProperties p = new JwtProperties();
        p.setSecret("unit-test-secret-key-must-be-at-least-32-bytes-long!!");
        p.setAccessTtl(60L); p.setRefreshTtl(120L);
        jwt = new JwtUtils(p);
    }
    @Test void access_token_roundtrip_keeps_claims(){
        String token = jwt.generateAccess(1L, "alice", java.util.List.of("STUDENT"));
        Claims c = jwt.parse(token);
        assertEquals(1L, Long.parseLong(c.getSubject()));
        assertEquals("alice", c.get("username"));
    }
    @Test void parse_invalid_token_returns_null(){
        assertNull(jwt.parse("not.a.jwt"));
    }
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `mvn -q test -Dtest=JwtUtilsTest`
Expected: 编译失败（JwtUtils/JwtProperties 不存在）。

- [ ] **Step 3: 实现 `JwtProperties` + `JwtUtils`**

```java
package com.lab.reservation.security;
import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Data @Component
@ConfigurationProperties(prefix = "jwt")
public class JwtProperties {
    private String secret;
    private Long accessTtl;   // 秒
    private Long refreshTtl;  // 秒
}
```

```java
package com.lab.reservation.security;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date; import java.util.List;

public class JwtUtils {
    private final JwtProperties props;
    private final SecretKey key;
    public JwtUtils(JwtProperties props){
        this.props = props;
        this.key = Keys.hmacShaKeyFor(props.getSecret().getBytes(StandardCharsets.UTF_8));
    }
    public String generateAccess(Long userId, String username, List<String> roles){
        return build(userId, username, roles, props.getAccessTtl(), "access");
    }
    public String generateRefresh(Long userId, String username){
        return build(userId, username, null, props.getRefreshTtl(), "refresh");
    }
    private String build(Long userId, String username, List<String> roles, long ttlSec, String type){
        long now = System.currentTimeMillis();
        var b = Jwts.builder().subject(String.valueOf(userId)).issuedAt(new Date(now))
                .expiration(new Date(now + ttlSec*1000)).claim("username", username).claim("type", type);
        if (roles != null) b.claim("roles", roles);
        return b.signWith(key).compact();
    }
    public Claims parse(String token){
        try { return Jwts.parser().verifyWith(key).build().parseSignedClaims(token).getPayload(); }
        catch (Exception e){ return null; }
    }
}
```

- [ ] **Step 4: 把 JwtUtils 注册为 Bean（在 SecurityConfig 里 `@Bean`，见 Task 6）**——此处测试用 `new JwtUtils(props)`，生产由 Spring 注入。先加一个配置类桥接：

Create `security/JwtConfig.java`：
```java
package com.lab.reservation.security;
import org.springframework.context.annotation.Bean; import org.springframework.context.annotation.Configuration;

@Configuration
public class JwtConfig {
    @Bean public JwtUtils jwtUtils(JwtProperties p){ return new JwtUtils(p); }
}
```

- [ ] **Step 5: 跑测试验证通过**

Run: `mvn -q test -Dtest=JwtUtilsTest`
Expected: PASS（2 个用例）。

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(security): JwtUtils+Properties(TDD)"
```

---

## Task 6: Security 链路 + Auth 模块 + 默认管理员初始化

**Files:**
- Create: `security/SecurityUserDetails.java`, `security/JwtAuthenticationFilter.java`, `config/SecurityConfig.java`
- Create: `security/CustomUserDetailsService.java`
- Create: `service/AuthService.java`, `service/impl/AuthServiceImpl.java`, `controller/AuthController.java`
- Create: `dto/auth/LoginDTO.java`, `dto/auth/RegisterDTO.java`, `vo/auth/LoginVO.java`, `vo/auth/UserInfoVO.java`
- Create: `init/DataInitializer.java`

- [ ] **Step 1: `SecurityUserDetails` + `CustomUserDetailsService`**

```java
package com.lab.reservation.security;
import lombok.Getter;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.User;
import java.util.List; import java.util.stream.Collectors;

@Getter
public class SecurityUserDetails extends User {
    private final Long userId;
    public SecurityUserDetails(Long userId, String username, String password,
                               List<String> roles, List<String> perms){
        super(username, password,
              roles.stream().map(r->new SimpleGrantedAuthority("ROLE_"+r)).collect(Collectors.toList()),
              perms.stream().map(SimpleGrantedAuthority::new).collect(Collectors.toList()));
        this.userId = userId;
    }
    // 合并 roles(ROLE_xxx) 与 perms 为 authorities（super 已合并）
}
```
注：`User` 构造的 authorities 同时含 `ROLE_*` 与 perm_code，`hasRole/hasAuthority` 均可用。

```java
package com.lab.reservation.security;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.lab.reservation.entity.*;
import com.lab.reservation.mapper.*;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;
import java.util.List; import java.util.stream.Collectors;

@Service @RequiredArgsConstructor
public class CustomUserDetailsService implements UserDetailsService {
    private final SysUserMapper userMapper;
    private final SysUserRoleMapper userRoleMapper;
    private final SysRoleMapper roleMapper;
    private final SysRolePermissionMapper rpMapper;
    private final SysPermissionMapper permMapper;

    @Override public UserDetails loadUserByUsername(String username){
        SysUser u = userMapper.selectOne(new LambdaQueryWrapper<SysUser>().eq(SysUser::getUsername, username));
        if (u == null) throw new UsernameNotFoundException(username);
        List<Long> roleIds = userRoleMapper.selectList(new LambdaQueryWrapper<SysUserRole>().eq(SysUserRole::getUserId, u.getId()))
                .stream().map(SysUserRole::getRoleId).collect(Collectors.toList());
        List<String> roleCodes = roleMapper.selectBatchIds(roleIds).stream().map(SysRole::getRoleCode).collect(Collectors.toList());
        List<Long> permIds = rpMapper.selectList(new LambdaQueryWrapper<SysRolePermission>().in(SysRolePermission::getRoleId, roleIds))
                .stream().map(SysRolePermission::getPermissionId).collect(Collectors.toList());
        List<String> permCodes = permIds.isEmpty()? List.of() :
                permMapper.selectBatchIds(permIds).stream().map(SysPermission::getPermCode).collect(Collectors.toList());
        return new SecurityUserDetails(u.getId(), u.getUsername(), u.getPassword(), roleCodes, permCodes);
    }

    public Long userIdOf(org.springframework.security.core.userdetails.UserDetails ud){ return ((SecurityUserDetails)ud).getUserId(); }
}
```

- [ ] **Step 2: `JwtAuthenticationFilter`**

```java
package com.lab.reservation.security;
import io.jsonwebtoken.Claims;
import jakarta.servlet.FilterChain; import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest; import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import java.io.IOException;

@Component @RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter {
    private final JwtUtils jwt; private final CustomUserDetailsService uds;
    @Override protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
            throws ServletException, IOException {
        String header = req.getHeader("Authorization");
        if (header != null && header.startsWith("Bearer ")){
            String token = header.substring(7);
            Claims c = jwt.parse(token);
            if (c != null && SecurityContextHolder.getContext().getAuthentication() == null){
                String username = String.valueOf(c.get("username"));
                try {
                    UserDetails ud = uds.loadUserByUsername(username);
                    UsernamePasswordAuthenticationToken auth =
                        new UsernamePasswordAuthenticationToken(ud, null, ud.getAuthorities());
                    auth.setDetails(new WebAuthenticationDetailsSource().buildDetails(req));
                    SecurityContextHolder.getContext().setAuthentication(auth);
                } catch (Exception ignored){}
            }
        }
        chain.doFilter(req, res);
    }
}
```

- [ ] **Step 3: `SecurityConfig`**

```java
package com.lab.reservation.config;
import com.lab.reservation.security.JwtAuthenticationFilter;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean; import org.springframework.context.annotation.Configuration;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.config.annotation.authentication.configuration.AuthenticationConfiguration;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

@Configuration @EnableMethodSecurity @RequiredArgsConstructor
public class SecurityConfig {
    private final JwtAuthenticationFilter jwtFilter;
    @Bean public PasswordEncoder passwordEncoder(){ return new BCryptPasswordEncoder(); }
    @Bean public AuthenticationManager authenticationManager(AuthenticationConfiguration cfg) throws Exception { return cfg.getAuthenticationManager(); }
    @Bean public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http.csrf(c->c.disable()).cors(c->{}).sessionManagement(s->s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(a -> a
                .requestMatchers("/auth/login","/auth/register","/auth/refresh",
                                 "/doc.html","/doc.html/**","/webjars/**","/v3/api-docs/**","/swagger-resources/**","/favicon.ico").permitAll()
                .anyRequest().authenticated())
            .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }
}
```
注意：因 `server.servlet.context-path=/api`，匹配路径不带 `/api` 前缀。

- [ ] **Step 4: DTO/VO**

`LoginDTO{username,password}`；`RegisterDTO{username,password,realName,phone,userType(默认STUDENT)}`；`LoginVO{accessToken,refreshToken,expiresIn,userInfo}`；`UserInfoVO{id,username,realName,roles(List),permissions(List)}`。

- [ ] **Step 5: `AuthService` + impl**

```java
package com.lab.reservation.service;
import com.lab.reservation.dto.auth.LoginDTO;
import com.lab.reservation.dto.auth.RegisterDTO;
import com.lab.reservation.vo.auth.LoginVO;
public interface AuthService {
    LoginVO login(LoginDTO dto);
    void register(RegisterDTO dto);
    String refresh(String refreshToken);
    void logout(String token);
}
```
> `logout` 在无状态 JWT 下阶段1 为**前端丢弃 token** 即可（服务端不强制）。接口保留一个空实现端点以满足 spec §8.1，可选追加注释「服务端黑名单/Redis 失效延后到阶段2」。

`AuthServiceImpl` 要点（完整实现）：
- `login`：用 `AuthenticationManager`（或 `UserDetailsService` + `passwordEncoder.matches`）校验；账号禁用（status=0）抛 `ACCOUNT_DISABLED`；校验通过后 `jwt.generateAccess/Refresh`，组装 `LoginVO`（userInfo 含 roles/permissions，从 `SecurityUserDetails.getAuthorities` 拆出 `ROLE_` 与 perm_code）。
- `register`：username 已存在抛 `USERNAME_EXISTS`；密码 BCrypt 加密；插入 sys_user；插入 sys_user_role 绑定 STUDENT 角色id。
- `refresh`：`jwt.parse(refreshToken)`，type 必须为 `refresh`，否则抛 `UNAUTHORIZED`；重新签发 access。

- [ ] **Step 6: `AuthController`**

```java
package com.lab.reservation.controller;
import com.lab.reservation.common.result.Result;
import com.lab.reservation.dto.auth.LoginDTO;
import com.lab.reservation.dto.auth.RegisterDTO;
import com.lab.reservation.service.AuthService;
import com.lab.reservation.vo.auth.LoginVO;
import com.lab.reservation.vo.auth.UserInfoVO;
import com.lab.reservation.security.CustomUserDetailsService;
import com.lab.reservation.security.SecurityUserDetails;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@Tag(name="鉴权") @RestController @RequestMapping("/auth") @RequiredArgsConstructor
public class AuthController {
    private final AuthService authService;
    private final CustomUserDetailsService uds;

    @Operation(summary="登录") @PostMapping("/login")
    public Result<LoginVO> login(@Valid @RequestBody LoginDTO dto){ return Result.ok(authService.login(dto)); }

    @Operation(summary="注册") @PostMapping("/register")
    public Result<?> register(@Valid @RequestBody RegisterDTO dto){ authService.register(dto); return Result.ok(); }

    @Operation(summary="刷新token") @PostMapping("/refresh")
    public Result<?> refresh(@RequestParam String refreshToken){ return Result.ok(java.util.Map.of("accessToken", authService.refresh(refreshToken))); }

    @Operation(summary="登出") @PostMapping("/logout")
    public Result<?> logout(@RequestHeader("Authorization") String auth){ authService.logout(auth); return Result.ok(); }

    @Operation(summary="当前用户") @GetMapping("/me")
    public Result<UserInfoVO> me(@AuthenticationPrincipal SecurityUserDetails ud){
        UserInfoVO vo = new UserInfoVO();
        vo.setId(ud.getUserId()); vo.setUsername(ud.getUsername());
        List<String> auths = ud.getAuthorities().stream().map(a->a.getAuthority()).toList();
        vo.setRoles(auths.stream().filter(a->a.startsWith("ROLE_")).map(a->a.substring(5)).toList());
        vo.setPermissions(auths.stream().filter(a->!a.startsWith("ROLE_")).toList());
        return Result.ok(vo);
    }
}
```
（`/me` 需 `import java.util.List;` 与 `UserInfoVO`。从 `SecurityUserDetails` 取 userId/username，并把 authorities 拆成 `ROLE_*`(→roles) 与 perm_code(→permissions)。）

- [ ] **Step 7: `DataInitializer`（启动种默认 SYS_ADMIN，避免硬编码 BCrypt 哈希）**

```java
package com.lab.reservation.init;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.lab.reservation.entity.*;
import com.lab.reservation.mapper.*;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean; import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.password.PasswordEncoder;

@Configuration @RequiredArgsConstructor
public class DataInitializer {
    @Bean ApplicationRunner seedAdmin(SysUserMapper userMapper, SysRoleMapper roleMapper,
                                      SysUserRoleMapper urMapper, PasswordEncoder encoder){
        return args -> {
            if (userMapper.exists(new LambdaQueryWrapper<SysUser>().eq(SysUser::getUsername, "admin"))) return;
            SysUser admin = new SysUser();
            admin.setUsername("admin"); admin.setPassword(encoder.encode("admin123"));
            admin.setRealName("超级管理员"); admin.setUserType("STAFF"); admin.setStatus(1);
            userMapper.insert(admin);
            SysRole sysRole = roleMapper.selectOne(new LambdaQueryWrapper<SysRole>().eq(SysRole::getRoleCode,"SYS_ADMIN"));
            SysUserRole ur = new SysUserRole(); ur.setUserId(admin.getId()); ur.setRoleId(sysRole.getId());
            urMapper.insert(ur);
        };
    }
}
```

- [ ] **Step 8: 端到端冒烟（手动）**

Run: `mvn spring-boot:run`
另开终端：
```
curl -X POST http://localhost:8080/api/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}'
```
Expected: 返回 `{"code":200,...,"data":{"accessToken":"...",...}}`。用该 token 调 `/auth/me` 返回用户信息。

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat(auth): Security链路+登录注册/刷新/me+默认admin"
```

---

## Task 7: SlotCalculator（纯逻辑，严格 TDD —— 防超约前置）

**Files:**
- Create: `service/SlotCalculatorService.java`
- Create: `common/SlotKey.java`（或 inner record）
- Test: `service/SlotCalculatorServiceTest.java`

- [ ] **Step 1: 先写失败测试（覆盖 spec §6.2 全部边界）**

```java
package com.lab.reservation.service;
import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.exception.BusinessException;
import org.junit.jupiter.api.Test;
import java.time.LocalDate; import java.time.LocalDateTime; import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class SlotCalculatorServiceTest {
    private final SlotCalculatorService calc = new SlotCalculatorService(15, java.time.LocalTime.of(8,0), java.time.LocalTime.of(22,0));
    // 工作窗 08:00-22:00，15分/槽 → 当日 slot 0..55

    @Test void single_slot_aligned(){
        var items = calc.compute(1L, LocalDateTime.of(2026,7,1,8,0), LocalDateTime.of(2026,7,1,8,15));
        assertEquals(1, items.size());
        assertEquals(0, items.get(0).slotIndex());
        assertEquals(LocalDate.of(2026,7,1), items.get(0).date());
    }
    @Test void multi_slot_same_day(){
        var items = calc.compute(1L, LocalDateTime.of(2026,7,1,9,0), LocalDateTime.of(2026,7,1,10,30));
        assertEquals(6, items.size());           // 90分钟/15=6
        assertEquals(4, items.get(0).slotIndex());
    }
    @Test void not_aligned_throws(){
        BusinessException e = assertThrows(BusinessException.class, () ->
            calc.compute(1L, LocalDateTime.of(2026,7,1,9,7), LocalDateTime.of(2026,7,1,10,0)));
        assertEquals(ResultCode.SLOT_NOT_ALIGNED.getCode(), e.getCode());
    }
    @Test void out_of_window_before_throws(){
        BusinessException e = assertThrows(BusinessException.class, () ->
            calc.compute(1L, LocalDateTime.of(2026,7,1,7,0), LocalDateTime.of(2026,7,1,8,15)));
        assertEquals(ResultCode.SLOT_OUT_OF_WORK_WINDOW.getCode(), e.getCode());
    }
    @Test void out_of_window_after_throws(){
        assertThrows(BusinessException.class, () ->
            calc.compute(1L, LocalDateTime.of(2026,7,1,21,45), LocalDateTime.of(2026,7,1,22,15)));
    }
    @Test void start_equals_end_throws(){
        assertThrows(BusinessException.class, () ->
            calc.compute(1L, LocalDateTime.of(2026,7,1,9,0), LocalDateTime.of(2026,7,1,9,0)));
    }
    @Test void cross_day_spans_two_dates(){
        // 跨天但仍在各自工作窗内：21:45→次日09:00
        var items = calc.compute(1L, LocalDateTime.of(2026,7,1,21,45), LocalDateTime.of(2026,7,2,9,0));
        // 首日 21:45-22:00 = 1 槽(slot 55)
        assertTrue(items.stream().anyMatch(i -> i.date().equals(LocalDate.of(2026,7,1)) && i.slotIndex()==55));
        // 次日 08:00-09:00 = 4 槽(slot 0..3)，顺序保留
        List<Integer> nextDay = items.stream().filter(i->i.date().equals(LocalDate.of(2026,7,2)))
            .map(SlotKey::slotIndex).toList();
        assertEquals(List.of(0,1,2,3), nextDay);
    }
}
```
（修正 cross_day 断言里笔误：`LocalDate.of(2026,7,2)`。）

- [ ] **Step 2: 跑测试确认失败（类不存在）**

Run: `mvn -q test -Dtest=SlotCalculatorServiceTest`
Expected: 编译失败。

- [ ] **Step 3: 实现 `SlotCalculatorService` + `SlotKey`**

```java
package com.lab.reservation.service;
import java.time.LocalDate; import java.time.LocalTime;
public record SlotKey(Long deviceId, LocalDate date, int slotIndex) {}
```

```java
package com.lab.reservation.service;
import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.exception.BusinessException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import java.time.LocalDate; import java.time.LocalDateTime; import java.time.LocalTime; import java.time.Duration;
import java.util.ArrayList; import java.util.List;

@Component
public class SlotCalculatorService {
    private final int slotMinutes;
    private final LocalTime workStart; private final LocalTime workEnd;

    public SlotCalculatorService(@Value("${lab.slot.minutes:15}") int slotMinutes,
                                 @Value("${lab.slot.work-start:08:00}") String workStart,
                                 @Value("${lab.slot.work-end:22:00}") String workEnd){
        this.slotMinutes = slotMinutes;
        this.workStart = LocalTime.parse(workStart);
        this.workEnd = LocalTime.parse(workEnd);
    }

    public List<SlotKey> compute(Long deviceId, LocalDateTime start, LocalDateTime end){
        if (!start.isBefore(end)) throw new BusinessException(ResultCode.SLOT_NOT_ALIGNED);
        if (!isAligned(start) || !isAligned(end)) throw new BusinessException(ResultCode.SLOT_NOT_ALIGNED);

        List<SlotKey> out = new ArrayList<>();
        for (LocalDate d = start.toLocalDate(); !d.isAfter(end.toLocalDate()); d = d.plusDays(1)){
            LocalTime dayStart = d.equals(start.toLocalDate()) ? start.toLocalTime() : workStart;
            LocalTime dayEnd   = d.equals(end.toLocalDate())   ? end.toLocalTime()   : workEnd;
            if (!dayStart.isBefore(workStart) || dayStart.equals(workStart)) { /* ok */ }
            if (dayStart.isBefore(workStart)) throw new BusinessException(ResultCode.SLOT_OUT_OF_WORK_WINDOW);
            if (dayEnd.isAfter(workEnd)) throw new BusinessException(ResultCode.SLOT_OUT_OF_WORK_WINDOW);
            int startSlot = (int) Duration.between(workStart, dayStart).toMinutes() / slotMinutes;
            int endSlot   = (int) Duration.between(workStart, dayEnd).toMinutes() / slotMinutes;
            for (int s = startSlot; s < endSlot; s++) out.add(new SlotKey(deviceId, d, s));
        }
        if (out.isEmpty()) throw new BusinessException(ResultCode.SLOT_NOT_ALIGNED);
        return out;
    }
    private boolean isAligned(LocalDateTime t){
        return t.getMinute() % slotMinutes == 0 && t.getSecond()==0 && t.getNano()==0;
    }
}
```

- [ ] **Step 4: 跑测试验证通过**

Run: `mvn -q test -Dtest=SlotCalculatorServiceTest`
Expected: PASS（修正 cross_day 断言后全绿）。

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(reservation): SlotCalculator纯逻辑(TDD)"
```

---

## Task 8: Lab / DeviceCategory / Device（CRUD + 多条件检索 + 设备日历）

**Files:**
- Create: `service/{LabService,DeviceCategoryService,DeviceService}.java` + `impl/*`
- Create: `controller/{LabController,DeviceCategoryController,DeviceController}.java`
- Create: `dto/device/DeviceQueryDTO.java`, `dto/device/DeviceCreateDTO.java`
- Create: `vo/device/DeviceVO.java`, `vo/device/DeviceCalendarItemVO.java`

实现要点（按经典 MVC）：
- **DeviceService.search(DeviceQueryDTO, Pageable)**：MyBatis-Plus `LambdaQueryWrapper` 拼 categoryId/labId/status/keyword(like name)/needApproval/minPrice/maxPrice，分页 `IPage`。**LAB_ADMIN 仅查自辖实验室**：用下方公共 `LabScopeHelper` 过滤。
- **`LabScopeHelper.managedLabIds(currentUserId)`**（公共组件，Task 8 建立，Task 11/13/15 复用）：`SYS_ADMIN` 返回 `null`（表示不限）；`LAB_ADMIN` 查询 `lab.manager_id=currentUserId` 的 id 列表；调用方据此拼 `lab_id IN (...)` 或不拼。**避免各模块各写一份**。
- **DeviceService.calendar(deviceId, from, to)**：查 `reservation_item` JOIN `reservation`（status ∈ PENDING/APPROVED/IN_USE），between from/to，返回 `List<DeviceCalendarItemVO>{date, slotIndex, reservationId, status}`。可在 ReservationItemMapper 写自定义 XML/`@Select`。
- **DeviceCategoryService.tree()**：查全部 category 内存构树。
- **DeviceController**：`GET /devices`(分页检索)、`GET /devices/{id}`、`GET /devices/{id}/calendar`、`POST/PUT/DELETE /devices`(`@PreAuthorize("hasAuthority('device:manage')")`)、`PATCH /devices/{id}/status`。
- **LabController**：CRUD `/labs`，`@PreAuthorize` 按角色。
- **DeviceCategoryController**：`GET /device-categories`。

- [ ] **Step 1: 实现 DTO/VO/Service/Controller（按上述要点）**

- [ ] **Step 2: 手动验证**：用 admin token `GET /api/devices` 返回 3 台种子设备；`GET /api/devices/1/calendar?from=2026-07-01&to=2026-07-02` 返回空数组（无预约）。

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat(device): 实验室/分类/设备 CRUD+检索+日历"
```

---

## Task 9: Reservation 创建 + 防超约（TDD + 并发集成测试 —— 本阶段技术核心）

**Files:**
- Create: `service/ReservationService.java` + `impl/ReservationServiceImpl.java`
- Create: `controller/ReservationController.java`（仅 create，其余在 Task 10）
- Create: `dto/reservation/ReservationCreateDTO.java`
- Create: `vo/reservation/ReservationVO.java`
- Test: `reservation/ReservationConcurrencyIT.java`（Testcontainers，亮点）

- [ ] **Step 1: `ReservationCreateDTO` + `ReservationVO`**

`ReservationCreateDTO{ Long deviceId; LocalDateTime startTime; LocalDateTime endTime; String purpose; }`（加 `@NotNull`/`@NotBlank` 校验）。

- [ ] **Step 2: 写并发集成测试 `ReservationConcurrencyIT`（先写，作为防超约的契约）**

```java
package com.lab.reservation.reservation;
import com.lab.reservation.dto.reservation.ReservationCreateDTO;
import com.lab.reservation.entity.Reservation;
import com.lab.reservation.entity.ReservationItem;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.ReservationItemMapper;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.service.ReservationService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container; import org.testcontainers.junit.jupiter.Testcontainers;
import java.time.LocalDateTime; import java.util.ArrayList; import java.util.List; import java.util.UUID; import java.util.concurrent.*;

import static org.junit.jupiter.api.Assertions.*;

/** 防超约亮点实证：N 线程并发抢同一设备同一时段，断言恰好 1 成功。 */
@Testcontainers @SpringBootTest
class ReservationConcurrencyIT {
    @Container static MySQLContainer<?> mysql = new MySQLContainer<>("mysql:8.0").withDatabaseName("test").withReuse(false);
    @DynamicPropertySource static void props(DynamicPropertyRegistry r){
        r.add("spring.datasource.url", mysql::getJdbcUrl);
        r.add("spring.datasource.username", mysql::getUsername);
        r.add("spring.datasource.password", mysql::getPassword);
    }
    @Autowired ReservationService reservationService;
    @Autowired ReservationItemMapper itemMapper;
    @Autowired org.springframework.jdbc.core.JdbcTemplate jdbc;

    private final List<Long> userIds = new ArrayList<>();

    @org.junit.jupiter.api.BeforeEach void seedUsers(){
        // 设备 id=1 由 Flyway V2 种子提供(need_approval=0, max=8h)。预插 8 个学生用户拿自增 id。
        for (int i=0;i<8;i++){
            jdbc.update("INSERT INTO sys_user(username,password,real_name,status) VALUES (?,?,?,1)",
                "stu"+i, "dummy-hash-not-validated-in-create");
            userIds.add(jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class));
        }
    }

    @Test void concurrent_same_slot_only_one_wins() throws Exception {
        Long deviceId = 1L;
        LocalDateTime start = LocalDateTime.of(2026,7,3,9,0);
        LocalDateTime end   = LocalDateTime.of(2026,7,3,10,0);

        ExecutorService pool = Executors.newFixedThreadPool(8);
        List<Callable<Long>> tasks = new ArrayList<>();
        for (int i=0;i<8;i++){
            final Long uid = userIds.get(i);
            tasks.add(() -> {
                ReservationCreateDTO dto = new ReservationCreateDTO();
                dto.setDeviceId(deviceId); dto.setStartTime(start); dto.setEndTime(end);
                dto.setPurpose("p-"+uid);
                return reservationService.create(dto, uid);
            });
        }
        List<Future<Long>> futures = pool.invokeAll(tasks);
        int ok=0, conflict=0;
        for (Future<Long> f: futures){
            try { f.get(); ok++; } catch (Exception e){ if (e.getCause() instanceof BusinessException) conflict++; }
        }
        pool.shutdown();
        assertEquals(1, ok, "恰好一个预约成功");
        assertEquals(7, conflict, "其余 7 个全部冲突");
        // DB 断言：该设备该日仅 4 个槽被占(60min/15=4) 且槽号互不重复
        List<ReservationItem> held = itemMapper.selectList(null).stream()
            .filter(it -> it.getDeviceId().equals(deviceId) && it.getDate().equals(start.toLocalDate())).toList();
        assertEquals(4, held.size());
        assertEquals(4, held.stream().map(ReservationItem::getSlotIndex).distinct().count(), "槽号无重复");
    }
}
```

> **无 Docker 备选**：删除 `@Testcontainers`/`@Container`/`@DynamicPropertySource`，改 `@SpringBootTest` 默认走 dev 的本地 MySQL（先 `DROP/CREATE` 测试库或加 `spring.sql.init.mode` 清表）。并发语义不变。

- [ ] **Step 3: 跑测试确认失败（ReservationService.create 未实现）**

Run: `mvn -q test -Dtest=ReservationConcurrencyIT`
Expected: 编译/运行失败。

- [ ] **Step 4: 实现 `ReservationServiceImpl.create`**

```java
@Transactional
public Long create(ReservationCreateDTO dto, Long currentUserId){
    Device d = deviceMapper.selectById(dto.getDeviceId());
    if (d == null || "MAINTENANCE".equals(d.getStatus())) throw new BusinessException(ResultCode.DEVICE_UNAVAILABLE);
    if (!dto.getStartTime().isBefore(dto.getEndTime())) throw new BusinessException(ResultCode.SLOT_NOT_ALIGNED);
    if (dto.getStartTime().isBefore(LocalDateTime.now())) throw new BusinessException(ResultCode.PARAM_INVALID);

    List<SlotKey> slots = slotCalculator.compute(d.getId(), dto.getStartTime(), dto.getEndTime());
    int maxSlots = (int) Math.floor(d.getMaxReservationHours().doubleValue() * 60 / 15); // 槽向下取整
    if (slots.size() > maxSlots) throw new BusinessException(ResultCode.EXCEED_MAX_DURATION);

    Reservation r = new Reservation();
    r.setUserId(currentUserId); r.setDeviceId(d.getId()); r.setPurpose(dto.getPurpose());
    r.setStartTime(dto.getStartTime()); r.setEndTime(dto.getEndTime()); r.setSlotCount(slots.size());
    r.setStatus(d.getNeedApproval()==1 ? "PENDING" : "APPROVED");
    reservationMapper.insert(r);

    try {
        for (SlotKey s : slots){
            ReservationItem it = new ReservationItem();
            it.setReservationId(r.getId()); it.setDeviceId(s.deviceId()); it.setDate(s.date()); it.setSlotIndex(s.slotIndex());
            itemMapper.insert(it);
        }
    } catch (org.springframework.dao.DuplicateKeyException e){
        throw new BusinessException(ResultCode.RESERVATION_CONFLICT);
    }
    notificationService.notify(currentUserId, "RESERVATION",
        r.getStatus().equals("APPROVED") ? "预约成功" : "预约已提交，待审批", r.getId(), "RESERVATION");
    return r.getId();
}
```
说明：`itemMapper.insert` 循环插入——每条单独 INSERT，命中唯一索引即抛 `DuplicateKeyException`，整方法 `@Transactional` 回滚 reservation 插入。若要批量优化，改 `itemMapper` 自定义批量 insert XML，保证整批一个语句、失败整体回滚（事务内同样回滚）。

- [ ] **Step 5: `ReservationController.create`**

```java
@Operation(summary="创建预约") @PostMapping("/reservations")
public Result<Long> create(@Valid @RequestBody ReservationCreateDTO dto,
                           @AuthenticationPrincipal SecurityUserDetails ud){
    return Result.ok(reservationService.create(dto, ud.getUserId()));
}
```

- [ ] **Step 6: 跑并发测试验证通过**

Run: `mvn -q test -Dtest=ReservationConcurrencyIT`
Expected: PASS（恰好 1 成功，其余冲突，DB 断言通过）。

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat(reservation): 创建+唯一索引防超约(并发测试实证)"
```

---

## Task 10: 预约生命周期（取消/签到/归还/违规 + 我的预约）

**Files:**
- Modify: `service/ReservationService.java`（加 cancel/checkIn/checkOut/markViolated/myReservations/detail）
- Test: `service/ReservationLifecycleTest.java`（状态机分支，mock mapper）

- [ ] **Step 1: 写 `ReservationLifecycleTest`（状态转换校验）**

覆盖 spec §6.3 的转换前置条件：`cancel` 仅 PENDING/APPROVED 且未到 start；`checkIn` 需 APPROVED 且在时间窗；`checkOut` 需 IN_USE；非法转换抛 `STATUS_TRANSITION_INVALID`。用 Mockito mock ReservationMapper/DeviceMapper/ItemMapper，断言 status 写入与设备状态联动。

- [ ] **Step 2: 实现各方法（要点）**
- `cancel(id, userId)`：查预约，校验归属 + 状态 ∈ {PENDING,APPROVED} + now<start；置 CANCELLED；`itemMapper.delete(by reservation_id)`；通知。
- `checkIn(id)`：状态 APPROVED 且 now ∈ [start-grace, end]；置 IN_USE；`device.status=IN_USE`；check_in_at=now。
- `checkOut(id)`：状态 IN_USE；置 COMPLETED；`device.status=IDLE`；删除 item（清理）；check_out_at=now。
- `markViolated(id)` / `markNoShow(id)`（管理员）：置 VIOLATED/NO_SHOW；若设备 IN_USE→IDLE；删 item。
- `myReservations(userId, status, page)`：LambdaQueryWrapper `user_id` + 可选 status，分页。
- `detail(id)`：返回 VO，校验权限（本人或管理员）。

- [ ] **Step 3: 跑测试验证通过**

Run: `mvn -q test -Dtest=ReservationLifecycleTest`
Expected: PASS。

- [ ] **Step 4: 补 Controller 端点**：`POST /reservations/{id}/cancel`、`/check-in`、`/check-out`、`GET /reservations/mine`、`GET /reservations/{id}`、`POST /reservations/{id}/violate`（管理员 `@PreAuthorize`）。

- [ ] **Step 5: 手动冒烟**：admin 为设备1建预约→签到→归还，验证 device status 联动 IDLE→IN_USE→IDLE。

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(reservation): 取消/签到/归还/违规生命周期(TDD)"
```

---

## Task 11: 用户管理 CRUD（管理员）

**Files:**
- Create: `service/UserService.java` + `impl/UserServiceImpl.java`
- Create: `controller/UserController.java`
- Create: `dto/user/UserQueryDTO.java`, `dto/user/UserCreateDTO.java`

实现要点：
- `list(UserQueryDTO, page)`：按 username/realName 模糊、status 等值搜索，分页。阶段1 仅 `SYS_ADMIN` 开放用户管理（`LAB_ADMIN` 不开放）。
- `create(UserCreateDTO)`：username 查重（`USERNAME_EXISTS`）；BCrypt 加密密码；插 sys_user；按 `roleCodes` 绑定 sys_user_role。
- `update(id, dto)`：改 real_name/phone/email/dept_name/user_type；password 非空则重新 BCrypt；同步重绑角色。
- `delete(id)`：禁止删除当前登录用户自身；删除 sys_user + 解绑 sys_user_role。
- `updateStatus(id, status)`：封禁(0)/解封(1)。

- [ ] **Step 1: Controller（全部 `@PreAuthorize("hasAuthority('user:manage')")`）**

```java
@Tag(name="用户管理") @RestController @RequestMapping("/users") @RequiredArgsConstructor
public class UserController {
    private final UserService userService;
    @GetMapping public Result<?> list(UserQueryDTO q){ return Result.ok(userService.list(q)); }
    @PostMapping public Result<?> create(@Valid @RequestBody UserCreateDTO d){ userService.create(d); return Result.ok(); }
    @PutMapping("/{id}") public Result<?> update(@PathVariable Long id,@Valid @RequestBody UserCreateDTO d){ userService.update(id,d); return Result.ok(); }
    @DeleteMapping("/{id}") public Result<?> delete(@PathVariable Long id,@AuthenticationPrincipal SecurityUserDetails ud){
        userService.delete(id, ud.getUserId()); return Result.ok();
    }
    @PatchMapping("/{id}/status") public Result<?> status(@PathVariable Long id,@RequestParam Integer status){ userService.updateStatus(id,status); return Result.ok(); }
}
```

- [ ] **Step 2: 实现 DTO/Service/Impl**（`UserQueryDTO{username,realName,status,page,size}`；`UserCreateDTO{username,password,realName,phone,email,userType,roleCodes}`）

- [ ] **Step 3: 手动验证**：admin 创建一个 STUDENT、封禁/解封、改密后该用户能/不能登录。

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(user): 用户管理CRUD+封禁解封"
```

---

## Task 12: 审批模块

**Files:**
- Create: `service/ApprovalService.java` + `impl/ApprovalServiceImpl.java`
- Create: `controller/ApprovalController.java`

实现要点：
- `pendingList(page)`：仅 LAB_ADMIN 可调；查其自辖 lab_id 集合 → 查 `reservation.status=PENDING AND device.lab_id IN (集合)`，分页。
- `approve(id)`：校验 PENDING + 该预约设备 lab 在自辖范围；置 APPROVED + approver_id + approved_at；通知用户。
- `reject(id, reason)`：置 REJECTED + reject_reason；删除 item 释放槽；通知。
- `batchApprove(ids[])`：循环 approve（单事务）。

Controller：`GET /approvals/pending`、`POST /approvals/{id}/approve`、`POST /approvals/{id}/reject`、`POST /approvals/batch-approve`，均 `@PreAuthorize("hasAuthority('device:approve')")`。

- [ ] **Step 1: 实现 + Controller**
- [ ] **Step 2: 手动验证**：建一台 need_approval=1 设备的预约 → admin 待审批列表可见 → 通过/拒绝。
- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat(approval): 待审批列表+通过/拒绝/批量"
```

---

## Task 13: 报修模块（最小版，含设备状态联动）

**Files:**
- Create: `service/RepairReportService.java` + `impl/RepairReportServiceImpl.java`
- Create: `controller/RepairReportController.java`
- Create: `dto/repair/RepairCreateDTO.java`
- Test: `service/RepairReportServiceTest.java`（take→MAINTENANCE / resolve→IDLE 联动）

实现要点（spec §6.4）：
- `create(dto, userId)`：插 repair_report(PENDING)。
- `take(id)`（管理员）：PENDING→PROCESSING；`device.status=MAINTENANCE`（不校验设备当前状态）；handler_id=当前。
- `resolve(id, note)`：PROCESSING→RESOLVED；`device.status=IDLE`；resolution_note；resolved_at。
- `reject(id, note)`：PENDING→REJECTED；设备不变。
- `mine(userId)` / `list(status, page)`（管理员，按自辖 lab 过滤设备）。

Controller：`POST /repair-reports`、`GET /repair-reports/mine`、`GET /repair-reports`、`POST /repair-reports/{id}/take|resolve|reject`。

- [ ] **Step 1: 实现 + 测试设备状态联动**
- [ ] **Step 2: 跑测试 + 手动验证 take 后该设备无法新建预约（DEVICE_UNAVAILABLE）**
- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat(repair): 报修最小版+设备MAINTENANCE联动"
```

---

## Task 14: 通知模块 + 事件接入

**Files:**
- Create: `service/NotificationService.java` + `impl/NotificationServiceImpl.java`
- Create: `controller/NotificationController.java`

实现要点：
- `notify(userId, type, content, relatedId, relatedType)`：插 notification 记录（被 Reservation/Approval/Repair 调用——Task 9/10/12/13 已引用，此处补全实现）。
- `mine(userId, onlyUnread, page)`、`markRead(id)`、`markAllRead(userId)`。

Controller：`GET /notifications/mine`、`PATCH /notifications/{id}/read`、`PATCH /notifications/read-all`。

- [ ] **Step 1: 实现 + Controller**
- [ ] **Step 2: 手动验证**：建预约后 `/notifications/mine` 有记录。
- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat(notification): DB通知+事件接入"
```

---

## Task 15: Dashboard 汇总（仅数字）

**Files:**
- Create: `service/DashboardService.java` + `impl/DashboardServiceImpl.java`
- Create: `controller/DashboardController.java`
- Create: `vo/dashboard/DashboardSummaryVO.java`

实现要点：
- `summary()`：`device` 按 status 分组 count；`todayReservations` = 今日 start_time 的活跃预约数；`pendingApprovals`（按角色：LAB_ADMIN 统计自辖 lab 的 PENDING，SYS_ADMIN 全量）；`weeklyReservationTrend` 近 7 天每天 count（`GROUP BY DATE(start_time)`）。
- Controller：`GET /dashboard/summary`，`@PreAuthorize("hasAnyRole('LAB_ADMIN','SYS_ADMIN')")`。

- [ ] **Step 1: 实现 + Controller**
- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "feat(dashboard): 统计数字汇总"
```

---

## Task 16: 操作日志 AOP

**Files:**
- Create: `aspect/Log.java`, `aspect/OperationLogAspect.java`

```java
package com.lab.reservation.aspect;
import java.lang.annotation.*;
@Target(ElementType.METHOD) @Retention(RetentionPolicy.RUNTIME)
public @interface Log { String value() default ""; }
```

`OperationLogAspect`：`@Around("@annotation(log)")` 环绕标注方法，记录 username（从 SecurityContextHolder 取）、action(log.value)、method、params(入参 JSON)、ip(RequestContextHolder)、cost_ms；`@Async` 异步写 operation_log；异常也记录。

- [ ] **Step 1: 实现注解 + 切面**
- [ ] **Step 2: 在关键写操作 Controller 方法标注 `@Log("创建预约")` 等**
- [ ] **Step 3: 手动验证**：调一个标注的接口后 `operation_log` 表有记录。
- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(log): @Log注解+操作日志AOP"
```

---

## Task 17: Knife4j 配置 + 全量测试 + DoD 收尾

**Files:**
- Create: `config/Knife4jConfig.java`

- [ ] **Step 1: `Knife4jConfig`**

```java
package com.lab.reservation.config;
import io.swagger.v3.oas.models.OpenAPI; import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.security.SecurityRequirement; import io.swagger.v3.oas.models.security.SecurityScheme;
import io.swagger.v3.oas.models.Components;
import org.springframework.context.annotation.Bean; import org.springframework.context.annotation.Configuration;

@Configuration
public class Knife4jConfig {
    @Bean public OpenAPI openAPI(){
        return new OpenAPI().info(new Info().title("实验室设备预约 API").version("v1"))
            .addSecurityItem(new SecurityRequirement().addList("Bearer"))
            .components(new Components().addSecuritySchemes("Bearer",
                new SecurityScheme().type(SecurityScheme.Type.HTTP).scheme("bearer").bearerFormat("JWT")));
    }
}
```

- [ ] **Step 2: 全量测试**

Run: `mvn -q test`
Expected: BUILD SUCCESS，所有单测 + 并发集成测试 PASS。

- [ ] **Step 3: DoD 手动冒烟清单**（启动后用 Knife4j `/api/doc.html`）
1. 注册/登录拿 token（admin/admin123）。
2. `GET /devices` 见 3 台；`GET /devices/1/calendar` 空。
3. 建预约（设备1，09:00–10:00）→ 成功 → `/reservations/mine` 可见 → `/notifications/mine` 有记录。
4. 并发脚本（两个 token 同时段抢设备3）→ 一个成功一个 409。
5. 设备2(need_approval)建预约 → `/approvals/pending` 可见 → approve/reject。
6. 签到/归还 → device status IDLE→IN_USE→IDLE。
7. 报修设备1 → take(转 MAINTENANCE) → 该设备建预约被拒 → resolve(转 IDLE) → 可再约。
8. `GET /dashboard/summary` 返回统计。
9. 标注 @Log 的接口调用后 `operation_log` 有记录。

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(docs): Knife4j配置+DoD收尾"
```

---

## 验收口径（对照 spec §12 DoD）

- [x] 17 个任务覆盖范围、§3.1 依赖、经典 MVC 包结构、混合槽模型、防超约、RBAC、状态机、用户管理、报修、通知、操作日志。
- [x] 防超约有并发集成测试实证（Task 9）。
- [x] 纯逻辑（SlotCalculator、JWT、生命周期）严格 TDD。

完成本计划 = 阶段1 后端核心 MVP 可运行、可演示、可答辩，为阶段2（Redis 分布式锁/推荐/WebSocket/驾驶舱）奠定基础。
