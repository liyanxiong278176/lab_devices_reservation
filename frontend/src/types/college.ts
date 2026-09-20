export interface CollegeVO {
  id: number
  code: string
  name: string
  managerId?: number | null
  managerName?: string | null
}

export interface ManagerVO {
  id: number
  username: string
  realName?: string | null
  collegeId: number
}

export interface CollegeWritePayload {
  code: string
  name: string
  managerId?: number | null
}
