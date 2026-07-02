import request from './request'
import type { Page } from '@/types/common'
import type { UserCreatePayload, UserQuery, UserVO } from '@/types/user'

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
  request.get<unknown, Page<UserVO>>('/users', { params: q })

export const createUser = (data: UserCreatePayload) =>
  request.post<unknown, UserVO>('/users', data)

export const updateUser = (id: number, data: UserCreatePayload) =>
  request.put<unknown, UserVO>(`/users/${id}`, data)

export const deleteUser = (id: number) =>
  request.delete<unknown, void>(`/users/${id}`)

// status 为 @RequestParam（query string），非 body
export const patchUserStatus = (id: number, status: number) =>
  request.patch<unknown, void>(`/users/${id}/status`, null, { params: { status } })
