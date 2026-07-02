package com.lab.reservation.dto.user;

import lombok.Data;

/**
 * 用户列表分页检索参数（仅 SYS_ADMIN 使用）。
 */
@Data
public class UserQueryDTO {
    /** 用户名模糊匹配 */
    private String username;
    /** 真实姓名模糊匹配 */
    private String realName;
    /** 状态等值：0 禁用 / 1 启用 */
    private Integer status;
    /** 默认 1 */
    private Long page = 1L;
    /** 默认 10 */
    private Long size = 10L;
}
