package com.lab.reservation.ai.service;

import com.lab.reservation.ai.config.AiProperties;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentMatcher;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;

import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class RagSearchServiceTest {

    @Test
    void search_passes_threshold_and_topk() {
        VectorStore vs = mock(VectorStore.class);
        when(vs.similaritySearch(argThat(anySearchRequest())))
                .thenReturn(java.util.List.of());
        AiProperties props = new AiProperties();
        RagSearchService svc = new RagSearchService(vs, props);

        svc.search("怎么开机", null);

        verify(vs).similaritySearch(argThat(topKAndThreshold(5, 0.6)));
    }

    @Test
    void search_with_device_id_sets_filter_expression() {
        VectorStore vs = mock(VectorStore.class);
        when(vs.similaritySearch(argThat(anySearchRequest())))
                .thenReturn(java.util.List.of());
        AiProperties props = new AiProperties();
        RagSearchService svc = new RagSearchService(vs, props);

        svc.search("怎么开机", 5L);

        verify(vs).similaritySearch(argThat(topKThresholdAndFilter()));
    }

    /** 任意 SearchRequest 匹配器 — 用于 stubbing。 */
    private static ArgumentMatcher<SearchRequest> anySearchRequest() {
        return req -> true;
    }

    private static ArgumentMatcher<SearchRequest> topKAndThreshold(int topK, double threshold) {
        return req -> req.getTopK() == topK
                && Double.compare(req.getSimilarityThreshold(), threshold) == 0;
    }

    private static ArgumentMatcher<SearchRequest> topKThresholdAndFilter() {
        return req -> req.getTopK() == 5
                && Double.compare(req.getSimilarityThreshold(), 0.6) == 0
                && req.hasFilterExpression();
    }
}