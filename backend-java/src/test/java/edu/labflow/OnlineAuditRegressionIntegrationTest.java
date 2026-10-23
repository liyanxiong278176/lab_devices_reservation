package edu.labflow;

import static org.assertj.core.api.Assertions.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.transaction.annotation.Transactional;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ContextConfiguration(initializers = RuntimeEnvironment.class)
@EnabledIfEnvironmentVariable(
    named = "LAB_JDBC_URL",
    matches = "jdbc:mysql:.*labflow_migration_test_fresh.*")
@Transactional
class OnlineAuditRegressionIntegrationTest {
  @Autowired Database db;
  @Autowired FixtureCommand fixtures;
  @Autowired ReservationLifecycle lifecycle;
  @Autowired ReservationService reservations;
  @Autowired RepairService repairs;
  @Autowired ObjectMapper json;
  Map<String, Object> fixture;
  Principal manager;
  Principal student;

  @BeforeEach
  @SuppressWarnings("unchecked")
  void seed() {
    String prefix = "e2e-audit-" + UUID.randomUUID().toString().substring(0, 8);
    fixture = (Map<String, Object>) fixtures.seed(prefix);
    long college = Database.id(fixture, "college_id");
    long managerId = db.count("SELECT id FROM sys_user WHERE username=?", prefix + "-manager");
    manager =
        new Principal(
            managerId,
            prefix + "-manager",
            college,
            Set.of("LAB_ADMIN"),
            Set.of(
                "reservation:approve",
                "reservation:handover",
                "reservation:read:scope",
                "repair:handle"),
            "test");
    student =
        new Principal(
            Database.id(fixture, "user_id"),
            prefix + "-user",
            college,
            Set.of("STUDENT"),
            Set.of("repair:create", "repair:read:own"),
            "test");
  }

  long booking(String state, String handover) {
    var day = BusinessTime.today();
    long id =
        db.insert(
            "INSERT INTO reservation (college_id,user_id,device_id,purpose,start_date,end_date,start_time,end_time,slot_count,status,handover_status) VALUES (?,?,?,'audit',?,?,?,?,1,?,?)",
            fixture.get("college_id"),
            fixture.get("user_id"),
            fixture.get("device_id"),
            day,
            day,
            day.atStartOfDay(),
            day.atTime(23, 59, 59),
            state,
            handover);
    db.execute(
        "INSERT INTO v2_device_handover (reservation_id,device_id,user_id,college_id,status) VALUES (?,?,?,?,?)",
        id,
        fixture.get("device_id"),
        fixture.get("user_id"),
        fixture.get("college_id"),
        handover);
    return id;
  }

  @Test
  void rejectionCancelsBothHandoverStates() {
    long id = booking("PENDING", "PENDING");
    lifecycle.approval(manager, id, false, "用途不符合要求");
    assertThat(db.one("SELECT status,handover_status FROM reservation WHERE id=?", id))
        .containsEntry("status", "REJECTED")
        .containsEntry("handover_status", "CANCELLED");
    assertThat(db.one("SELECT status FROM v2_device_handover WHERE reservation_id=?", id))
        .containsEntry("status", "CANCELLED");
  }

  @ParameterizedTest
  @CsvSource({"PENDING,APPROVED", "EXCEPTION,APPROVED", "RETURN_PENDING,IN_USE"})
  @SuppressWarnings("unchecked")
  void legacyTerminalRowsAreExcludedBeforeCountingAndPagination(String handover, String active) {
    long wanted = booking(active, handover);
    for (String ended : List.of("REJECTED", "CANCELLED", "COMPLETED")) booking(ended, handover);
    var page = reservations.list(manager, new Pagination(1, 1), "handovers", null, handover);
    assertThat(((Number) page.get("total")).longValue()).isEqualTo(1);
    var items = (List<Map<String, Object>>) page.get("items");
    assertThat(items).hasSize(1);
    assertThat(Database.id(items.getFirst(), "id")).isEqualTo(wanted);
  }

  @Test
  void repairCreationAndResolutionStayUtcWithANonUtcMysqlSession() throws Exception {
    db.execute("SET time_zone = '+08:00'");
    try {
      var report =
          repairs.create(student, Map.of("device_id", fixture.get("device_id"), "title", "时区回归"));
      long id = Database.id(report, "id");
      var stored =
          (LocalDateTime)
              db.one("SELECT created_at FROM v2_repair_report WHERE id=?", id).get("created_at");
      assertThat(Duration.between(stored, BusinessTime.utcNow()).abs())
          .isLessThan(Duration.ofSeconds(10));
      repairs.take(manager, id);
      var resolved = repairs.resolve(manager, id, "已完成测试维修", false);
      assertThat(resolved.get("created_at")).isInstanceOf(OffsetDateTime.class);
      assertThat(resolved.get("resolved_at")).isInstanceOf(OffsetDateTime.class);
      assertThat(json.writeValueAsString(resolved)).contains("Z\"");
      var createdAt = (OffsetDateTime) resolved.get("created_at");
      var resolvedAt = (OffsetDateTime) resolved.get("resolved_at");
      assertThat(Duration.between(createdAt, resolvedAt).abs()).isLessThan(Duration.ofSeconds(10));
    } finally {
      db.execute("SET time_zone = '+00:00'");
    }
  }

  @Test
  @SuppressWarnings("unchecked")
  void legacyLocalCreationUsesItsUtcCreationEventWithoutRewritingHistory() {
    var report =
        repairs.create(student, Map.of("device_id", fixture.get("device_id"), "title", "历史时间回归"));
    long id = Database.id(report, "id");
    var event =
        (LocalDateTime)
            db.one(
                    "SELECT created_at FROM v2_repair_worklog WHERE report_id=? AND status='PENDING' ORDER BY id LIMIT 1",
                    id)
                .get("created_at");
    db.execute("UPDATE v2_repair_report SET created_at=? WHERE id=?", event.plusHours(8), id);
    var page = repairs.list(student, new Pagination(1, 20), true, null, null, null);
    var row = ((List<Map<String, Object>>) page.get("items")).getFirst();
    assertThat(row.get("created_at")).isEqualTo(event.atOffset(ZoneOffset.UTC));
    assertThat(row).doesNotContainKey("creation_event_at");
    assertThat(db.one("SELECT created_at FROM v2_repair_report WHERE id=?", id).get("created_at"))
        .isEqualTo(event.plusHours(8));
  }
}
