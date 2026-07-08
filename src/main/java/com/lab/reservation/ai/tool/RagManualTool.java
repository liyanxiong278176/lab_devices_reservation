package com.lab.reservation.ai.tool;

import com.lab.reservation.ai.dto.ToolExecutionResult;
import com.lab.reservation.ai.service.RagSearchService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.document.Document;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 设备手册 / FAQ 检索的 AI 工具（RAG）。
 *
 * <p>把 {@link RagSearchService#search(String, Long)} 暴露成 LLM 可调用的工具。
 * Spring AI 1.0.6 的 {@code Document} 直接序列化进 data 对 LLM 不友好（getText/getMetadata
 * 都是 getter,Jackson 需要额外配置），这里把它映射成 {@code Map<String,Object>}
 * 形态: {@code text / metadata}。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class RagManualTool {

    private final RagSearchService ragSearchService;

    @Tool(name = "searchDeviceManuals",
          description = "用自然语言问题在设备手册/FAQ 中检索相关片段(RAG)。"
                  + "deviceId 非空时只在该设备手册中检索;为空则跨设备检索。"
                  + "返回 top-K 片段,每条带 text + metadata。{roles:STUDENT,LAB_ADMIN,SYS_ADMIN}")
    public ToolExecutionResult searchDeviceManuals(
            @ToolParam(description = "检索问题(自然语言)") String query,
            @ToolParam(description = "限定设备 ID(可空)") Long deviceId) {

        // query 必填且非空;deviceId 可空(走跨设备检索)
        if (query == null || query.isBlank()) {
            return ToolExecutionResult.fail("PARAM_INVALID", "query 不能为空");
        }

        try {
            List<Document> hits = ragSearchService.search(query, deviceId);
            List<Map<String, Object>> out = new ArrayList<>(hits == null ? 0 : hits.size());
            if (hits != null) {
                for (Document d : hits) {
                    if (d == null) continue;
                    Map<String, Object> row = new HashMap<>();
                    row.put("text", d.getText());
                    row.put("metadata", d.getMetadata() == null ? Map.of() : d.getMetadata());
                    // Document.getScore() 在不同实现里可能为 null,安全取
                    Double score = d.getScore();
                    if (score != null) {
                        row.put("score", score);
                    }
                    out.add(row);
                }
            }
            log.info("searchDeviceManuals query='{}' deviceId={} hits={}",
                    query, deviceId, out.size());
            return ToolExecutionResult.ok(out);
        } catch (RuntimeException e) {
            // RAG 失败（Chroma 不可达等）不应让整个 LLM 流程炸 — 转成 fail
            log.warn("searchDeviceManuals failed: {}", e.getMessage());
            return ToolExecutionResult.fail("RAG_UNAVAILABLE", "知识库检索失败: " + e.getMessage());
        }
    }
}
