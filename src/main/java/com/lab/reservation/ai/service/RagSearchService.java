package com.lab.reservation.ai.service;

import com.lab.reservation.ai.config.AiProperties;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * RAG 检索服务 — 在 Chroma collection 中按相似度召回 top-K 文档。
 *
 * <p>top-K / 相似度阈值都从 {@link AiProperties#getRag()} 取,方便运维改 yml
 * 调参,不用动代码。
 *
 * <p>{@code deviceId} 非空时附加 Chroma 过滤表达式 {@code device_id == <id>},
 * 让单设备的咨询能精确召回该设备专属手册片段。
 *
 * <p>Phase B 将把本服务暴露成 LLM function-calling 工具 {@code search_device_manuals}。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Service
@RequiredArgsConstructor
@ConditionalOnProperty(name = "spring.ai.vectorstore.type", havingValue = "chroma", matchIfMissing = true)
public class RagSearchService {

    private final VectorStore vectorStore;
    private final AiProperties props;

    /**
     * @param query    用户原始问题(后续 Phase B 可经 query-rewrite 优化)
     * @param deviceId 限定召回某设备的手册片段;为 null 则跨设备召回
     * @return 按相似度降序的 chunk 列表
     */
    public List<Document> search(String query, Long deviceId) {
        SearchRequest.Builder builder = SearchRequest.builder()
                .query(query)
                .topK(props.getRag().getTopK())
                .similarityThreshold(props.getRag().getSimilarityThreshold());
        if (deviceId != null) {
            builder = builder.filterExpression("device_id == " + deviceId);
        }
        List<Document> hits = vectorStore.similaritySearch(builder.build());
        log.debug("RAG search query='{}' deviceId={} hits={}", query, deviceId, hits.size());
        return hits;
    }
}
