package com.lab.reservation.service;

import com.lab.reservation.vo.recommendation.RecommendationItemVO;

import java.util.List;

/**
 * 智能推荐服务：基于混合启发式打分（类目/实验室亲和 + 热门度 + 标签匹配 - 已约扣分），
 * 附带可解释理由与冷启动降级。
 */
public interface RecommendationService {

    /**
     * 为给定用户生成设备推荐列表。
     *
     * @param userId 当前登录用户 ID
     * @param limit  返回条数上限（&lt;=0 取默认 10；服务端另有全局上限）
     * @return 按得分降序排列的推荐项
     */
    List<RecommendationItemVO> recommend(Long userId, int limit);
}
