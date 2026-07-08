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
    void split_returns_chunks_with_all_metadata() {
        VectorStore vs = mock(VectorStore.class);
        RagIngestService svc = new RagIngestService(vs);
        String text = "段落1\n\n段落2 较短的。\n\n段落3".repeat(50);

        List<Document> chunks = svc.splitIntoChunks(text, "manual-facsaria-001", 5L);

        assertThat(chunks).isNotEmpty();
        for (int i = 0; i < chunks.size(); i++) {
            Document c = chunks.get(i);
            assertThat(c.getMetadata()).containsKey("doc_id");
            assertThat(c.getMetadata()).containsKey("doc_type");
            assertThat(c.getMetadata()).containsKey("device_id");
            assertThat(c.getMetadata()).containsKey("ingested_at");
            assertThat(c.getMetadata()).containsKey("chunk_index");
            assertThat(c.getMetadata()).containsKey("chunk_total");
            assertThat(c.getMetadata().get("doc_id")).isEqualTo("manual-facsaria-001");
            assertThat(c.getMetadata().get("chunk_index")).isEqualTo(i);
        }
    }

    @Test
    void ingest_writes_chunks_to_vector_store() {
        VectorStore vs = mock(VectorStore.class);
        RagIngestService svc = new RagIngestService(vs);

        // Use text > withMinChunkLengthToEmbed(5) so splitter produces ≥1 chunk
        int chunks = svc.ingest("manual-001", "This is a complete device manual paragraph.", 5L);

        assertThat(chunks).isGreaterThan(0);
        verify(vs).add(any(List.class));
    }
}