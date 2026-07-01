package com.lab.reservation.vo.auth;

import lombok.Data;

@Data
public class LoginVO {
    private String accessToken;
    private String refreshToken;
    private Long expiresIn;
    private UserInfoVO userInfo;
}
