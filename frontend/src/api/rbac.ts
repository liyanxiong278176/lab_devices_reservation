import request from './request'

export interface PermissionVO {
  code: string
  name: string
  module: string
  description: string | null
}

export interface RoleVO {
  id: number
  code: string
  name: string
  is_system: boolean
  permissions: string[]
}

export const listPermissions = () => request.get<unknown, PermissionVO[]>('/rbac/permissions')
export const listRoles = () => request.get<unknown, RoleVO[]>('/rbac/roles')
export const createRole = (payload: {
  role_code: string
  role_name: string
  permission_codes: string[]
}) => request.post<unknown, RoleVO>('/rbac/roles', payload)
export const renameRole = (id: number, role_name: string) =>
  request.patch<unknown, RoleVO>(`/rbac/roles/${id}`, { role_name })
export const updateRolePermissions = (id: number, permission_codes: string[]) =>
  request.put<unknown, RoleVO>(`/rbac/roles/${id}/permissions`, { permission_codes })
export const deleteRole = (id: number) => request.delete<unknown, void>(`/rbac/roles/${id}`)
