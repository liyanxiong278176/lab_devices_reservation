<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Calendar, Check, CircleClose, Cpu, Refresh } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import {
  acknowledgeSafety,
  getDevice,
  listSafetyDocuments,
  myQualification,
  submitQualification,
  uploadQualificationMaterial,
  deviceAvailability,
} from '@/api/device'
import { createReservation, preflightReservation } from '@/api/reservation'
import type { DeviceAvailabilityVO, DeviceVO } from '@/types/device'
import type { ReservationCreatePayload, ReservationPreflightVO } from '@/types/reservation'
import PageHeader from '@/components/ui/PageHeader.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import Tag from '@/components/ui/Tag.vue'

const route = useRoute()
const router = useRouter()
const formRef = ref<FormInstance>()
const loading = ref(false)
const preflightLoading = ref(false)
const submitting = ref(false)
const device = ref<DeviceVO | null>(null)
const preflight = ref<ReservationPreflightVO | null>(null)
const availabilityDays = ref<DeviceAvailabilityVO[]>([])
const availabilityLoading = ref(false)
const safetyDocs = ref<import('@/types/device').DeviceDocumentVO[]>([])
const qualification = ref<import('@/types/device').QualificationVO | null>(null)
const safetyAcking = ref(false)
const qualificationSubmitting = ref(false)
const qualificationNote = ref('')
const qualificationFile = ref<File | null>(null)
const selectedDates = ref<[string, string] | null>(null)
const form = ref({ purpose: '' })

const rules: FormRules = {
  purpose: [{ required: true, min: 2, message: '请填写至少 2 个字的使用用途', trigger: 'blur' }],
}

const deviceId = computed(() => Number(route.query.deviceId))
const dateRange = computed(() => selectedDates.value ? selectedDates.value.join(' 至 ') : '尚未选择')
const conflictCount = computed(() => preflight.value?.conflicts.length || 0)
const availabilityMap = computed(() => new Map(availabilityDays.value.map((day) => [day.date, day])))
const canSubmit = computed(() => Boolean(
  device.value &&
  selectedDates.value &&
  form.value.purpose.trim() &&
  !preflightLoading.value &&
  preflight.value?.all_available &&
  (!preflight.value.safety_required || preflight.value.safety_acknowledged) &&
  (!preflight.value.qualification_required || preflight.value.qualification_approved),
))

function todayStart() {
  return dayjs().startOf('day')
}

function isDisabledDate(value: Date) {
  const current = dayjs(value)
  if (current.isBefore(todayStart(), 'day')) return true
  const day = availabilityMap.value.get(current.format('YYYY-MM-DD'))
  return day ? !day.available : false
}

function selectAvailableDate(value: string) {
  if (!selectedDates.value || selectedDates.value[0] !== selectedDates.value[1]) {
    selectedDates.value = [value, value]
    return
  }
  const start = dayjs(selectedDates.value[0])
  const picked = dayjs(value)
  selectedDates.value = picked.isBefore(start, 'day')
    ? [value, selectedDates.value[0]]
    : [selectedDates.value[0], value]
}

async function loadAvailability() {
  if (!device.value) return
  availabilityLoading.value = true
  try {
    const start = todayStart()
    const span = Math.min(device.value.maxReservationDays || 31, 31)
    availabilityDays.value = await deviceAvailability(
      device.value.id,
      start.format('YYYY-MM-DD'),
      start.add(span - 1, 'day').format('YYYY-MM-DD'),
    )
  } finally {
    availabilityLoading.value = false
  }
}

async function loadDevice() {
  if (!deviceId.value) return
  loading.value = true
  try {
    device.value = await getDevice(deviceId.value)
    await loadAvailability()
  } finally {
    loading.value = false
  }
}

async function runPreflight() {
  if (!device.value || !selectedDates.value) {
    preflight.value = null
    return
  }
  preflightLoading.value = true
  try {
    preflight.value = await preflightReservation({
      deviceId: device.value.id,
      startDate: selectedDates.value[0],
      endDate: selectedDates.value[1],
      purpose: form.value.purpose || '设备使用',
    })
    if (preflight.value.safety_required || preflight.value.qualification_required) {
      const [docs, mine] = await Promise.all([
        listSafetyDocuments(device.value.id),
        myQualification(device.value.id),
      ])
      safetyDocs.value = docs
      qualification.value = mine
    } else {
      safetyDocs.value = []
      qualification.value = null
    }
  } finally {
    preflightLoading.value = false
  }
}

async function acknowledgeCurrentSafety() {
  if (!device.value) return
  safetyAcking.value = true
  try {
    await acknowledgeSafety(device.value.id)
    await runPreflight()
    ElMessage.success('已记录安全须知确认')
  } finally {
    safetyAcking.value = false
  }
}

function onQualificationFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  qualificationFile.value = input.files?.[0] || null
}

async function applyQualification() {
  if (!device.value) return
  qualificationSubmitting.value = true
  try {
    let assetId: number | undefined
    if (qualificationFile.value) {
      const uploaded = await uploadQualificationMaterial(device.value.id, qualificationFile.value)
      assetId = uploaded.asset_id
    }
    qualification.value = await submitQualification(device.value.id, {
      assetId,
      note: qualificationNote.value.trim() || undefined,
    })
    qualificationFile.value = null
    qualificationNote.value = ''
    ElMessage.success('资质申请已提交，请等待负责人审核')
  } finally {
    qualificationSubmitting.value = false
  }
}

watch([selectedDates, () => device.value?.id], () => {
  void runPreflight()
})

async function onSubmit() {
  if (!formRef.value || !selectedDates.value || !device.value) {
    ElMessage.warning('请选择设备和完整的预约日期')
    return
  }
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  if (!preflight.value) await runPreflight()
  if (!preflight.value?.all_available) {
    ElMessage.warning('存在冲突日期，请重新选择一段完全可用的连续日期')
    return
  }
  submitting.value = true
  try {
    const payload: ReservationCreatePayload = {
      deviceId: device.value.id,
      startDate: selectedDates.value[0],
      endDate: selectedDates.value[1],
      purpose: form.value.purpose.trim(),
      commitMode: 'all_or_nothing',
    }
    const result = await createReservation(payload)
    ElMessage.success(`已提交 ${result.created.length} 条预约`)
    await router.push({ name: 'reservation-mine' })
  } finally {
    submitting.value = false
  }
}

function onCancel() {
  router.back()
}

onMounted(loadDevice)
</script>

<template>
  <div class="reserve-create-v2">
    <PageHeader back title="预约设备" subtitle="按自然日选择连续使用区间，系统会先完成冲突预检" />

    <nav class="booking-steps" aria-label="预约流程">
      <div class="booking-step booking-step--done">
        <span>01</span>
        <strong>确认设备</strong>
      </div>
      <div class="booking-step" :class="{ 'booking-step--active': !selectedDates, 'booking-step--done': Boolean(selectedDates) }">
        <span>02</span>
        <strong>选择日期</strong>
      </div>
      <div class="booking-step" :class="{ 'booking-step--active': Boolean(selectedDates) && !form.purpose.trim(), 'booking-step--done': canSubmit }">
        <span>03</span>
        <strong>确认提交</strong>
      </div>
    </nav>

    <div v-loading="loading" class="reserve-create-v2__grid">
      <section class="reserve-create-v2__main">
        <div class="reserve-create-v2__device panel-card">
          <div class="device-mark"><Cpu /></div>
          <div>
            <span class="eyebrow">SELECTED DEVICE</span>
            <h2>{{ device?.name || '加载设备中…' }}</h2>
            <p>{{ [device?.brand, device?.model, device?.labName].filter(Boolean).join(' · ') || '设备信息' }}</p>
          </div>
          <StatusDot v-if="device" :status="device.status" :label="true" />
        </div>

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="panel-card reserve-form">
          <div class="form-heading"><span class="eyebrow">RESERVATION WINDOW</span><span class="date-note"><Calendar /> 仅精确到天</span></div>
          <el-form-item label="预约日期" required>
            <el-date-picker
              v-model="selectedDates"
              type="daterange"
              value-format="YYYY-MM-DD"
              range-separator="至"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              :disabled-date="isDisabledDate"
              :clearable="false"
              class="date-picker"
            />
          </el-form-item>
          <div class="availability-calendar" :class="{ 'is-loading': availabilityLoading }">
            <div class="availability-calendar__head">
              <span>近期可用日期</span>
              <span class="availability-calendar__legend"><i class="is-available" />可用 <i class="is-conflict" />不可用</span>
            </div>
            <div class="availability-calendar__days">
              <button
                v-for="day in availabilityDays"
                :key="day.date"
                type="button"
                class="availability-calendar__day"
                :class="{ 'is-available': day.available, 'is-conflict': !day.available, 'is-selected': selectedDates?.includes(day.date) }"
                :disabled="!day.available"
                @click="selectAvailableDate(day.date)"
              >
                <strong>{{ dayjs(day.date).format('MM-DD') }}</strong>
                <small>{{ day.available ? '可用' : '冲突' }}</small>
              </button>
            </div>
          </div>
          <el-form-item label="使用用途" prop="purpose">
            <el-input v-model="form.purpose" type="textarea" :rows="4" maxlength="500" show-word-limit placeholder="例如：完成材料拉伸实验并采集三组数据" />
          </el-form-item>
        </el-form>

        <section class="preflight-card panel-card" :class="{ 'is-conflict': conflictCount > 0, 'is-loading': preflightLoading }">
          <div class="preflight-card__head">
            <div><span class="eyebrow">AVAILABILITY PREFLIGHT</span><h3>可用性检查</h3></div>
            <el-icon v-loading="preflightLoading"><Refresh /></el-icon>
          </div>
          <div v-if="!selectedDates" class="preflight-empty"><Calendar />选择日期后自动检查</div>
          <template v-else-if="preflight">
            <div class="preflight-summary">
              <span class="summary-good"><Check /> {{ preflight.available_dates.length }} 天可用</span>
              <span v-if="conflictCount" class="summary-bad"><CircleClose /> {{ conflictCount }} 天冲突</span>
            </div>
            <div v-if="conflictCount" class="conflict-tip">存在冲突日期，连续区间不能提交；请重新选择一段完全可用的日期。</div>
            <ul v-if="conflictCount" class="conflict-list">
              <li v-for="conflict in preflight.conflicts" :key="conflict.date"><strong>{{ conflict.date }}</strong><span>{{ conflict.reason }}</span></li>
            </ul>
          </template>
        </section>

        <section
          v-if="preflight && (preflight.safety_required || preflight.qualification_required)"
          class="access-card panel-card"
        >
          <div class="preflight-card__head">
            <div><span class="eyebrow">ACCESS CONTROL</span><h3>使用前准入</h3></div>
            <span class="access-card__state">{{ canSubmit ? '已满足' : '待处理' }}</span>
          </div>
          <div v-if="preflight.safety_required" class="access-card__item">
            <div>
              <strong>阅读并确认安全须知</strong>
              <p>当前版本 {{ preflight.safety_document_version || '1.0' }}，确认后才可提交预约。</p>
              <div class="access-card__docs">
                <a v-for="doc in safetyDocs" :key="doc.id" :href="doc.url" target="_blank" rel="noreferrer">
                  {{ doc.title }} · v{{ doc.version }}
                </a>
              </div>
            </div>
            <GradientButton
              v-if="!preflight.safety_acknowledged"
              size="small"
              :loading="safetyAcking"
              @click="acknowledgeCurrentSafety"
            >
              我已阅读并确认
            </GradientButton>
            <Tag v-else variant="success" size="small" round>已确认</Tag>
          </div>
          <div v-if="preflight.qualification_required" class="access-card__item">
            <div>
              <strong>使用资质审核</strong>
              <p v-if="qualification?.status === 'PENDING'">申请已提交，等待实验室负责人审核。</p>
              <p v-else-if="qualification?.status === 'REJECTED'">上次申请未通过，请补充说明后重新提交。</p>
              <p v-else-if="qualification?.status === 'APPROVED'">资质有效期至 {{ qualification.validUntil || '长期有效' }}。</p>
              <p v-else>该设备需要先提交培训或操作资质。</p>
              <div v-if="qualification?.status !== 'APPROVED'" class="access-card__apply">
                <input type="file" accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp" @change="onQualificationFileChange" />
                <el-input v-model="qualificationNote" maxlength="500" placeholder="培训记录、证书或申请说明（可选）" />
              </div>
            </div>
            <GradientButton
              v-if="qualification?.status !== 'PENDING' && qualification?.status !== 'APPROVED'"
              size="small"
              :loading="qualificationSubmitting"
              @click="applyQualification"
            >
              提交资质申请
            </GradientButton>
            <Tag v-else-if="qualification?.status === 'PENDING'" variant="warning" size="small" round>审核中</Tag>
            <Tag v-else variant="success" size="small" round>已通过</Tag>
          </div>
        </section>
      </section>

      <aside class="reserve-create-v2__aside">
        <section class="summary-card panel-card">
          <span class="eyebrow">BOOKING SUMMARY</span>
          <h3>预约摘要</h3>
          <dl><dt>设备</dt><dd>{{ device?.name || '—' }}</dd><dt>日期</dt><dd>{{ dateRange }}</dd><dt>学院范围</dt><dd>仅当前学院</dd><dt>审批</dt><dd>{{ device?.needApproval ? '负责人审批' : '自动确认' }}</dd></dl>
          <div class="summary-card__rule"></div>
          <p class="summary-card__hint summary-card__approval-hint">
            {{ device?.needApproval ? '提交后会进入负责人待审批列表。' : '该设备提交后会直接确认，不会出现在管理员待审批列表。' }}
          </p>
          <p class="summary-card__hint">提交后仍会在数据库唯一键层做最终并发校验。</p>
          <GradientButton :loading="submitting" :disabled="!canSubmit" class="submit-button" @click="onSubmit">提交预约</GradientButton>
          <GhostButton class="cancel-button" @click="onCancel">取消</GhostButton>
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped lang="scss">
.reserve-create-v2 { display: flex; flex-direction: column; gap: 22px; color: var(--text-primary); }
.booking-steps { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0; padding: 0 4px 6px; border-bottom: 1px solid var(--border-default); }
.booking-step { position: relative; display: flex; align-items: center; gap: 10px; min-height: 42px; color: var(--text-tertiary); font-size: 12px; }
.booking-step::after { content: ''; position: absolute; right: 18px; left: 78px; top: 50%; height: 1px; background: var(--border-subtle); }
.booking-step:last-child::after { display: none; }
.booking-step span { display: grid; place-items: center; width: 28px; height: 28px; color: var(--text-tertiary); border: 1px solid var(--border-default); border-radius: 50%; font-family: var(--font-mono); font-size: 10px; }
.booking-step strong { position: relative; z-index: 1; padding-right: 14px; background: var(--bg-base); font-weight: 600; }
.booking-step--active { color: var(--accent); }
.booking-step--active span, .booking-step--done span { color: var(--accent); border-color: var(--accent); background: var(--accent-soft); }
.booking-step--done:not(:last-child)::after { background: color-mix(in srgb, var(--accent) 40%, var(--border-subtle)); }
.reserve-create-v2__grid { display: grid; grid-template-columns: minmax(0, 1fr) 310px; gap: 18px; align-items: start; }.reserve-create-v2__main { display: grid; gap: 14px; }.panel-card { background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: var(--radius-card); box-shadow: var(--shadow-soft-light); }
.reserve-create-v2__device { display: flex; align-items: center; gap: 13px; padding: 18px; }.device-mark { display: grid; place-items: center; width: 42px; height: 42px; color: var(--accent); background: rgba(34,211,238,.1); border: 1px solid rgba(34,211,238,.22); border-radius: 11px; }.device-mark svg { width: 20px; }.eyebrow { color: var(--text-tertiary); font-family: var(--font-mono); font-size: 10px; letter-spacing: .12em; }.reserve-create-v2__device h2 { margin: 4px 0 2px; font-family: var(--font-display); font-size: 18px; }.reserve-create-v2__device p { margin: 0; color: var(--text-secondary); font-size: 12px; }.reserve-create-v2__device > :last-child { margin-left: auto; }
.reserve-form { padding: 20px; }.form-heading,.preflight-card__head { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 18px; }.form-heading .date-note { display: inline-flex; align-items: center; gap: 5px; color: var(--accent); font-family: var(--font-mono); font-size: 10px; }.date-note svg { width: 13px; }.reserve-form :deep(.el-form-item__label) { color: var(--text-secondary); font-size: 12px; }.date-picker { width: 100%; }.reserve-form :deep(.el-textarea__inner) { min-height: 100px; }
.availability-calendar { display: grid; gap: 10px; margin: -4px 0 18px; padding: 12px; background: var(--bg-elevated); border: 1px solid var(--border-subtle); border-radius: 9px; opacity: 1; transition: opacity var(--d-fast) var(--ease-out-expo); }.availability-calendar.is-loading { opacity: .55; }.availability-calendar__head { display: flex; align-items: center; justify-content: space-between; color: var(--text-secondary); font-family: var(--font-mono); font-size: 10px; }.availability-calendar__legend { display: inline-flex; align-items: center; gap: 5px; color: var(--text-tertiary); font-size: 9px; }.availability-calendar__legend i { width: 6px; height: 6px; border-radius: 50%; }.availability-calendar__legend i.is-available { background: var(--status-success); }.availability-calendar__legend i.is-conflict { background: var(--status-danger); }.availability-calendar__days { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 5px; }.availability-calendar__day { display: grid; gap: 2px; padding: 7px 3px; color: var(--text-tertiary); background: transparent; border: 1px solid var(--border-subtle); border-radius: 6px; cursor: pointer; font: inherit; }.availability-calendar__day strong { color: var(--text-secondary); font-family: var(--font-mono); font-size: 10px; font-weight: 500; }.availability-calendar__day small { font-size: 9px; }.availability-calendar__day.is-available { border-color: color-mix(in srgb, var(--status-success) 30%, transparent); }.availability-calendar__day.is-available small { color: var(--status-success); }.availability-calendar__day.is-conflict { cursor: not-allowed; opacity: .65; border-color: color-mix(in srgb, var(--status-danger) 30%, transparent); }.availability-calendar__day.is-conflict small { color: var(--status-danger); }.availability-calendar__day.is-selected { color: var(--text-on-accent); background: color-mix(in srgb, var(--accent) 18%, transparent); border-color: var(--accent); }.availability-calendar__day.is-selected strong,.availability-calendar__day.is-selected small { color: var(--accent); }.availability-calendar__day:disabled { color: var(--text-tertiary); }.conflict-tip { margin-top: 12px; padding: 10px 12px; color: var(--status-danger); background: rgba(248,113,113,.06); border-left: 2px solid var(--status-danger); font-size: 11px; line-height: 1.5; }
.preflight-card { padding: 20px; }.preflight-card__head h3,.summary-card h3 { margin: 5px 0 0; font-family: var(--font-display); font-size: 17px; }.preflight-card__head > .el-icon { color: var(--accent); }.preflight-empty { display: flex; align-items: center; justify-content: center; gap: 8px; min-height: 76px; color: var(--text-tertiary); font-size: 12px; }.preflight-empty svg { color: var(--accent); }.preflight-empty svg { color: var(--accent); }.preflight-summary { display: flex; gap: 16px; padding: 11px; background: var(--bg-elevated); border-radius: 8px; font-family: var(--font-mono); font-size: 11px; }.summary-good { color: var(--status-success); }.summary-bad { color: var(--status-danger); }.summary-good svg,.summary-bad svg { width: 13px; vertical-align: -2px; }.conflict-list { display: grid; gap: 6px; margin: 12px 0 0; padding: 0; list-style: none; }.conflict-list li { display: flex; justify-content: space-between; gap: 12px; padding: 8px 10px; color: var(--text-secondary); background: rgba(248,113,113,.05); border-left: 2px solid var(--status-danger); font-size: 11px; }.conflict-list strong { color: var(--text-primary); font-family: var(--font-mono); font-weight: 500; }.conflict-list span { color: var(--text-tertiary); }
.access-card { display: grid; gap: 16px; padding: 20px; }.access-card__state { color: var(--status-warning); font-family: var(--font-mono); font-size: 11px; }.access-card__item { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 14px; background: var(--bg-elevated); border: 1px solid var(--border-subtle); border-radius: 10px; }.access-card__item strong { color: var(--text-primary); font-size: 13px; }.access-card__item p { margin: 6px 0 0; color: var(--text-tertiary); font-size: 11px; line-height: 1.6; }.access-card__docs { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }.access-card__docs a { color: var(--accent); font-size: 11px; text-decoration: none; }.access-card__docs a:hover { text-decoration: underline; }.access-card__apply { display: grid; gap: 8px; margin-top: 10px; }.access-card__apply input { max-width: 260px; color: var(--text-secondary); font-size: 11px; }
.summary-card { position: sticky; top: 84px; padding: 20px; }.summary-card dl { display: grid; grid-template-columns: 70px 1fr; gap: 13px 8px; margin: 22px 0; font-size: 12px; }.summary-card dt { color: var(--text-tertiary); }.summary-card dd { margin: 0; color: var(--text-primary); text-align: right; }.summary-card__rule { height: 1px; background: var(--border-subtle); }.summary-card__hint { color: var(--text-tertiary); font-size: 11px; line-height: 1.6; }.submit-button,.cancel-button { width: 100%; margin-top: 10px; }.cancel-button { justify-content: center; }
@media (max-width: 900px) { .reserve-create-v2__grid { grid-template-columns: 1fr; }.summary-card { position: static; } }
@media (max-width: 560px) { .booking-steps { grid-template-columns: 1fr; gap: 8px; padding-bottom: 12px; }.booking-step::after { display: none; }.booking-step strong { background: transparent; }.preflight-options { flex-direction: column; } }
</style>
