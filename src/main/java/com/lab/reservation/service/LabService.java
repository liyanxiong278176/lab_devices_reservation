package com.lab.reservation.service;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.lab.reservation.entity.Lab;
import com.lab.reservation.security.SecurityUserDetails;

public interface LabService {

    IPage<Lab> page(long page, long size, SecurityUserDetails user);

    Lab getById(Long id, SecurityUserDetails user);

    Lab create(Lab lab);

    Lab update(Lab lab, SecurityUserDetails user);

    void delete(Long id, SecurityUserDetails user);
}
