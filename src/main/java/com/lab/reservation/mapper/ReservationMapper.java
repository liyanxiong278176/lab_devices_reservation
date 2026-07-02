package com.lab.reservation.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.lab.reservation.entity.Reservation;
import com.lab.reservation.vo.dashboard.ReservationTrendItemVO;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.time.LocalDateTime;
import java.util.List;

@Mapper
public interface ReservationMapper extends BaseMapper<Reservation> {

    /**
     * 活跃预约趋势：按 DATE(start_time) 聚合。
     * 活跃状态：PENDING / APPROVED / IN_USE。
     * 起始时间由调用方传入（近 7 天为 start_time >= 当天 00:00 减 6 天）。
     * 返回结果可能不含无预约的日期，调用方需自行补 0。
     */
    @Select("SELECT DATE(start_time) AS date, COUNT(*) AS count "
            + "FROM reservation "
            + "WHERE start_time >= #{from} "
            + "AND status IN ('PENDING','APPROVED','IN_USE') "
            + "GROUP BY DATE(start_time) "
            + "ORDER BY date")
    List<ReservationTrendItemVO> selectDailyActiveTrend(@Param("from") LocalDateTime from);
}
