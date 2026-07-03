package com.lab.reservation.notification;

import com.lab.reservation.entity.Notification;
import com.lab.reservation.mapper.NotificationMapper;
import com.lab.reservation.service.impl.NotificationServiceImpl;
import org.junit.jupiter.api.Test;
import org.springframework.messaging.simp.SimpMessagingTemplate;

import java.time.LocalDateTime;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 验证 NotificationService.notify() 在写库后，会通过 SimpMessagingTemplate
 * 向用户专属队列 /user/{userId}/queue/notifications 推送实时通知（DB/WS 双写）。
 */
class NotificationBroadcastTest {

    @Test
    void notify_persists_and_pushes_to_user_queue() {
        NotificationMapper mapper = mock(NotificationMapper.class);
        SimpMessagingTemplate tpl = mock(SimpMessagingTemplate.class);

        // 模拟 MyBatis-Plus insert 回填：生产中 MetaObjectHandler 会填充 id+createdAt；
        // Map.of() 不允许 null 值，故在 mock 中一并回填，避免 payload 构造时 NPE。
        when(mapper.insert(any(Notification.class))).thenAnswer(inv -> {
            Notification n = inv.getArgument(0);
            n.setId(1L);
            n.setCreatedAt(LocalDateTime.now());
            return 1;
        });

        NotificationServiceImpl svc = new NotificationServiceImpl(mapper, tpl);

        svc.notify(7L, "RESERVATION", "预约成功", "设备X", 1L, "RESERVATION");

        verify(tpl).convertAndSendToUser(eq("7"), eq("/queue/notifications"), any());
    }
}
