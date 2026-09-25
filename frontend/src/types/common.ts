/**
 * 后端列表接口统一返回的分页结构。
 * 后端 JSON 形如：{ records, total, size, current, pages, ... }
 */
export interface Page<T> {
  records: T[]
  total: number
  size: number
  current: number
  pages?: number
  /** True when the full result set extends beyond the 100,000-row deep-page cap. */
  truncated?: boolean
}
