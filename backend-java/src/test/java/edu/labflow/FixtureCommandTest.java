package edu.labflow;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

import org.junit.jupiter.api.Test;
import org.springframework.boot.DefaultApplicationArguments;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.transaction.PlatformTransactionManager;

class FixtureCommandTest {
  @Test
  void refusesBusinessDatabaseBeforeStartingTransaction() {
    var env =
        environment("e2e-example123")
            .withProperty("spring.datasource.url", "jdbc:mysql://127.0.0.1/lab_reservation");
    var db = mock(Database.class);
    var tm = mock(PlatformTransactionManager.class);
    var command = new FixtureCommand(db, null, env, tm, new Settings(env), null, null);
    assertThatThrownBy(() -> command.run(new DefaultApplicationArguments()))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("database named");
    verifyNoInteractions(db, tm);
  }

  @Test
  void refusesUnscopedPrefixBeforeStartingTransaction() {
    var env = environment("admin");
    var db = mock(Database.class);
    var tm = mock(PlatformTransactionManager.class);
    var command = new FixtureCommand(db, null, env, tm, new Settings(env), null, null);
    assertThatThrownBy(() -> command.run(new DefaultApplicationArguments()))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("isolated e2e prefix");
    verifyNoInteractions(db, tm);
  }

  private MockEnvironment environment(String prefix) {
    return new MockEnvironment()
        .withProperty("LAB_JWT_SECRET", "public-test-secret-with-at-least-32-characters")
        .withProperty("LAB_ENVIRONMENT", "test")
        .withProperty("labflow.fixture", "seed")
        .withProperty("prefix", prefix);
  }
}
