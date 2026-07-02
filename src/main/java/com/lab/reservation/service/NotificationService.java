package com.lab.reservation.service;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.lab.reservation.vo.notification.NotificationVO;

/**
 * 站内通知服务。规格 §8.7。
 *
 * 双重职责：
 * <ul>
 *   <li>事件接入：业务事件（预约/审批/报修）触发后由对应 service 回调
 *       {@link #notify} 写入 notification 表。</li>
 *   <li>用户自助：登录用户查/读/全部已读自己的通知。</li>
 * </ul>
 */
public interface NotificationService {

    /**
     * 写入一条通知。is_read 默认 0（未读）。
     *
     * @param userId      接收人
     * @param type        类型（RESERVATION / APPROVAL / REPAIR）
     * @param title       标题
     * @param content     正文
     * @param relatedId   关联业务 id（预约 id / 报修 id）
     * @param relatedType 关联类型（RESERVATION / REPAIR）
     */
    void notify(Long userId, String type, String title, String content, Long relatedId, String relatedType);

    /**
     * 我的通知（按 user_id 过滤，可 onlyUnread，createdAt 倒序分页）。
     */
    IPage<NotificationVO> mine(Long userId, Boolean onlyUnread, int page, int size);

    /**
     * 标记单条为已读。校验该通知归属 userId，否则 FORBIDDEN/NOT_FOUND。
     */
    void markRead(Long id, Long userId);

    /**
     * 当前用户全部未读标记为已读。
     */
    void markAllRead(Long userId);
}
