package com.lab.reservation.config;

import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.annotation.EnableRabbit;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

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

    @Bean
    public MessageConverter jacksonMessageConverter() { return new Jackson2JsonMessageConverter(); }

    @Bean public DirectExchange notifyExchange() { return ExchangeBuilder.directExchange(NOTIFY_EXCHANGE).durable(true).build(); }
    @Bean public Queue notifyQueue() {
        return QueueBuilder.durable(NOTIFY_QUEUE)
                .withArgument("x-dead-letter-exchange", NOTIFY_DLX)
                .withArgument("x-dead-letter-routing-key", NOTIFY_ROUTING_KEY).build();
    }
    @Bean public Binding notifyBinding() { return BindingBuilder.bind(notifyQueue()).to(notifyExchange()).with(NOTIFY_ROUTING_KEY); }
    @Bean public DirectExchange notifyDlx() { return ExchangeBuilder.directExchange(NOTIFY_DLX).durable(true).build(); }
    @Bean public Queue notifyDlq() { return QueueBuilder.durable(NOTIFY_DLQ).build(); }
    @Bean public Binding notifyDlqBinding() { return BindingBuilder.bind(notifyDlq()).to(notifyDlx()).with(NOTIFY_ROUTING_KEY); }

    @Bean public Queue timeoutQueue() {
        return QueueBuilder.durable(TIMEOUT_QUEUE)
                .withArgument("x-dead-letter-exchange", CANCEL_EXCHANGE)
                .withArgument("x-dead-letter-routing-key", CANCEL_ROUTING_KEY).build();
    }
    @Bean public DirectExchange cancelExchange() { return ExchangeBuilder.directExchange(CANCEL_EXCHANGE).durable(true).build(); }
    @Bean public Queue cancelQueue() { return QueueBuilder.durable(CANCEL_QUEUE).build(); }
    @Bean public Binding cancelBinding() { return BindingBuilder.bind(cancelQueue()).to(cancelExchange()).with(CANCEL_ROUTING_KEY); }
}
