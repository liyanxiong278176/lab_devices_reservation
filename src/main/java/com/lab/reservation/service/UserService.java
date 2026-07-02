package com.lab.reservation.service;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.lab.reservation.dto.user.UserCreateDTO;
import com.lab.reservation.dto.user.UserQueryDTO;
import com.lab.reservation.vo.user.UserVO;

public interface UserService {

    IPage<UserVO> list(UserQueryDTO query);

    UserVO create(UserCreateDTO dto);

    UserVO update(Long id, UserCreateDTO dto);

    void delete(Long id, Long currentUserId);

    void updateStatus(Long id, Integer status);
}
