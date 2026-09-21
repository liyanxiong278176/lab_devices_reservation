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
  /** Keyset pagination metadata; page-number UI may use it to build a cursor chain. */
  nextCursor?: number | null
  hasMore?: boolean
}
