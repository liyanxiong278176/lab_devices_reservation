/** 用户视图（vo/user/UserVO.java），不含 password。 */
export interface UserVO {
  id: number
  username: string
  realName?: string
  phone?: string
  email?: string
  userType?: string
  deptName?: string
  /** 0 禁用 / 1 启用 */
  status: number
  roles: string[]
  createdAt?: string
}

/** 用户创建/更新参数（dto/user/UserCreateDTO.java）。 */
export interface UserCreatePayload {
  username: string
  /** 创建必填；更新为空表示不改密码 */
  password?: string
  realName?: string
  phone?: string
  email?: string
  userType?: string
  deptName?: string
  roleCodes?: string[]
}

/** 用户列表分页检索参数（dto/user/UserQueryDTO.java）。 */
export interface UserQuery {
  username?: string
  realName?: string
  /** 0 禁用 / 1 启用 */
  status?: number
  page?: number
  size?: number
}
