package com.lab.reservation.service;

import com.lab.reservation.vo.device.DeviceCategoryNodeVO;

import java.util.List;

public interface DeviceCategoryService {

    List<DeviceCategoryNodeVO> tree();
}
