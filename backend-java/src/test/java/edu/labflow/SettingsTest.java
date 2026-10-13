package edu.labflow;

import static org.assertj.core.api.Assertions.*;

import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;

class SettingsTest {
  @Test
  void emptyComposeOverridesUseDefaultsAndSharedSecretAliases() {
    var env =
        new MockEnvironment()
            .withProperty("LAB_JWT_SECRET", "")
            .withProperty("JWT_SECRET", "public-test-secret-with-at-least-32-characters")
            .withProperty("LAB_OUTBOX_WORKER_CONCURRENCY", "")
            .withProperty("LAB_RATE_LIMIT_ENABLED", "")
            .withProperty("LAB_METRICS_TOKEN", "")
            .withProperty("PROMETHEUS_METRICS_TOKEN", "public-metrics-test-token");
    var settings = new Settings(env);
    assertThat(settings.integer("OUTBOX_WORKER_CONCURRENCY", 4)).isEqualTo(4);
    assertThat(settings.bool("RATE_LIMIT_ENABLED", true)).isTrue();
    assertThat(settings.get("METRICS_TOKEN", "")).isEqualTo("public-metrics-test-token");
  }

  @Test
  void productionRejectsMissingDatabaseCredentials() {
    var env =
        new MockEnvironment()
            .withProperty("LAB_ENVIRONMENT", "prod")
            .withProperty("LAB_JWT_SECRET", "public-test-secret-with-at-least-32-characters");
    assertThatThrownBy(() -> new Settings(env))
        .isInstanceOf(IllegalStateException.class)
        .hasMessageContaining("database credentials");
  }
}
