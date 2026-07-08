package com.lab.reservation.ai.tool;

import com.lab.reservation.ai.dto.ToolExecutionResult;
import com.lab.reservation.ai.service.RagSearchService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.ai.document.Document;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class RagManualToolTest {

    private RagSearchService ragSearchService;
    private RagManualTool ragManualTool;

    @BeforeEach
    void setUp() {
        ragSearchService = mock(RagSearchService.class);
        ragManualTool = new RagManualTool(ragSearchService);
    }

    @Test
    void searchDeviceManuals_calls_rag_service() {
        // given
        Document d1 = new Document("这是一段手册文本",
                Map.of("device_id", "12", "doc_type", "manual"));
        Document d2 = new Document("另一段",
                Map.of("device_id", "12", "doc_type", "faq"));
        List<Document> hits = new ArrayList<>();
        hits.add(d1);
        hits.add(d2);
        when(ragSearchService.search(eq("怎么校准"), eq(12L))).thenReturn(hits);

        // when
        ToolExecutionResult result = ragManualTool.searchDeviceManuals("怎么校准", 12L);

        // then
        assertThat(result.isOk()).isTrue();
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> data = (List<Map<String, Object>>) result.getData();
        assertThat(data).hasSize(2);
        assertThat(data.get(0).get("text")).isEqualTo("这是一段手册文本");
        assertThat((Map<String, Object>) data.get(0).get("metadata"))
                .containsEntry("device_id", "12");

        ArgumentCaptor<String> qCap = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Long> dCap = ArgumentCaptor.forClass(Long.class);
        verify(ragSearchService).search(qCap.capture(), dCap.capture());
        assertThat(qCap.getValue()).isEqualTo("怎么校准");
        assertThat(dCap.getValue()).isEqualTo(12L);
    }

    @Test
    void searchDeviceManuals_null_deviceId_passes_through() {
        when(ragSearchService.search(eq("faq"), eq(null))).thenReturn(new ArrayList<>());

        ToolExecutionResult r = ragManualTool.searchDeviceManuals("faq", null);
        assertThat(r.isOk()).isTrue();
        verify(ragSearchService).search("faq", null);
    }

    @Test
    void searchDeviceManuals_empty_query_returns_fail_envelope() {
        ToolExecutionResult r = ragManualTool.searchDeviceManuals("  ", 1L);
        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo("PARAM_INVALID");
    }

    @Test
    void searchDeviceManuals_rag_failure_returns_fail_envelope() {
        when(ragSearchService.search(eq("x"), eq(null)))
                .thenThrow(new RuntimeException("Chroma unreachable"));

        ToolExecutionResult r = ragManualTool.searchDeviceManuals("x", null);
        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo("RAG_UNAVAILABLE");
        assertThat(r.getMsg()).contains("Chroma unreachable");
    }
}
