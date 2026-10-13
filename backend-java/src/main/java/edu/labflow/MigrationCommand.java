package edu.labflow;

import javax.sql.DataSource;
import org.flywaydb.core.Flyway;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

@Component
public class MigrationCommand implements ApplicationRunner {
  private final DataSource dataSource;
  private final SchemaVerifier schema;
  private final Environment env;
  private final org.springframework.data.redis.core.StringRedisTemplate redis;

  public MigrationCommand(
      DataSource dataSource,
      SchemaVerifier schema,
      Environment env,
      org.springframework.data.redis.core.StringRedisTemplate redis) {
    this.dataSource = dataSource;
    this.schema = schema;
    this.env = env;
    this.redis = redis;
  }

  @Override
  public void run(ApplicationArguments args) {
    String action = env.getProperty("labflow.migration", "none");
    if (action.equals("none")) return;
    var flyway =
        Flyway.configure()
            .dataSource(dataSource)
            .baselineVersion("1")
            .baselineOnMigrate(false)
            .cleanDisabled(true)
            .load();
    switch (action) {
      case "verify" -> {
        var differences = schema.differences();
        if (!differences.isEmpty()) throw new IllegalStateException(String.join("; ", differences));
      }
      case "baseline" -> {
        schema.requireLegacyHead();
        flyway.baseline();
      }
      case "migrate" -> flyway.migrate();
      case "invalidate-sessions" -> {
        for (String pattern :
            java.util.List.of("lab:v2:auth:session:*", "lab:v2:auth:user-sessions:*"))
          try (var cursor =
              redis.scan(
                  org.springframework.data.redis.core.ScanOptions.scanOptions()
                      .match(pattern)
                      .count(200)
                      .build())) {
            var batch = new java.util.ArrayList<String>();
            while (cursor.hasNext()) {
              batch.add(cursor.next());
              if (batch.size() == 200) {
                redis.unlink(batch);
                batch.clear();
              }
            }
            if (!batch.isEmpty()) redis.unlink(batch);
          }
      }
      default ->
          throw new IllegalArgumentException(
              "Supported migration commands: verify, baseline, migrate, invalidate-sessions");
    }
  }
}
