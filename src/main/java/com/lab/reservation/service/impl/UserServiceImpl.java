package com.lab.reservation.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.dto.user.UserCreateDTO;
import com.lab.reservation.dto.user.UserQueryDTO;
import com.lab.reservation.entity.SysRole;
import com.lab.reservation.entity.SysUser;
import com.lab.reservation.entity.SysUserRole;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.SysRoleMapper;
import com.lab.reservation.mapper.SysUserMapper;
import com.lab.reservation.mapper.SysUserRoleMapper;
import com.lab.reservation.service.UserService;
import com.lab.reservation.vo.user.UserVO;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.BeanUtils;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 用户管理服务（仅 SYS_ADMIN 通过 user:manage 权限调用）。
 *
 * 关键安全约束：
 * - UserVO 永不返回 password（toVO 不拷贝该字段）。
 * - delete 禁止删除当前登录用户自身。
 * - create/update 角色绑定采用先删后插，事务保证一致。
 */
@Service
@RequiredArgsConstructor
public class UserServiceImpl implements UserService {

    private final SysUserMapper userMapper;
    private final SysRoleMapper roleMapper;
    private final SysUserRoleMapper userRoleMapper;
    private final PasswordEncoder passwordEncoder;

    @Override
    public IPage<UserVO> list(UserQueryDTO q) {
        LambdaQueryWrapper<SysUser> wrapper = new LambdaQueryWrapper<>();
        if (q.getUsername() != null && !q.getUsername().isBlank()) {
            wrapper.like(SysUser::getUsername, q.getUsername());
        }
        if (q.getRealName() != null && !q.getRealName().isBlank()) {
            wrapper.like(SysUser::getRealName, q.getRealName());
        }
        if (q.getStatus() != null) {
            wrapper.eq(SysUser::getStatus, q.getStatus());
        }
        wrapper.orderByDesc(SysUser::getId);

        Page<SysUser> page = userMapper.selectPage(new Page<>(q.getPage(), q.getSize()), wrapper);
        // 批量预加载本页所有用户的 roleCodes，避免 N+1
        List<Long> pageUserIds = page.getRecords().stream().map(SysUser::getId).toList();
        Map<Long, List<String>> rolesByUser = loadRoleCodes(pageUserIds);
        return page.convert(u -> toVO(u, rolesByUser.getOrDefault(u.getId(), Collections.emptyList())));
    }

    @Override
    @Transactional
    public UserVO create(UserCreateDTO dto) {
        boolean exists = userMapper.exists(
                new LambdaQueryWrapper<SysUser>().eq(SysUser::getUsername, dto.getUsername()));
        if (exists) {
            throw new BusinessException(ResultCode.USERNAME_EXISTS);
        }
        if (dto.getPassword() == null || dto.getPassword().isBlank()) {
            throw new BusinessException(ResultCode.PARAM_INVALID.getCode(), "密码不能为空");
        }
        SysUser u = new SysUser();
        u.setUsername(dto.getUsername());
        u.setPassword(passwordEncoder.encode(dto.getPassword()));
        u.setRealName(dto.getRealName());
        u.setPhone(dto.getPhone());
        u.setEmail(dto.getEmail());
        u.setUserType(dto.getUserType() == null ? "STUDENT" : dto.getUserType());
        u.setDeptName(dto.getDeptName());
        u.setStatus(1);
        userMapper.insert(u);
        rebindRoles(u.getId(), dto.getRoleCodes());
        SysUser saved = userMapper.selectById(u.getId());
        List<String> roles = dto.getRoleCodes() == null ? Collections.emptyList() : dto.getRoleCodes();
        return toVO(saved, roles);
    }

    @Override
    @Transactional
    public UserVO update(Long id, UserCreateDTO dto) {
        SysUser exist = userMapper.selectById(id);
        if (exist == null) {
            throw new BusinessException(ResultCode.NOT_FOUND);
        }
        // 仅允许更新以下字段；username 不可改
        exist.setRealName(dto.getRealName());
        exist.setPhone(dto.getPhone());
        exist.setEmail(dto.getEmail());
        exist.setDeptName(dto.getDeptName());
        if (dto.getUserType() != null) {
            exist.setUserType(dto.getUserType());
        }
        if (dto.getPassword() != null && !dto.getPassword().isBlank()) {
            exist.setPassword(passwordEncoder.encode(dto.getPassword()));
        }
        userMapper.updateById(exist);
        // roleCodes==null 表示不改角色（避免误清空用户角色）；传空列表=清空；传非空=重绑
        List<String> rolesResult;
        if (dto.getRoleCodes() != null) {
            rebindRoles(id, dto.getRoleCodes());
            rolesResult = dto.getRoleCodes();
        } else {
            rolesResult = loadRoleCodes(List.of(id)).getOrDefault(id, Collections.emptyList());
        }
        SysUser saved = userMapper.selectById(id);
        return toVO(saved, rolesResult);
    }

    @Override
    @Transactional
    public void delete(Long id, Long currentUserId) {
        if (id != null && id.equals(currentUserId)) {
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
        SysUser exist = userMapper.selectById(id);
        if (exist == null) {
            throw new BusinessException(ResultCode.NOT_FOUND);
        }
        userMapper.deleteById(id);
        userRoleMapper.delete(new LambdaQueryWrapper<SysUserRole>().eq(SysUserRole::getUserId, id));
    }

    @Override
    public void updateStatus(Long id, Integer status) {
        if (status == null || (status != 0 && status != 1)) {
            throw new BusinessException(ResultCode.PARAM_INVALID);
        }
        SysUser exist = userMapper.selectById(id);
        if (exist == null) {
            throw new BusinessException(ResultCode.NOT_FOUND);
        }
        exist.setStatus(status);
        userMapper.updateById(exist);
    }

    // ---- helpers ----

    /**
     * 重绑角色：先删该用户所有旧绑定，再按 roleCodes 解析角色 id 插入新绑定。
     * roleCodes 为空时表示清空角色。未识别的 roleCode 抛 PARAM_INVALID。
     */
    private void rebindRoles(Long userId, List<String> roleCodes) {
        userRoleMapper.delete(new LambdaQueryWrapper<SysUserRole>().eq(SysUserRole::getUserId, userId));
        if (roleCodes == null || roleCodes.isEmpty()) {
            return;
        }
        List<SysRole> roles = roleMapper.selectList(
                new LambdaQueryWrapper<SysRole>().in(SysRole::getRoleCode, roleCodes));
        if (roles.size() != roleCodes.size()) {
            Set<String> found = roles.stream().map(SysRole::getRoleCode).collect(Collectors.toSet());
            List<String> unknown = roleCodes.stream().filter(c -> !found.contains(c)).toList();
            throw new BusinessException(ResultCode.PARAM_INVALID.getCode(),
                    "未知角色编码: " + String.join(",", unknown));
        }
        for (SysRole r : roles) {
            SysUserRole ur = new SysUserRole();
            ur.setUserId(userId);
            ur.setRoleId(r.getId());
            userRoleMapper.insert(ur);
        }
    }

    /**
     * 用户转 VO。roles 由调用方预加载（避免 N+1）。
     * 注意：BeanUtils.copyProperties 只拷贝 UserVO 中存在的字段，
     * UserVO 不含 password，故 password 永不外泄。
     */
    private UserVO toVO(SysUser u, List<String> roles) {
        UserVO vo = new UserVO();
        BeanUtils.copyProperties(u, vo);
        vo.setRoles(roles);
        return vo;
    }

    /**
     * 批量加载多个用户的 roleCodes，避免列表场景下的 N+1。
     * 返回 userId -> List<roleCode> 映射（一个用户可有多角色）。
     */
    private Map<Long, List<String>> loadRoleCodes(List<Long> userIds) {
        if (userIds == null || userIds.isEmpty()) {
            return Collections.emptyMap();
        }
        List<SysUserRole> urs = userRoleMapper.selectList(
                new LambdaQueryWrapper<SysUserRole>().in(SysUserRole::getUserId, userIds));
        if (urs.isEmpty()) {
            return Collections.emptyMap();
        }
        List<Long> roleIds = urs.stream().map(SysUserRole::getRoleId).distinct().toList();
        Map<Long, String> codeById = roleMapper.selectBatchIds(roleIds).stream()
                .collect(Collectors.toMap(SysRole::getId, SysRole::getRoleCode, (a, b) -> a));
        Map<Long, List<String>> result = new java.util.HashMap<>();
        for (SysUserRole ur : urs) {
            String code = codeById.get(ur.getRoleId());
            if (code != null) {
                result.computeIfAbsent(ur.getUserId(), k -> new ArrayList<>()).add(code);
            }
        }
        return result;
    }
}
