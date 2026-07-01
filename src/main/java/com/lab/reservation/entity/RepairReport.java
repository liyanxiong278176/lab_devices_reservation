package com.lab.reservation.entity;

import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.time.LocalDateTime;
import java.util.List;

@Data
@EqualsAndHashCode(callSuper = true)
@TableName(value = "repair_report", autoResultMap = true)
public class RepairReport extends BaseEntity {
    private Long deviceId;
    private Long reporterId;
    private String title;
    private String description;
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<String> imageUrls;
    private String status;
    private Long handlerId;
    private String resolutionNote;
    private LocalDateTime resolvedAt;
}
