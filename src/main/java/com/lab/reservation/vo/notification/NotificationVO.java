package com.lab.reservation.vo.notification;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 通知返回视图。规格 §8.7。
 */
@Data
public class NotificationVO {
    private Long id;
    private Long userId;
    private String type;
    private String title;
    private String content;
    private Long relatedId;
    private String relatedType;
    private Integer isRead;
    private LocalDateTime createdAt;
}
