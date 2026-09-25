<script setup lang="ts">
// 预约详情页:展示预约、审批、负责人交接、用户归还和负责人验收的完整生命周期。
// ——仅换展示层;Timeline items 由既有 status + 时间字段 computed 组装。
// 设备名通过既有 getDevice 拉取(单一详情页,网络成本可接受),仅用于副标题展示。
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import {
  cancelReservation,
  checkOutReservation,
  getReservationFeedback,
  getReservation,
  submitReservationFeedback,
} from '@/api/reservation'
import { uploadRepairImage } from '@/api/repair'
import type { ReservationFeedbackVO } from '@/api/reservation'
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
const returnDialogVisible = ref(false)
const returnCondition = ref<'NORMAL' | 'DAMAGED' | 'MISSING'>('NORMAL')
const returnNote = ref('')
const returnPhotoFiles = ref<File[]>([])
const feedback = ref<ReservationFeedbackVO | null>(null)
const feedbackDialogVisible = ref(false)
const feedbackRating = ref(5)
const feedbackComment = ref('')
const feedbackSubmitting = ref(false)

const id = computed(() => Number(route.params.id))

async function load() {
  loading.value = true
  try {
    const r = await getReservation(id.value)
    reservation.value = r
    feedback.value = r.status === 'COMPLETED' ? await getReservationFeedback(r.id) : null
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
  return t ? dayjs(t).format('YYYY-MM-DD') : '—'
}

function inspectionLabel(condition?: ReservationVO['inspectionCondition']): string {
  if (condition === 'DAMAGED') return '发现损坏'
  if (condition === 'MISSING') return '设备缺失'
  if (condition === 'NORMAL') return '验收正常'
  return '—'
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
// 顺序:提交 → 审批 → 负责人交接 → 用户归还 → 负责人验收。
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

  // 3. 负责人现场交接；规则切换时已在使用中的预约不补造交接人/时间。
  if (s === 'NO_SHOW') {
    items.push({
      id: 'handover',
      title: '未按时办理交接',
      desc: '预约首日未完成交接，系统已标记爽约',
      status: 'done',
    })
    return items
  }
  const handoverDone = ['IN_USE', 'COMPLETED', 'VIOLATED'].includes(s)
  const legacyInUse = r.handoverStatus === 'LEGACY_IN_USE'
  items.push({
    id: 'handover',
    title: s === 'APPROVED'
      ? '等待负责人交接'
      : legacyInUse
        ? '规则调整前已开始使用'
        : handoverDone
          ? '负责人已完成交接'
          : '待负责人交接',
    desc: s === 'APPROVED'
      ? `预约首日：${fmt(r.startDate || r.startTime)}`
      : legacyInUse
        ? '预约在统一交接规则启用前已开始使用；实际归还后仍需负责人验收。'
        : undefined,
    time: handoverDone && !legacyInUse ? fmt(r.checkInAt) : undefined,
    status: s === 'APPROVED' ? 'current' : handoverDone ? 'done' : 'todo',
  })

  // 4. 使用与归还申请
  if (s === 'IN_USE' && r.handoverStatus !== 'RETURN_PENDING') {
    items.push({
      id: 'return-request',
      title: '使用中，待归还',
      desc: `预约结束日：${fmt(r.endDate || r.endTime)}`,
      status: 'current',
    })
  } else if ((s === 'IN_USE' && r.handoverStatus === 'RETURN_PENDING') || s === 'COMPLETED') {
    items.push({
      id: 'return-request',
      title: s === 'COMPLETED' ? '设备已归还' : '设备已归还，等待验收',
      desc: s === 'COMPLETED' ? undefined : `预约结束日：${fmt(r.endDate || r.endTime)}`,
      time: s === 'COMPLETED' ? fmt(r.checkOutAt) : undefined,
      status: 'done',
    })
  } else if (s === 'VIOLATED') {
    items.push({
      id: 'return-request',
      title: '预约已违规终止',
      desc: r.rejectReason || '预约履约流程被负责人终止',
      status: 'done',
    })
  } else {
    items.push({ id: 'return-request', title: '等待预约开始并归还', status: 'todo' })
  }

  // 5. 负责人归还验收
  if (s === 'IN_USE' && r.handoverStatus === 'RETURN_PENDING') {
    items.push({ id: 'acceptance', title: '等待负责人验收', status: 'current' })
  } else if (s === 'COMPLETED') {
    items.push({
      id: 'acceptance',
      title: '负责人已完成验收',
      time: fmt(r.checkOutAt),
      status: 'done',
    })
  } else if (s === 'VIOLATED') {
    items.push({ id: 'acceptance', title: '预约流程已终止', status: 'done' })
  } else {
    items.push({ id: 'acceptance', title: '待负责人验收', status: 'todo' })
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
    { label: '开始日期', value: fmt(r.startDate || r.startTime) },
    { label: '结束日期', value: fmt(r.endDate || r.endTime) },
    { label: '预约天数', value: `${r.slotCount} 天` },
    { label: '计费粒度', value: '自然日' },
    { label: '申请人', value: `用户 #${r.userId}` },
    { label: '交接状态', value: handoverLabel(r.handoverStatus) },
    { label: '交接/开始使用时间', value: fmt(r.checkInAt) },
    { label: '归还时间', value: fmt(r.checkOutAt) },
    { label: '归还验收', value: inspectionLabel(r.inspectionCondition) },
    { label: '验收备注', value: r.inspectionNote || '—' },
    ...(r.status === 'REJECTED'
      ? [{ label: '驳回原因', value: r.rejectReason || '负责人未填写原因' }]
      : []),
    ...(feedback.value
      ? [{ label: '使用评价', value: `${feedback.value.rating} / 5${feedback.value.comment ? ` · ${feedback.value.comment}` : ''}` }]
      : []),
  ]
})

function handoverLabel(status?: string): string {
  const labels: Record<string, string> = {
    PENDING: '待负责人交接',
    HANDED_OVER: '已交接',
    LEGACY_IN_USE: '规则调整前已开始使用，归还后待验收',
    RETURN_PENDING: '已归还，待负责人验收',
    RETURNED: '已完成归还验收',
    CANCELLED: '交接流程已取消',
    NOT_REQUIRED: '历史记录无需交接',
  }
  return status ? labels[status] || status : '待负责人交接'
}

// ---- 操作权限(按状态显隐;实际时间窗由后端校验)-------------------------------
function canCancel(): boolean {
  const s = reservation.value?.status
  return s === 'PENDING' || s === 'APPROVED'
}
function canCheckOut(): boolean {
  return reservation.value?.status === 'IN_USE'
    && reservation.value?.handoverStatus !== 'RETURN_PENDING'
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

function openReturnDialog() {
  if (!reservation.value) return
  returnCondition.value = 'NORMAL'
  returnNote.value = ''
  returnPhotoFiles.value = []
  returnDialogVisible.value = true
}

function onReturnPhotoChange(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (files.length < 1 || files.length > 6) {
    ElMessage.warning('请上传 1 至 6 张归还现场照片')
    returnPhotoFiles.value = []
    input.value = ''
    return
  }
  if (files.some((file) => file.size > 5 * 1024 * 1024 || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type))) {
    ElMessage.warning('照片仅支持 5 MB 以内 JPG、PNG 或 WebP')
    returnPhotoFiles.value = []
    input.value = ''
    return
  }
  returnPhotoFiles.value = files
}

function openFeedbackDialog() {
  feedbackRating.value = 5
  feedbackComment.value = ''
  feedbackDialogVisible.value = true
}

async function submitFeedback() {
  if (!reservation.value) return
  feedbackSubmitting.value = true
  try {
    feedback.value = await submitReservationFeedback(reservation.value.id, {
      rating: feedbackRating.value,
      comment: feedbackComment.value.trim() || undefined,
    })
    feedbackDialogVisible.value = false
    ElMessage.success('评价已提交')
  } catch {
    // 拦截器已提示
  } finally {
    feedbackSubmitting.value = false
  }
}

async function submitReturn() {
  if (!reservation.value) return
  try {
    if (returnPhotoFiles.value.length === 0) {
      ElMessage.warning('请先上传 1 至 6 张归还现场照片')
      return
    }
    const uploads = await Promise.all(returnPhotoFiles.value.map((file) => uploadRepairImage(file)))
    await checkOutReservation(reservation.value.id, {
      condition: returnCondition.value,
      note: returnNote.value.trim() || undefined,
      imageUrls: uploads.map((image) => image.url),
    })
    returnDialogVisible.value = false
    ElMessage.success('已提交归还，等待负责人验收')
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
    <PageHeader back title="预约详情" :subtitle="subtitle">
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

        <!-- sticky 操作区:归还 / 取消,负责人交接后才会进入使用中 -->
        <div class="rsv-detail__actions">
          <GradientButton v-if="canCheckOut()" type="primary" @click="openReturnDialog">
            归还
          </GradientButton>
          <GhostButton
            v-if="reservation.status === 'COMPLETED' && !feedback"
            @click="openFeedbackDialog"
          >
            评价设备
          </GhostButton>
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

    <el-dialog v-model="returnDialogVisible" title="提交归还" width="520px">
      <div class="rsv-detail__return-form">
        <p class="rsv-detail__return-hint">
          设备实际归还后提交申请；请如实说明设备状态，负责人将现场验收。
        </p>
        <el-radio-group v-model="returnCondition">
          <el-radio value="NORMAL">设备状态正常</el-radio>
          <el-radio value="DAMAGED">发现损坏</el-radio>
          <el-radio value="MISSING">设备缺失</el-radio>
        </el-radio-group>
        <el-input
          v-model="returnNote"
          type="textarea"
          :rows="4"
          maxlength="1000"
          show-word-limit
          placeholder="补充验收备注（可选）"
        />
        <label class="rsv-detail__return-photos">
          <span>归还现场照片（必填，1–6 张）</span>
          <input type="file" accept="image/jpeg,image/png,image/webp" multiple @change="onReturnPhotoChange" />
          <small>{{ returnPhotoFiles.length }} 张已选择</small>
        </label>
      </div>
      <template #footer>
        <GhostButton @click="returnDialogVisible = false">取消</GhostButton>
        <GradientButton type="primary" @click="submitReturn">确认归还</GradientButton>
      </template>
    </el-dialog>

    <el-dialog v-model="feedbackDialogVisible" title="评价本次使用" width="520px">
      <div class="rsv-detail__feedback-form">
        <span class="rsv-detail__return-hint">你的反馈会帮助负责人持续改善设备服务。</span>
        <el-rate v-model="feedbackRating" size="large" />
        <el-input
          v-model="feedbackComment"
          type="textarea"
          :rows="4"
          maxlength="500"
          show-word-limit
          placeholder="分享一下设备状态或使用体验（可选）"
        />
      </div>
      <template #footer>
        <GhostButton @click="feedbackDialogVisible = false">取消</GhostButton>
        <GradientButton :loading="feedbackSubmitting" type="primary" @click="submitFeedback">
          提交评价
        </GradientButton>
      </template>
    </el-dialog>
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

  &__return-form {
    display: grid;
    gap: 16px;
  }

  &__feedback-form {
    display: grid;
    gap: 16px;
  }

  &__return-hint {
    margin: 0;
    color: var(--text-secondary);
    font-size: 13px;
    line-height: 1.6;
  }

  &__return-photos {
    display: grid;
    gap: 8px;
    color: var(--text-secondary);
    font-size: 12px;

    input { color: var(--text-tertiary); }
    small { color: var(--text-tertiary); }
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
