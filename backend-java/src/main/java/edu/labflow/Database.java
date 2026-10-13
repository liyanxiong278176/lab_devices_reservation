package edu.labflow;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.sql.Date;
import java.sql.Timestamp;
import java.util.*;
import org.springframework.stereotype.Component;

@Component
public class Database {
  private final SqlMapper mapper;
  private final ObjectMapper json;

  public Database(SqlMapper mapper, ObjectMapper json) {
    this.mapper = mapper;
    this.json = json;
  }

  public List<Map<String, Object>> rows(String sql, Object... params) {
    return mapper.select(args(sql, params)).stream().map(this::normalize).toList();
  }

  public Map<String, Object> one(String sql, Object... params) {
    var rows = rows(sql, params);
    return rows.isEmpty() ? null : rows.getFirst();
  }

  public long count(String sql, Object... params) {
    Long value = mapper.scalar(args(sql, params));
    return value == null ? 0 : value;
  }

  public int execute(String sql, Object... params) {
    return mapper.update(args(sql, params));
  }

  public long insert(String sql, Object... params) {
    var args = args(sql, params);
    mapper.insert(args);
    return ((Number) args.get("generated_id")).longValue();
  }

  private Map<String, Object> args(String sql, Object[] values) {
    var args = new HashMap<String, Object>();
    var rendered = new StringBuilder();
    int index = 0;
    for (char ch : sql.toCharArray()) {
      if (ch == '?') {
        rendered.append("#{p").append(index).append("}");
        args.put("p" + index, values[index++]);
      } else rendered.append(ch);
    }
    if (index != values.length) throw new IllegalArgumentException("SQL parameter count mismatch");
    args.put("_sql", rendered.toString());
    return args;
  }

  private Map<String, Object> normalize(Map<String, Object> row) {
    row.replaceAll(
        (key, value) -> {
          if (value instanceof Timestamp t) return t.toLocalDateTime();
          if (value instanceof Date d) return d.toLocalDate();
          if (value instanceof byte[] bytes)
            return new String(bytes, java.nio.charset.StandardCharsets.UTF_8);
          return value;
        });
    return row;
  }

  public String json(Object value) {
    try {
      return json.writeValueAsString(value);
    } catch (Exception e) {
      throw new IllegalArgumentException(e);
    }
  }

  public Object parse(Object value, Object fallback) {
    if (value == null) return fallback;
    if (!(value instanceof String s)) return value;
    try {
      return json.readValue(s, Object.class);
    } catch (Exception e) {
      return fallback;
    }
  }

  public static long id(Map<String, Object> row, String key) {
    Object v = row.get(key);
    if (v == null) return 0;
    if (v instanceof Boolean b) return b ? 1 : 0;
    if (!(v instanceof Number n) || n.doubleValue() != n.longValue())
      throw ApiError.validation("整数参数无效");
    return n.longValue();
  }

  public static String str(Map<String, Object> row, String key, String fallback) {
    return row.get(key) == null ? fallback : row.get(key).toString();
  }
}
