package com.lab.reservation.service;

import com.lab.reservation.dto.auth.LoginDTO;
import com.lab.reservation.dto.auth.RegisterDTO;
import com.lab.reservation.vo.auth.LoginVO;

public interface AuthService {

    LoginVO login(LoginDTO dto);

    void register(RegisterDTO dto);

    String refresh(String refreshToken);

    void logout(String token);
}
