package com.lab.reservation.service;

import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.exception.BusinessException;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class SlotCalculatorServiceTest {
    private final SlotCalculatorService calc = new SlotCalculatorService(15, java.time.LocalTime.of(8, 0), java.time.LocalTime.of(22, 0));

    @Test
    void single_slot_aligned() {
        var items = calc.compute(1L, LocalDateTime.of(2026, 7, 1, 8, 0), LocalDateTime.of(2026, 7, 1, 8, 15));
        assertEquals(1, items.size());
        assertEquals(0, items.get(0).slotIndex());
        assertEquals(LocalDate.of(2026, 7, 1), items.get(0).date());
    }

    @Test
    void multi_slot_same_day() {
        var items = calc.compute(1L, LocalDateTime.of(2026, 7, 1, 9, 0), LocalDateTime.of(2026, 7, 1, 10, 30));
        assertEquals(6, items.size());
        assertEquals(4, items.get(0).slotIndex());
    }

    @Test
    void not_aligned_throws() {
        BusinessException e = assertThrows(BusinessException.class, () ->
            calc.compute(1L, LocalDateTime.of(2026, 7, 1, 9, 7), LocalDateTime.of(2026, 7, 1, 10, 0)));
        assertEquals(ResultCode.SLOT_NOT_ALIGNED.getCode(), e.getCode());
    }

    @Test
    void out_of_window_before_throws() {
        BusinessException e = assertThrows(BusinessException.class, () ->
            calc.compute(1L, LocalDateTime.of(2026, 7, 1, 7, 0), LocalDateTime.of(2026, 7, 1, 8, 15)));
        assertEquals(ResultCode.SLOT_OUT_OF_WORK_WINDOW.getCode(), e.getCode());
    }

    @Test
    void out_of_window_after_throws() {
        assertThrows(BusinessException.class, () ->
            calc.compute(1L, LocalDateTime.of(2026, 7, 1, 21, 45), LocalDateTime.of(2026, 7, 1, 22, 15)));
    }

    @Test
    void start_equals_end_throws() {
        assertThrows(BusinessException.class, () ->
            calc.compute(1L, LocalDateTime.of(2026, 7, 1, 9, 0), LocalDateTime.of(2026, 7, 1, 9, 0)));
    }

    @Test
    void cross_day_spans_two_dates() {
        var items = calc.compute(1L, LocalDateTime.of(2026, 7, 1, 21, 45), LocalDateTime.of(2026, 7, 2, 9, 0));
        assertTrue(items.stream().anyMatch(i -> i.date().equals(LocalDate.of(2026, 7, 1)) && i.slotIndex() == 55));
        List<Integer> nextDay = items.stream().filter(i -> i.date().equals(LocalDate.of(2026, 7, 2)))
            .map(SlotKey::slotIndex).toList();
        assertEquals(List.of(0, 1, 2, 3), nextDay);
    }

    @Test
    void cross_three_days() {
        var items = calc.compute(1L, LocalDateTime.of(2026, 7, 1, 21, 0), LocalDateTime.of(2026, 7, 3, 9, 0));
        assertFalse(items.isEmpty());
        assertEquals(3, items.stream().map(SlotKey::date).distinct().count());
        // 首日 21:00-22:00 => slot 52..55
        List<Integer> firstDay = items.stream().filter(i -> i.date().equals(LocalDate.of(2026, 7, 1)))
            .map(SlotKey::slotIndex).toList();
        assertEquals(List.of(52, 53, 54, 55), firstDay);
        // 中间日 08:00-22:00 => slot 0..55 全天 56 槽
        List<Integer> midDay = items.stream().filter(i -> i.date().equals(LocalDate.of(2026, 7, 2)))
            .map(SlotKey::slotIndex).toList();
        assertEquals(56, midDay.size());
        assertEquals(0, midDay.get(0));
        assertEquals(55, midDay.get(55));
        // 末日 08:00-09:00 => slot 0..3
        List<Integer> lastDay = items.stream().filter(i -> i.date().equals(LocalDate.of(2026, 7, 3)))
            .map(SlotKey::slotIndex).toList();
        assertEquals(List.of(0, 1, 2, 3), lastDay);
    }

    @Test
    void full_work_window_boundary() {
        var items = calc.compute(1L, LocalDateTime.of(2026, 7, 1, 8, 0), LocalDateTime.of(2026, 7, 1, 22, 0));
        assertEquals(56, items.size());
        assertEquals(0, items.get(0).slotIndex());
        assertEquals(55, items.get(55).slotIndex());
    }
}
