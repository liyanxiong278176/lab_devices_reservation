package com.lab.reservation.vo.dashboard;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 设备占用 slot 聚合（利用率计算用）：某设备在时间窗口内的有效占用 slot 数。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class OccupiedSlotCountVO {
    private Long deviceId;
    private Long occupied;
}
