import request from './request'

export interface LoginPayload {
  username: string
  password: string
}

export interface UserInfoVO {
  id: number
  username: string
  realName: string
  roles: string[]
  permissions: string[]
}

export interface LoginVO {
  accessToken: string
  refreshToken: string
  expiresIn: number
  userInfo: UserInfoVO
}

export const login = (data: LoginPayload) => request.post<unknown, LoginVO>('/auth/login', data)

// 后端 AuthController.refresh 用 @RequestParam（query/form 参数），非 JSON body
export const refresh = (refreshToken: string) =>
  request.post<unknown, { accessToken: string }>('/auth/refresh', null, {
    params: { refreshToken },
  })

export const getMe = () => request.get<unknown, UserInfoVO>('/auth/me')
