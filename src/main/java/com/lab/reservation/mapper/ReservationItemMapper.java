package com.lab.reservation.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.lab.reservation.entity.ReservationItem;
import com.lab.reservation.vo.dashboard.HeatmapCellVO;
import com.lab.reservation.vo.dashboard.OccupiedSlotCountVO;
import com.lab.reservation.vo.device.DeviceCalendarItemVO;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.time.LocalDate;
import java.util.List;

@Mapper
public interface ReservationItemMapper extends BaseMapper<ReservationItem> {

    /**
     * 设备日历：查询设备在 [from, to] 区间内被「有效预约」占用的 slot。
     * 有效状态 = PENDING / APPROVED / IN_USE（REJECTED/CANCELLED/COMPLETED/VIOLATED/NO_SHOW 不显示占用）。
     */
    @Select("SELECT ri.date AS date, ri.slot_index AS slotIndex, ri.reservation_id AS reservationId, r.status AS status "
            + "FROM reservation_item ri "
            + "JOIN reservation r ON ri.reservation_id = r.id "
            + "WHERE ri.device_id = #{deviceId} "
            + "AND ri.date BETWEEN #{from} AND #{to} "
            + "AND r.status IN ('PENDING','APPROVED','IN_USE') "
            + "ORDER BY ri.date, ri.slot_index")
    List<DeviceCalendarItemVO> selectCalendar(@Param("deviceId") Long deviceId,
                                              @Param("from") LocalDate from,
                                              @Param("to") LocalDate to);

    /**
     * 设备占用 slot 聚合（利用率用）：按 device_id 分组统计有效占用 slot 数。
     *
     * <p>仅统计 PENDING / APPROVED / IN_USE 的预约（JOIN reservation 过滤）。
     *
     * @param deviceIds 设备范围；null 表示不限（SYS_ADMIN 全量），非空列表表示 LAB_ADMIN 自辖设备
     */
    @Select("<script>"
            + "SELECT ri.device_id AS deviceId, COUNT(*) AS occupied "
            + "FROM reservation_item ri "
            + "JOIN reservation r ON ri.reservation_id = r.id "
            + "WHERE ri.date BETWEEN #{from} AND #{to} "
            + "AND r.status IN ('PENDING','APPROVED','IN_USE') "
            + "<if test='deviceIds != null'>AND ri.device_id IN "
            + "<foreach collection='deviceIds' item='did' open='(' separator=',' close=')'>#{did}</foreach>"
            + "</if> "
            + "GROUP BY ri.device_id"
            + "</script>")
    List<OccupiedSlotCountVO> selectOccupiedSlotCounts(@Param("deviceIds") List<Long> deviceIds,
                                                       @Param("from") LocalDate from,
                                                       @Param("to") LocalDate to);

    /**
     * 热力图聚合：按 星期(DAYOFWEEK) × 小时段 聚合有效预约的 slot 密度。
     *
     * <p>小时段 = slot_index DIV slotsPerHour（如 15min slot → 4 slot/hour → hour 偏移 0..13 对应 08:00..21:00）。
     *
     * @param deviceIds    设备范围；null 表示不限，非空列表表示限定设备
     * @param slotsPerHour 每小时 slot 数（60 / slotMinutes），用于把 slot_index 折叠为小时桶
     */
    @Select("<script>"
            + "SELECT DAYOFWEEK(ri.date) AS dayOfWeek, (ri.slot_index DIV #{slotsPerHour}) AS hour, COUNT(*) AS count "
            + "FROM reservation_item ri "
            + "JOIN reservation r ON ri.reservation_id = r.id "
            + "WHERE ri.date BETWEEN #{from} AND #{to} "
            + "AND r.status IN ('PENDING','APPROVED','IN_USE') "
            + "<if test='deviceIds != null'>AND ri.device_id IN "
            + "<foreach collection='deviceIds' item='did' open='(' separator=',' close=')'>#{did}</foreach>"
            + "</if> "
            + "GROUP BY dayOfWeek, hour"
            + "</script>")
    List<HeatmapCellVO> selectHeatmap(@Param("deviceIds") List<Long> deviceIds,
                                      @Param("from") LocalDate from,
                                      @Param("to") LocalDate to,
                                      @Param("slotsPerHour") int slotsPerHour);
}
