package com.lab.reservation.vo.auth;

import lombok.Data;

import java.util.List;

@Data
public class UserInfoVO {
    private Long id;
    private String username;
    private String realName;
    private List<String> roles;
    private List<String> permissions;
}
