package com.lab.reservation.ai.service;

import com.lab.reservation.security.SecurityUserDetails;
import org.springframework.ai.tool.ToolCallback;

import java.util.Map;

/** 测试缝:user → name→ToolCallback 解析。真 impl 用 ToolRegistry + MethodToolCallbackProvider。 */
public interface ToolCallbackResolver {
    Map<String, ToolCallback> resolve(SecurityUserDetails user);
}
