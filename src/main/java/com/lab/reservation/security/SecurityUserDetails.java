package com.lab.reservation.security;

import lombok.Getter;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.User;

import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;

/**
 * 认证主体。继承自 Spring Security 的 {@link User}。
 *
 * 注意：本类名 User 与父类 User 同名，但仅 import 父类，无冲突。
 * Spring Security 的 User(details) 构造器将传入的两个 authorities 集合合并为一个
 * authorities 集合（实际只取 grantedAuthorities；此处把角色（ROLE_ 前缀）与权限合并传入）。
 *
 * 关键设计：父类的 enabled 字段直接反映账号状态（status != 0），
 * 这样 Spring Security 原生的账号锁定/禁用语义与业务状态字段保持一致，
 * 登录、/me、JWT 过滤器等链路均能统一读取，无需重复查库。
 */
@Getter
public class SecurityUserDetails extends User {
    private final Long userId;
    private final String realName;

    public SecurityUserDetails(Long userId, String username, String password,
                               boolean enabled, String realName,
                               List<String> roles, List<String> perms) {
        super(username, password, enabled, true, true, true,
                mergeAuthorities(roles, perms));
        this.userId = userId;
        this.realName = realName;
    }

    private static List<SimpleGrantedAuthority> mergeAuthorities(List<String> roles, List<String> perms) {
        List<SimpleGrantedAuthority> list = new ArrayList<>();
        if (roles != null) {
            list.addAll(roles.stream()
                    .map(r -> new SimpleGrantedAuthority("ROLE_" + r))
                    .collect(Collectors.toList()));
        }
        if (perms != null) {
            list.addAll(perms.stream()
                    .map(SimpleGrantedAuthority::new)
                    .collect(Collectors.toList()));
        }
        return list;
    }
}
