import request from './request'
import type { CollegeVO, CollegeWritePayload, ManagerVO } from '@/types/college'

interface V2College {
  id: number
  code: string
  name: string
  manager_id?: number | null
  manager_name?: string | null
}

interface V2Manager {
  id: number
  username: string
  real_name?: string | null
  college_id: number
}

export const listColleges = () =>
  request.get<unknown, V2College[]>('/colleges').then((rows) =>
    rows.map((row) => ({
      id: row.id,
      code: row.code,
      name: row.name,
      managerId: row.manager_id,
      managerName: row.manager_name,
    } satisfies CollegeVO)),
  )

export const listManagers = (collegeId: number) =>
  request.get<unknown, V2Manager[]>('/organization/managers', { params: { college_id: collegeId } }).then((rows) =>
    rows.map((row) => ({
      id: row.id,
      username: row.username,
      realName: row.real_name,
      collegeId: row.college_id,
    } satisfies ManagerVO)),
  )

const payload = (data: CollegeWritePayload) => ({
  code: data.code,
  name: data.name,
  manager_id: data.managerId ?? null,
})

export const createCollege = (data: CollegeWritePayload) =>
  request.post<unknown, CollegeVO>('/colleges', payload(data))

export const updateCollege = (id: number, data: CollegeWritePayload) =>
  request.put<unknown, CollegeVO>(`/colleges/${id}`, payload(data))
