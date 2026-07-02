package com.lab.reservation.dto.user;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

import java.util.List;

/**
 * 用户创建/更新参数（仅 SYS_ADMIN 使用）。
 * 更新时 username 不可改；password 为空表示不改密码。
 */
@Data
public class UserCreateDTO {
    /** 创建时必填，更新时忽略 */
    @NotBlank(message = "用户名不能为空")
    private String username;
    /** 创建时必填；更新时为空表示不改密码 */
    private String password;
    private String realName;
    private String phone;
    private String email;
    /** STUDENT / TEACHER / STAFF */
    private String userType;
    private String deptName;
    /** 角色编码列表（如 SYS_ADMIN/LAB_ADMIN/STUDENT），重绑 */
    private List<String> roleCodes;
}
