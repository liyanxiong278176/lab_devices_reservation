package edu.labflow;

import static org.assertj.core.api.Assertions.*;

import java.time.LocalDate;
import java.util.*;
import org.junit.jupiter.api.Test;

class ReservationPlanTest {
  private final LocalDate day = LocalDate.of(2026, 10, 13);

  private ReservationPlan plan(
      Long device,
      Long pool,
      int qty,
      LocalDate start,
      LocalDate end,
      List<LocalDate> dates,
      List<ReservationPlan.Window> windows) {
    return new ReservationPlan(
        device, pool, null, qty, "实验用途", null, null, start, end, dates, windows, null);
  }

  @Test
  void includesBothRangeBoundariesAndKeepsRepeatedSegmentsSeparate() {
    assertThat(plan(1L, null, 1, day, day.plusDays(2), null, null).requestedDates())
        .containsExactly(day, day.plusDays(1), day.plusDays(2));
    assertThat(plan(1L, null, 1, null, null, List.of(day.plusDays(1), day), null).segments())
        .containsExactly(List.of(day), List.of(day.plusDays(1)));
  }

  @Test
  void rejectsOverlappingWindowsAndMoreThan31Days() {
    assertThatThrownBy(
            () ->
                plan(
                    1L,
                    null,
                    1,
                    null,
                    null,
                    null,
                    List.of(
                        new ReservationPlan.Window(day, day.plusDays(2)),
                        new ReservationPlan.Window(day.plusDays(2), day.plusDays(3)))))
        .isInstanceOf(ApiError.class);
    assertThatThrownBy(() -> plan(1L, null, 1, day, day.plusDays(31), null, null))
        .isInstanceOf(ApiError.class);
  }

  @Test
  void requiresPoolForMultipleUnitsAndExactlyOneTarget() {
    assertThatThrownBy(() -> plan(1L, null, 2, day, day, null, null)).isInstanceOf(ApiError.class);
    assertThatThrownBy(() -> plan(1L, 2L, 1, day, day, null, null)).isInstanceOf(ApiError.class);
    assertThat(plan(null, 2L, 2, day, day, null, null).quantity()).isEqualTo(2);
  }

  @Test
  void paginationUsesLongArithmeticAndCapsAccessibleDepth() {
    assertThatThrownBy(() -> new Pagination(Integer.MAX_VALUE, 100)).isInstanceOf(ApiError.class);
    assertThat(new Pagination(1001, 100).offset()).isEqualTo(100000);
    assertThat(new Pagination(1, 100).result(List.of(), 200000))
        .containsEntry("pages", 1001L)
        .containsEntry("truncated", true);
  }

  @Test
  void dayEndUsesShanghaiDayStoredAsUtc() {
    assertThat(BusinessTime.dayEnd(day).toLocalDate()).isEqualTo(day);
    assertThat(BusinessTime.dayEnd(day).getHour()).isEqualTo(15);
  }
}
