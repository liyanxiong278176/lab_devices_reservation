package com.lab.reservation.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.dto.device.DeviceQueryDTO;
import com.lab.reservation.dto.device.DeviceSaveDTO;
import com.lab.reservation.entity.Device;
import com.lab.reservation.entity.DeviceCategory;
import com.lab.reservation.entity.Lab;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.DeviceCategoryMapper;
import com.lab.reservation.mapper.DeviceMapper;
import com.lab.reservation.mapper.LabMapper;
import com.lab.reservation.mapper.ReservationItemMapper;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.DeviceService;
import com.lab.reservation.service.LabScopeHelper;
import com.lab.reservation.vo.device.DeviceCalendarItemVO;
import com.lab.reservation.vo.device.DeviceVO;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.List;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class DeviceServiceImpl implements DeviceService {

    private final DeviceMapper deviceMapper;
    private final LabMapper labMapper;
    private final DeviceCategoryMapper categoryMapper;
    private final ReservationItemMapper reservationItemMapper;
    private final LabScopeHelper labScopeHelper;

    @Override
    public IPage<DeviceVO> search(DeviceQueryDTO q) {
        // 浏览端点：所有已登录用户（含学生）可见全部设备，用于查找可预约设备。
        // 设备管理范围隔离（LAB_ADMIN 仅自辖）在写操作 create/update/delete/updateStatus
        // 里由 assertLabInScope 保障，不在此浏览查询做。
        LambdaQueryWrapper<Device> wrapper = new LambdaQueryWrapper<>();
        if (q.getCategoryId() != null) {
            wrapper.eq(Device::getCategoryId, q.getCategoryId());
        }
        if (q.getLabId() != null) {
            // 按 lab 显式过滤
            wrapper.eq(Device::getLabId, q.getLabId());
        }
        if (q.getStatus() != null && !q.getStatus().isBlank()) {
            wrapper.eq(Device::getStatus, q.getStatus());
        }
        if (q.getNeedApproval() != null) {
            wrapper.eq(Device::getNeedApproval, q.getNeedApproval());
        }
        if (q.getKeyword() != null && !q.getKeyword().isBlank()) {
            wrapper.like(Device::getName, q.getKeyword());
        }
        if (q.getMinPrice() != null) {
            wrapper.ge(Device::getPricePerHour, q.getMinPrice());
        }
        if (q.getMaxPrice() != null) {
            wrapper.le(Device::getPricePerHour, q.getMaxPrice());
        }
        wrapper.orderByDesc(Device::getId);

        Page<Device> page = deviceMapper.selectPage(new Page<>(q.getPage(), q.getSize()), wrapper);
        return page.convert(this::toVO);
    }

    @Override
    public DeviceVO getById(Long id) {
        Device d = deviceMapper.selectById(id);
        if (d == null) {
            throw new BusinessException(ResultCode.NOT_FOUND);
        }
        return toVO(d);
    }

    @Override
    public List<DeviceCalendarItemVO> calendar(Long deviceId, LocalDate from, LocalDate to) {
        if (deviceMapper.selectById(deviceId) == null) {
            throw new BusinessException(ResultCode.NOT_FOUND);
        }
        if (from == null) {
            throw new BusinessException(ResultCode.PARAM_INVALID);
        }
        if (to == null) {
            to = from;
        }
        if (to.isBefore(from)) {
            throw new BusinessException(ResultCode.PARAM_INVALID);
        }
        return reservationItemMapper.selectCalendar(deviceId, from, to);
    }

    @Override
    public DeviceVO create(DeviceSaveDTO dto, SecurityUserDetails user) {
        assertLabInScope(dto.getLabId(), user);
        assertCategoryExists(dto.getCategoryId());
        Device d = new Device();
        BeanUtils.copyProperties(dto, d);
        if (d.getStatus() == null) {
            d.setStatus("IDLE");
        }
        deviceMapper.insert(d);
        return toVO(deviceMapper.selectById(d.getId()));
    }

    @Override
    public DeviceVO update(Long id, DeviceSaveDTO dto, SecurityUserDetails user) {
        Device exist = deviceMapper.selectById(id);
        if (exist == null) {
            throw new BusinessException(ResultCode.NOT_FOUND);
        }
        assertLabInScope(exist.getLabId(), user);
        // 若变更 labId，新 lab 也须在自辖范围内
        if (dto.getLabId() != null && !dto.getLabId().equals(exist.getLabId())) {
            assertLabInScope(dto.getLabId(), user);
        }
        assertCategoryExists(dto.getCategoryId());
        BeanUtils.copyProperties(dto, exist);
        deviceMapper.updateById(exist);
        return toVO(deviceMapper.selectById(id));
    }

    @Override
    public void delete(Long id, SecurityUserDetails user) {
        Device exist = deviceMapper.selectById(id);
        if (exist == null) {
            throw new BusinessException(ResultCode.NOT_FOUND);
        }
        assertLabInScope(exist.getLabId(), user);
        deviceMapper.deleteById(id);
    }

    @Override
    public void updateStatus(Long id, String status, SecurityUserDetails user) {
        Device exist = deviceMapper.selectById(id);
        if (exist == null) {
            throw new BusinessException(ResultCode.NOT_FOUND);
        }
        assertLabInScope(exist.getLabId(), user);
        Set<String> valid = Set.of("IDLE", "IN_USE", "MAINTENANCE");
        if (status == null || !valid.contains(status)) {
            throw new BusinessException(ResultCode.PARAM_INVALID);
        }
        exist.setStatus(status);
        deviceMapper.updateById(exist);
    }

    // ---- helpers ----

    /**
     * 校验：LAB_ADMIN 只能操作自辖 lab 内的设备；SYS_ADMIN 不受限。
     */
    private void assertLabInScope(Long labId, SecurityUserDetails user) {
        if (labId == null) {
            return;
        }
        List<Long> ids = labScopeHelper.managedLabIds(user);
        if (ids == null) {
            return; // SYS_ADMIN
        }
        if (!ids.contains(labId)) {
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
    }

    private void assertCategoryExists(Long categoryId) {
        if (categoryId != null && categoryMapper.selectById(categoryId) == null) {
            throw new BusinessException(ResultCode.PARAM_INVALID);
        }
    }

    private DeviceVO toVO(Device d) {
        DeviceVO vo = new DeviceVO();
        BeanUtils.copyProperties(d, vo);
        if (d.getLabId() != null) {
            Lab lab = labMapper.selectById(d.getLabId());
            if (lab != null) {
                vo.setLabName(lab.getName());
            }
        }
        if (d.getCategoryId() != null) {
            DeviceCategory cat = categoryMapper.selectById(d.getCategoryId());
            if (cat != null) {
                vo.setCategoryName(cat.getName());
            }
        }
        return vo;
    }
}
