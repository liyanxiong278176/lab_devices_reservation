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
    private final int slotMinutes;
    private final LocalTime workStart;
    private final LocalTime workEnd;

    public SlotCalculatorService(@Value("${lab.slot.minutes:15}") int slotMinutes,
                                 @Value("${lab.slot.work-start:08:00}") LocalTime workStart,
                                 @Value("${lab.slot.work-end:22:00}") LocalTime workEnd) {
        if (slotMinutes <= 0 || 60 % slotMinutes != 0) {
            throw new IllegalArgumentException("slotMinutes 须为 60 的正约数, 实际: " + slotMinutes);
        }
        if (!workStart.isBefore(workEnd)) {
            throw new IllegalArgumentException("workStart 必须早于 workEnd, workStart=" + workStart + ", workEnd=" + workEnd);
        }
        this.slotMinutes = slotMinutes;
        this.workStart = workStart;
        this.workEnd = workEnd;
    }

    public List<SlotKey> compute(Long deviceId, LocalDateTime start, LocalDateTime end) {
        if (!start.isBefore(end)) throw new BusinessException(ResultCode.SLOT_NOT_ALIGNED);
        if (!isAligned(start) || !isAligned(end)) throw new BusinessException(ResultCode.SLOT_NOT_ALIGNED);

        List<SlotKey> out = new ArrayList<>();
        for (LocalDate d = start.toLocalDate(); !d.isAfter(end.toLocalDate()); d = d.plusDays(1)) {
            LocalTime dayStart = d.equals(start.toLocalDate()) ? start.toLocalTime() : workStart;
            LocalTime dayEnd = d.equals(end.toLocalDate()) ? end.toLocalTime() : workEnd;
            if (dayStart.isBefore(workStart)) throw new BusinessException(ResultCode.SLOT_OUT_OF_WORK_WINDOW);
            if (dayEnd.isAfter(workEnd)) throw new BusinessException(ResultCode.SLOT_OUT_OF_WORK_WINDOW);
            int startSlot = (int) Duration.between(workStart, dayStart).toMinutes() / slotMinutes;
            int endSlot = (int) Duration.between(workStart, dayEnd).toMinutes() / slotMinutes;
            for (int s = startSlot; s < endSlot; s++) out.add(new SlotKey(deviceId, d, s));
        }
        if (out.isEmpty()) throw new IllegalStateException("unreachable: empty slots after validation");
        return out;
    }

    private boolean isAligned(LocalDateTime t) {
        return t.getMinute() % slotMinutes == 0 && t.getSecond() == 0 && t.getNano() == 0;
    }
}
