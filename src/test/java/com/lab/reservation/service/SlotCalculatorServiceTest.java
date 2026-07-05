package com.lab.reservation.service;

import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.exception.BusinessException;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * SlotCalculatorService 单元测试。
 *
 * <p>随工作时段约束放宽(取消 08:00-22:00 工作时段窗口),slot 索引改为从当日 00:00 起算:
 * <ul>
 *   <li>每天 96 个 slot(15 分钟/格,从 00:00 开始,07:00 对应 slot 28,12:00 对应 slot 48,23:45 对应 slot 95);</li>
 *   <li>过去对应的 out_of_window_*_throws 测试已删除(不再有限制,前/后移窗口不再抛 SLOT_OUT_OF_WORK_WINDOW);</li>
 *   <li>slotIdx 期望值已重算反映 00:00 = 0 的偏移。</li>
 * </ul>
 */
class SlotCalculatorServiceTest {
    private final SlotCalculatorService calc = new SlotCalculatorService(15);

    @Test
    void single_slot_aligned_at_midnight() {
        var items = calc.compute(1L, LocalDateTime.of(2026, 7, 1, 0, 0), LocalDateTime.of(2026, 7, 1, 0, 15));
        assertEquals(1, items.size());
        assertEquals(0, items.get(0).slotIndex());
        assertEquals(LocalDate.of(2026, 7, 1), items.get(0).date());
    }

    @Test
    void single_slot_aligned_at_21() {
        // 21:00 = slot 84 (21 * 4 + 0)
        var items = calc.compute(1L, LocalDateTime.of(2026, 7, 1, 21, 0), LocalDateTime.of(2026, 7, 1, 21, 15));
        assertEquals(1, items.size());
        assertEquals(84, items.get(0).slotIndex());
    }

    @Test
    void multi_slot_same_day() {
        // 09:00-10:30 = 6 slots:9 * 4 = 36 .. (10*4+2) - 1 = 41
        var items = calc.compute(1L, LocalDateTime.of(2026, 7, 1, 9, 0), LocalDateTime.of(2026, 7, 1, 10, 30));
        assertEquals(6, items.size());
        assertEquals(36, items.get(0).slotIndex());
        assertEquals(41, items.get(5).slotIndex());
    }

    @Test
    void not_aligned_throws() {
        BusinessException e = assertThrows(BusinessException.class, () ->
            calc.compute(1L, LocalDateTime.of(2026, 7, 1, 9, 7), LocalDateTime.of(2026, 7, 1, 10, 0)));
        assertEquals(ResultCode.SLOT_NOT_ALIGNED.getCode(), e.getCode());
    }

    @Test
    void before_work_start_now_legal() {
        // 旧版本:07:00-08:15 抛 SLOT_OUT_OF_WORK_WINDOW;新版本:07:00 是合法的 15 分钟边界,正常运行
        // 07:00 = slot 28, 08:15 = slot 33,slot 数 = 33 - 28 = 5
        var items = calc.compute(1L, LocalDateTime.of(2026, 7, 1, 7, 0), LocalDateTime.of(2026, 7, 1, 8, 15));
        assertEquals(5, items.size());
        assertEquals(28, items.get(0).slotIndex());
    }

    @Test
    void after_work_end_now_legal() {
        // 旧版本:21:45-22:15 抛 SLOT_OUT_OF_WORK_WINDOW;新版本:21:45 起 22:15 止,5 个 slot(21:45 = slot 87..22:00 = slot 87 末尾 ⇒ 实际上 21:45 → 22:15 = slot 87,88,89,90,91 不对应该是 21:45 = (21*4+3) = 87,22:15 = (22*4+1) = 89,结束 slot 是开区间不包含,所以 slots = 87,88)
        var items = calc.compute(1L, LocalDateTime.of(2026, 7, 1, 21, 45), LocalDateTime.of(2026, 7, 1, 22, 15));
        // 22:00 是 22 * 4 = 88,所以 [21:45, 22:15) 对应 slot 87,再加 22:00 = 88(?),22:00-22:15 = slot 88 (22:15 写在结束不算) = 2 个 slot
        // 重新算:21:45 是 (21 小时 + 45 分钟) = 21*60+45 = 1305 分钟 = 1305/15 = 87;22:15 是 (22*60+15) = 1335/15 = 89;s[87..89) 即 slot 87,88 = 2 slots
        assertEquals(2, items.size());
        assertEquals(87, items.get(0).slotIndex());
        assertEquals(88, items.get(1).slotIndex());
    }

    @Test
    void start_equals_end_throws() {
        assertThrows(BusinessException.class, () ->
            calc.compute(1L, LocalDateTime.of(2026, 7, 1, 9, 0), LocalDateTime.of(2026, 7, 1, 9, 0)));
    }

    @Test
    void cross_day_spans_two_dates() {
        // 21:45 day1 -> 09:00 day2
        // day1: 21:45 = slot 87, 22:00 = slot 88,s[87..88) = 1 slot,即 slot 87
        // day2: 00:00..09:00 = slots 0..35 即 36 个 slot
        var items = calc.compute(1L, LocalDateTime.of(2026, 7, 1, 21, 45), LocalDateTime.of(2026, 7, 2, 9, 0));
        assertTrue(items.stream().anyMatch(i -> i.date().equals(LocalDate.of(2026, 7, 1)) && i.slotIndex() == 87));
        List<Integer> nextDay = items.stream().filter(i -> i.date().equals(LocalDate.of(2026, 7, 2)))
            .map(SlotKey::slotIndex).toList();
        assertEquals(36, nextDay.size());
        assertEquals(0, nextDay.get(0));
        assertEquals(35, nextDay.get(35));
    }

    @Test
    void cross_three_days() {
        // 21:00 day1 -> 09:00 day3
        // day1: 21:00-24:00 -> s[84..96) = 84,85,86,87,88,89,90,91,92,93,94,95 (12 slots)
        // day2: 00:00-24:00 -> s[0..96) = 0..95 (96 slots)
        // day3: 00:00-09:00 -> s[0..36) = 0..35 (36 slots)
        var items = calc.compute(1L, LocalDateTime.of(2026, 7, 1, 21, 0), LocalDateTime.of(2026, 7, 3, 9, 0));
        assertFalse(items.isEmpty());
        assertEquals(3, items.stream().map(SlotKey::date).distinct().count());
        List<Integer> firstDay = items.stream().filter(i -> i.date().equals(LocalDate.of(2026, 7, 1)))
            .map(SlotKey::slotIndex).toList();
        assertEquals(12, firstDay.size());
        assertEquals(84, firstDay.get(0));
        assertEquals(95, firstDay.get(11));
        List<Integer> midDay = items.stream().filter(i -> i.date().equals(LocalDate.of(2026, 7, 2)))
            .map(SlotKey::slotIndex).toList();
        assertEquals(96, midDay.size());
        assertEquals(0, midDay.get(0));
        assertEquals(95, midDay.get(95));
        List<Integer> lastDay = items.stream().filter(i -> i.date().equals(LocalDate.of(2026, 7, 3)))
            .map(SlotKey::slotIndex).toList();
        assertEquals(36, lastDay.size());
        assertEquals(0, lastDay.get(0));
        assertEquals(35, lastDay.get(35));
    }

    @Test
    void full_day_24h_now_legal() {
        // 00:00 - 24:00 (即次日 00:00)= 96 slots
        var items = calc.compute(1L, LocalDateTime.of(2026, 7, 1, 0, 0), LocalDateTime.of(2026, 7, 2, 0, 0));
        assertEquals(96, items.size());
        assertEquals(0, items.get(0).slotIndex());
        assertEquals(95, items.get(95).slotIndex());
    }
}
