import request from './request'
import type { UserCreatePayload, UserQuery, UserVO } from '@/types/user'

interface V2User {
  id: number
  username: string
  real_name?: string
  phone?: string
  email?: string
  user_type?: string
  college_id?: number | null
  status: number
  roles: string[]
  created_at?: string
}

interface V2UserPage {
  records: V2User[]
  total: number
  size: number
  current: number
  pages?: number
  truncated: boolean
}

function mapUser(user: V2User): UserVO {
  return {
    id: user.id,
    username: user.username,
    realName: user.real_name,
    phone: user.phone,
    email: user.email,
    userType: user.user_type,
    collegeId: user.college_id,
    status: user.status,
    roles: user.roles,
    createdAt: user.created_at,
  }
}

/**
 * 用户管理接口（对齐 UserController）。全部需 user:manage 权限（仅 SYS_ADMIN）。
 *
 * 关键契约：
 *  - GET    /users                  → 分页检索（UserQueryDTO 为 query 参数）
 *  - POST   /users                  → 创建（body UserCreateDTO）
 *  - PUT    /users/{id}             → 更新（body UserCreateDTO，username 不可改；password 空则不改）
 *  - DELETE /users/{id}             → 删除（禁止删自己）
 *  - PATCH  /users/{id}/status?status=0|1 → 封禁/解封（status 为 @RequestParam）
 */
export const listUsers = (q: UserQuery = {}) =>
  request
    .get<unknown, V2UserPage>('/users', {
      params: {
        username: q.username,
        real_name: q.realName,
        status: q.status,
        page: q.page,
        size: q.size,
      },
    })
    .then((data) => ({
      records: data.records.map(mapUser),
      total: data.total,
      size: data.size,
      current: data.current,
      pages: data.pages,
      truncated: data.truncated,
    }))

export const createUser = (data: UserCreatePayload) =>
  request.post<unknown, UserVO>('/users', {
    username: data.username,
    password: data.password,
    real_name: data.realName,
    phone: data.phone,
    email: data.email,
    user_type: data.userType,
    role_codes: data.roleCodes,
    college_id: data.collegeId,
  })

export const updateUser = (id: number, data: UserCreatePayload) =>
  request.put<unknown, UserVO>(`/users/${id}`, {
    username: data.username,
    password: data.password,
    real_name: data.realName,
    phone: data.phone,
    email: data.email,
    user_type: data.userType,
    role_codes: data.roleCodes,
    college_id: data.collegeId,
  })

export const deleteUser = (id: number) =>
  request.delete<unknown, void>(`/users/${id}`)

// status 为 @RequestParam（query string），非 body
export const patchUserStatus = (id: number, status: number) =>
  request.patch<unknown, void>(`/users/${id}/status`, null, { params: { status } })
