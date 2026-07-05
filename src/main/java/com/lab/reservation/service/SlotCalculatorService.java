package com.lab.reservation.service;

import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.exception.BusinessException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;

@Component
public class SlotCalculatorService {
    /** 当天总 slot 数(slotMinutes=15 时为 96)。用于跨日中"非起止日"的整天覆盖。 */
    private static final int SLOTS_PER_DAY_15MIN = 96;
    private final int slotMinutes;

    public SlotCalculatorService(@Value("${lab.slot.minutes:15}") int slotMinutes) {
        if (slotMinutes <= 0 || 60 % slotMinutes != 0) {
            throw new IllegalArgumentException("slotMinutes 须为 60 的正约数, 实际: " + slotMinutes);
        }
        this.slotMinutes = slotMinutes;
    }

    /**
     * 计算 [start, end) 区间内每个 slot 的 (deviceId, date, slotIdx)。
     *
     * <p>语义变化(相对老版):
     * <ul>
     *   <li>取消 lab.slot.work-start / work-end 工作时段边界:用户可选当天任意分钟(00:00-23:59)且从今天起任意日期;</li>
     *   <li>slotIdx 从 00:00 起算(每天 0..95 视 slotMinutes=15)。若已有历史数据按"08:00 = slotIdx 0"写入,本变更后同一时刻会产生不同
     *       slotIdx,导致冲突检测错位 —— 旧数据需迁移(migration)或重建冲突表。</li>
     * </ul>
     *
     * <p>保留约束(不可放宽):
     * <ul>
     *   <li>start 必须早于 end;</li>
     *   <li>起止必须 15 分钟对齐(slotMinutes 倍数,分钟为 0);</li>
     *   <li>slotIdx 通过 00:00 偏移推算(00:00 = 0, 23:45 = 95)。</li>
     * </ul>
     */
    public List<SlotKey> compute(Long deviceId, LocalDateTime start, LocalDateTime end) {
        if (!start.isBefore(end)) throw new BusinessException(ResultCode.SLOT_NOT_ALIGNED);
        if (!isAligned(start) || !isAligned(end)) throw new BusinessException(ResultCode.SLOT_NOT_ALIGNED);

        int slotsPerDay = 24 * 60 / slotMinutes; // 15min → 96
        List<SlotKey> out = new ArrayList<>();
        for (LocalDate d = start.toLocalDate(); !d.isAfter(end.toLocalDate()); d = d.plusDays(1)) {
            // start 日:从用户的 start.toLocalTime() 起;其它日:从 00:00 起
            int startSlot = d.equals(start.toLocalDate())
                ? (int) Duration.between(LocalTime.MIDNIGHT, start.toLocalTime()).toMinutes() / slotMinutes
                : 0;
            // end 日:到用户的 end.toLocalTime() 止;其它日(中段日 / start≠end 但 d=start):到整天 (slotsPerDay)
            int endSlot = d.equals(end.toLocalDate())
                ? (int) Duration.between(LocalTime.MIDNIGHT, end.toLocalTime()).toMinutes() / slotMinutes
                : slotsPerDay;
            for (int s = startSlot; s < endSlot; s++) out.add(new SlotKey(deviceId, d, s));
        }
        if (out.isEmpty()) throw new IllegalStateException("unreachable: empty slots after validation");
        return out;
    }

    private boolean isAligned(LocalDateTime t) {
        return t.getMinute() % slotMinutes == 0 && t.getSecond() == 0 && t.getNano() == 0;
    }
}
