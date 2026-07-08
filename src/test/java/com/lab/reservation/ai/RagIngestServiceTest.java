package com.lab.reservation.ai;

import com.lab.reservation.ai.service.RagIngestService;
import org.junit.jupiter.api.Test;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.VectorStore;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class RagIngestServiceTest {

    @Test
    void split_returns_chunks_with_metadata() {
        VectorStore vs = mock(VectorStore.class);
        RagIngestService svc = new RagIngestService(vs);
        String text = "段落1\n\n段落2 较短的。\n\n段落3".repeat(50);

        List<Document> chunks = svc.splitIntoChunks(text, "manual-facsaria-001", 5L);

        assertThat(chunks).isNotEmpty();
        chunks.forEach(c -> {
            assertThat(c.getMetadata()).containsKey("doc_id");
            assertThat(c.getMetadata()).containsKey("device_id");
            assertThat(c.getMetadata()).containsKey("chunk_index");
        });
    }

    @Test
    void ingest_writes_to_vector_store() {
        VectorStore vs = mock(VectorStore.class);
        RagIngestService svc = new RagIngestService(vs);

        svc.ingest("manual-001", "测试内容", 5L);

        verify(vs).add(any(List.class));
    }
}
