package com.lab.reservation.init;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.lab.reservation.entity.SysRole;
import com.lab.reservation.entity.SysUser;
import com.lab.reservation.entity.SysUserRole;
import com.lab.reservation.mapper.SysRoleMapper;
import com.lab.reservation.mapper.SysUserMapper;
import com.lab.reservation.mapper.SysUserRoleMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.password.PasswordEncoder;

/**
 * 启动时种子默认管理员账号 admin / admin123（绑定 SYS_ADMIN 角色）。
 * 已存在则跳过。
 */
@Configuration
@RequiredArgsConstructor
public class DataInitializer {

    @Bean
    ApplicationRunner seedAdmin(SysUserMapper userMapper, SysRoleMapper roleMapper,
                                SysUserRoleMapper urMapper, PasswordEncoder encoder) {
        return args -> {
            if (userMapper.exists(new LambdaQueryWrapper<SysUser>()
                    .eq(SysUser::getUsername, "admin"))) {
                return;
            }
            SysUser admin = new SysUser();
            admin.setUsername("admin");
            admin.setPassword(encoder.encode("admin123"));
            admin.setRealName("超级管理员");
            admin.setUserType("STAFF");
            admin.setStatus(1);
            userMapper.insert(admin);

            SysRole sysRole = roleMapper.selectOne(new LambdaQueryWrapper<SysRole>()
                    .eq(SysRole::getRoleCode, "SYS_ADMIN"));
            if (sysRole != null) {
                SysUserRole ur = new SysUserRole();
                ur.setUserId(admin.getId());
                ur.setRoleId(sysRole.getId());
                urMapper.insert(ur);
            }
        };
    }
}
