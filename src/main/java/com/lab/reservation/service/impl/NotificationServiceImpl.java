package com.lab.reservation.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.entity.Notification;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.NotificationMapper;
import com.lab.reservation.service.NotificationService;
import com.lab.reservation.vo.notification.NotificationVO;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

/**
 * 通知服务实现。规格 §8.7。
 *
 * 归属校验：markRead 时必须 notification.user_id == 入参 userId，否则 FORBIDDEN
 * （即便 id 不存在也返回 NOT_FOUND 以避免泄露存在性）。
 */
@Service
@RequiredArgsConstructor
public class NotificationServiceImpl implements NotificationService {

    private final NotificationMapper notificationMapper;

    @Override
    public void notify(Long userId, String type, String title, String content, Long relatedId, String relatedType) {
        Notification n = new Notification();
        n.setUserId(userId);
        n.setType(type);
        n.setTitle(title);
        n.setContent(content);
        n.setRelatedId(relatedId);
        n.setRelatedType(relatedType);
        n.setIsRead(0);
        notificationMapper.insert(n);
    }

    @Override
    public IPage<NotificationVO> mine(Long userId, Boolean onlyUnread, int page, int size) {
        Page<Notification> p = new Page<>(page, size);
        LambdaQueryWrapper<Notification> qw = new LambdaQueryWrapper<Notification>()
                .eq(Notification::getUserId, userId);
        if (Boolean.TRUE.equals(onlyUnread)) {
            qw.eq(Notification::getIsRead, 0);
        }
        qw.orderByDesc(Notification::getCreatedAt);

        IPage<Notification> np = notificationMapper.selectPage(p, qw);
        return np.convert(this::toVO);
    }

    @Override
    public void markRead(Long id, Long userId) {
        Notification n = notificationMapper.selectById(id);
        if (n == null) {
            throw new BusinessException(ResultCode.NOT_FOUND);
        }
        if (!n.getUserId().equals(userId)) {
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
        n.setIsRead(1);
        notificationMapper.updateById(n);
    }

    @Override
    public void markAllRead(Long userId) {
        notificationMapper.update(null, new LambdaUpdateWrapper<Notification>()
                .eq(Notification::getUserId, userId)
                .eq(Notification::getIsRead, 0)
                .set(Notification::getIsRead, 1));
    }

    private NotificationVO toVO(Notification n) {
        NotificationVO vo = new NotificationVO();
        vo.setId(n.getId());
        vo.setUserId(n.getUserId());
        vo.setType(n.getType());
        vo.setTitle(n.getTitle());
        vo.setContent(n.getContent());
        vo.setRelatedId(n.getRelatedId());
        vo.setRelatedType(n.getRelatedType());
        vo.setIsRead(n.getIsRead());
        vo.setCreatedAt(n.getCreatedAt());
        return vo;
    }
}
