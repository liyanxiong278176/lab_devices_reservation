package com.lab.reservation.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDate;

@Data
@TableName("reservation_item")
public class ReservationItem {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long reservationId;
    private Long deviceId;
    private LocalDate date;
    private Integer slotIndex;
}
