package edu.labflow;

import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.*;

/** SQL is supplied exclusively by application code; values always use MyBatis bound parameters. */
@Mapper
public interface SqlMapper {
  @SelectProvider(type = Statements.class, method = "sql")
  List<Map<String, Object>> select(Map<String, Object> args);

  @SelectProvider(type = Statements.class, method = "sql")
  Long scalar(Map<String, Object> args);

  @UpdateProvider(type = Statements.class, method = "sql")
  int update(Map<String, Object> args);

  @InsertProvider(type = Statements.class, method = "sql")
  @Options(useGeneratedKeys = true, keyProperty = "generated_id")
  int insert(Map<String, Object> args);

  class Statements {
    public static String sql(Map<String, Object> args) {
      return (String) args.get("_sql");
    }
  }
}
