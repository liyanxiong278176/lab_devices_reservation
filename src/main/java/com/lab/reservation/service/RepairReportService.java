package com.lab.reservation.service;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.lab.reservation.dto.repair.RepairCreateDTO;
import com.lab.reservation.dto.repair.RepairHandleDTO;
import com.lab.reservation.entity.enums.RepairStatus;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.vo.repair.RepairReportVO;

/**
 * 报修服务（最小版）。规格 §6.4 / §8.9。
 *
 * 状态机：PENDING --take--> PROCESSING --resolve--> RESOLVED；PENDING --reject--> REJECTED。
 * 设备联动：take 时设备置 MAINTENANCE（阻塞新预约），resolve 时设备置回 IDLE。
 */
public interface RepairReportService {

    /** 用户提交报修：状态 PENDING，设备状态不变。返回新报修 id。 */
    Long create(RepairCreateDTO dto, Long userId);

    /** 我的报修（按 reporter_id 分页，按创建时间倒序）。 */
    IPage<RepairReportVO> mine(Long userId, int page, int size);

    /**
     * 管理员列表（按自辖 lab 范围过滤；SYS_ADMIN 全量；可按 status 过滤）。
     */
    IPage<RepairReportVO> list(RepairStatus status, int page, int size, SecurityUserDetails ud);

    /** 受理：PENDING → PROCESSING，设备 → MAINTENANCE。 */
    void take(Long id, SecurityUserDetails ud);

    /** 解决：PROCESSING → RESOLVED，设备 → IDLE。 */
    void resolve(Long id, RepairHandleDTO dto, SecurityUserDetails ud);

    /** 驳回（非真实故障）：PENDING → REJECTED，设备不变。 */
    void reject(Long id, RepairHandleDTO dto, SecurityUserDetails ud);
}
