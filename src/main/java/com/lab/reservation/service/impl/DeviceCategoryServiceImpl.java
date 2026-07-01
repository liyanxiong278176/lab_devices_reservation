package com.lab.reservation.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.lab.reservation.entity.DeviceCategory;
import com.lab.reservation.mapper.DeviceCategoryMapper;
import com.lab.reservation.service.DeviceCategoryService;
import com.lab.reservation.vo.device.DeviceCategoryNodeVO;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class DeviceCategoryServiceImpl implements DeviceCategoryService {

    private final DeviceCategoryMapper categoryMapper;

    @Override
    public List<DeviceCategoryNodeVO> tree() {
        List<DeviceCategory> all = categoryMapper.selectList(
                new LambdaQueryWrapper<DeviceCategory>().orderByAsc(DeviceCategory::getSort));

        // 转节点
        Map<Long, DeviceCategoryNodeVO> nodeMap = new LinkedHashMap<>();
        for (DeviceCategory c : all) {
            DeviceCategoryNodeVO node = new DeviceCategoryNodeVO();
            node.setId(c.getId());
            node.setName(c.getName());
            node.setParentId(c.getParentId());
            node.setSort(c.getSort());
            nodeMap.put(c.getId(), node);
        }

        // 按 parentId 分组挂载子节点
        List<DeviceCategoryNodeVO> roots = new ArrayList<>();
        for (DeviceCategoryNodeVO node : nodeMap.values()) {
            Long pid = node.getParentId();
            if (pid == null || pid == 0L || !nodeMap.containsKey(pid)) {
                roots.add(node);
            } else {
                nodeMap.get(pid).getChildren().add(node);
            }
        }

        // 排序（sort 升序，空值补 0）
        sortTree(roots);
        return roots;
    }

    private void sortTree(List<DeviceCategoryNodeVO> nodes) {
        if (nodes == null || nodes.isEmpty()) {
            return;
        }
        nodes.sort(Comparator.comparing(n -> n.getSort() == null ? Integer.MAX_VALUE : n.getSort(),
                Comparator.nullsLast(Comparator.naturalOrder())));
        for (DeviceCategoryNodeVO n : nodes) {
            sortTree(n.getChildren());
        }
    }
}
