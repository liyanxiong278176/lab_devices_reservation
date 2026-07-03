package com.lab.reservation.vo.recommendation;

import lombok.Data;

import java.math.BigDecimal;

/**
 * 智能推荐单个设备项。
 *
 * <p>除设备概要字段外，额外携带启发式打分 {@link #score} 与可解释理由 {@link #reason}。
 */
@Data
public class RecommendationItemVO {

    /** 设备 ID */
    private Long deviceId;

    /** 设备名称 */
    private String name;

    /** 类目 ID */
    private Long categoryId;

    /** 类目名称 */
    private String categoryName;

    /** 实验室 ID */
    private Long labId;

    /** 实验室名称 */
    private String labName;

    /** 综合得分（保留 4 位小数） */
    private double score;

    /** 推荐理由（可解释） */
    private String reason;

    /** 品牌（可选概要字段） */
    private String brand;

    /** 型号（可选概要字段） */
    private String model;

    /** 状态字符串（IDLE 等，可选概要字段） */
    private String status;

    /** 每小时单价（可选概要字段） */
    private BigDecimal pricePerHour;
}
