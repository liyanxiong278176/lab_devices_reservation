package edu.labflow;

import jakarta.validation.constraints.*;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.*;

public record ReservationPlan(
    Long device_id,
    Long pool_id,
    Long preferred_device_id,
    Integer quantity,
    @NotNull @Size(min = 2, max = 500) String purpose,
    String purpose_category,
    @Size(max = 160) String project_reference,
    LocalDate start_date,
    LocalDate end_date,
    List<LocalDate> dates,
    List<Window> windows,
    String commit_mode) {
  public record Window(LocalDate start_date, LocalDate end_date) {
    public List<LocalDate> days() {
      if (start_date == null
          || end_date == null
          || end_date.isBefore(start_date)
          || ChronoUnit.DAYS.between(start_date, end_date) >= 31)
        throw ApiError.validation("日期范围无效或超过 31 天");
      return start_date.datesUntil(end_date.plusDays(1)).toList();
    }
  }

  public ReservationPlan {
    quantity = quantity == null ? 1 : quantity;
    purpose_category = purpose_category == null ? "OTHER" : purpose_category;
    commit_mode = commit_mode == null ? "all_or_nothing" : commit_mode;
    if ((device_id == null) == (pool_id == null)
        || quantity < 1
        || (quantity > 1 && pool_id == null)
        || (preferred_device_id != null && (pool_id == null || quantity > 1)))
      throw ApiError.validation("设备或资源池参数无效");
    if (device_id != null && device_id <= 0
        || pool_id != null && pool_id <= 0
        || preferred_device_id != null && preferred_device_id <= 0)
      throw ApiError.validation("设备标识无效");
    if (!Set.of("TEACHING", "RESEARCH", "COMPETITION_GRADUATION", "OTHER")
            .contains(purpose_category)
        || !Set.of("all_or_nothing", "available_only").contains(commit_mode))
      throw ApiError.validation("预约用途或提交方式无效");
    int shapes =
        (start_date != null || end_date != null ? 1 : 0)
            + (dates != null && !dates.isEmpty() ? 1 : 0)
            + (windows != null && !windows.isEmpty() ? 1 : 0);
    if (shapes != 1) throw ApiError.validation("请选择一种预约日期方式");
    if (start_date != null || end_date != null) new Window(start_date, end_date).days();
    if (dates != null) {
      if (dates.size() > 31
          || new HashSet<>(dates).size() != dates.size()
          || dates.stream().anyMatch(Objects::isNull)) throw ApiError.validation("日期不能重复或超过 31 天");
      dates = dates.stream().sorted().toList();
    }
    if (windows != null) {
      var all = new HashSet<LocalDate>();
      int count = 0;
      for (var w : windows) {
        var ds = w.days();
        count += ds.size();
        for (var d : ds) if (!all.add(d)) throw ApiError.validation("重复区间不能重叠");
      }
      if (count > 31) throw ApiError.validation("单次最多预约 31 个自然日");
    }
  }

  public List<List<LocalDate>> segments() {
    if (start_date != null) return List.of(new Window(start_date, end_date).days());
    if (dates != null) return dates.stream().map(List::of).toList();
    return windows.stream().map(Window::days).toList();
  }

  public List<LocalDate> requestedDates() {
    return segments().stream().flatMap(Collection::stream).sorted().toList();
  }
}
