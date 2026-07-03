package com.lab.reservation.config;

import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.annotation.EnableRabbit;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * RabbitMQ 拓扑声明。规格 §4.2。
 *
 * <p>两条核心链路：
 * <ol>
 *   <li><b>通知链</b>：业务事件 → {@link #NOTIFY_EXCHANGE} → {@link #NOTIFY_QUEUE}。
 *       消费失败经 retry（见 application*.yml 的 spring.rabbitmq.listener.simple.retry）
 *       耗尽后，因 default-requeue-rejected=false 且队列声明了 x-dead-letter-exchange，
 *       被路由到 {@link #NOTIFY_DLX} → {@link #NOTIFY_DLQ} 兜底，避免消息静默丢失。</li>
 *   <li><b>延迟取消链</b>：预约签到超时消息先入 {@link #TIMEOUT_QUEUE}（TTL 队列，
 *       x-dead-letter-exchange={@link #CANCEL_EXCHANGE}），消息过期后经死信路由落到
 *       {@link #CANCEL_QUEUE}，由取消消费者触发自动取消。本期只声明拓扑，消费逻辑留待后续阶段。</li>
 * </ol>
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

    /** JSON 消息转换器：Producer/Consumer 间以对象序列化传输。 */
    @Bean
    public MessageConverter jacksonMessageConverter() {
        return new Jackson2JsonMessageConverter();
    }

    @Bean
    public DirectExchange notifyExchange() {
        return ExchangeBuilder.directExchange(NOTIFY_EXCHANGE).durable(true).build();
    }

    /** 主消费队列：消费失败进入死信交换机 {@link #NOTIFY_DLX}。 */
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

    /** 死信交换机：接收 notify.queue 拒绝/失败的消息。 */
    @Bean
    public DirectExchange notifyDlx() {
        return ExchangeBuilder.directExchange(NOTIFY_DLX).durable(true).build();
    }

    /** 死信队列：兜底存储，便于排查/重放。 */
    @Bean
    public Queue notifyDlq() {
        return QueueBuilder.durable(NOTIFY_DLQ).build();
    }

    @Bean
    public Binding notifyDlqBinding() {
        return BindingBuilder.bind(notifyDlq()).to(notifyDlx()).with(NOTIFY_ROUTING_KEY);
    }

    /** 超时队列：消息 TTL 到期后死信路由到 {@link #CANCEL_EXCHANGE}，实现延迟取消。 */
    @Bean
    public Queue timeoutQueue() {
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
