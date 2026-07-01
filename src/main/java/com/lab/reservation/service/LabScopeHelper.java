package com.lab.reservation.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.lab.reservation.entity.Lab;
import com.lab.reservation.mapper.LabMapper;
import com.lab.reservation.security.SecurityUserDetails;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.stream.Collectors;

/**
 * 实验室自辖范围过滤器：用于 LAB_ADMIN 数据隔离。
 *
 * 语义约定（被 T8/T11/T13/T15 复用）：
 * <ul>
 *   <li>返回 {@code null}  → 不加 lab 过滤（SYS_ADMIN，全局可见）。</li>
 *   <li>返回非 null 空列表 → LAB_ADMIN 当前未管辖任何 lab，应返回空结果。</li>
 *   <li>返回非空列表     → 仅可见这些 lab（lab_id IN (list)）。</li>
 * </ul>
 */
@Component
@RequiredArgsConstructor
public class LabScopeHelper {

    private final LabMapper labMapper;

    public List<Long> managedLabIds(SecurityUserDetails user) {
        if (user == null) {
            return List.of();
        }
        boolean isSysAdmin = user.getAuthorities().stream()
                .anyMatch(a -> a.getAuthority().equals("ROLE_SYS_ADMIN"));
        if (isSysAdmin) {
            return null;
        }
        return labMapper.selectList(new LambdaQueryWrapper<Lab>()
                        .eq(Lab::getManagerId, user.getUserId()))
                .stream().map(Lab::getId).collect(Collectors.toList());
    }
}
