package com.lab.reservation.vo.dashboard;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;

/**
 * 预约趋势单项：某日活跃预约数。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class ReservationTrendItemVO {
    private LocalDate date;
    private long count;
}
