package com.lab.reservation.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.dto.auth.LoginDTO;
import com.lab.reservation.dto.auth.RegisterDTO;
import com.lab.reservation.entity.SysRole;
import com.lab.reservation.entity.SysUser;
import com.lab.reservation.entity.SysUserRole;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.SysRoleMapper;
import com.lab.reservation.mapper.SysUserMapper;
import com.lab.reservation.mapper.SysUserRoleMapper;
import com.lab.reservation.security.CustomUserDetailsService;
import com.lab.reservation.security.JwtProperties;
import com.lab.reservation.security.JwtUtils;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.AuthService;
import com.lab.reservation.vo.auth.LoginVO;
import com.lab.reservation.vo.auth.UserInfoVO;
import io.jsonwebtoken.Claims;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class AuthServiceImpl implements AuthService {

    private final SysUserMapper userMapper;
    private final SysRoleMapper roleMapper;
    private final SysUserRoleMapper userRoleMapper;
    private final CustomUserDetailsService uds;
    private final PasswordEncoder passwordEncoder;
    private final JwtUtils jwt;
    private final JwtProperties jwtProperties;

    @Override
    public LoginVO login(LoginDTO dto) {
        SecurityUserDetails ud;
        try {
            ud = (SecurityUserDetails) uds.loadUserByUsername(dto.getUsername());
        } catch (Exception e) {
            throw new BusinessException(ResultCode.USERNAME_OR_PASSWORD_ERROR);
        }
        if (!passwordEncoder.matches(dto.getPassword(), ud.getPassword())) {
            throw new BusinessException(ResultCode.USERNAME_OR_PASSWORD_ERROR);
        }
        // 账号禁用判断：直接复用 SecurityUserDetails 的 enabled（已反映 status）
        if (!ud.isEnabled()) {
            throw new BusinessException(ResultCode.ACCOUNT_DISABLED);
        }

        List<String> auths = ud.getAuthorities().stream()
                .map(GrantedAuthority::getAuthority).collect(Collectors.toList());
        List<String> roleCodes = splitRoles(auths);
        List<String> permCodes = splitPermissions(auths);

        String accessToken = jwt.generateAccess(ud.getUserId(), ud.getUsername(), roleCodes);
        String refreshToken = jwt.generateRefresh(ud.getUserId(), ud.getUsername());

        LoginVO vo = new LoginVO();
        vo.setAccessToken(accessToken);
        vo.setRefreshToken(refreshToken);
        vo.setExpiresIn(jwtProperties.getAccessTtl());
        UserInfoVO info = new UserInfoVO();
        info.setId(ud.getUserId());
        info.setUsername(ud.getUsername());
        info.setRealName(ud.getRealName());
        info.setRoles(roleCodes);
        info.setPermissions(permCodes);
        vo.setUserInfo(info);
        return vo;
    }

    @Override
    @Transactional
    public void register(RegisterDTO dto) {
        boolean exists = userMapper.exists(
                new LambdaQueryWrapper<SysUser>().eq(SysUser::getUsername, dto.getUsername()));
        if (exists) {
            throw new BusinessException(ResultCode.USERNAME_EXISTS);
        }
        SysUser u = new SysUser();
        u.setUsername(dto.getUsername());
        u.setPassword(passwordEncoder.encode(dto.getPassword()));
        u.setRealName(dto.getRealName());
        u.setPhone(dto.getPhone());
        u.setUserType(dto.getUserType() == null ? "STUDENT" : dto.getUserType());
        u.setStatus(1);
        userMapper.insert(u);

        // 绑定 STUDENT 角色
        SysRole studentRole = roleMapper.selectOne(
                new LambdaQueryWrapper<SysRole>().eq(SysRole::getRoleCode, "STUDENT"));
        if (studentRole != null) {
            SysUserRole ur = new SysUserRole();
            ur.setUserId(u.getId());
            ur.setRoleId(studentRole.getId());
            userRoleMapper.insert(ur);
        }
    }

    @Override
    public String refresh(String refreshToken) {
        Claims c = jwt.parse(refreshToken);
        if (c == null || !"refresh".equals(c.get("type"))) {
            throw new BusinessException(ResultCode.UNAUTHORIZED);
        }
        Long userId = Long.valueOf(c.getSubject());
        String username = String.valueOf(c.get("username"));
        // refresh token 不含 roles claim，从 DB 重查
        List<String> roleCodes = loadRoleCodes(userId);
        return jwt.generateAccess(userId, username, roleCodes);
    }

    @Override
    public void logout(String token) {
        // 无状态 JWT：客户端丢弃 token 即可，服务端不维护黑名单
    }

    private static List<String> splitRoles(List<String> auths) {
        return auths.stream()
                .filter(a -> a.startsWith("ROLE_"))
                .map(a -> a.substring(5))
                .collect(Collectors.toList());
    }

    private static List<String> splitPermissions(List<String> auths) {
        return auths.stream()
                .filter(a -> !a.startsWith("ROLE_"))
                .collect(Collectors.toList());
    }

    private List<String> loadRoleCodes(Long userId) {
        List<Long> roleIds = userRoleMapper.selectList(
                        new LambdaQueryWrapper<SysUserRole>().eq(SysUserRole::getUserId, userId))
                .stream().map(SysUserRole::getRoleId).collect(Collectors.toList());
        if (roleIds.isEmpty()) {
            return List.of();
        }
        return roleMapper.selectBatchIds(roleIds).stream()
                .map(SysRole::getRoleCode).collect(Collectors.toList());
    }
}
