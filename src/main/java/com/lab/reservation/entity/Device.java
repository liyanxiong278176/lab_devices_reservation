package com.lab.reservation.entity;

import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.math.BigDecimal;
import java.util.List;

@Data
@EqualsAndHashCode(callSuper = true)
@TableName(value = "device", autoResultMap = true)
public class Device extends BaseEntity {
    private String name;
    private Long categoryId;
    private Long labId;
    private String brand;
    private String model;
    private String specs;
    private String imageUrl;
    private String status;
    private Integer needApproval;
    private BigDecimal maxReservationHours;
    private BigDecimal pricePerHour;
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<String> tags;
    private String description;
}
