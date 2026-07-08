package com.lab.reservation.ai;

import com.lab.reservation.ai.service.RagIngestService;
import com.lab.reservation.aspect.Log;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * RAG 摄入入口(管理员)。
 *
 * <p>Phase A 完成后可由配置管理界面接管;现实生产中应由异步消息 +
 * 上传文件批处理替代手写文本提交,本端点仅做最小可行的人工兜底。
 *
 * <p>权限:仅 {@code LAB_ADMIN} / {@code SYS_ADMIN} 可调;{@code @PreAuthorize}
 * 配合项目的 SecurityConfig 强制 401/403 JSON 响应(详见 CLAUDE.md §5)。
 *
 * <p>注意:REST 路径不带 {@code /api} 前缀 — 全局 {@code server.servlet.context-path=/api}
 * 会由容器自动拼上。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Tag(name = "AI 助手-管理")
@RestController
@RequestMapping("/admin/rag")
@RequiredArgsConstructor
@PreAuthorize("hasAnyRole('LAB_ADMIN','SYS_ADMIN')")
public class AdminRagController {

    private final RagIngestService ingestService;

    /**
     * 摄入一段设备手册 / FAQ 文本到 Chroma collection {@code lab_manuals}。
     *
     * <p>请求体示例:
     * <pre>
     * {
     *   "doc_id":   "manual-facsaria-001",
     *   "device_id": 5,
     *   "text":     "..."
     * }
     * </pre>
     */
    @Operation(summary = "摄入设备手册")
    @Log("RAG 摄入")
    @PostMapping("/ingest")
    public Map<String, Object> ingest(@RequestBody Map<String, Object> req) {
        String docId = (String) req.get("doc_id");
        String text = (String) req.get("text");
        Long deviceId = ((Number) req.get("device_id")).longValue();
        int chunks = ingestService.ingest(docId, text, deviceId);
        return Map.of("ok", true, "chunks_ingested", chunks);
    }
}
