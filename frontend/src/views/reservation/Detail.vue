<script setup lang="ts">
// 预约详情页(R5.2 重构):PageHeader + Timeline 生命周期(创建/审批/签到/归还)
// + 详情 GlowCard + sticky 操作区。数据来源(API)/签到/归还/取消逻辑零改
// ——仅换展示层;Timeline items 由既有 status + 时间字段 computed 组装。
// 设备名通过既有 getDevice 拉取(单一详情页,网络成本可接受),仅用于副标题展示。
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import {
  cancelReservation,
  checkInReservation,
  checkOutReservation,
  getReservation,
} from '@/api/reservation'
import { getDevice } from '@/api/device'
import type { DeviceVO } from '@/types/device'
import type { ReservationStatus, ReservationVO } from '@/types/reservation'
import { reservationStatusTag } from '@/composables/useDeviceStatus'
import PageHeader from '@/components/ui/PageHeader.vue'
import GlowCard from '@/components/ui/GlowCard.vue'
import Tag from '@/components/ui/Tag.vue'
import Timeline from '@/components/ui/Timeline.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'

type TimelineStatus = 'done' | 'current' | 'todo'
interface TimelineItem {
  id: string
  title: string
  desc?: string
  time?: string
  status: TimelineStatus
}

const route = useRoute()
const reservation = ref<ReservationVO | null>(null)
const device = ref<DeviceVO | null>(null)
const loading = ref(false)

const id = computed(() => Number(route.params.id))

async function load() {
  loading.value = true
  try {
    const r = await getReservation(id.value)
    reservation.value = r
    // 拉设备名仅用于副标题展示(沿用既有 getDevice),失败不阻断详情
    try {
      device.value = await getDevice(r.deviceId)
    } catch {
      device.value = null
    }
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function fmt(t?: string): string {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'
}

/** 时长(slotCount × 15min)→ "X 小时 Y 分"。 */
function durationLabel(slots: number): string {
  const mins = slots * 15
  const h = Math.floor(mins / 60)
  const m = mins % 60
  if (h === 0) return `${m} 分`
  if (m === 0) return `${h} 小时`
  return `${h} 小时 ${m} 分`
}

// ---- 状态 → Tag variant 映射 ------------------------------------------------
function statusVariant(s: ReservationStatus): 'success' | 'warning' | 'danger' | 'info' | 'accent' {
  const t = reservationStatusTag(s).type
  if (t === 'primary') return 'accent'
  return t
}

function statusLabel(s: ReservationStatus): string {
  return reservationStatusTag(s).label
}

// ============================================================================
// Timeline 生命周期:由既有 status + 时间字段组装,done/current/todo 三态
// (R1 Timeline 仅支持此三态;错误分支用 done + 描述性标题表达)。
// 顺序:创建 → 审批 → 签到 → 归还;CANCELLED 在审批前中止,REJECTED 在审批处中止。
// ============================================================================
const timelineItems = computed<TimelineItem[]>(() => {
  const r = reservation.value
  if (!r) return []
  const s = r.status
  const items: TimelineItem[] = []

  // 1. 创建(恒发生)
  items.push({
    id: 'created',
    title: '提交预约',
    desc: `预约 #${r.id} · 设备 #${r.deviceId}`,
    time: r.createdAt ? fmt(r.createdAt) : undefined,
    status: 'done',
  })

  // 用户主动取消:在审批节点前/后中止,直接展示取消态并停止后续
  if (s === 'CANCELLED') {
    items.push({
      id: 'cancelled',
      title: '预约已取消',
      desc: '用户主动取消预约',
      status: 'done',
    })
    return items
  }

  // 2. 审批
  if (s === 'PENDING') {
    items.push({
      id: 'approve',
      title: '等待审批',
      desc: '预约已提交,等待管理员审批',
      status: 'current',
    })
  } else if (s === 'REJECTED') {
    items.push({
      id: 'approve',
      title: '审批未通过',
      desc: '管理员拒绝了本次预约',
      status: 'done',
    })
    return items
  } else {
    // APPROVED / IN_USE / COMPLETED / VIOLATED / NO_SHOW —— 审批已通过
    items.push({
      id: 'approve',
      title: '审批通过',
      status: 'done',
    })
  }

  // 3. 签到
  if (s === 'APPROVED') {
    items.push({
      id: 'checkin',
      title: '等待签到',
      desc: `预约时段开始:${fmt(r.startTime)}`,
      status: 'current',
    })
  } else if (s === 'NO_SHOW') {
    items.push({
      id: 'checkin',
      title: '未签到(爽约)',
      desc: '预约时段内未完成签到',
      status: 'done',
    })
    return items
  } else if (s === 'IN_USE') {
    items.push({
      id: 'checkin',
      title: '已签到使用',
      time: fmt(r.startTime),
      status: 'done',
    })
  } else {
    // COMPLETED / VIOLATED —— 已签到
    items.push({
      id: 'checkin',
      title: '已签到',
      time: fmt(r.startTime),
      status: 'done',
    })
  }

  // 4. 归还
  if (s === 'IN_USE') {
    items.push({
      id: 'checkout',
      title: '使用中,待归还',
      desc: `预计 ${fmt(r.endTime)} 结束`,
      status: 'current',
    })
  } else if (s === 'COMPLETED') {
    items.push({
      id: 'checkout',
      title: '已归还完成',
      time: fmt(r.endTime),
      status: 'done',
    })
  } else if (s === 'VIOLATED') {
    items.push({
      id: 'checkout',
      title: '违规结束',
      desc: '未按时归还或违反使用规范',
      status: 'done',
    })
  } else {
    items.push({
      id: 'checkout',
      title: '归还完成',
      status: 'todo',
    })
  }

  return items
})

// ---- 详情 spec 行(展示层增强,数据零改)------------------------------------
const specRows = computed(() => {
  const r = reservation.value
  if (!r) return []
  const deviceName = device.value?.name || `设备 #${r.deviceId}`
  return [
    { label: '设备', value: deviceName },
    { label: '开始时间', value: fmt(r.startTime) },
    { label: '结束时间', value: fmt(r.endTime) },
    { label: '时长', value: durationLabel(r.slotCount) },
    { label: '时段数', value: `${r.slotCount} 个(每段 15 分钟)` },
    { label: '申请人', value: `用户 #${r.userId}` },
  ]
})

// ---- 操作权限(按状态显隐;实际时间窗由后端校验)-------------------------------
function canCancel(): boolean {
  const s = reservation.value?.status
  return s === 'PENDING' || s === 'APPROVED'
}
function canCheckIn(): boolean {
  return reservation.value?.status === 'APPROVED'
}
function canCheckOut(): boolean {
  return reservation.value?.status === 'IN_USE'
}

async function onCancel() {
  if (!reservation.value) return
  const r = reservation.value
  try {
    await ElMessageBox.confirm(`确认取消预约 #${r.id}？`, '取消预约', {
      type: 'warning',
      confirmButtonText: '确认取消',
      cancelButtonText: '保留',
    })
  } catch {
    return
  }
  try {
    await cancelReservation(r.id)
    ElMessage.success('已取消')
    load()
  } catch {
    // 拦截器已提示
  }
}

async function onCheckIn() {
  if (!reservation.value) return
  try {
    await checkInReservation(reservation.value.id)
    ElMessage.success('签到成功')
    load()
  } catch {
    // 拦截器已提示
  }
}

async function onCheckOut() {
  if (!reservation.value) return
  try {
    await ElMessageBox.confirm(
      `确认归还设备(预约 #${reservation.value.id})？`,
      '归还确认',
      { type: 'warning', confirmButtonText: '确认归还', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await checkOutReservation(reservation.value.id)
    ElMessage.success('归还成功')
    load()
  } catch {
    // 拦截器已提示
  }
}

const subtitle = computed(() => {
  const r = reservation.value
  if (!r) return ''
  const name = device.value?.name || `设备 #${r.deviceId}`
  return `${name} · 创建于 ${fmt(r.createdAt)}`
})

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="rsv-detail">
    <!-- hero:PageHeader 标题 + 副标题(设备名 + 创建时间)+ 状态 Tag -->
    <PageHeader title="预约详情" :subtitle="subtitle">
      <template v-if="reservation" #actions>
        <Tag
          :variant="statusVariant(reservation.status)"
          effect="light"
          size="large"
          round
        >
          {{ statusLabel(reservation.status) }}
        </Tag>
      </template>
    </PageHeader>

    <div v-if="reservation" class="rsv-detail__layout">
      <!-- 左:详情 GlowCard(设备/时段/时长/费用/用途/审批人)-->
      <GlowCard as="section" accent class="rsv-detail__main">
        <dl class="rsv-detail__grid">
          <div v-for="row in specRows" :key="row.label" class="rsv-detail__field">
            <dt>{{ row.label }}</dt>
            <dd>{{ row.value }}</dd>
          </div>
        </dl>

        <section class="rsv-detail__purpose">
          <h3 class="rsv-detail__purpose-label">使用用途</h3>
          <p class="rsv-detail__purpose-text">{{ reservation.purpose || '—' }}</p>
        </section>

        <!-- sticky 操作区:签到 / 归还 / 取消,按状态显隐 -->
        <div class="rsv-detail__actions">
          <GradientButton v-if="canCheckIn()" type="primary" @click="onCheckIn">
            签到
          </GradientButton>
          <GradientButton v-if="canCheckOut()" type="primary" @click="onCheckOut">
            归还
          </GradientButton>
          <GhostButton v-if="canCancel()" class="rsv-detail__cancel" @click="onCancel">
            取消预约
          </GhostButton>
        </div>
      </GlowCard>

      <!-- 右:Timeline 生命周期 -->
      <GlowCard as="aside" class="rsv-detail__timeline">
        <div class="rsv-detail__timeline-head">
          <h2 class="rsv-detail__timeline-title">状态流转</h2>
          <p class="rsv-detail__timeline-hint">预约生命周期</p>
        </div>
        <Timeline :items="timelineItems" />
      </GlowCard>
    </div>
  </div>
</template>

<style scoped lang="scss">
.rsv-detail {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding-bottom: 40px;

  // ============================================================================
  // 双栏布局:左侧主信息(详情卡)/ 右侧 Timeline;窄屏堆叠
  // ============================================================================
  &__layout {
    display: grid;
    grid-template-columns: 1.4fr 1fr;
    gap: 20px;
    align-items: start;

    @media (max-width: 960px) {
      grid-template-columns: 1fr;
    }
  }

  // ---- 详情卡 ----------------------------------------------------------------
  &__main {
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 28px;
  }

  &__grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0;
    margin: 0;

    @media (max-width: 720px) {
      grid-template-columns: 1fr;
    }
  }

  &__field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 14px 16px;
    border-bottom: 1px solid var(--border-subtle);

    &:nth-child(odd) {
      border-right: 1px solid var(--border-subtle);

      @media (max-width: 720px) {
        border-right: none;
      }
    }

    dt {
      margin: 0;
      font-size: 11px;
      font-weight: 500;
      color: var(--text-tertiary);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    dd {
      margin: 0;
      font-size: 14px;
      font-weight: 500;
      color: var(--text-primary);
      line-height: 1.5;
      font-variant-numeric: tabular-nums;
      word-break: break-word;
    }
  }

  // ---- 用途区 --------------------------------------------------------------
  &__purpose {
    padding-top: 18px;
    border-top: 1px solid var(--border-subtle);
  }

  &__purpose-label {
    margin: 0 0 8px;
    font-family: var(--font-display);
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary);
    letter-spacing: 0.01em;
  }

  &__purpose-text {
    margin: 0;
    font-size: 14px;
    line-height: 1.7;
    color: var(--text-secondary);
  }

  // ---- 操作区 --------------------------------------------------------------
  &__actions {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    padding-top: 18px;
    border-top: 1px solid var(--border-subtle);
  }

  // 取消按钮:danger 描边(局部覆盖 GhostButton hover 青色)
  &__cancel {
    color: var(--status-danger) !important;
    border-color: color-mix(in srgb, var(--status-danger) 40%, transparent) !important;

    &:hover,
    &:focus {
      background: color-mix(in srgb, var(--status-danger) 8%, transparent) !important;
      color: var(--status-danger) !important;
      border-color: var(--status-danger) !important;
    }
  }

  // ---- Timeline 卡 ---------------------------------------------------------
  &__timeline {
    padding: 24px;
    position: sticky;
    top: 8px;
  }

  &__timeline-head {
    margin-bottom: 20px;
    padding-bottom: 14px;
    border-bottom: 1px solid var(--border-subtle);
  }

  &__timeline-title {
    margin: 0;
    font-family: var(--font-display);
    font-size: 17px;
    font-weight: 600;
    color: var(--text-primary);
    letter-spacing: -0.1px;
  }

  &__timeline-hint {
    margin: 4px 0 0;
    font-size: 12px;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
}
</style>
