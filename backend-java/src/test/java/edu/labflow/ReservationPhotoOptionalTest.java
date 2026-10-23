package edu.labflow;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.util.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.PlatformTransactionManager;

class ReservationPhotoOptionalTest {
  private final Database db = mock(Database.class);
  private final ScopeAccess scope = mock(ScopeAccess.class);
  private final ReservationService reservations = mock(ReservationService.class);
  private final BusinessEvents events = mock(BusinessEvents.class);
  private final RepairService repairs = mock(RepairService.class);
  private final Principal principal =
      new Principal(1, "demo", 1L, Set.of("SYS_ADMIN"), Set.of(), "demo");
  private final StorageService storage =
      new StorageService(db, mock(Settings.class), scope, mock(PlatformTransactionManager.class));
  private final ReservationLifecycle lifecycle =
      new ReservationLifecycle(
          db, scope, reservations, mock(CatalogService.class), storage, events, repairs);
  private final Map<String, Object> row = new HashMap<>();

  @BeforeEach
  void setup() {
    row.putAll(
        Map.of(
            "id",
            10L,
            "device_id",
            2L,
            "user_id",
            1L,
            "college_id",
            1L,
            "start_date",
            BusinessTime.today(),
            "end_date",
            BusinessTime.today()));
    when(db.one(startsWith("SELECT * FROM reservation WHERE"), any(Object[].class)))
        .thenReturn(row);
    when(scope.device(principal, 2L, true)).thenReturn(Map.of("id", 2L, "status", "IDLE"));
    when(db.execute(anyString(), any(Object[].class))).thenReturn(1);
    when(db.parse(any(), any())).thenAnswer(call -> call.getArgument(1));
    when(reservations.get(principal, 10L)).thenReturn(Map.of("id", 10L));
  }

  @Test
  void handoverWithoutPhotosStartsUse() {
    row.put("status", "APPROVED");
    row.put("handover_status", "PENDING");
    assertThat(lifecycle.handover(principal, 10L, Map.of("condition", "NORMAL")))
        .containsEntry("id", 10L);
    verify(events)
        .audit(eq(principal), eq("DEVICE_HANDOVER"), eq("RESERVATION"), eq(10L), anyMap());
    verifyNoInteractions(repairs);
  }

  @Test
  void returnWithoutPhotosWaitsForAcceptance() {
    row.put("status", "IN_USE");
    row.put("handover_status", "HANDED_OVER");
    assertThat(lifecycle.requestReturn(principal, 10L, Map.of("condition", "NORMAL")))
        .containsEntry("id", 10L);
    verify(db, never()).execute(startsWith("DELETE FROM v2_reservation_day"), any(Object[].class));
  }

  @Test
  void acceptanceWithoutPhotosCompletesAndReleasesTheDevice() {
    row.put("status", "IN_USE");
    row.put("handover_status", "RETURN_PENDING");
    when(db.one(startsWith("SELECT * FROM v2_device_handover"), any(Object[].class)))
        .thenReturn(Map.of("reservation_id", 10L, "return_image_urls", "[]"));
    assertThat(lifecycle.acceptReturn(principal, 10L, Map.of("condition", "NORMAL")))
        .containsEntry("id", 10L);
    verify(db).execute("DELETE FROM v2_reservation_day WHERE reservation_id=?", 10L);
    verifyNoInteractions(repairs);
  }

  @Test
  void optionalPhotosStillRejectInvalidOrForeignAttachments() {
    assertThatCode(() -> storage.evidence(principal, null, 1L)).doesNotThrowAnyException();
    assertThatCode(() -> storage.evidence(principal, List.of(), 1L)).doesNotThrowAnyException();
    assertThatThrownBy(() -> storage.evidence(principal, List.of("https://example.com/a.jpg"), 1L))
        .isInstanceOf(ApiError.class);
    when(db.one(startsWith("SELECT * FROM v2_upload_asset"), any(Object[].class))).thenReturn(null);
    assertThatThrownBy(
            () -> storage.evidence(principal, List.of("/api/v2/repair-uploads/foreign"), 1L))
        .isInstanceOf(ApiError.class);
  }
}
