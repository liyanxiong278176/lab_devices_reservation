package com.lab.reservation.ai.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.document.Document;
import org.springframework.ai.transformer.splitter.TokenTextSplitter;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.IntStream;

/**
 * RAG 摄入服务 — 把设备手册 / FAQ 切块后写入 Chroma。
 *
 * <p>Spring AI 1.0.6 的 {@code VectorStore} bean(由 {@code spring-ai-starter-vector-store-chroma}
 * 自动装配)已经绑死了 collection name = {@code lab_manuals},所以这里不需要
 * 显式指定 collection。
 *
 * <p>切块策略:500 token / 块、最小 350 字符、最小可嵌入长度 5。
 * 元数据: doc_id / doc_type / device_id / chunk_index / chunk_total / ingested_at。
 *
 * <p>重建 collection(切 embedding 模型时)需要直接走 ChromaApi,
 * 不属于本任务范围,见后续 Phase。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RagIngestService {

    private final VectorStore vectorStore;
    /**
     * {@code splitter} 在声明处初始化 — Lombok 的 {@code @RequiredArgsConstructor}
     * 不会把它纳入必填构造器,生成的构造器只有 {@code vectorStore} 一个参数,
     * 这也是单测能 {@code new RagIngestService(vs)} 直接构造的原因。
     */
    private final TokenTextSplitter splitter = TokenTextSplitter.builder()
            .withChunkSize(500)
            .withMinChunkSizeChars(350)
            .withMinChunkLengthToEmbed(5)
            .build();

    /** 切块(不写库,纯逻辑测试用)。返回的每个 Document 都带 6 个元数据字段。 */
    public List<Document> splitIntoChunks(String text, String docId, Long deviceId) {
        List<Document> raw = splitter.split(new Document(text));
        int total = raw.size();
        return IntStream.range(0, total)
                .mapToObj(i -> {
                    Document d = raw.get(i);
                    Map<String, Object> meta = new HashMap<>();
                    meta.put("doc_id", docId);
                    meta.put("doc_type", "manual");
                    meta.put("device_id", deviceId);
                    meta.put("ingested_at", Instant.now().toString());
                    meta.put("chunk_index", i);
                    meta.put("chunk_total", total);
                    return new Document(d.getText(), meta);
                })
                .toList();
    }

    /** 摄入一段文本(管理员调用)。返回写入的 chunk 数。 */
    public int ingest(String docId, String text, Long deviceId) {
        List<Document> chunks = splitIntoChunks(text, docId, deviceId);
        vectorStore.add(chunks);
        log.info("ingested doc={} device={} chunks={}", docId, deviceId, chunks.size());
        return chunks.size();
    }
}
