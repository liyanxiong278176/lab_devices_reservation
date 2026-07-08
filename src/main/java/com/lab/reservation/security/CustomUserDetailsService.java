package com.lab.reservation.security;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.lab.reservation.entity.SysPermission;
import com.lab.reservation.entity.SysRole;
import com.lab.reservation.entity.SysRolePermission;
import com.lab.reservation.entity.SysUser;
import com.lab.reservation.entity.SysUserRole;
import com.lab.reservation.mapper.SysPermissionMapper;
import com.lab.reservation.mapper.SysRoleMapper;
import com.lab.reservation.mapper.SysRolePermissionMapper;
import com.lab.reservation.mapper.SysUserMapper;
import com.lab.reservation.mapper.SysUserRoleMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class CustomUserDetailsService implements UserDetailsService {

    private final SysUserMapper userMapper;
    private final SysUserRoleMapper userRoleMapper;
    private final SysRoleMapper roleMapper;
    private final SysRolePermissionMapper rpMapper;
    private final SysPermissionMapper permMapper;

    @Override
    public UserDetails loadUserByUsername(String username) throws UsernameNotFoundException {
        SysUser u = userMapper.selectOne(
                new LambdaQueryWrapper<SysUser>().eq(SysUser::getUsername, username));
        if (u == null) {
            throw new UsernameNotFoundException(username);
        }

        // 用户 -> 角色ID
        List<Long> roleIds = userRoleMapper.selectList(
                        new LambdaQueryWrapper<SysUserRole>().eq(SysUserRole::getUserId, u.getId()))
                .stream().map(SysUserRole::getRoleId).collect(Collectors.toList());

        // 角色ID -> 角色编码
        List<String> roleCodes = roleIds.isEmpty() ? List.of()
                : roleMapper.selectBatchIds(roleIds).stream()
                .map(SysRole::getRoleCode).collect(Collectors.toList());

        // 角色 -> 权限ID
        List<Long> permIds = roleIds.isEmpty() ? List.of()
                : rpMapper.selectList(
                        new LambdaQueryWrapper<SysRolePermission>().in(SysRolePermission::getRoleId, roleIds))
                .stream().map(SysRolePermission::getPermissionId).collect(Collectors.toList());

        // 权限ID -> 权限编码
        List<String> permCodes = permIds.isEmpty() ? List.of()
                : permMapper.selectBatchIds(permIds).stream()
                .map(SysPermission::getPermCode).collect(Collectors.toList());

        boolean enabled = u.getStatus() != null && u.getStatus() != 0;
        return new SecurityUserDetails(u.getId(), u.getUsername(), u.getPassword(),
                enabled, u.getRealName(), roleCodes, permCodes);
    }

    /**
     * 通过 userId 直接加载 SecurityUserDetails — AI 助手 WS 握手用:
     * JwtHandshakeHandler 已经在拦截器阶段拿到了 userId,无需再去解析 token。
     */
    public SecurityUserDetails loadSecurityUserById(Long userId) {
        if (userId == null) {
            throw new UsernameNotFoundException("userId is null");
        }
        SysUser u = userMapper.selectById(userId);
        if (u == null) {
            throw new UsernameNotFoundException("user not found: " + userId);
        }
        return (SecurityUserDetails) loadUserByUsername(u.getUsername());
    }
}
