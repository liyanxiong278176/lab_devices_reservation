package com.lab.reservation.dto.reservation;

import com.lab.reservation.entity.enums.ReservationStatus;
import lombok.Data;

/**
 * 我的预约查询参数。
 *
 * status 为可选过滤项（不传则查全部状态）；page/size 分页，默认 page=1,size=10。
 */
@Data
public class ReservationQueryDTO {

    /** 过滤状态，可空。 */
    private ReservationStatus status;

    /** 页码，默认 1。 */
    private Integer page = 1;

    /** 每页大小，默认 10。 */
    private Integer size = 10;
}
