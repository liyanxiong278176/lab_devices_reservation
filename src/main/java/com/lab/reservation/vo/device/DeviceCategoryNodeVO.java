package com.lab.reservation.vo.device;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

/**
 * 设备分类树节点。parent_id = 0 视为根。
 */
@Data
public class DeviceCategoryNodeVO {
    private Long id;
    private String name;
    private Long parentId;
    private Integer sort;
    private List<DeviceCategoryNodeVO> children = new ArrayList<>();
}
