package com.lab.reservation.vo.dashboard;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 热力图单元格：星期 x 小时段 的预约密度。
 *
 * <p>dayOfWeek 取 MySQL DAYOFWEEK()（1=周日 ... 7=周六）；
 * hour 为相对 work-start 的小时偏移（0..13 对应 08:00..21:00）。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class HeatmapCellVO {
    private Integer dayOfWeek;
    private Integer hour;
    private Long count;
}
