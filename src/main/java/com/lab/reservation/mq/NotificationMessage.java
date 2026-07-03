package com.lab.reservation.mq;
import lombok.AllArgsConstructor; import lombok.Data; import lombok.NoArgsConstructor;
@Data @NoArgsConstructor @AllArgsConstructor
public class NotificationMessage {
    private String msgId; private Long userId; private String type;
    private String title; private String content; private Long relatedId; private String relatedType;
}
