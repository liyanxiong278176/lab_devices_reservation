package edu.labflow;

import static org.assertj.core.api.Assertions.*;

import java.sql.*;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

@EnabledIfEnvironmentVariable(
    named = "LAB_TEST_MYSQL_URL",
    matches = "jdbc:mysql:.*labflow_migration_test.*")
class WorkflowRemovalMigrationTest {
  @Test
  void removesExclusiveEvidenceButProtectsSharedAssetsAndBusinessRows() throws Exception {
    String source = System.getenv("LAB_TEST_MYSQL_URL"),
        password = System.getenv("LAB_TEST_MYSQL_PASSWORD");
    String name = "labflow_workflow_test_" + UUID.randomUUID().toString().replace("-", "");
    String url = source.replace("labflow_migration_test", name);
    try (var connection = DriverManager.getConnection(source, "root", password);
        var statement = connection.createStatement()) {
      statement.execute("CREATE DATABASE " + name + " CHARACTER SET utf8mb4");
    }
    try {
      Flyway.configure()
          .dataSource(url, "root", password)
          .target("3")
          .cleanDisabled(true)
          .load()
          .migrate();
      try (var connection = DriverManager.getConnection(url, "root", password);
          var stmt = connection.createStatement()) {
        stmt.execute(
            "INSERT INTO sys_user (id,username,password,college_id,user_type,status,credit_score,booking_blocked_until) VALUES (1,'test','unchanged-password',1,'STAFF',1,40,'2099-01-01')");
        stmt.execute(
            "INSERT INTO device (id,name,college_id,status) VALUES (1,'test',1,'MAINTENANCE')");
        stmt.execute(
            "INSERT INTO v2_upload_asset (id,asset_token,user_id,college_id,original_name,content_type,size_bytes,storage_path) VALUES (1,'exclusive-token-123456789',1,1,'exclusive.pdf','application/pdf',8,'exclusive.pdf'),(2,'shared-token-123456789012',1,1,'shared.pdf','application/pdf',8,'shared.pdf')");
        stmt.execute(
            "INSERT INTO v2_device_document (device_id,college_id,asset_id,title,created_by) VALUES (1,1,2,'retained document',1)");
        stmt.execute(
            "INSERT INTO v2_device_maintenance_plan (id,device_id,college_id,plan_type,title,interval_value,interval_unit,due_date,created_by,updated_by) VALUES (1,1,1,'CALIBRATION','test',1,'MONTH','2026-01-01',1,1)");
        stmt.execute(
            "INSERT INTO v2_device_maintenance_record (plan_id,device_id,college_id,cycle_due_date,completed_date,result,performed_by,evidence_asset_id,idempotency_key,request_hash) VALUES (1,1,1,'2026-01-01','2026-01-01','PASSED',1,1,'exclusive','hash'),(1,1,1,'2026-02-01','2026-02-01','PASSED',1,2,'shared','hash')");
      }
      Flyway.configure().dataSource(url, "root", password).cleanDisabled(true).load().migrate();
      try (var connection = DriverManager.getConnection(url, "root", password);
          var stmt = connection.createStatement()) {
        assertThat(count(stmt, "SELECT COUNT(*) FROM v2_upload_asset WHERE id=1")).isZero();
        assertThat(count(stmt, "SELECT COUNT(*) FROM v2_upload_asset WHERE id=2")).isEqualTo(1);
        assertThat(count(stmt, "SELECT COUNT(*) FROM v2_removed_workflow_file_cleanup WHERE id=1"))
            .isEqualTo(1);
        assertThat(count(stmt, "SELECT COUNT(*) FROM v2_removed_workflow_file_cleanup WHERE id=2"))
            .isZero();
        assertThat(count(stmt, "SELECT COUNT(*) FROM v2_device_document")).isEqualTo(1);
        assertThat(count(stmt, "SELECT COUNT(*) FROM device WHERE status='MAINTENANCE'"))
            .isEqualTo(1);
        assertThat(
                count(
                    stmt,
                    "SELECT COUNT(*) FROM sys_user WHERE password='unchanged-password' AND credit_score=100 AND booking_blocked_until IS NULL"))
            .isEqualTo(1);
        assertThat(
                count(
                    stmt,
                    "SELECT COUNT(*) FROM sys_permission WHERE permission_code LIKE 'maintenance:%'"))
            .isZero();
        assertThat(
                count(
                    stmt,
                    "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND (TABLE_NAME LIKE 'v2_penalty_%' OR TABLE_NAME LIKE 'v2_device_maintenance_%')"))
            .isZero();
      }
    } finally {
      try (var connection = DriverManager.getConnection(source, "root", password);
          var stmt = connection.createStatement()) {
        stmt.execute("DROP DATABASE " + name);
      }
    }
  }

  private long count(Statement stmt, String sql) throws SQLException {
    try (var rs = stmt.executeQuery(sql)) {
      rs.next();
      return rs.getLong(1);
    }
  }
}
