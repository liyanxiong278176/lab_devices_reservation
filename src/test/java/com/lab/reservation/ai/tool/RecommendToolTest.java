package com.lab.reservation.ai.tool;

import com.lab.reservation.ai.dto.ToolExecutionResult;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.RecommendationService;
import com.lab.reservation.vo.recommendation.RecommendationItemVO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class RecommendToolTest {

    private RecommendationService recommendationService;
    private ToolArgumentValidator validator;
    private RecommendTool recommendTool;

    @BeforeEach
    void setUp() {
        recommendationService = mock(RecommendationService.class);
        validator = new ToolArgumentValidator();
        recommendTool = new RecommendTool(recommendationService, validator);

        try {
            validator.register("RecommendTool.recommendDevices",
                    RecommendTool.class.getDeclaredMethod("recommendDevices", Integer.class));
        } catch (NoSuchMethodException e) {
            throw new RuntimeException(e);
        }

        SecurityUserDetails user = new SecurityUserDetails(
                7L, "bob", "password", true, "Bob",
                List.of("STUDENT"), List.of());
        var auth = new UsernamePasswordAuthenticationToken(user, "password", user.getAuthorities());
        SecurityContextHolder.getContext().setAuthentication(auth);
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void recommendDevices_calls_service() {
        // given
        List<RecommendationItemVO> recs = new ArrayList<>();
        RecommendationItemVO r1 = new RecommendationItemVO();
        r1.setDeviceId(101L);
        r1.setName("光谱仪");
        r1.setScore(0.92);
        recs.add(r1);
        when(recommendationService.recommend(eq(7L), anyInt())).thenReturn(recs);

        // when
        ToolExecutionResult result = recommendTool.recommendDevices(5);

        // then
        assertThat(result.isOk()).isTrue();
        assertThat(result.getData()).isInstanceOf(List.class);
        @SuppressWarnings("unchecked")
        List<RecommendationItemVO> data = (List<RecommendationItemVO>) result.getData();
        assertThat(data).hasSize(1);
        assertThat(data.get(0).getName()).isEqualTo("光谱仪");

        ArgumentCaptor<Long> userCaptor = ArgumentCaptor.forClass(Long.class);
        ArgumentCaptor<Integer> topCaptor = ArgumentCaptor.forClass(Integer.class);
        verify(recommendationService).recommend(userCaptor.capture(), topCaptor.capture());
        assertThat(userCaptor.getValue()).isEqualTo(7L);
        assertThat(topCaptor.getValue()).isEqualTo(5);
    }

    @Test
    void recommendDevices_non_positive_topN_throws_via_validator() {
        org.junit.jupiter.api.Assertions.assertThrows(
                com.lab.reservation.ai.exception.ToolArgumentException.class,
                () -> recommendTool.recommendDevices(0));
    }

    @Test
    void recommendDevices_no_security_context_throws() {
        SecurityContextHolder.clearContext();
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalStateException.class,
                () -> recommendTool.recommendDevices(5));
    }
}
