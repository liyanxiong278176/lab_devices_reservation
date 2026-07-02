/**
 * MyBatis-Plus IPage 分页响应结构（后端 list 接口统一返回）。
 * 后端 JSON 形如：{ records, total, size, current, pages, ... }
 */
export interface Page<T> {
  records: T[]
  total: number
  size: number
  current: number
  pages?: number
}
