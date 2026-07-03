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

    /**
     * 活跃预约趋势（带设备范围）：按 DATE(start_time) 聚合，可限定设备集。
     *
     * <p>活跃状态：PENDING / APPROVED / IN_USE。用于仪表盘 overview 的 30 天趋势（LAB_ADMIN 范围过滤）。
     *
     * @param from      起始时间（含）
     * @param deviceIds 设备范围；null 表示不限（SYS_ADMIN 全量），非空列表表示 LAB_ADMIN 自辖设备
     */
    @Select("<script>"
            + "SELECT DATE(start_time) AS date, COUNT(*) AS count "
            + "FROM reservation "
            + "WHERE start_time >= #{from} "
            + "AND status IN ('PENDING','APPROVED','IN_USE') "
            + "<if test='deviceIds != null'>AND device_id IN "
            + "<foreach collection='deviceIds' item='did' open='(' separator=',' close=')'>#{did}</foreach>"
            + "</if> "
            + "GROUP BY DATE(start_time) "
            + "ORDER BY date"
            + "</script>")
    List<ReservationTrendItemVO> selectDailyActiveTrendScoped(@Param("from") LocalDateTime from,
                                                              @Param("deviceIds") List<Long> deviceIds);
}
