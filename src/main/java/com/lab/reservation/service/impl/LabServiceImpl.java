package com.lab.reservation.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.entity.Lab;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.LabMapper;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.LabService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
public class LabServiceImpl implements LabService {

    private final LabMapper labMapper;

    @Override
    public IPage<Lab> page(long page, long size, SecurityUserDetails user) {
        LambdaQueryWrapper<Lab> wrapper = new LambdaQueryWrapper<Lab>().orderByDesc(Lab::getId);
        if (user != null) {
            boolean isSysAdmin = user.getAuthorities().stream()
                    .anyMatch(a -> a.getAuthority().equals("ROLE_SYS_ADMIN"));
            if (!isSysAdmin) {
                // LAB_ADMIN 仅见自辖 lab
                wrapper.eq(Lab::getManagerId, user.getUserId());
            }
        }
        return labMapper.selectPage(new Page<>(page, size), wrapper);
    }

    @Override
    public Lab getById(Long id, SecurityUserDetails user) {
        Lab lab = labMapper.selectById(id);
        if (lab == null) {
            throw new BusinessException(ResultCode.NOT_FOUND);
        }
        if (user != null) {
            boolean isSysAdmin = user.getAuthorities().stream()
                    .anyMatch(a -> a.getAuthority().equals("ROLE_SYS_ADMIN"));
            if (!isSysAdmin && !user.getUserId().equals(lab.getManagerId())) {
                throw new BusinessException(ResultCode.FORBIDDEN);
            }
        }
        return lab;
    }

    @Override
    public Lab create(Lab lab) {
        lab.setStatus(lab.getStatus() == null ? 1 : lab.getStatus());
        labMapper.insert(lab);
        return labMapper.selectById(lab.getId());
    }

    @Override
    public Lab update(Lab lab, SecurityUserDetails user) {
        Lab exist = labMapper.selectById(lab.getId());
        if (exist == null) {
            throw new BusinessException(ResultCode.NOT_FOUND);
        }
        if (user != null) {
            boolean isSysAdmin = user.getAuthorities().stream()
                    .anyMatch(a -> a.getAuthority().equals("ROLE_SYS_ADMIN"));
            if (!isSysAdmin && !user.getUserId().equals(exist.getManagerId())) {
                throw new BusinessException(ResultCode.FORBIDDEN);
            }
        }
        labMapper.updateById(lab);
        return labMapper.selectById(lab.getId());
    }

    @Override
    public void delete(Long id, SecurityUserDetails user) {
        Lab exist = labMapper.selectById(id);
        if (exist == null) {
            throw new BusinessException(ResultCode.NOT_FOUND);
        }
        if (user != null) {
            boolean isSysAdmin = user.getAuthorities().stream()
                    .anyMatch(a -> a.getAuthority().equals("ROLE_SYS_ADMIN"));
            if (!isSysAdmin && !user.getUserId().equals(exist.getManagerId())) {
                throw new BusinessException(ResultCode.FORBIDDEN);
            }
        }
        labMapper.deleteById(id);
    }
}
