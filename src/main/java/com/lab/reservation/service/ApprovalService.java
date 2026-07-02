package com.lab.reservation.service;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.vo.approval.ApprovalItemVO;

import java.util.List;

/**
 * 审批服务（§8.6）。
 *
 * 数据隔离复用 {@link LabScopeHelper}：
 * <ul>
 *   <li>SYS_ADMIN  → 全量待审批（labIds == null）。</li>
 *   <li>LAB_ADMIN  → 仅自辖 lab 下设备的待审批（labIds 非空）。</li>
 *   <li>学生无 device:approve 权限，进不来这层。</li>
 * </ul>
 *
 * 状态语义：
 * <ul>
 *   <li>{@code approve}：PENDING → APPROVED，保留槽（预约生效）。</li>
 *   <li>{@code reject} ：PENDING → REJECTED，删除 reservation_item（释放槽）。</li>
 * </ul>
 */
public interface ApprovalService {

    /** 待审批列表（按角色范围过滤，分页，按开始时间升序：先到期的先审批）。 */
    IPage<ApprovalItemVO> pendingList(int page, int size, SecurityUserDetails ud);

    /** 通过预约（PENDING → APPROVED）。 */
    void approve(Long id, SecurityUserDetails ud);

    /** 拒绝预约（PENDING → REJECTED，释放槽）。 */
    void reject(Long id, String reason, SecurityUserDetails ud);

    /**
     * 批量通过。@Transactional 内顺序执行；任一非 PENDING 抛错回滚整体。
     */
    void batchApprove(List<Long> ids, SecurityUserDetails ud);
}
