import request from './request'

export interface LoginPayload {
  username: string
  password: string
}

export interface UserInfoVO {
  id: number
  username: string
  real_name: string | null
  college_id: number | null
  roles: string[]
}

export interface TokenVO {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export const login = (data: LoginPayload) => request.post<unknown, TokenVO>('/auth/login', data)

export const refresh = (refreshToken: string) =>
  request.post<unknown, TokenVO>('/auth/refresh', { refresh_token: refreshToken })

export const getMe = () => request.get<unknown, UserInfoVO>('/auth/me')

export const logout = (refreshToken: string) =>
  request.post<unknown, void>('/auth/logout', { refresh_token: refreshToken })
