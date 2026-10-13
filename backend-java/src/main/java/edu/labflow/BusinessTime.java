package edu.labflow;

import java.time.*;

public final class BusinessTime {
  private BusinessTime() {}

  public static final ZoneId ZONE = ZoneId.of("Asia/Shanghai");

  public static LocalDate today() {
    return LocalDate.now(ZONE);
  }

  public static LocalDateTime utcNow() {
    return LocalDateTime.now(ZoneOffset.UTC);
  }

  public static LocalDateTime dayEnd(LocalDate day) {
    return LocalDateTime.ofInstant(
        day.plusDays(1).atStartOfDay(ZONE).toInstant().minusNanos(1000), ZoneOffset.UTC);
  }
}
