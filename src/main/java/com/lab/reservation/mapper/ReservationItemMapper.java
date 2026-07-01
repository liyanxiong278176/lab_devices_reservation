package com.lab.reservation.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.lab.reservation.entity.ReservationItem;
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
}
