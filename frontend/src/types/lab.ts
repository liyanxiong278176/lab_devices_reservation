/** 实验室（entity/Lab.java）。 */
export interface Lab {
  id: number
  name: string
  collegeId?: number | null
  collegeName?: string | null
  location?: string
  managerId?: number | null
  managerName?: string | null
  description?: string
  /** 0 禁用 / 1 启用 */
  status?: number
  createdAt?: string
  updatedAt?: string
}

export interface LabWritePayload {
  collegeId: number
  name: string
  location?: string
  managerId?: number | null
  description?: string
}
