package edu.labflow;

import io.github.cdimascio.dotenv.Dotenv;
import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.HashMap;
import org.springframework.context.ApplicationContextInitializer;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.MapPropertySource;

/** Reads the repository's single .env; command-line and process environment take precedence. */
public class RuntimeEnvironment
    implements ApplicationContextInitializer<ConfigurableApplicationContext> {
  @Override
  public void initialize(ConfigurableApplicationContext context) {
    Path cwd = Path.of("").toAbsolutePath();
    Path root = cwd.getFileName().toString().equals("backend-java") ? cwd.getParent() : cwd;
    var dotenv = Dotenv.configure().directory(root.toString()).ignoreIfMissing().load();
    var properties = new HashMap<String, Object>();
    dotenv.entries().stream()
        .filter(e -> !e.getValue().isBlank())
        .forEach(e -> properties.put(e.getKey(), e.getValue()));
    context
        .getEnvironment()
        .getPropertySources()
        .addLast(new MapPropertySource("root-dotenv", properties));
    var env = context.getEnvironment();
    var connection = new HashMap<String, Object>();
    for (var entry :
        java.util.Map.of(
                "LAB_JWT_SECRET", "JWT_SECRET", "LAB_METRICS_TOKEN", "PROMETHEUS_METRICS_TOKEN")
            .entrySet()) {
      String existing = env.getProperty(entry.getKey()), shared = env.getProperty(entry.getValue());
      if ((existing == null || existing.isBlank()) && shared != null && !shared.isBlank())
        connection.put(entry.getKey(), shared);
    }
    String jdbc = env.getProperty("LAB_JDBC_URL");
    if (jdbc != null && !jdbc.isBlank()) {
      connection.put("spring.datasource.url", jdbc);
      connection.put("spring.datasource.username", env.getProperty("LAB_DB_USERNAME", ""));
      connection.put("spring.datasource.password", env.getProperty("LAB_DB_PASSWORD", ""));
    } else {
      String dsn = env.getProperty("LAB_MYSQL_DSN");
      if (dsn == null) throw new IllegalStateException("LAB_JDBC_URL or LAB_MYSQL_DSN is required");
      URI uri = URI.create(dsn.replace("mysql+asyncmy://", "mysql://"));
      String[] auth = uri.getRawUserInfo().split(":", 2);
      connection.put(
          "spring.datasource.url",
          "jdbc:mysql://"
              + uri.getHost()
              + ":"
              + (uri.getPort() < 0 ? 3306 : uri.getPort())
              + uri.getPath()
              + "?connectionTimeZone=UTC&characterEncoding=UTF-8");
      connection.put("spring.datasource.username", decode(auth[0]));
      connection.put("spring.datasource.password", auth.length > 1 ? decode(auth[1]) : "");
    }
    URI redis = URI.create(env.getProperty("LAB_REDIS_URL", "redis://127.0.0.1:6379/0"));
    connection.put("spring.data.redis.host", redis.getHost());
    connection.put("spring.data.redis.port", redis.getPort() < 0 ? 6379 : redis.getPort());
    connection.put(
        "spring.data.redis.database",
        redis.getPath().length() > 1 ? redis.getPath().substring(1) : "0");
    if (redis.getRawUserInfo() != null) {
      var auth = redis.getRawUserInfo().split(":", 2);
      if (auth.length > 1 && !auth[0].isEmpty())
        connection.put("spring.data.redis.username", decode(auth[0]));
      connection.put("spring.data.redis.password", decode(auth[auth.length - 1]));
    }
    connection.put("spring.data.redis.ssl.enabled", "rediss".equals(redis.getScheme()));
    connection.put("labflow.root", root.toString());
    context
        .getEnvironment()
        .getPropertySources()
        .addLast(new MapPropertySource("labflow-connections", connection));
  }

  private static String decode(String value) {
    return URLDecoder.decode(value.replace("+", "%2B"), StandardCharsets.UTF_8);
  }
}
