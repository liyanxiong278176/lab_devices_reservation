import request from './request'

export interface LoginPayload {
  username: string
  password: string
}

export interface RegisterPayload extends LoginPayload {
  real_name: string
  college_id: number
}

export interface UserInfoVO {
  id: number
  username: string
  real_name: string | null
  college_id: number | null
  roles: string[]
  permissions: string[]
}

export interface SessionVO {
  authenticated: boolean
  expires_in: number
  csrf_token: string
}

export interface PublicCollegeVO {
  id: number
  code: string
  name: string
}

export const getCsrf = () => request.get<unknown, { csrf_token: string }>('/auth/csrf')

export const listRegistrationColleges = () =>
  request.get<unknown, PublicCollegeVO[]>('/auth/colleges')

export const login = (data: LoginPayload) =>
  request.post<unknown, SessionVO>('/auth/login', data)

export const register = (data: RegisterPayload) =>
  request.post<unknown, SessionVO>('/auth/register', data)

export const refresh = () => request.post<unknown, SessionVO>('/auth/refresh', {})

export const getMe = () => request.get<unknown, UserInfoVO>('/auth/me')

export const logout = () => request.post<unknown, void>('/auth/logout', {})
