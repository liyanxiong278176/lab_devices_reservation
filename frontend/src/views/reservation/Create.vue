<script setup lang="ts">
// 建预约页(R5 重构):多步 stepper + 实时摘要 + 渐变提交。
// 数据/校验/提交逻辑零改——沿用既有 range 检查 + form.validate + createReservation,
// 仅换展示层:el-steps(深色青色进度)+ 双列布局(主表单 / sticky GlowCard 实时摘要)
// + 底部 GradientButton 提交 / GhostButton 上一步-取消。
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import dayjs from 'dayjs'
import { getDevice } from '@/api/device'
import { createReservation } from '@/api/reservation'
import type { DeviceVO } from '@/types/device'
import type { ReservationCreatePayload } from '@/types/reservation'
import PageHeader from '@/components/ui/PageHeader.vue'
import GlowCard from '@/components/ui/GlowCard.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import StatusDot from '@/components/ui/StatusDot.vue'

const route = useRoute()
const router = useRouter()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const deviceLoading = ref(false)
const device = ref<DeviceVO | null>(null)

// [startTime, endTime] — datetimerange(value-format="x" → 时间戳字符串)
const range = ref<[Date, Date] | null>(null)
const form = reactive({
  purpose: '',
})

const rules: FormRules = {
  purpose: [{ required: true, message: '请填写使用用途', trigger: 'blur' }],
}

const deviceId = computed(() => Number(route.query.deviceId))

// ---- stepper 状态 --------------------------------------------------------
// 既有页是单表单无 stepper,按内容自然分段造 3 步:选时段 / 填用途 / 确认提交。
// 0=选时段 / 1=填用途 / 2=确认提交
const active = ref(0)
const steps = [
  { title: '选择时段', description: '设备 + 起止时间' },
  { title: '填写用途', description: '说明本次使用' },
  { title: '确认提交', description: '复核并提交' },
]

async function loadDevice() {
  if (!deviceId.value || Number.isNaN(deviceId.value)) return
  deviceLoading.value = true
  try {
    device.value = await getDevice(deviceId.value)
  } catch {
    // 拦截器已提示
  } finally {
    deviceLoading.value = false
  }
}

function toIso(d: Date): string {
  // 后端接收 LocalDateTime（ISO yyyy-MM-ddTHH:mm:ss）
  return dayjs(d).format('YYYY-MM-DDTHH:mm:ss')
}

// ---- 实时摘要 computed(纯展示派生,不改逻辑)----------------------------
const startLabel = computed(() =>
  range.value && range.value[0]
    ? dayjs(range.value[0]).format('MM-DD HH:mm')
    : '—',
)
const endLabel = computed(() =>
  range.value && range.value[1]
    ? dayjs(range.value[1]).format('MM-DD HH:mm')
    : '—',
)
const durationHours = computed(() => {
  if (!range.value || range.value.length !== 2 || !range.value[0] || !range.value[1]) return 0
  const ms = dayjs(range.value[1]).valueOf() - dayjs(range.value[0]).valueOf()
  return ms > 0 ? ms / 3_600_000 : 0
})
const durationLabel = computed(() => {
  const h = durationHours.value
  if (!h) return '—'
  const hh = Math.floor(h)
  const m = Math.round((h - hh) * 60)
  return m > 0 ? `${hh} 时 ${m} 分` : `${hh} 时`
})
const pricePerHourNum = computed(() => {
  const p = device.value?.pricePerHour
  if (p == null || p === '') return 0
  const n = Number(p)
  return Number.isFinite(n) ? n : 0
})
// 费用估算 = 单价 × 时长(spec §7 建预约行:实时摘要费用估算)
const costEstimate = computed(() => {
  if (!durationHours.value || !pricePerHourNum.value) return null
  return Math.round(pricePerHourNum.value * durationHours.value * 100) / 100
})
const needsApproval = computed(() => device.value?.needApproval === 1)

// ---- 步进 + 校验(沿既有 onSubmit 校验顺序,拆到对应步)------------------
function next() {
  if (active.value === 0) {
    // 步 1 → 2:需选时段(等价 onSubmit 中的 range 检查)
    if (!range.value || range.value.length !== 2) {
      ElMessage.warning('请选择预约起止时间')
      return
    }
    active.value = 1
    return
  }
  if (active.value === 1) {
    // 步 2 → 3:需校验用途(等价 onSubmit 中的 form.validate)
    formRef.value?.validate((valid) => {
      if (valid) active.value = 2
    })
    return
  }
}

function prev() {
  // 步 0 的"上一步"语义=取消;其余步退一步
  if (active.value === 0) {
    onCancel()
    return
  }
  active.value -= 1
}

async function onSubmit() {
  // 最终提交:保留既有校验顺序(range → deviceId → validate → API),零改。
  if (!formRef.value) return
  if (!range.value || range.value.length !== 2) {
    ElMessage.warning('请选择预约起止时间')
    return
  }
  if (!deviceId.value) {
    ElMessage.warning('缺少设备信息')
    return
  }
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    submitting.value = true
    const payload: ReservationCreatePayload = {
      deviceId: deviceId.value,
      startTime: toIso(range.value![0]),
      endTime: toIso(range.value![1]),
      purpose: form.purpose,
    }
    try {
      const newId = await createReservation(payload)
      ElMessage.success(`预约提交成功（#${newId}）`)
      router.push({ name: 'reservation-mine' })
    } catch {
      // 拦截器已提示（含冲突/防超约错误）
    } finally {
      submitting.value = false
    }
  })
}

function onCancel() {
  router.back()
}

onMounted(loadDevice)
</script>

<template>
  <div class="reserve-create">
    <PageHeader
      title="新建预约"
      subtitle="选择时段并填写用途,提交后系统将进行冲突检测"
    />

    <!-- 多步 stepper:深色 + 青色进度(覆盖 --el-step 状态色 + 连线) -->
    <el-steps
      :active="active"
      finish-status="finish"
      process-status="process"
      align-center
      class="reserve-create__steps"
    >
      <el-step
        v-for="s in steps"
        :key="s.title"
        :title="s.title"
        :description="s.description"
      />
    </el-steps>

    <!-- 双列:主表单 / sticky 实时摘要 -->
    <div class="reserve-create__grid">
      <!-- 左:主表单区(设备信息 + 当前步表单) -->
      <div v-loading="deviceLoading" class="reserve-create__main">
        <!-- 设备信息(常驻,三步都看得到) -->
        <section v-if="device" class="reserve-create__device">
          <div class="reserve-create__device-head">
            <h2 class="reserve-create__device-name">{{ device.name }}</h2>
            <StatusDot :status="device.status" :label="true" />
          </div>
          <p class="reserve-create__device-sub">
            {{ device.brand }} {{ device.model }}
            <span v-if="device.labName"> · {{ device.labName }}</span>
            <span> · 单价 ¥{{ device.pricePerHour ?? '—' }}/时</span>
          </p>
        </section>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          @submit.prevent
        >
          <!-- 步 1:选择时段 -->
          <div v-show="active === 0" class="reserve-create__step">
            <el-form-item
              label="预约时段(15 分钟对齐,工作时段 08:00-22:00)"
              required
            >
              <el-date-picker
                v-model="range"
                type="datetimerange"
                range-separator="至"
                start-placeholder="开始时间"
                end-placeholder="结束时间"
                format="YYYY-MM-DD HH:mm"
                value-format="x"
                :step="{ hours: 1, minutes: 15, seconds: 0 }"
                style="width: 100%; max-width: 520px"
              />
            </el-form-item>
          </div>

          <!-- 步 2:填写用途 -->
          <div v-show="active === 1" class="reserve-create__step">
            <el-form-item label="使用用途" prop="purpose">
              <el-input
                v-model="form.purpose"
                type="textarea"
                :rows="5"
                placeholder="请简述本次预约的使用用途"
                maxlength="300"
                show-word-limit
              />
            </el-form-item>
          </div>

          <!-- 步 3:确认 -->
          <div v-show="active === 2" class="reserve-create__step">
            <div class="reserve-create__confirm">
              <h3 class="reserve-create__confirm-title">请确认预约信息</h3>
              <dl class="reserve-create__confirm-grid">
                <div class="reserve-create__confirm-row">
                  <dt>设备</dt>
                  <dd>{{ device?.name ?? '—' }}</dd>
                </div>
                <div class="reserve-create__confirm-row">
                  <dt>起止时间</dt>
                  <dd>{{ startLabel }} → {{ endLabel }}</dd>
                </div>
                <div class="reserve-create__confirm-row">
                  <dt>时长</dt>
                  <dd>{{ durationLabel }}</dd>
                </div>
                <div class="reserve-create__confirm-row">
                  <dt>用途</dt>
                  <dd>{{ form.purpose || '—' }}</dd>
                </div>
                <div class="reserve-create__confirm-row">
                  <dt>费用估算</dt>
                  <dd>
                    <span class="reserve-create__confirm-cost">
                      {{ costEstimate != null ? `¥${costEstimate}` : '—' }}
                    </span>
                  </dd>
                </div>
              </dl>
            </div>
          </div>
        </el-form>
      </div>

      <!-- 右:sticky 实时摘要 GlowCard -->
      <aside class="reserve-create__aside">
        <GlowCard accent class="reserve-create__summary">
          <h3 class="reserve-create__summary-title">实时摘要</h3>
          <dl class="reserve-create__summary-grid">
            <div class="reserve-create__summary-row">
              <dt>设备</dt>
              <dd>{{ device?.name ?? '未选择' }}</dd>
            </div>
            <div class="reserve-create__summary-row">
              <dt>开始</dt>
              <dd>{{ startLabel }}</dd>
            </div>
            <div class="reserve-create__summary-row">
              <dt>结束</dt>
              <dd>{{ endLabel }}</dd>
            </div>
            <div class="reserve-create__summary-row">
              <dt>时长</dt>
              <dd>{{ durationLabel }}</dd>
            </div>
            <div class="reserve-create__summary-row reserve-create__summary-row--accent">
              <dt>费用估算</dt>
              <dd>{{ costEstimate != null ? `¥${costEstimate}` : '—' }}</dd>
            </div>
          </dl>

          <div class="reserve-create__summary-status">
            <span
              class="reserve-create__summary-badge"
              :class="needsApproval ? 'is-warn' : 'is-ok'"
            >
              {{ needsApproval ? '提交后需审批' : '免审批 · 提交后直接生效' }}
            </span>
          </div>
        </GlowCard>
      </aside>
    </div>

    <!-- 底部操作栏 -->
    <div class="reserve-create__actionbar">
      <GhostButton @click="prev">
        {{ active === 0 ? '取消' : '上一步' }}
      </GhostButton>
      <GradientButton v-if="active < 2" @click="next">下一步</GradientButton>
      <GradientButton v-else :loading="submitting" @click="onSubmit">
        提交预约
      </GradientButton>
    </div>
  </div>
</template>

<style scoped lang="scss">
// ============================================================================
// Create.vue 深色科技风(spec §7 建预约行)
// 全量走 token,scoped scss。结构:PageHeader / el-steps / 双列(主表单+sticky 摘要)/ 底部操作栏。
// ============================================================================

.reserve-create {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding-bottom: 8px;

  // ---- el-steps 容器 -----------------------------------------------------
  &__steps {
    // 给 stepper 一个卡面底,跟整体深色卡风一致(参考 Detail 的 Panel/tabs 包裹)
    padding: 18px 24px;
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-soft-light);
  }

  // ---- 双列网格:主表单 / sticky 摘要 -------------------------------------
  &__grid {
    display: grid;
    grid-template-columns: minmax(0, 1.6fr) minmax(280px, 1fr);
    gap: 24px;
    align-items: start;

    @media (max-width: 960px) {
      grid-template-columns: 1fr;
    }
  }

  &__main {
    // 左主列:设备信息 + 当前步表单
    min-width: 0;
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-soft-light);
    padding: 28px;
  }

  &__aside {
    // 右 sticky 摘要:随左列滚动吸顶
    position: sticky;
    top: 16px;

    @media (max-width: 960px) {
      position: static;
    }
  }

  // ---- 设备信息块(主列顶部,常驻)----------------------------------------
  &__device {
    padding-bottom: 20px;
    margin-bottom: 24px;
    border-bottom: 1px solid var(--border-subtle);
  }

  &__device-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
  }

  &__device-name {
    margin: 0;
    font-family: var(--font-display);
    font-size: 18px;
    font-weight: 600;
    line-height: 1.3;
    color: var(--text-primary);
  }

  &__device-sub {
    margin: 6px 0 0;
    font-size: 13px;
    color: var(--text-secondary);
  }

  // ---- 步容器 ------------------------------------------------------------
  &__step {
    min-height: 220px;
  }

  // ---- 步 3:确认网格(复用摘要样式但不依赖 sticky)------------------------
  &__confirm-title {
    margin: 0 0 16px;
    font-family: var(--font-display);
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
  }

  &__confirm-grid,
  &__summary-grid {
    display: flex;
    flex-direction: column;
    gap: 0;
    margin: 0;
  }

  &__confirm-row,
  &__summary-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    padding: 12px 0;
    border-bottom: 1px solid var(--border-subtle);

    &:last-child {
      border-bottom: none;
    }

    dt {
      margin: 0;
      font-size: 11px;
      font-weight: 500;
      color: var(--text-tertiary);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      flex-shrink: 0;
    }

    dd {
      margin: 0;
      font-size: 14px;
      font-weight: 500;
      color: var(--text-primary);
      font-family: var(--font-mono);
      text-align: right;
      word-break: break-word;
    }
  }

  &__confirm-cost {
    color: var(--accent);
    font-weight: 600;
  }

  // ---- 摘要 GlowCard 内部 ------------------------------------------------
  &__summary {
    padding: 22px;
  }

  &__summary-title {
    margin: 0 0 14px;
    font-family: var(--font-display);
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    letter-spacing: 0.01em;
  }

  &__summary-row--accent dd {
    color: var(--accent);
    font-weight: 600;
  }

  &__summary-status {
    margin-top: 16px;
    padding-top: 14px;
    border-top: 1px solid var(--border-subtle);
  }

  &__summary-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 500;
    border-radius: var(--radius-pill);
    line-height: 1.4;

    &.is-ok {
      color: var(--status-success);
      background: color-mix(in srgb, var(--status-success) 10%, transparent);
      border: 1px solid color-mix(in srgb, var(--status-success) 30%, transparent);
    }

    &.is-warn {
      color: var(--status-warning);
      background: color-mix(in srgb, var(--status-warning) 10%, transparent);
      border: 1px solid color-mix(in srgb, var(--status-warning) 30%, transparent);
    }
  }

  // ---- 底部操作栏:GradientButton 提交 / GhostButton 上一步-取消 ----------
  &__actionbar {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 12px;
    padding: 18px 24px;
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-soft-light);
    // sticky 底部:stepper 每步 CTA 始终可达(R5.6 复审 🔵)
    position: sticky;
    bottom: 16px;
    z-index: 2;
  }
}

// ============================================================================
// el-steps 深色青色进度覆盖(spec §7 建预约行 + 模式参考 R4.2 Detail el-tabs 覆盖)
// 已完成/当前节点青色,未到 tertiary,连线 track hairline + 已完成连线青色。
// 通过 :deep 改状态类色 + icon 圆背景 + 连线 inner 边框色,无 !important。
// ============================================================================

// icon 圆背景:与 surface 卡底区分(elevated 抬升一档)
:deep(.el-step__icon) {
  background: var(--bg-elevated);
}

// ---- 未到(wait):tertiary ------------------------------------------------
:deep(.el-step__head.is-wait) {
  color: var(--text-tertiary);
  border-color: var(--text-tertiary);
}
:deep(.el-step__title.is-wait) {
  color: var(--text-tertiary);
  font-weight: 500;
}
:deep(.el-step__description.is-wait) {
  color: var(--text-tertiary);
}

// ---- 已完成(finish):青色描边 + 青色字 ----------------------------------
:deep(.el-step__head.is-finish) {
  color: var(--accent);
  border-color: var(--accent);
}
:deep(.el-step__title.is-finish) {
  color: var(--accent);
  font-weight: 600;
}
:deep(.el-step__description.is-finish) {
  color: var(--accent-bright);
}

// ---- 当前(process):实心青色圆 + 深字(更突出)-------------------------
:deep(.el-step__head.is-process) {
  color: var(--accent);
  border-color: var(--accent);
}
:deep(.el-step__head.is-process .el-step__icon.is-text) {
  background: var(--accent);
  border-color: var(--accent);
}
:deep(.el-step__head.is-process .el-step__icon-inner) {
  color: var(--text-on-accent);
}
:deep(.el-step__title.is-process) {
  color: var(--accent);
  font-weight: 600;
}
:deep(.el-step__description.is-process) {
  color: var(--accent-bright);
}

// ---- 连线 track(未完成段):hairline-strong ------------------------------
:deep(.el-step__line) {
  background-color: var(--border-strong);
}

// ---- 连线 fill(已完成段):青色(border 1px solid,色由 currentColor 接管)
:deep(.el-step__line-inner) {
  border-color: var(--accent);
}

// ============================================================================
// prefers-reduced-motion 兜底(spec §6.1 铁律)
// ============================================================================
@media (prefers-reduced-motion: reduce) {
  :deep(.el-step__icon),
  :deep(.el-step__line-inner) {
    transition: none;
  }
}
</style>
