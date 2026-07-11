package com.lab.reservation.ai.service;

import com.lab.reservation.security.SecurityUserDetails;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.method.MethodToolCallbackProvider;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class ToolCallbackResolverImpl implements ToolCallbackResolver {

    private final ToolRegistry registry;

    @Override
    public Map<String, ToolCallback> resolve(SecurityUserDetails user) {
        Object[] beans = registry.availableFor(user).stream()
                .map(ToolRegistry.ToolDefinition::bean).distinct().toArray();
        ToolCallback[] arr = MethodToolCallbackProvider.builder()
                .toolObjects(beans).build().getToolCallbacks();
        Map<String, ToolCallback> map = new LinkedHashMap<>();
        for (ToolCallback cb : arr) {
            map.put(cb.getToolDefinition().name(), cb);
        }
        return map;
    }
}
