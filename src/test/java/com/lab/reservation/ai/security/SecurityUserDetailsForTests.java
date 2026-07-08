package com.lab.reservation.ai.security;

import com.lab.reservation.security.SecurityUserDetails;

import java.util.List;

/**
 * 测试用的 SecurityUserDetails 构造 helper,避免在每个测试里重复 7-arg 构造器。
 * 真实 SecurityUserDetails 是 7-arg:(Long userId, String username, String password,
 * boolean enabled, String realName, List&lt;String&gt; roles, List&lt;String&gt; perms)。
 *
 * <p>放在 src/test 里,不会进生产 jar。
 */
public final class SecurityUserDetailsForTests {

    private SecurityUserDetailsForTests() {}

    public static SecurityUserDetails student() {
        return new SecurityUserDetails(
                1L, "student1", "password",
                true, "学生1",
                List.of("STUDENT"),
                List.of()
        );
    }

    public static SecurityUserDetails labAdmin() {
        return new SecurityUserDetails(
                2L, "admin", "password",
                true, "管理员",
                List.of("LAB_ADMIN"),
                List.of()
        );
    }

    public static SecurityUserDetails sysAdmin() {
        return new SecurityUserDetails(
                3L, "sysadmin", "password",
                true, "系统管理员",
                List.of("SYS_ADMIN"),
                List.of("device:approve")
        );
    }
}
