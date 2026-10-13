package edu.labflow;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.regex.*;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

@Component
public class SchemaVerifier {
  private final Database db;

  public SchemaVerifier(Database db) {
    this.db = db;
  }

  public List<String> differences() {
    String snapshot;
    try (var stream =
        new ClassPathResource("db/migration/V1__non_ai_schema.sql").getInputStream()) {
      snapshot = new String(stream.readAllBytes(), StandardCharsets.UTF_8);
    } catch (IOException e) {
      throw new IllegalStateException(e);
    }
    var errors = new ArrayList<String>();
    Matcher tables =
        Pattern.compile("CREATE TABLE `([^`]+)` \\((.*?)\\) ENGINE=", Pattern.DOTALL)
            .matcher(snapshot);
    boolean removed =
        db.count(
                "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='v2_removed_workflow_file_cleanup'")
            > 0;
    var removedTables =
        Set.of(
            "v2_reservation_booking_restriction",
            "v2_reservation_overdue_followup",
            "v2_reservation_overdue",
            "v2_penalty_appeal",
            "v2_penalty_case",
            "v2_penalty_rule_version",
            "v2_penalty_grace_bounds",
            "v2_credit_event",
            "v2_college_credit_account",
            "v2_device_maintenance_record",
            "v2_device_maintenance_plan");
    while (tables.find()) {
      String table = tables.group(1);
      if (removed && removedTables.contains(table)) continue;
      var columns =
          db.rows(
              "SELECT COLUMN_NAME,DATA_TYPE,IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=?",
              table);
      var actual = new HashMap<String, Map<String, Object>>();
      for (var row : columns) actual.put(row.get("COLUMN_NAME").toString(), row);
      Matcher expected =
          Pattern.compile("(?m)^  `([^`]+)` ([a-z]+)(?:\\([^)]*\\))?([^\\n]*)")
              .matcher(tables.group(2));
      while (expected.find()) {
        String name = expected.group(1), type = expected.group(2);
        var row = actual.get(name);
        if (row == null) {
          errors.add(table + "." + name + " missing");
          continue;
        }
        if (!type.equals(row.get("DATA_TYPE"))) errors.add(table + "." + name + " type mismatch");
        if (expected.group(3).contains("NOT NULL") && !"NO".equals(row.get("IS_NULLABLE")))
          errors.add(table + "." + name + " must be NOT NULL");
      }
      Matcher indexes =
          Pattern.compile("UNIQUE KEY `[^`]+` \\(([^)]+)\\)").matcher(tables.group(2));
      while (indexes.find()) {
        String expectedColumns = indexes.group(1).replace("`", "");
        if (db.count(
                "SELECT COUNT(*) FROM (SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX SEPARATOR ',') cols FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? AND NON_UNIQUE=0 GROUP BY INDEX_NAME) idx WHERE idx.cols=?",
                table,
                expectedColumns)
            == 0) errors.add(table + " unique constraint missing: " + expectedColumns);
      }
      Matcher foreignKeys =
          Pattern.compile("FOREIGN KEY \\(`([^`]+)`\\) REFERENCES `([^`]+)` \\(`([^`]+)`\\)")
              .matcher(tables.group(2));
      while (foreignKeys.find())
        if (db.count(
                "SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? AND COLUMN_NAME=? AND REFERENCED_TABLE_NAME=? AND REFERENCED_COLUMN_NAME=?",
                table,
                foreignKeys.group(1),
                foreignKeys.group(2),
                foreignKeys.group(3))
            != 1) errors.add(table + " foreign key missing: " + foreignKeys.group(1));
    }
    return errors;
  }

  public void requireLegacyHead() {
    if (db.count("SELECT COUNT(*) FROM alembic_version") != 1)
      throw new IllegalStateException("Expected one verified historical migration head");
    var row = db.one("SELECT version_num FROM alembic_version");
    if (row == null || !"0038_penalties_overdue".equals(row.get("version_num")))
      throw new IllegalStateException(
          "Expected Alembic head 0038_penalties_overdue; upgrade with the historical backend before baselining");
    var differences = differences();
    if (!differences.isEmpty())
      throw new IllegalStateException(
          "Business schema mismatch: " + String.join("; ", differences));
  }
}
