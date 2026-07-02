/** 实验室（entity/Lab.java）。 */
export interface Lab {
  id: number
  name: string
  location?: string
  managerId?: number
  description?: string
  /** 0 禁用 / 1 启用 */
  status?: number
  createdAt?: string
  updatedAt?: string
}
