package edu.labflow;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.time.LocalDate;
import java.util.*;
import org.junit.jupiter.api.Test;

class ReportServiceTest {
  @Test
  void legacyInitialStatusWithoutOldStatusCanBeReported() {
    var first = LocalDate.of(2026, 10, 1);
    var event = new HashMap<String, Object>();
    event.put("old_status", null);
    event.put("new_status", "IDLE");
    event.put("created_at", first.atTime(9, 0));
    assertThat(summary(first, List.of(event), null).get("bookableDeviceDays")).isEqualTo(2);
  }

  @Test
  void legacyFollowingStatusWithoutOldStatusCanBeReported() {
    var following = new HashMap<String, Object>();
    following.put("old_status", null);
    assertThat(summary(LocalDate.of(2026, 10, 1), List.of(), following).get("bookableDeviceDays"))
        .isEqualTo(2);
  }

  private Map<String, Object> summary(
      LocalDate first, List<Map<String, Object>> history, Map<String, Object> following) {
    var db = mock(Database.class);
    var scope = mock(ScopeAccess.class);
    var principal = new Principal(1, "report-test", null, Set.of("SYS_ADMIN"), Set.of(), "test");
    when(scope.devicePredicate(principal, "d", true)).thenReturn("1=1");
    when(db.one(anyString(), any(Object[].class))).thenReturn(null);
    doAnswer(
            call -> {
              String sql = call.getArgument(0);
              if (sql.startsWith("SELECT d.*"))
                return List.of(Map.of("id", 1L, "status", "IDLE", "college_id", 1L, "lab_id", 1L));
              if (sql.startsWith("SELECT * FROM v2_device_status_history")) return history;
              return List.of();
            })
        .when(db)
        .rows(anyString(), any(Object[].class));
    when(db.one(startsWith("SELECT old_status"), any(Object[].class))).thenReturn(following);
    return new ReportService(db, scope, mock(Settings.class), mock(BusinessEvents.class))
        .summary(principal, first, first.plusDays(1), null);
  }
}
