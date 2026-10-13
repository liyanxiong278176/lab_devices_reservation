package edu.labflow;

import java.util.*;

public record Pagination(int page, int size) {
  public Pagination {
    if (page < 1 || size < 1 || size > 200 || ((long) page - 1) * size > 100000)
      throw new ApiError("PAGE_DEPTH_EXCEEDED", "请缩小筛选范围后重试", 422);
  }

  public int offset() {
    return (page - 1) * size;
  }

  public Map<String, Object> result(List<?> items, long total) {
    long actual = (total + size - 1) / size, accessible = 100000 / size + 1;
    return Map.of(
        "items",
        items,
        "total",
        total,
        "page",
        page,
        "page_size",
        size,
        "pages",
        Math.min(actual, accessible),
        "truncated",
        actual > accessible);
  }

  public Map<String, Object> legacy(List<?> items, long total) {
    var result = new HashMap<>(result(items, total));
    result.put("records", result.remove("items"));
    result.put("current", result.remove("page"));
    result.put("size", result.remove("page_size"));
    return result;
  }
}
