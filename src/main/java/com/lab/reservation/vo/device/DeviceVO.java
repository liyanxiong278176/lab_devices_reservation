package com.lab.reservation.vo.device;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

@Data
public class DeviceVO {
    private Long id;
    private String name;
    private Long categoryId;
    private String categoryName;
    private Long labId;
    private String labName;
    private String brand;
    private String model;
    private String specs;
    private String imageUrl;
    private String status;
    private Integer needApproval;
    private BigDecimal maxReservationHours;
    private BigDecimal pricePerHour;
    private List<String> tags;
    private String description;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
