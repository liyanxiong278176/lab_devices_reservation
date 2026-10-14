package edu.labflow;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Path;
import java.util.List;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

@Component
public class Settings {
  private final Environment env;

  public Settings(Environment env) {
    this.env = env;
    if (prod()) {
      String password = env.getProperty("spring.datasource.password", "");
      String username = env.getProperty("spring.datasource.username", "");
      if (username.isBlank()
          || password.isBlank()
          || List.of(
                  "root", "password", "123456", "change-me", "changeme", "labflow", "labflow-dev")
              .contains(password.toLowerCase()))
        throw new IllegalStateException("Production requires private database credentials");
      if (get("JWT_SECRET", "").toLowerCase().contains("change-me")
          || get("JWT_SECRET", "").toLowerCase().contains("replace-me"))
        throw new IllegalStateException("Production requires a private JWT secret");
    }
    if (get("JWT_SECRET", "").length() < 32)
      throw new IllegalStateException("LAB_JWT_SECRET must contain at least 32 characters");
    if (prod() && (get("JWT_SECRET", "").startsWith("dev-only") || !bool("COOKIE_SECURE", true)))
      throw new IllegalStateException(
          "Production requires a private JWT secret and secure cookies");
  }

  public String get(String key, String fallback) {
    String value = env.getProperty("LAB_" + key);
    if (value == null || value.isBlank()) {
      if (key.equals("JWT_SECRET")) value = env.getProperty("JWT_SECRET");
      else if (key.equals("METRICS_TOKEN")) value = env.getProperty("PROMETHEUS_METRICS_TOKEN");
    }
    return value == null || value.isBlank() ? fallback : value;
  }

  public int integer(String key, int fallback) {
    return Integer.parseInt(get(key, "" + fallback));
  }

  public long longInteger(String key, long fallback) {
    return Long.parseLong(get(key, "" + fallback));
  }

  public boolean bool(String key, boolean fallback) {
    if ((key.equals("ENABLE_WORKERS") || key.equals("ENABLE_NOTIFICATION_RELAY"))
        && (!env.getProperty("labflow.migration", "none").equals("none")
            || !env.getProperty("labflow.fixture", "none").equals("none"))) return false;
    return Boolean.parseBoolean(get(key, "" + fallback));
  }

  public boolean prod() {
    return get("ENVIRONMENT", "local").equals("prod");
  }

  public List<String> origins() {
    try {
      return new ObjectMapper()
          .readValue(
              get("CORS_ORIGINS", "[\"http://localhost:5173\",\"http://127.0.0.1:5173\"]"),
              new TypeReference<>() {});
    } catch (Exception e) {
      throw new IllegalStateException("LAB_CORS_ORIGINS must be a JSON list");
    }
  }

  public Path uploads() {
    Path root = Path.of(env.getRequiredProperty("labflow.root"));
    Path value = Path.of(get("UPLOAD_DIR", ".data/uploads"));
    return (value.isAbsolute() ? value : root.resolve("backend").resolve(value)).normalize();
  }
}
