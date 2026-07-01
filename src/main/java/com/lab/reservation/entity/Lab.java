package com.lab.reservation.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = true)
@TableName("lab")
public class Lab extends BaseEntity {
    private String name;
    private String location;
    private Long managerId;
    private String description;
    private Integer status;
}
