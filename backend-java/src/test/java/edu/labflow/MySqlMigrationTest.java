package edu.labflow;

import static org.assertj.core.api.Assertions.*;

import java.sql.*;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

@EnabledIfEnvironmentVariable(
    named = "LAB_TEST_MYSQL_URL",
    matches = "jdbc:mysql:.*labflow_migration_test.*")
class MySqlMigrationTest {
  @Test
  void baselinePreservesBusinessRowsAndRemovesOnlyAiTables() throws Exception {
    String url = System.getenv("LAB_TEST_MYSQL_URL"),
        password = System.getenv("LAB_TEST_MYSQL_PASSWORD");
    try (var conn = DriverManager.getConnection(url, "root", password);
        var stmt = conn.createStatement()) {
      stmt.executeUpdate(
          "INSERT IGNORE INTO sys_user (username,password,real_name,user_type,college_id,status,credit_score) VALUES ('migration-retained-user','not-a-real-password','保留测试','STUDENT',(SELECT MIN(id) FROM college),1,100)");
      long users = count(stmt, "SELECT COUNT(*) FROM sys_user"),
          colleges = count(stmt, "SELECT COUNT(*) FROM college");
      var flyway =
          Flyway.configure()
              .dataSource(url, "root", password)
              .baselineVersion("1")
              .cleanDisabled(true)
              .load();
      try (var rs =
          stmt.executeQuery(
              "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='flyway_schema_history'")) {
        rs.next();
        if (rs.getLong(1) == 0) flyway.baseline();
      }
      flyway.migrate();
      assertThat(count(stmt, "SELECT COUNT(*) FROM sys_user")).isEqualTo(users);
      assertThat(count(stmt, "SELECT COUNT(*) FROM college")).isEqualTo(colleges);
      assertThat(
              count(
                  stmt,
                  "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND (TABLE_NAME LIKE 'v2_ai_%' OR TABLE_NAME LIKE 'v2_knowledge_%')"))
          .isZero();
      assertThat(
              count(
                  stmt,
                  "SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='v2_reservation_day' AND NON_UNIQUE=0 AND INDEX_NAME IN (SELECT INDEX_NAME FROM (SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='v2_reservation_day' AND NON_UNIQUE=0 GROUP BY INDEX_NAME HAVING GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)='device_id,date') day_unique)"))
          .isEqualTo(2);
      stmt.execute(
          "CREATE DATABASE IF NOT EXISTS labflow_migration_test_fresh CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci");
    }
    String fresh = url.replace("labflow_migration_test", "labflow_migration_test_fresh");
    Flyway.configure().dataSource(fresh, "root", password).cleanDisabled(true).load().migrate();
    try (var conn = DriverManager.getConnection(fresh, "root", password);
        var stmt = conn.createStatement()) {
      assertThat(
              count(stmt, "SELECT COUNT(*) FROM sys_permission WHERE permission_code LIKE 'ai:%'"))
          .isZero();
      assertThat(count(stmt, "SELECT COUNT(*) FROM sys_role")).isGreaterThan(0);
      assertThat(
              count(
                  stmt,
                  "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='v2_reservation_day'"))
          .isEqualTo(1);
    }
  }

  private long count(Statement stmt, String sql) throws SQLException {
    try (var rs = stmt.executeQuery(sql)) {
      rs.next();
      return rs.getLong(1);
    }
  }
}
