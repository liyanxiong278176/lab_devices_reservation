import type { DeviceStatus } from '@/types/device'
import type { ReservationStatus } from '@/types/reservation'

/**
 * 设备状态 → el-tag 类型映射（DESIGN.md badge 调色板）。
 *   IDLE       → success(emerald #34d399)
 *   IN_USE     → primary(blue #3b82f6)
 *   MAINTENANCE→ warning(orange #fb923c)
 */
export function deviceStatusTag(status: DeviceStatus): 'success' | 'primary' | 'warning' | 'info' {
  switch (status) {
    case 'IDLE':
      return 'success'
    case 'IN_USE':
      return 'primary'
    case 'MAINTENANCE':
      return 'warning'
    default:
      return 'info'
  }
}

/**
 * 预约状态 → el-tag 类型 + 中文标签。
 */
export function reservationStatusTag(
  status: ReservationStatus,
): { type: 'info' | 'warning' | 'success' | 'primary' | 'danger'; label: string } {
  const map: Record<ReservationStatus, { type: 'info' | 'warning' | 'success' | 'primary' | 'danger'; label: string }> = {
    PENDING: { type: 'warning', label: '待审批' },
    APPROVED: { type: 'primary', label: '已通过' },
    IN_USE: { type: 'success', label: '使用中' },
    COMPLETED: { type: 'info', label: '已完成' },
    CANCELLED: { type: 'info', label: '已取消' },
    REJECTED: { type: 'danger', label: '已拒绝' },
    VIOLATED: { type: 'danger', label: '已违规' },
    NO_SHOW: { type: 'danger', label: '已爽约' },
  }
  return map[status] ?? { type: 'info', label: status }
}
