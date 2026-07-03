# 阶段4 实现计划：RabbitMQ 接入 + Docker 一键部署 + 论文素材

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 RabbitMQ 承担真实业务（异步通知解耦 + 延迟队列超时取消）、整套系统 Docker 一键起、产出 drawio 图集与 JMeter 实测压测数据。

**Architecture:** 纵切 S1(MQ)→S2(Docker)→S3(论文/压测)，依赖线性：代码定型→容器化→压测最终系统。MQ 用原生 TTL+DLX 延迟队列（不装插件）；部署用 multi-stage 镜像 + nginx 反代 + prod compose。

**Tech Stack:** Spring Boot 3.2.5 / Java 17 / spring-boot-starter-amqp / Redisson(StringRedisTemplate) / Flyway V4 / Docker / Nginx / drawio / JMeter(docker)。

**关联 spec:** `docs/superpowers/specs/2026-07-03-phase4-mq-deploy-thesis-design.md`

**执行约束（来自项目记忆，子代理务必遵守）：**
- Maven 必须用 JDK17：`export JAVA_HOME="/d/jdk17/jdk-17.0.13+11"; export PATH="$JAVA_HOME/bin:$PATH"; mvn ...`（路径 `+` 会让内联 `MVN="..."` 失效，必须 export）。
- 后端由主控会话 `mvn spring-boot:run` 常驻，**子代理不要启停后端/杀 java 进程/跑 `docker compose down`**——会切断常驻后端 DB 连接导致退出。子代理只用 `mvn test` 验证。
- 集成测试连**本地 compose 中间件**（非 Testcontainers，本机不可用）。S1 MQ 的 IT 直连本地 rabbitmq(localhost:5672)。
- Flyway V1-V3 不可改；新 schema 走 V4。
- `server.servlet.context-path=/api`：SecurityConfig matcher 不带 `/api` 前缀。
- 中间件已起（`docker compose ps`：lab-mysql/lab-redis/lab-rabbitmq）。

---

## File Structure（创建/修改清单）

**S1 RabbitMQ**
- Create: `src/main/java/com/lab/reservation/config/RabbitMQConfig.java`（交换机/队列/绑定声明）
- Create: `src/main/java/com/lab/reservation/mq/NotificationMessage.java`（消息 DTO）
- Create: `src/main/java/com/lab/reservation/mq/NotificationProducer.java`（生产者，事务后投递）
- Create: `src/main/java/com/lab/reservation/mq/NotificationConsumer.java`（消费者，Redis 幂等）
- Create: `src/main/java/com/lab/reservation/mq/ReservationTimeoutProducer.java`（延迟消息生产者）
- Create: `src/main/java/com/lab/reservation/mq/ReservationTimeoutConsumer.java`（延迟取消消费者）
- Create: `src/main/resources/db/migration/V4__add_cancel_reason.sql`
- Modify: `src/main/java/com/lab/reservation/entity/Reservation.java`（加 cancelReason 字段）
- Modify: `src/main/java/com/lab/reservation/entity/enums/ReservationStatus.java`（确认枚举，不改）
- Modify: `src/main/java/com/lab/reservation/service/impl/{ApprovalServiceImpl,RepairReportServiceImpl,ReservationServiceImpl}.java`（9 处 notify→producer）
- Modify: `src/main/resources/application-dev.yml`（rabbitmq 连接 + lab.reservation 配置）
- Test: `src/test/java/com/lab/reservation/mq/{NotificationProducerTest,NotificationConsumerTest,ReservationTimeoutConsumerTest}.java` + `ReservationDelayQueueIT.java`

**S2 Docker**
- Create: `Dockerfile`（后端 multi-stage）、`.dockerignore`
- Create: `frontend/Dockerfile`（前端 multi-stage）、`frontend/nginx.conf`、`frontend/.dockerignore`
- Create: `frontend/.env.development`、`frontend/.env.production`
- Modify: `frontend/src/composables/useWebSocket.ts`（WS URL 同源化）
- Create: `src/main/resources/application-prod.yml`
- Create: `docker-compose.prod.yml`

**S3 论文 + 压测**
- Create: `docs/thesis/drawings/*.drawio` + 导出 `*.png`（6 张）
- Create: `docs/thesis/{architecture,data-model,highlights,flow}.md`
- Create: `benchmark/jmeter/*.jmx`、`benchmark/run.sh`、`benchmark/README.md`
- Create: `docs/thesis/screenshots/`（三角色截图）

---

# S1 — RabbitMQ 接入

### Task 1: 加 amqp 依赖 + RabbitMQ 配置与拓扑声明

**Files:**
- Modify: `pom.xml`
- Modify: `src/main/resources/application-dev.yml`
- Create: `src/main/java/com/lab/reservation/config/RabbitMQConfig.java`

- [ ] **Step 1: pom 加 amqp 依赖**

`pom.xml` 的 `<dependencies>` 内（紧挨 websocket starter 之后）加：
```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-amqp</artifactId>
</dependency>
```

- [ ] **Step 2: application-dev.yml 加 rabbitmq 连接 + 超时配置**

`src/main/resources/application-dev.yml` 的 `spring:` 节点下加：
```yaml
  rabbitmq:
    host: localhost
    port: 5672
    username: guest
    password: guest
    virtual-host: /
```
`lab:` 节点下加：
```yaml
  reservation:
    signin-grace-minutes: 30   # 预约开始后宽限 N 分钟未签到则超时取消；demo 可调小
  mq:
    retry-max-attempts: 3
    idempotent-ttl-hours: 24
```

- [ ] **Step 3: 创建 RabbitMQConfig 声明全部拓扑**

`src/main/java/com/lab/reservation/config/RabbitMQConfig.java`：
```java
package com.lab.reservation.config;

import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.annotation.EnableRabbit;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * RabbitMQ 拓扑声明（规格 §4.2/§4.3）。
 *
 * 两条链：
 * 1) 异步通知：notify.exchange(direct) → notify.queue → consumer；
 *    消费失败经 notify.dlx → notify.dlq 兜底。
 * 2) 延迟取消：reservation.timeout.queue(无消费者, 消息级 TTL) → 过期死信
 *    → reservation.cancel.exchange → reservation.cancel.queue → consumer。
 */
@EnableRabbit
@Configuration
public class RabbitMQConfig {

    public static final String NOTIFY_EXCHANGE = "notify.exchange";
    public static final String NOTIFY_QUEUE = "notify.queue";
    public static final String NOTIFY_ROUTING_KEY = "notify";
    public static final String NOTIFY_DLX = "notify.dlx";
    public static final String NOTIFY_DLQ = "notify.dlq";

    public static final String TIMEOUT_QUEUE = "reservation.timeout.queue";
    public static final String CANCEL_EXCHANGE = "reservation.cancel.exchange";
    public static final String CANCEL_QUEUE = "reservation.cancel.queue";
    public static final String CANCEL_ROUTING_KEY = "reservation.cancel";

    // ---- JSON 序列化（消息体用 JSON，便于排查）----
    @Bean
    public MessageConverter jacksonMessageConverter() {
        return new Jackson2JsonMessageConverter();
    }

    // ===== 异步通知链 =====
    @Bean
    public DirectExchange notifyExchange() {
        return ExchangeBuilder.directExchange(NOTIFY_EXCHANGE).durable(true).build();
    }

    @Bean
    public Queue notifyQueue() {
        return QueueBuilder.durable(NOTIFY_QUEUE)
                .withArgument("x-dead-letter-exchange", NOTIFY_DLX)
                .withArgument("x-dead-letter-routing-key", NOTIFY_ROUTING_KEY)
                .build();
    }

    @Bean
    public Binding notifyBinding() {
        return BindingBuilder.bind(notifyQueue()).to(notifyExchange()).with(NOTIFY_ROUTING_KEY);
    }

    @Bean
    public DirectExchange notifyDlx() {
        return ExchangeBuilder.directExchange(NOTIFY_DLX).durable(true).build();
    }

    @Bean
    public Queue notifyDlq() {
        return QueueBuilder.durable(NOTIFY_DLQ).build();
    }

    @Bean
    public Binding notifyDlqBinding() {
        return BindingBuilder.bind(notifyDlq()).to(notifyDlx()).with(NOTIFY_ROUTING_KEY);
    }

    // ===== 延迟取消链（TTL + DLX，原生不装插件）=====
    @Bean
    public Queue timeoutQueue() {
        // 无消费者；消息过期后死信路由到 cancel.exchange
        return QueueBuilder.durable(TIMEOUT_QUEUE)
                .withArgument("x-dead-letter-exchange", CANCEL_EXCHANGE)
                .withArgument("x-dead-letter-routing-key", CANCEL_ROUTING_KEY)
                .build();
    }

    @Bean
    public DirectExchange cancelExchange() {
        return ExchangeBuilder.directExchange(CANCEL_EXCHANGE).durable(true).build();
    }

    @Bean
    public Queue cancelQueue() {
        return QueueBuilder.durable(CANCEL_QUEUE).build();
    }

    @Bean
    public Binding cancelBinding() {
        return BindingBuilder.bind(cancelQueue()).to(cancelExchange()).with(CANCEL_ROUTING_KEY);
    }
}
```

- [ ] **Step 4: 启动验证拓扑声明成功**

主控会话后端 `mvn spring-boot:run` 已在跑；改了 config 会触发重启。验证：打开 `http://localhost:15672`（guest/guest）→ Queues 页应看到 `notify.queue / notify.dlq / reservation.timeout.queue / reservation.cancel.queue` 四个队列、Exchanges 页有 `notify.exchange / notify.dlx / reservation.cancel.exchange`。或命令：
```bash
docker exec lab-rabbitmq rabbitmqctl list_queues name
```
Expected: 列出上述 4 个队列。

- [ ] **Step 5: Commit**
```bash
git add pom.xml src/main/resources/application-dev.yml src/main/java/com/lab/reservation/config/RabbitMQConfig.java
git commit -m "feat(mq): amqp依赖+RabbitMQ拓扑声明(通知链+延迟取消链)"
```

---

### Task 2: NotificationMessage + NotificationProducer（事务后投递）TDD

**Files:**
- Create: `src/main/java/com/lab/reservation/mq/NotificationMessage.java`
- Create: `src/main/java/com/lab/reservation/mq/NotificationProducer.java`
- Test: `src/test/java/com/lab/reservation/mq/NotificationProducerTest.java`

- [ ] **Step 1: 写失败测试**

`src/test/java/com/lab/reservation/mq/NotificationProducerTest.java`：
```java
package com.lab.reservation.mq;

import org.junit.jupiter.api.Test;
import org.springframework.amqp.rabbit.core.RabbitTemplate;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

class NotificationProducerTest {

    @Test
    void notify_sends_message_with_msgId_to_notify_exchange() {
        RabbitTemplate rabbit = mock(RabbitTemplate.class);
        NotificationProducer producer = new NotificationProducer(rabbit);

        producer.notify(25L, "APPROVAL", "预约已通过", "内容", 12L, "RESERVATION");

        // 验证：消息发到 notify.exchange，routingKey notify，且消息体是 NotificationMessage
        verify(rabbit).convertAndSend(eq("notify.exchange"), eq("notify"), any(NotificationMessage.class));
    }

    @Test
    void notify_generates_unique_msgId_for_idempotency() {
        RabbitTemplate rabbit = mock(RabbitTemplate.class);
        NotificationProducer producer = new NotificationProducer(rabbit);

        producer.notify(1L, "T", "t", "c", 1L, "R");
        producer.notify(1L, "T", "t", "c", 1L, "R");

        // 两次调用，msgId 必须不同（幂等去重依赖）
        org.mockito.ArgumentCaptor<NotificationMessage> cap =
                org.mockito.ArgumentCaptor.forClass(NotificationMessage.class);
        verify(rabbit, times(2)).convertAndSend(anyString(), anyString(), cap.capture());
        var ids = cap.getAllValues().stream().map(NotificationMessage::getMsgId).toList();
        org.assertj.core.api.Assertions.assertThat(ids.get(0)).isNotEqualTo(ids.get(1));
    }
}
```

- [ ] **Step 2: 运行验证失败**

Run: `export JAVA_HOME="/d/jdk17/jdk-17.0.13+11"; export PATH="$JAVA_HOME/bin:$PATH"; mvn test -Dtest=NotificationProducerTest`
Expected: 编译失败（NotificationMessage/NotificationProducer 不存在）。

- [ ] **Step 3: 创建 NotificationMessage**

`src/main/java/com/lab/reservation/mq/NotificationMessage.java`：
```java
package com.lab.reservation.mq;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/** 异步通知消息体。msgId 用于消费者幂等去重（at-least-once 重复投递）。 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class NotificationMessage {
    private String msgId;
    private Long userId;
    private String type;
    private String title;
    private String content;
    private Long relatedId;
    private String relatedType;
}
```

- [ ] **Step 4: 创建 NotificationProducer（事务后投递）**

`src/main/java/com/lab/reservation/mq/NotificationProducer.java`：
```java
package com.lab.reservation.mq;

import com.lab.reservation.config.RabbitMQConfig;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.util.UUID;

/**
 * 通知消息生产者。业务方调用此处的 notify(...) 替代原同步 NotificationService.notify。
 *
 * 事务后投递：若当前存在活跃事务，注册 afterCommit 回调，确保「事务回滚则不发消息」，
 * 避免「业务回滚但通知已发」的不一致（答辩可靠投递要点）。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class NotificationProducer {

    private final RabbitTemplate rabbitTemplate;

    public void notify(Long userId, String type, String title, String content, Long relatedId, String relatedType) {
        NotificationMessage msg = new NotificationMessage(
                UUID.randomUUID().toString(), userId, type, title, content, relatedId, relatedType);

        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    doSend(msg);
                }
            });
        } else {
            doSend(msg); // 无事务上下文（如调度/测试）直接发
        }
    }

    private void doSend(NotificationMessage msg) {
        rabbitTemplate.convertAndSend(RabbitMQConfig.NOTIFY_EXCHANGE, RabbitMQConfig.NOTIFY_ROUTING_KEY, msg);
        log.debug("notify message sent: userId={} type={} msgId={}", msg.getUserId(), msg.getType(), msg.getMsgId());
    }
}
```

- [ ] **Step 5: 运行测试通过**

Run: `mvn test -Dtest=NotificationProducerTest`
Expected: PASS（2 tests）。

- [ ] **Step 6: Commit**
```bash
git add src/main/java/com/lab/reservation/mq/NotificationMessage.java src/main/java/com/lab/reservation/mq/NotificationProducer.java src/test/java/com/lab/reservation/mq/NotificationProducerTest.java
git commit -m "feat(mq): NotificationProducer事务后投递+msgId幂等(TDD)"
```

---

### Task 3: NotificationConsumer（Redis 幂等 + 复用 notify）TDD

**Files:**
- Create: `src/main/java/com/lab/reservation/mq/NotificationConsumer.java`
- Test: `src/test/java/com/lab/reservation/mq/NotificationConsumerTest.java`

- [ ] **Step 1: 写失败测试**

```java
package com.lab.reservation.mq;

import com.lab.reservation.service.NotificationService;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.time.Duration;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class NotificationConsumerTest {

    @Test
    void onMessage_first_time_calls_notifyService() {
        NotificationService svc = mock(NotificationService.class);
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        ValueOperations<String, String> ops = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(ops);
        when(ops.setIfAbsent(anyString(), anyString(), any(Duration.class))).thenReturn(true);

        NotificationConsumer consumer = new NotificationConsumer(svc, redis);
        NotificationMessage msg = new NotificationMessage("msg-1", 7L, "T", "t", "c", 1L, "R");

        consumer.onMessage(msg);

        verify(svc).notify(7L, "T", "t", "c", 1L, "R");
    }

    @Test
    void onMessage_duplicate_msgId_skips_notifyService() {
        NotificationService svc = mock(NotificationService.class);
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        ValueOperations<String, String> ops = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(ops);
        // Redis SET NX 返回 false = msgId 已存在 → 重复消息，跳过
        when(ops.setIfAbsent(anyString(), anyString(), any(Duration.class))).thenReturn(false);

        NotificationConsumer consumer = new NotificationConsumer(svc, redis);
        consumer.onMessage(new NotificationMessage("dup", 7L, "T", "t", "c", 1L, "R"));

        verify(svc, never()).notify(anyLong(), anyString(), anyString(), anyString(), anyLong(), anyString());
    }
}
```

- [ ] **Step 2: 运行验证失败**（NotificationConsumer 不存在）

- [ ] **Step 3: 创建 NotificationConsumer**

```java
package com.lab.reservation.mq;

import com.lab.reservation.service.NotificationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;

/**
 * 异步通知消费者。收到消息 → 幂等校验（Redis SET NX msgId）→ 复用 NotificationService.notify 写 DB+WS。
 * 幂等：RabbitMQ 是 at-least-once，重复投递时第二次 SET NX 返回 false → 跳过，避免重复通知。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class NotificationConsumer {

    private final NotificationService notificationService;
    private final StringRedisTemplate redisTemplate;

    @Value("${lab.mq.idempotent-ttl-hours:24}")
    private long idempotentTtlHours;

    @RabbitListener(queues = RabbitMQConfig.NOTIFY_QUEUE)
    public void onMessage(NotificationMessage msg) {
        String key = "mq:notify:" + msg.getMsgId();
        Boolean first = redisTemplate.opsForValue()
                .setIfAbsent(key, "1", Duration.ofHours(idempotentTtlHours));
        if (Boolean.FALSE.equals(first)) {
            log.info("duplicate notify message skipped, msgId={}", msg.getMsgId());
            return;
        }
        notificationService.notify(msg.getUserId(), msg.getType(), msg.getTitle(),
                msg.getContent(), msg.getRelatedId(), msg.getRelatedType());
    }
}
```

> **注：** `NOTIFY_QUEUE` 是 `RabbitMQConfig` 的 `public static final String` 常量，`@RabbitListener(queues = RabbitMQConfig.NOTIFY_QUEUE)` 直接引用即可（与 ReservationTimeoutConsumer 用 `CANCEL_QUEUE` 一致），无需额外 String bean。需 import `com.lab.reservation.config.RabbitMQConfig`。

- [ ] **Step 4: 运行测试通过**

Run: `mvn test -Dtest=NotificationConsumerTest`
Expected: PASS（2 tests）。

- [ ] **Step 5: Commit**
```bash
git add src/main/java/com/lab/reservation/mq/NotificationConsumer.java src/main/java/com/lab/reservation/config/RabbitMQConfig.java
git commit -m "feat(mq): NotificationConsumer Redis幂等+复用notify(TDD)"
```

---

### Task 4: 改造 9 处调用点（sync notify → producer）

**Files:**
- Modify: `src/main/java/com/lab/reservation/service/impl/ApprovalServiceImpl.java`
- Modify: `src/main/java/com/lab/reservation/service/impl/RepairReportServiceImpl.java`
- Modify: `src/main/java/com/lab/reservation/service/impl/ReservationServiceImpl.java`

9 处调用点（spec §4.2 已核对）：
- `ApprovalServiceImpl`:132,154（approve / reject）
- `RepairReportServiceImpl`:167,191,208（accept / resolve / reject）
- `ReservationServiceImpl`:128,156,184,206（create / cancel / checkin / return）

- [ ] **Step 1: 每个类注入 NotificationProducer，替换 notify 调用**

对三个 Impl 类：
1. 构造器加 `private final NotificationProducer notificationProducer;`（`@RequiredArgsConstructor` 自动注入，只需加字段）。
2. 删除/保留 `NotificationService notificationService` 字段——**保留**（其他地方可能直接用；若仅 notify 用则可删，但保守起见保留以免破坏编译）。实际：仅替换 9 处 `notificationService.notify(...)` → `notificationProducer.notify(...)`，字段保留不动。
3. import `com.lab.reservation.mq.NotificationProducer`。

示例（ApprovalServiceImpl 行 132-133）：
```java
// 改前
notificationService.notify(r.getUserId(), "APPROVAL", "预约已通过",
        "预约 " + r.getId() + " 已通过审批", r.getId(), "RESERVATION");
// 改后
notificationProducer.notify(r.getUserId(), "APPROVAL", "预约已通过",
        "预约 " + r.getId() + " 已通过审批", r.getId(), "RESERVATION");
```
其余 8 处同理（仅 `notificationService` → `notificationProducer`）。

- [ ] **Step 2: 编译通过 + 全量回归**

Run: `export JAVA_HOME="/d/jdk17/jdk-17.0.13+11"; export PATH="$JAVA_HOME/bin:$PATH"; mvn test`
Expected: 全绿（阶段1-3 零回归 + Task2/3 新增 4 测试）。注意：`NotificationServiceImplTest`/`NotificationBroadcastTest` 仍测 NotificationService（消费者内部用），不受影响。

- [ ] **Step 3: Commit**
```bash
git add src/main/java/com/lab/reservation/service/impl/ApprovalServiceImpl.java src/main/java/com/lab/reservation/service/impl/RepairReportServiceImpl.java src/main/java/com/lab/reservation/service/impl/ReservationServiceImpl.java
git commit -m "feat(mq): 9处同步notify改异步(NotificationProducer)"
```

---

### Task 5: V4 迁移 cancel_reason + Reservation 实体 + cancel() 设 USER

**Files:**
- Create: `src/main/resources/db/migration/V4__add_cancel_reason.sql`
- Modify: `src/main/java/com/lab/reservation/entity/Reservation.java`
- Modify: `src/main/java/com/lab/reservation/service/impl/ReservationServiceImpl.java`（cancel 方法）

- [ ] **Step 1: V4 迁移**

`src/main/resources/db/migration/V4__add_cancel_reason.sql`：
```sql
-- 区分取消来源：USER（用户主动）/ TIMEOUT（超时未签到自动取消）
ALTER TABLE reservation ADD COLUMN cancel_reason VARCHAR(32) NULL AFTER status;
```

- [ ] **Step 2: Reservation 实体加字段**

`Reservation.java` 加（status 字段后）：
```java
    private String cancelReason;
```

- [ ] **Step 3: cancel() 方法设 cancelReason="USER"**

`ReservationServiceImpl` 的 cancel 方法内，设置状态为 CANCELLED 处加：
```java
r.setStatus(ReservationStatus.CANCELLED.name());
r.setCancelReason("USER");   // 新增
```

- [ ] **Step 4: 重启验证 V4 迁移执行 + 全量回归**

主控后端重启时 Flyway 自动跑 V4。验证：
```bash
docker exec lab-mysql mysql -uroot -p123456 lab_reservation -e "DESCRIBE reservation;" | grep cancel_reason
```
Expected: 输出 `cancel_reason | varchar(32) | YES | | NULL |`。
Run: `mvn test`
Expected: 全绿。

- [ ] **Step 5: Commit**
```bash
git add src/main/resources/db/migration/V4__add_cancel_reason.sql src/main/java/com/lab/reservation/entity/Reservation.java src/main/java/com/lab/reservation/service/impl/ReservationServiceImpl.java
git commit -m "feat(reservation): V4 cancel_reason区分取消来源(USER/TIMEOUT)"
```

---

### Task 6: ReservationTimeoutProducer + approve 发延迟消息 TDD

**Files:**
- Create: `src/main/java/com/lab/reservation/mq/ReservationTimeoutProducer.java`
- Modify: `src/main/java/com/lab/reservation/service/impl/ApprovalServiceImpl.java`
- Test: `src/test/java/com/lab/reservation/mq/ReservationTimeoutProducerTest.java`

- [ ] **Step 1: 写失败测试**

```java
package com.lab.reservation.mq;

import org.junit.jupiter.api.Test;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessagePostProcessor;
import org.springframework.amqp.rabbit.core.RabbitTemplate;

import java.time.LocalDateTime;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class ReservationTimeoutProducerTest {

    @Test
    void sendTimeout_sends_to_timeout_queue_with_expiration() {
        RabbitTemplate rabbit = mock(RabbitTemplate.class);
        ReservationTimeoutProducer producer = new ReservationTimeoutProducer(rabbit);

        LocalDateTime start = LocalDateTime.now().plusMinutes(30);
        producer.sendTimeout(42L, start);

        // 验证发到 timeout 队列，且带了 expiration（MessagePostProcessor 设 expiration）
        // 3-arg convertAndSend(routingKey, message, postProcessor)：默认 exchange + 队列名 routingKey
        verify(rabbit).convertAndSend(eq("reservation.timeout.queue"), eq("timeout:42"), any(MessagePostProcessor.class));
    }
}
```

- [ ] **Step 2: 运行验证失败**

- [ ] **Step 3: 创建 ReservationTimeoutProducer**

```java
package com.lab.reservation.mq;

import com.lab.reservation.config.RabbitMQConfig;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.core.MessagePostProcessor;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.time.Duration;
import java.time.LocalDateTime;

/**
 * 延迟取消生产者：审批通过时调用，发延迟消息到 timeout 队列（消息级 TTL）。
 * TTL = 预约开始时间 - now + 宽限分钟。到期后死信路由到 cancel.queue。
 *
 * 队头阻塞取舍：消息级 TTL 存在队头阻塞（队首未过期则其后消息即便过期也不出队）。
 * 预约场景按审批时间近似有序、TTL 相近，影响可控。详见 spec §4.4。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ReservationTimeoutProducer {

    private final RabbitTemplate rabbitTemplate;

    @Value("${lab.reservation.signin-grace-minutes:30}")
    private long graceMinutes;

    public void sendTimeout(Long reservationId, LocalDateTime startTime) {
        long ttlMillis = Math.max(0,
                Duration.between(LocalDateTime.now(), startTime).toMillis() + graceMinutes * 60_000);
        String payload = "timeout:" + reservationId;
        MessagePostProcessor mpp = msg -> {
            msg.getMessageProperties().setExpiration(String.valueOf(ttlMillis));
            return msg;
        };

        // 事务后投递（与 NotificationProducer 同模式）：审批事务提交后才发延迟消息，
        // 避免「审批回滚但超时消息已发」。
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    doSend(payload, mpp, reservationId, ttlMillis);
                }
            });
        } else {
            doSend(payload, mpp, reservationId, ttlMillis);
        }
    }

    private void doSend(String payload, MessagePostProcessor mpp, Long id, long ttlMillis) {
        // 3-arg convertAndSend(routingKey, message, postProcessor)：默认 exchange("") + 队列名作 routingKey
        // → 路由到同名 timeout.queue。切勿用 4-arg（会把队列名误当 exchange，消息不可路由）。
        rabbitTemplate.convertAndSend(RabbitMQConfig.TIMEOUT_QUEUE, payload, mpp);
        log.info("reservation timeout message sent: id={} ttlMs={}", id, ttlMillis);
    }
}
```

- [ ] **Step 4: approve 方法注入 producer 并发延迟消息**

`ApprovalServiceImpl`：
1. 加字段 `private final ReservationTimeoutProducer timeoutProducer;`。
2. `approve()` 末尾（notify 之后）加：
```java
timeoutProducer.sendTimeout(r.getId(), r.getStartTime());
```
（`sendTimeout` 内部已实现事务后投递（afterCommit，与 NotificationProducer 一致）；`approve` 末尾直接调用即可。Step 3 给的就是最终 afterCommit 版，直接用。）

- [ ] **Step 5: 运行测试通过**

Run: `mvn test -Dtest=ReservationTimeoutProducerTest`
Expected: PASS。

- [ ] **Step 6: Commit**
```bash
git add src/main/java/com/lab/reservation/mq/ReservationTimeoutProducer.java src/main/java/com/lab/reservation/service/impl/ApprovalServiceImpl.java src/test/java/com/lab/reservation/mq/ReservationTimeoutProducerTest.java
git commit -m "feat(mq): 延迟队列Producer+审批通过发超时消息(TDD)"
```

---

### Task 7: ReservationTimeoutConsumer（判仍 APPROVED → 取消 TIMEOUT + 通知）TDD

**Files:**
- Create: `src/main/java/com/lab/reservation/mq/ReservationTimeoutConsumer.java`
- Test: `src/test/java/com/lab/reservation/mq/ReservationTimeoutConsumerTest.java`

- [ ] **Step 1: 写失败测试**

```java
package com.lab.reservation.mq;

import com.lab.reservation.entity.Reservation;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.service.ReservationService;
import org.junit.jupiter.api.Test;

import static org.mockito.Mockito.*;

class ReservationTimeoutConsumerTest {

    @Test
    void onTimeout_approved_reservation_is_cancelled_and_notified() {
        ReservationMapper mapper = mock(ReservationMapper.class);
        ReservationService svc = mock(ReservationService.class);
        NotificationProducer notify = mock(NotificationProducer.class);

        Reservation r = new Reservation();
        r.setId(42L); r.setUserId(7L);
        r.setStatus(ReservationStatus.APPROVED.name());
        when(mapper.selectById(42L)).thenReturn(r);

        ReservationTimeoutConsumer consumer = new ReservationTimeoutConsumer(mapper, svc, notify);
        consumer.onTimeout("42");

        verify(svc).markTimeoutCancelled(42L);
        verify(notify).notify(eq(7L), eq("RESERVATION"), contains("超时"), anyString(), eq(42L), eq("RESERVATION"));
    }

    @Test
    void onTimeout_already_inuse_reservation_is_skipped() {
        ReservationMapper mapper = mock(ReservationMapper.class);
        ReservationService svc = mock(ReservationService.class);
        NotificationProducer notify = mock(NotificationProducer.class);

        Reservation r = new Reservation();
        r.setStatus(ReservationStatus.IN_USE.name());  // 已签到
        when(mapper.selectById(1L)).thenReturn(r);

        new ReservationTimeoutConsumer(mapper, svc, notify).onTimeout("1");

        verify(svc, never()).markTimeoutCancelled(anyLong());
        verify(notify, never()).notify(anyLong(), anyString(), anyString(), anyString(), anyLong(), anyString());
    }
}
```

- [ ] **Step 2: 运行验证失败**（ReservationService 无 markTimeoutCancelled）

- [ ] **Step 3: ReservationService 接口 + impl 加 markTimeoutCancelled**

`ReservationService` 接口加：
```java
void markTimeoutCancelled(Long id);
```
`ReservationServiceImpl` 实现（与 cancel 类似但设 TIMEOUT 原因、释放槽）：
```java
@Override
@Transactional
public void markTimeoutCancelled(Long id) {
    Reservation r = reservationMapper.selectById(id);
    if (r == null) throw new BusinessException(ResultCode.NOT_FOUND);
    r.setStatus(ReservationStatus.CANCELLED.name());
    r.setCancelReason("TIMEOUT");
    reservationMapper.updateById(r);
    // 释放槽：复用现有 itemMapper 字段（ReservationServiceImpl:60，cancel() 同款用法）
    itemMapper.delete(new LambdaQueryWrapper<ReservationItem>()
            .eq(ReservationItem::getReservationId, id));
}
```
（字段名是 `itemMapper`——ReservationServiceImpl:60 声明 `private final ReservationItemMapper itemMapper`，cancel() 用的同一字段。⚠️ 不是 `reservationItemMapper`，照抄会编译失败。）

- [ ] **Step 4: 创建 ReservationTimeoutConsumer**

```java
package com.lab.reservation.mq;

import com.lab.reservation.config.RabbitMQConfig;
import com.lab.reservation.entity.Reservation;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.service.ReservationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

/**
 * 延迟取消消费者：死信到期后从 cancel.queue 收到 reservationId。
 * 判断：状态仍 APPROVED（未签到则不会是 IN_USE）→ 标记 TIMEOUT 取消 + 通知用户。
 * 已签到(IN_USE)/已取消/已完成 → 幂等跳过。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ReservationTimeoutConsumer {

    private final ReservationMapper reservationMapper;
    private final ReservationService reservationService;
    private final NotificationProducer notificationProducer;

    @RabbitListener(queues = RabbitMQConfig.CANCEL_QUEUE)
    public void onTimeout(String reservationId) {
        Long id = Long.valueOf(reservationId.trim());
        Reservation r = reservationMapper.selectById(id);
        if (r == null) {
            log.warn("timeout: reservation {} not found", id);
            return;
        }
        if (!ReservationStatus.APPROVED.name().equals(r.getStatus())) {
            log.info("timeout: reservation {} status={}, skip", id, r.getStatus());
            return;
        }
        reservationService.markTimeoutCancelled(id);
        notificationProducer.notify(r.getUserId(), "RESERVATION", "预约超时已自动取消",
                "预约 " + id + " 超时未签到，已自动取消", id, "RESERVATION");
        log.info("reservation {} auto-cancelled by timeout", id);
    }
}
```

- [ ] **Step 5: 运行测试通过**

Run: `mvn test -Dtest=ReservationTimeoutConsumerTest`
Expected: PASS（2 tests）。

- [ ] **Step 6: Commit**
```bash
git add src/main/java/com/lab/reservation/mq/ReservationTimeoutConsumer.java src/main/java/com/lab/reservation/service/ReservationService.java src/main/java/com/lab/reservation/service/impl/ReservationServiceImpl.java src/test/java/com/lab/reservation/mq/ReservationTimeoutConsumerTest.java
git commit -m "feat(mq): 超时取消Consumer(判APPROVED→TIMEOUT取消+通知)TDD"
```

---

### Task 8: 延迟队列集成测试（本地 rabbitmq，短 TTL 验证死信）

**Files:**
- Test: `src/test/java/com/lab/reservation/mq/ReservationDelayQueueIT.java`

- [ ] **Step 1: 写集成测试**

```java
package com.lab.reservation.mq;

import com.lab.reservation.config.RabbitMQConfig;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessagePostProcessor;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 延迟队列集成测试：连本地 compose rabbitmq（localhost:5672）。
 * 发一条短 TTL(2s) 消息到 timeout.queue → 2s 后死信到 cancel.queue → 断言收到。
 * 证明 TTL+DLX 链路通（规格 §4.6）。
 */
@SpringBootTest
class ReservationDelayQueueIT {

    @Autowired
    private RabbitTemplate rabbitTemplate;

    // 抑制真 consumer：否则消息死信到 cancel.queue 时会被 ReservationTimeoutConsumer
    // 抢先消费（payload "it-test-..." 非数字 → NumberFormatException），测试 receive 拿不到。
    @org.springframework.boot.test.mock.mockito.MockBean
    ReservationTimeoutConsumer timeoutConsumer;

    @Test
    void short_ttl_message_deadletters_to_cancel_queue() throws Exception {
        String payload = "it-test-" + System.nanoTime();
        MessagePostProcessor mpp = m -> { m.getMessageProperties().setExpiration("2000"); return m; };
        rabbitTemplate.convertAndSend(RabbitMQConfig.TIMEOUT_QUEUE, payload, mpp);

        // 轮询 cancel.queue，最多等 8s（TTL 2s + 死信路由余量）
        Message received = null;
        for (int i = 0; i < 40; i++) {
            received = rabbitTemplate.receive(RabbitMQConfig.CANCEL_QUEUE, 500);
            if (received != null) break;
            Thread.sleep(200);
        }
        assertThat(received).as("2s TTL 消息应死信到 cancel.queue").isNotNull();
    }
}
```

- [ ] **Step 2: 运行（需本地 rabbitmq 已起）**

Run: `export JAVA_HOME="/d/jdk17/jdk-17.0.13+11"; export PATH="$JAVA_HOME/bin:$PATH"; mvn test -Dtest=ReservationDelayQueueIT`
Expected: PASS（消息 2s 后死信到 cancel.queue）。

- [ ] **Step 3: Commit**
```bash
git add src/test/java/com/lab/reservation/mq/ReservationDelayQueueIT.java
git commit -m "test(mq): 延迟队列IT(本地rabbitmq,短TTL验证死信)"
```

---

### Task 9: S1 端到端冒烟 + code review

- [ ] **Step 1: 全量回归**

Run: `mvn test`
Expected: 阶段1-3 零回归 + S1 新增测试全绿。

- [ ] **Step 2: 端到端冒烟（主控后端 + 前端）**

手工/脚本：学生建预约 → 管理员审批通过 → 观察 rabbitmq `reservation.timeout.queue` 出现消息 → 把 `lab.reservation.signin-grace-minutes` 调小或等 TTL → 预约状态变 CANCELLED(TIMEOUT) + 用户收到「超时已自动取消」通知（DB + WS toast）。

- [ ] **Step 3: dispatch code-reviewer 子代理审查 S1**

`superpowers:code-reviewer` 审 `src/main/java/com/lab/reservation/mq/` 全部 + 9 处调用点改动 + V4 迁移。修完问题再进 S2。

- [ ] **Step 4: Commit（如有 review 修复）**

---

# S2 — Docker 全容器化一键部署

### Task 10: 后端 Dockerfile + .dockerignore

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: 后端 multi-stage Dockerfile**

`Dockerfile`：
```dockerfile
# stage1: build
FROM maven:3.9-eclipse-temurin-17 AS builder
WORKDIR /build
# 先 copy pom 跑依赖解析（利用 Docker 层缓存）
COPY pom.xml .
RUN mvn -B dependency:go-offline
COPY src ./src
RUN mvn -B package -DskipTests

# stage2: runtime
FROM eclipse-temurin:17-jre-jammy
WORKDIR /app
COPY --from=builder /build/target/*.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java","-jar","/app/app.jar","--spring.profiles.active=prod"]
```

- [ ] **Step 2: .dockerignore**

```
target/
.git/
.idea/
*.iml
frontend/
docs/
img/
```

- [ ] **Step 3: 本地构建验证**

Run: `docker build -t lab-reservation-backend:test .`
Expected: 构建成功（multi-stage，最终镜像基于 jre）。

- [ ] **Step 4: Commit**
```bash
git add Dockerfile .dockerignore
git commit -m "feat(docker): 后端multi-stage Dockerfile(jar→jre17,prod profile)"
```

---

### Task 11: 前端 Dockerfile + nginx.conf + .dockerignore

**Files:**
- Create: `frontend/Dockerfile`
- Create: `frontend/nginx.conf`
- Create: `frontend/.dockerignore`

- [ ] **Step 1: 前端 multi-stage Dockerfile**

`frontend/Dockerfile`：
```dockerfile
# stage1: build
FROM node:20-alpine AS builder
WORKDIR /build
RUN corepack enable && corepack prepare pnpm@9 --activate
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

# stage2: nginx serve
FROM nginx:alpine
COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

- [ ] **Step 2: nginx.conf（serve 静态 + 反代 /api、/ws）**

`frontend/nginx.conf`：
```nginx
server {
    listen 80;
    server_name _;

    # SPA history 路由回退
    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # WebSocket（SockJS/STOMP）反代 —— 必须在 /api/ 之前，前缀更长优先匹配
    # 后端 context-path=/api，SockJS endpoint 实际在 /api/ws；这里直接走 /api/ws 路径（与 dev 一致）
    location /api/ws {
        proxy_pass http://app:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }

    # 后端 REST API 反代
    location /api/ {
        proxy_pass http://app:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

- [ ] **Step 3: .dockerignore**

`frontend/.dockerignore`：
```
node_modules/
dist/
.vite/
```

- [ ] **Step 4: Commit**
```bash
git add frontend/Dockerfile frontend/nginx.conf frontend/.dockerignore
git commit -m "feat(docker): 前端Dockerfile+nginx反代(/api,/ws)"
```

---

### Task 12: 前端 baseURL/env 修复（WS 同源 + .env.*）

**Files:**
- Modify: `frontend/src/composables/useWebSocket.ts`
- Create: `frontend/.env.development`
- Create: `frontend/.env.production`

- [ ] **Step 1: .env 文件**

`frontend/.env.development`：
```
VITE_WS_BASE=http://localhost:8080
```
`frontend/.env.production`：
```
VITE_WS_BASE=
```
（prod 空串 → useWebSocket 用 window.location 同源 `/api/ws`，经 nginx /api/ws 反代到 app:8080）

- [ ] **Step 2: useWebSocket.ts WS URL 同源化**

改 `webSocketFactory`（行 22-23）：
```ts
  client = new Client({
    webSocketFactory: () => {
      const base = import.meta.env.VITE_WS_BASE ?? ''
      const wsBase = base
        ? `${base}/api/ws`
        : `${window.location.protocol === 'https:' ? 'https' : 'http'}://${window.location.host}/api/ws`
      return new SockJS(`${wsBase}?token=${encodeURIComponent(u.accessToken)}`)
    },
    // ... 其余不变
```
> dev：`VITE_WS_BASE=http://localhost:8080` → `http://localhost:8080/api/ws`（直连后端，不经 vite 代理，与现状一致）。
> prod：空串 → 同源 `/api/ws`（经 nginx /api/ws 反代到 app:8080）。

- [ ] **Step 3: 前端构建验证**

Run: `cd frontend && pnpm build`
Expected: build 干净（vue-tsc + vite build）。

- [ ] **Step 4: Commit**
```bash
git add frontend/src/composables/useWebSocket.ts frontend/.env.development frontend/.env.production
git commit -m "fix(fe): WS URL同源化(VITE_WS_BASE)+.env.*,修部署硬编码"
```

---

### Task 13: application-prod.yml + docker-compose.prod.yml + 一键验证

**Files:**
- Create: `src/main/resources/application-prod.yml`
- Create: `docker-compose.prod.yml`

- [ ] **Step 1: application-prod.yml**

```yaml
spring:
  datasource:
    url: jdbc:mysql://mysql:3306/lab_reservation?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai&useSSL=false&allowPublicKeyRetrieval=true
    username: root
    password: ${DB_PASSWORD}
    driver-class-name: com.mysql.cj.jdbc.Driver
  flyway:
    enabled: true
    baseline-on-migrate: true
    baseline-version: 0
    locations: classpath:db/migration
  data:
    redis:
      host: redis
      port: 6379
      database: 0
      password:
  rabbitmq:
    host: rabbitmq
    port: 5672
    username: ${RABBITMQ_USERNAME}
    password: ${RABBITMQ_PASSWORD}
    virtual-host: /
logging:
  level:
    com.lab.reservation: info
jwt:
  secret: ${JWT_SECRET}
lab:
  reservation:
    signin-grace-minutes: 30
```

- [ ] **Step 2: docker-compose.prod.yml**

```yaml
services:
  mysql:
    image: mysql:8.0
    container_name: lab-mysql-prod
    environment:
      MYSQL_ROOT_PASSWORD: ${DB_PASSWORD}
      MYSQL_DATABASE: lab_reservation
      TZ: Asia/Shanghai
    command: --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
    volumes: ["mysql_data:/var/lib/mysql"]
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-uroot", "-p${DB_PASSWORD}"]
      interval: 5s
      timeout: 5s
      retries: 20
  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
    volumes: ["redis_data:/data"]
  rabbitmq:
    image: rabbitmq:3.13-management
    environment:
      RABBITMQ_DEFAULT_USER: ${RABBITMQ_USERNAME}
      RABBITMQ_DEFAULT_PASS: ${RABBITMQ_PASSWORD}
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
      interval: 10s
      timeout: 10s
      retries: 10
    volumes: ["rabbitmq_data:/var/lib/rabbitmq"]
  app:
    build: .
    depends_on:
      mysql: { condition: service_healthy }
      redis: { condition: service_healthy }
      rabbitmq: { condition: service_healthy }
    environment:
      DB_PASSWORD: ${DB_PASSWORD}
      RABBITMQ_USERNAME: ${RABBITMQ_USERNAME}
      RABBITMQ_PASSWORD: ${RABBITMQ_PASSWORD}
      JWT_SECRET: ${JWT_SECRET}
  frontend:
    build: ./frontend
    ports: ["80:80"]
    depends_on: [app]
volumes:
  mysql_data:
  redis_data:
  rabbitmq_data:
```

- [ ] **Step 3: 一键启动验证**

准备 `.env`（项目根，compose 自动读）或 export：
```bash
export DB_PASSWORD=123456 RABBITMQ_USERNAME=guest RABBITMQ_PASSWORD=guest
export JWT_SECRET="change-me-please-this-is-a-dev-secret-key-at-least-32-bytes-long!!"
docker compose -f docker-compose.prod.yml up -d --build
```
Expected: 5 服务 Up，`docker compose -f docker-compose.prod.yml ps` 全 healthy/Up。
浏览器 `http://localhost` → 登录 admin/admin123 → 驾驶舱渲染 → 触发 WS 推送（经 nginx /ws 反代）。
（⚠️ 与 dev 的 lab-mysql/lab-redis/lab-rabbitmq 容器名不同，prod 独立容器，不冲突。若 3306 端口冲突，prod mysql 不映射宿主端口——上面未写 ports，仅 app/frontend 映射，故无冲突。）

- [ ] **Step 4: Commit**
```bash
git add src/main/resources/application-prod.yml docker-compose.prod.yml
git commit -m "feat(docker): application-prod+docker-compose.prod一键起全套(含rabbitmq healthcheck)"
```

---

# S3 — 论文素材 + JMeter 压测

### Task 14: drawio 图集（6 张源文件 + 导出 PNG）

**Files:**
- Create: `docs/thesis/drawings/01-architecture.drawio` + `.png`
- Create: `docs/thesis/drawings/02-deploy-topology.drawio` + `.png`
- Create: `docs/thesis/drawings/03-er-diagram.drawio` + `.png`
- Create: `docs/thesis/drawings/04a-lock-sequence.drawio` + `.png`
- Create: `docs/thesis/drawings/04b-stomp-push-sequence.drawio` + `.png`
- Create: `docs/thesis/drawings/04c-recommend-flow.drawio` + `.png`
- Create: `docs/thesis/drawings/04d-dashboard-dataflow.drawio` + `.png`
- Create: `docs/thesis/drawings/05-mq-flow.drawio` + `.png`
- Create: `docs/thesis/drawings/06-reservation-lifecycle.drawio` + `.png`

**每张图规格（子代理据此生成原生 mxGraph XML，布局手算坐标）：**

1. **01-architecture**：四层（前端 Vue3+ElementPlus / nginx 网关 / 业务服务 SpringBoot[设备·预约·审批·报修·推荐·通知·驾驶舱] / 中间件 MySQL·Redis·RabbitMQ），标注技术栈与箭头方向。
2. **02-deploy-topology**：docker-compose.prod 服务依赖（frontend:80 → app:8080 → mysql/redis/rabbitmq），数据卷、healthcheck 标注。
3. **03-er-diagram**：核心表（sys_user/device/category/lab/reservation/reservation_item/notification/repair_report/operation_log）主键外键关系。
4. **04a-lock-sequence**：时序——学生A/B 并发建预约→ReservationLock.tryLock→A 成功/B 失败→A 写 DB（Redisson 锁 + 唯一索引双层）。
5. **04b-stomp-push**：时序——前端 SockJS(握手token)→WsAuthHandshakeInterceptor→JwtHandshakeHandler 设 Principal→SimpUserRegistry→convertAndSendToUser→前端 toast。
6. **04c-recommend-flow**：流程——用户行为→特征(类目/实验室/热度/标签/已用)→α/β/γ/δ/ε 加权打分→TopN→生成理由→冷启动降级(热度)。
7. **04d-dashboard-dataflow**：数据流——Mapper 聚合(利用率/热力/类目/报修)→Redis 缓存→REST→vue-echarts 三视角渲染。
8. **05-mq-flow**：两条链——异步通知(producer→notify.exchange→notify.queue→consumer→DB+WS) + 延迟取消(timeout.queue[TTL]→死信→cancel.exchange→cancel.queue→consumer→cancel)。
9. **06-reservation-lifecycle**：状态机/时序——PENDING→APPROVED→（超时分支→CANCELLED TIMEOUT）/ IN_USE→COMPLETED，含 MQ/锁/推送交互。

- [ ] **Step 1: 子代理逐图生成 .drawio（原生 mxGraph XML）**

每张图独立子代理，输入上述规格，产出 `.drawio`。

- [ ] **Step 2: drawio CLI 导出 PNG**

```bash
DRAWIO="/c/Users/A2781/AppData/Local/Programs/draw.io/draw.io.exe"
for f in docs/thesis/drawings/*.drawio; do
  "$DRAWIO" --export --format png --output "${f%.drawio}.png" "$f"
done
```
Expected: 每张 .drawio 产出同名 .png。若 CLI 无头受限（Electron 报错）→ 兜底手动用 draw.io 打开逐张导出。

- [ ] **Step 3: Commit**
```bash
git add docs/thesis/drawings/
git commit -m "docs(thesis): drawio图集(架构/部署/ER/四亮点/MQ/生命周期)+PNG"
```

---

### Task 15: JMeter 压测（docker jmeter）+ 实测 + README

**Files:**
- Create: `benchmark/jmeter/lock-concurrency.jmx`
- Create: `benchmark/jmeter/recommend-qps.jmx`
- Create: `benchmark/jmeter/dashboard-qps.jmx`
- Create: `benchmark/run.sh`
- Create: `benchmark/README.md`

**压测方案（用 justb4/jmeter docker 镜像，免本机安装）：**

- [ ] **Step 1: 锁并发脚本 lock-concurrency.jmx**

线程组：50 线程同时打 `POST /api/reservations`（同设备同时段），断言：恰好 1 个 200、其余 `code=409`(RESERVATION_CONFLICT)。变量：`${__P(host)}`=host.docker.internal、`${__P(port)}`=8080、登录 token 由 setUp 线程组先登录获取写入 props。

- [ ] **Step 2: 接口 QPS 脚本 recommend-qps.jmx / dashboard-qps.jmx**

线程组梯度（10/50/100 线程），打 `/api/recommendations`、`/api/dashboard/overview`（需 token），Listener 收 Aggregate（吞吐 P50/P95/P99）。对比 Redis 缓存命中 vs miss。

- [ ] **Step 3: run.sh 封装 docker 调用**

```bash
#!/usr/bin/env bash
# 用法: ./benchmark/run.sh <scenario>   scenario: lock|recommend|dashboard
set -e
SCN=$1
HOST=${HOST:-host.docker.internal}
PORT=${PORT:-8080}
mkdir -p benchmark/out
docker run --rm \
  -v "$PWD/benchmark:/benchmark" \
  -e HOST=$HOST -e PORT=$PORT \
  justb4/jmeter:latest \
  -n -t /benchmark/jmeter/${SCN}-concurrency.jmx -l /benchmark/out/${SCN}.jtl \
  -Jhost=$HOST -Jport=$PORT
```
（注：scenario→文件名映射，recommend 用 recommend-qps.jmx，脚本按需调整。）

- [ ] **Step 4: 实测执行（dev 后端 8080 跑着）**

Run:
```bash
cd /d/agent_learning/lab_devices_reservation
export JAVA_HOME="/d/jdk17/jdk-17.0.13+11"; export PATH="$JAVA_HOME/bin:$PATH"
mvn spring-boot:run &  # 主控已有常驻后端则跳过
./benchmark/run.sh lock
./benchmark/run.sh recommend
./benchmark/run.sh dashboard
```
（⚠️ 若主控会话已有常驻后端，不要重复起——直接跑 run.sh，target=host.docker.internal:8080。）
Expected: 产出 `.jtl` 结果文件。

- [ ] **Step 5: README 汇总实测数据 + 结论**

`benchmark/README.md`：压测环境、场景、实测表格（锁并发结果、各接口 QPS/延迟）、结论（Redisson 锁防超约实证、Redis 缓存对驾驶舱/推荐接口的吞吐提升）、复现命令。

- [ ] **Step 6: Commit**
```bash
git add benchmark/
git commit -m "docs(benchmark): JMeter压测脚本(锁并发/接口QPS)+实测数据+复现"
```

---

### Task 16: 论文说明文档 + 三角色截图

**Files:**
- Create: `docs/thesis/architecture.md`（配图1/2）
- Create: `docs/thesis/data-model.md`（配图3）
- Create: `docs/thesis/highlights.md`（配图4a-d/5，四亮点 + MQ 原理）
- Create: `docs/thesis/flow.md`（配图6，预约生命周期）
- Create: `docs/thesis/screenshots/*.png`（三角色界面）

- [ ] **Step 1: 写 4 篇 Markdown 说明**（每篇引用对应 drawio PNG，给出原理/技术选型/答辩要点文字）。

- [ ] **Step 2: 三角色截图**（手动）：admin(驾驶舱/用户管理)、lab_admin(审批/报修处理)、student(浏览/建预约/推荐/我的预约)。存 `docs/thesis/screenshots/`。

- [ ] **Step 3: Commit**
```bash
git add docs/thesis/
git commit -m "docs(thesis): 架构/数据模型/亮点/流程说明文档+三角色截图"
```

---

## 验收标准（DoD，对照 spec §9）
- [ ] **MQ**：9 处通知改异步、延迟队列超时取消可演示（短 TTL）、幂等+事务后投递有测试、延迟队列 IT 绿。
- [ ] **Docker**：`docker compose -f docker-compose.prod.yml up -d --build` 起全套，浏览器 `http://localhost` 走通 登录→驾驶舱→WS 推送。
- [ ] **论文/压测**：9 张 drawio 图（.drawio + .png）、JMeter 实测数据 + .jmx 归档、`benchmark/README.md`、三角色截图。
- [ ] **全回归**：后端测试全绿（阶段1-3 零回归 + S1 新增）、前端 `pnpm build` + vitest 绿。

## 风险提示（执行时关注）
- drawio CLI 无头导出可能受限 → 兜底手动导出。
- Task 15 压测若主控已有常驻后端，勿重复起，避免端口冲突。
- Task 6 的 ReservationTimeoutProducer 须补事务后投递（与 NotificationProducer 同模式），plan 内已标注。
- WS 压测需多 STOMP 连接脚本，可用简单 node/python 脚本（JMeter 对 WS 支持弱），README 注明。
