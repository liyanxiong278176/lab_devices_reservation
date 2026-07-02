/**
 * 待审批列表项（vo/approval/ApprovalItemVO.java）。
 *
 * 在 reservation 基础字段之外附带 deviceName / username / realName，
 * 便于前端直接展示「谁 / 用哪个设备 / 何时 / 用途」。
 */
export interface ApprovalItemVO {
  id: number
  userId: number
  username: string
  realName?: string
  deviceId: number
  deviceName: string
  purpose?: string
  startTime: string
  endTime: string
  slotCount?: number
  /** 列表来源即 PENDING */
  status: string
  createdAt?: string
}
