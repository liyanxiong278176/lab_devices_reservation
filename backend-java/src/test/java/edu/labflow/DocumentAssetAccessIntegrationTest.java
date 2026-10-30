package edu.labflow;

import static org.assertj.core.api.Assertions.*;

import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
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
class DocumentAssetAccessIntegrationTest {
  @Autowired Database db;
  @Autowired FixtureCommand fixtures;
  @Autowired StorageService storage;
  @Autowired DeviceAccessService documents;
  Map<String, Object> fixture;
  Principal admin;
  Principal student;
  String token;
  long asset;

  @BeforeEach
  @SuppressWarnings("unchecked")
  void seed() {
    String prefix = "e2e-doc-" + UUID.randomUUID().toString().substring(0, 8);
    fixture = (Map<String, Object>) fixtures.seed(prefix);
    long adminId =
        db.count("SELECT id FROM sys_user WHERE username=?", fixture.get("admin_username"));
    admin = new Principal(adminId, "admin", null, Set.of("SYS_ADMIN"), Set.of(), "test");
    student =
        new Principal(
            Database.id(fixture, "user_id"),
            "student",
            Database.id(fixture, "college_id"),
            Set.of("STUDENT"),
            Set.of("device:read"),
            "test");
    token = "document-" + UUID.randomUUID().toString().replace("-", "");
    asset =
        db.insert(
            "INSERT INTO v2_upload_asset (asset_token,user_id,college_id,original_name,content_type,size_bytes,storage_path) VALUES (?,?,NULL,'guide.txt','text/plain',20,'test-document.txt')",
            token,
            adminId);
  }

  Map<String, Object> publish(String type) {
    return documents.publish(
        admin,
        Database.id(fixture, "device_id"),
        Map.of("asset_id", asset),
        type,
        "测试设备文档",
        "1.0",
        false);
  }

  @ParameterizedTest
  @ValueSource(strings = {"MANUAL", "SOP", "SAFETY"})
  void sameCollegeStudentCanReadPublishedGlobalAdminUpload(String type) {
    assertThat(db.one("SELECT id,college_id FROM v2_upload_asset WHERE id=?", asset))
        .containsEntry("college_id", null);
    assertThatThrownBy(() -> storage.asset(student, token)).isInstanceOf(ApiError.class);
    publish(type);
    assertThat(Database.id(storage.asset(student, token), "id")).isEqualTo(asset);
  }

  @Test
  void anotherCollegeCannotReadThePublishedDocument() {
    publish("MANUAL");
    var outsider =
        new Principal(
            student.userId(),
            "outsider",
            student.collegeId() + 1_000_000,
            Set.of("STUDENT"),
            Set.of("device:read"),
            "test");
    assertThatThrownBy(() -> storage.asset(outsider, token))
        .isInstanceOfSatisfying(ApiError.class, error -> assertThat(error.status).isEqualTo(403));
  }

  @Test
  void archivedDocumentNoLongerGrantsStudentAccess() {
    var doc = publish("MANUAL");
    documents.archive(admin, Database.id(fixture, "device_id"), Database.id(doc, "id"));
    assertThatThrownBy(() -> storage.asset(student, token))
        .isInstanceOfSatisfying(ApiError.class, error -> assertThat(error.status).isEqualTo(403));
    assertThat(Database.id(storage.asset(admin, token), "id")).isEqualTo(asset);
  }

  @Test
  void revokedReadPermissionCannotUseDocumentAccess() {
    publish("MANUAL");
    var revoked =
        new Principal(
            student.userId(), "revoked", student.collegeId(), Set.of("STUDENT"), Set.of(), "test");
    assertThatThrownBy(() -> storage.asset(revoked, token))
        .isInstanceOfSatisfying(ApiError.class, error -> assertThat(error.status).isEqualTo(403));
  }

  @Test
  void unpublishedPrivateAttachmentRemainsRestrictedToItsOwner() {
    db.execute("UPDATE v2_upload_asset SET college_id=? WHERE id=?", student.collegeId(), asset);
    assertThatThrownBy(() -> storage.asset(student, token))
        .isInstanceOfSatisfying(ApiError.class, error -> assertThat(error.status).isEqualTo(403));
    db.execute("UPDATE v2_upload_asset SET user_id=? WHERE id=?", student.userId(), asset);
    assertThat(Database.id(storage.asset(student, token), "id")).isEqualTo(asset);
  }
}
