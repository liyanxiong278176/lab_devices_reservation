package com.lab.reservation.service;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.lab.reservation.dto.device.DeviceQueryDTO;
import com.lab.reservation.dto.device.DeviceSaveDTO;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.vo.device.DeviceCalendarItemVO;
import com.lab.reservation.vo.device.DeviceVO;

import java.time.LocalDate;
import java.util.List;

public interface DeviceService {

    IPage<DeviceVO> search(DeviceQueryDTO query);

    DeviceVO getById(Long id);

    List<DeviceCalendarItemVO> calendar(Long deviceId, LocalDate from, LocalDate to);

    DeviceVO create(DeviceSaveDTO dto, SecurityUserDetails user);

    DeviceVO update(Long id, DeviceSaveDTO dto, SecurityUserDetails user);

    void delete(Long id, SecurityUserDetails user);

    void updateStatus(Long id, String status, SecurityUserDetails user);
}
