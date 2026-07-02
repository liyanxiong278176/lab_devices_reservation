package com.lab.reservation.vo.user;

import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 用户视图对象。注意：不含 password 字段，确保密码永不外泄。
 */
@Data
public class UserVO {
    private Long id;
    private String username;
    private String realName;
    private String phone;
    private String email;
    private String userType;
    private String deptName;
    /** 0 禁用 / 1 启用 */
    private Integer status;
    /** 角色编码列表（如 ["SYS_ADMIN"]） */
    private List<String> roles;
    private LocalDateTime createdAt;
}
