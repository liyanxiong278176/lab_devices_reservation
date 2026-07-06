package com.lab.reservation.config;

import lombok.extern.slf4j.Slf4j;
import org.springframework.aop.interceptor.AsyncUncaughtExceptionHandler;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.AsyncConfigurer;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executor;
import java.util.concurrent.ThreadPoolExecutor;

/**
 * 异步执行配置。
 *
 * <p>替代 RabbitMQ 通知派发：{@code NotificationDispatcher.dispatch} 是 @Async，
 * 在此 executor 上跑。任务体只做"Redis 幂等 + 调 NotificationService 写库 + WS 推送"，
 * 不再经过 broker，避免 RabbitMQ 重投造成的重复通知（幂等依然保留作防御）。
 *
 * <h3>线程池参数取舍</h3>
 * <ul>
 *   <li>core=4 / max=16：单实例，4 核机器上保留 1 核给 Tomcat / @Scheduled</li>
 *   <li>queue=200：通知突发时缓冲；超 200 才走 CallerRuns（让 HTTP 线程阻塞背压）</li>
 *   <li>rejected=CallerRuns：队列满时让调用方线程跑，最朴素背压；日志告警但不丢任务</li>
 * </ul>
 *
 * <h3>异常处理</h3>
 * @Async 方法的返回值是 void 时，异常无法传到调用方。
 * {@link GlobalAsyncExceptionHandler} 兜底打 warn（含线程名 / 任务签名），失败任务不重试
 * —— 这是与 RabbitMQ 取舍点：原方案 broker 会重投 3 次，本方案只跑 1 次。
 * 接受度：单实例项目，DB 写失败时 Spring 事务回滚 + DB 落库失败是稀有事件；
 * 失败时用户不会收到通知，但会通过"我的通知"页面看到"无新通知"+ 主动查询预约状态。
 * 如需补强：加 DB outbox 表 + 兜底重试扫描。
 */
@Slf4j
@Configuration
@EnableAsync
@EnableScheduling
public class AsyncConfig implements AsyncConfigurer {

    @Bean(name = "asyncDispatchExecutor")
    public Executor asyncDispatchExecutor() {
        ThreadPoolTaskExecutor exec = new ThreadPoolTaskExecutor();
        exec.setCorePoolSize(4);
        exec.setMaxPoolSize(16);
        exec.setQueueCapacity(200);
        exec.setThreadNamePrefix("async-dispatch-");
        exec.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());
        // 不等待队列任务全部完成（关闭时丢弃未开始的任务），避免 SIGTERM 卡住
        exec.setWaitForTasksToCompleteOnShutdown(false);
        exec.setAwaitTerminationSeconds(5);
        exec.initialize();
        return exec;
    }

    @Override
    public AsyncUncaughtExceptionHandler getAsyncUncaughtExceptionHandler() {
        return new GlobalAsyncExceptionHandler();
    }

    /** @Async void 方法异常统一兜底。 */
    static class GlobalAsyncExceptionHandler implements AsyncUncaughtExceptionHandler {
        @Override
        public void handleUncaughtException(Throwable ex, java.lang.reflect.Method method, Object... params) {
            log.warn("async task failed: method={} params={} err={}",
                    method.getName(), params, ex.toString(), ex);
        }
    }
}
