<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { Document, Tools, Upload } from '@element-plus/icons-vue'
import {
  completeMaintenanceCycle,
  createMaintenancePlan,
  downloadMaintenanceEvidence,
  listMaintenanceDevices,
  listMaintenancePlans,
  listMaintenanceRecords,
  updateMaintenancePlan,
  uploadMaintenanceEvidence,
  type MaintenanceIntervalUnit,
  type MaintenancePlanVO,
  type MaintenanceRecordVO,
  type MaintenanceResult,
  type MaintenanceType,
} from '@/api/maintenance'
import type { DeviceVO } from '@/types/device'
import type { Page } from '@/types/common'
import { uuid } from '@/utils/uuid'
import PageHeader from '@/components/ui/PageHeader.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import TextButton from '@/components/ui/TextButton.vue'
import Tag from '@/components/ui/Tag.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PageDepthNotice from '@/components/ui/PageDepthNotice.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'

type PlanForm = {
  deviceId: number | undefined
  planType: MaintenanceType
  title: string
  intervalValue: number
  intervalUnit: MaintenanceIntervalUnit
  dueDate: string
  downtimeStart: string
  downtimeEnd: string
  active: boolean
}

const localDate = () => {
  const current = new Date()
  current.setMinutes(current.getMinutes() - current.getTimezoneOffset())
  return current.toISOString().slice(0, 10)
}

const router = useRouter()
const loading = ref(false)
const submitting = ref(false)
const deviceLoading = ref(false)
const devices = ref<DeviceVO[]>([])
const editingDeviceOption = ref<{
  id: number
  name: string
  assetCode: string | undefined
  labName: string | undefined
} | null>(null)
const planDeviceOptions = computed(() => {
  const options = devices.value.map((device) => ({
    id: device.id,
    name: device.name,
    assetCode: device.assetCode,
    labName: device.labName,
  }))
  if (editingDeviceOption.value && !options.some((device) => device.id === editingDeviceOption.value?.id)) {
    options.push(editingDeviceOption.value)
  }
  return options
})
const page = ref<Page<MaintenancePlanVO>>({ records: [], total: 0, size: 20, current: 1, pages: 0 })
const statusFilter = ref<'ACTIVE' | 'INACTIVE' | 'ALL'>('ACTIVE')
const statusFilterOptions = [
  { label: '生效中', value: 'ACTIVE' },
  { label: '已停用', value: 'INACTIVE' },
  { label: '全部', value: 'ALL' },
]
const deviceFilter = ref<number | undefined>()
const planDialog = ref(false)
const planMode = ref<'create' | 'edit'>('create')
const editingPlanId = ref<number | null>(null)
const planForm = reactive<PlanForm>({
  deviceId: undefined,
  planType: 'ROUTINE',
  title: '',
  intervalValue: 12,
  intervalUnit: 'MONTH',
  dueDate: '',
  downtimeStart: '',
  downtimeEnd: '',
  active: true,
})

const completionDialog = ref(false)
const completingPlan = ref<MaintenancePlanVO | null>(null)
const completionSubmitting = ref(false)
const completionFile = ref<File | null>(null)
const completionEvidenceToken = ref<string | null>(null)
const completionIdempotencyKey = ref('')
const completionForm = reactive({
  completedDate: localDate(),
  result: 'PASSED' as MaintenanceResult,
  notes: '',
})
const historyDialog = ref(false)
const historyLoading = ref(false)
const historyPlan = ref<MaintenancePlanVO | null>(null)
const historyRecords = ref<MaintenanceRecordVO[]>([])
const historyTotal = ref(0)
const historyPage = ref(1)

const activeValue = computed(() => statusFilter.value === 'ALL' ? null : statusFilter.value === 'ACTIVE')
const maxPage = computed(() => page.value.truncated ? Math.min(page.value.total, (page.value.pages || 1) * page.value.size) : page.value.total)
const evidenceRequired = computed(() =>
  Boolean(completingPlan.value && ['CALIBRATION', 'SAFETY_CHECK'].includes(completingPlan.value.planType)),
)

const TYPE_LABELS: Record<MaintenanceType, string> = {
  ROUTINE: '周期保养',
  CALIBRATION: '仪器校准',
  SAFETY_CHECK: '安全检查',
}
const UNIT_LABELS: Record<MaintenanceIntervalUnit, string> = {
  DAY: '天',
  MONTH: '个月',
  YEAR: '年',
}
const typeLabel = (value: MaintenanceType) => TYPE_LABELS[value]
const unitLabel = (value: MaintenanceIntervalUnit) => UNIT_LABELS[value]
const disableFutureDate = (value: Date) => value.getTime() > Date.now()

async function loadOptions() {
  return searchDeviceOptions('')
}

async function searchDeviceOptions(keyword: string) {
  deviceLoading.value = true
  try {
    const result = await listMaintenanceDevices({ page: 1, pageSize: 100, search: keyword })
    devices.value = result.records
  } catch {
    // shared request interceptor displays the reason
  } finally {
    deviceLoading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const result = await listMaintenancePlans({
      page: page.value.current,
      pageSize: page.value.size,
      deviceId: deviceFilter.value,
      active: activeValue.value,
    })
    page.value = {
      records: result.items,
      total: result.total,
      current: result.page,
      size: result.page_size,
      pages: result.pages,
      truncated: result.truncated,
    }
  } catch {
    // shared request interceptor displays the reason
  } finally {
    loading.value = false
  }
}

function setFilter() {
  page.value.current = 1
  void load()
}

function setStatusFilter(value: string | number) {
  if (value !== 'ACTIVE' && value !== 'INACTIVE' && value !== 'ALL') return
  statusFilter.value = value
  setFilter()
}

function resetPlanForm() {
  planForm.deviceId = deviceFilter.value || devices.value[0]?.id
  planForm.planType = 'ROUTINE'
  planForm.title = ''
  planForm.intervalValue = 12
  planForm.intervalUnit = 'MONTH'
  planForm.dueDate = ''
  planForm.downtimeStart = ''
  planForm.downtimeEnd = ''
  planForm.active = true
}

function openCreate() {
  planMode.value = 'create'
  editingPlanId.value = null
  editingDeviceOption.value = null
  resetPlanForm()
  planDialog.value = true
}

function openEdit(row: MaintenancePlanVO) {
  planMode.value = 'edit'
  editingPlanId.value = row.id
  if (!devices.value.some((device) => device.id === row.deviceId)) {
    editingDeviceOption.value = {
      id: row.deviceId,
      name: row.deviceName,
      assetCode: row.deviceAssetCode ?? undefined,
      labName: undefined,
    }
  } else {
    editingDeviceOption.value = null
  }
  planForm.deviceId = row.deviceId
  planForm.planType = row.planType
  planForm.title = row.title
  planForm.intervalValue = row.intervalValue
  planForm.intervalUnit = row.intervalUnit
  planForm.dueDate = row.dueDate
  planForm.downtimeStart = row.downtimeStart || ''
  planForm.downtimeEnd = row.downtimeEnd || ''
  planForm.active = row.active
  planDialog.value = true
}

async function savePlan() {
  if (!planForm.deviceId || planForm.title.trim().length < 2 || !planForm.dueDate) {
    ElMessage.warning('请选择设备、填写计划名称和下次到期日')
    return
  }
  if (Boolean(planForm.downtimeStart) !== Boolean(planForm.downtimeEnd)) {
    ElMessage.warning('计划停机开始和结束日期需要同时填写')
    return
  }
  submitting.value = true
  const payload = {
    planType: planForm.planType,
    title: planForm.title.trim(),
    intervalValue: planForm.intervalValue,
    intervalUnit: planForm.intervalUnit,
    dueDate: planForm.dueDate,
    downtimeStart: planForm.downtimeStart || null,
    downtimeEnd: planForm.downtimeEnd || null,
    active: planForm.active,
  }
  try {
    if (planMode.value === 'edit' && editingPlanId.value) {
      await updateMaintenancePlan(editingPlanId.value, payload)
    } else {
      await createMaintenancePlan(planForm.deviceId, payload)
    }
    planDialog.value = false
    await load()
    ElMessage.success(planMode.value === 'edit' ? '维护计划已更新' : '维护计划已创建')
  } catch {
    // shared request interceptor displays the reason
  } finally {
    submitting.value = false
  }
}

function openCompletion(row: MaintenancePlanVO) {
  completingPlan.value = row
  completionForm.completedDate = localDate()
  completionForm.result = 'PASSED'
  completionForm.notes = ''
  completionFile.value = null
  completionEvidenceToken.value = null
  completionIdempotencyKey.value = uuid()
  completionDialog.value = true
}

function onEvidenceChange(event: Event) {
  const input = event.target as HTMLInputElement
  completionFile.value = input.files?.[0] || null
  completionEvidenceToken.value = null
  completionIdempotencyKey.value = uuid()
}

async function submitCompletion() {
  const plan = completingPlan.value
  if (!plan) return
  if (evidenceRequired.value && !completionFile.value) {
    ElMessage.warning('校准与安全检查必须上传证书或检查记录')
    return
  }
  if (completionForm.result === 'FAILED' && completionForm.notes.trim().length < 2) {
    ElMessage.warning('不合格时请填写至少 2 个字的情况说明')
    return
  }
  completionSubmitting.value = true
  try {
    if (completionFile.value && !completionEvidenceToken.value) {
      const uploaded = await uploadMaintenanceEvidence(plan.deviceId, completionFile.value)
      completionEvidenceToken.value = uploaded.asset_token
    }
    const record = await completeMaintenanceCycle(
      plan.id,
      {
        cycleDueDate: plan.dueDate,
        completedDate: completionForm.completedDate,
        result: completionForm.result,
        notes: completionForm.notes.trim() || undefined,
        evidenceAssetToken: completionEvidenceToken.value || undefined,
      },
      completionIdempotencyKey.value,
    )
    completionDialog.value = false
    if (record.repairReportId) {
      ElMessage.success(`检查已记录，并自动创建报修工单 #${record.repairReportId}`)
    } else {
      ElMessage.success('完成记录已保存，下次到期日已按实际完成日期顺延')
    }
    await load()
  } catch {
    // Keep the idempotency key so retrying after a lost response is safe.
  } finally {
    completionSubmitting.value = false
  }
}

async function showHistory(row: MaintenancePlanVO, nextPage = 1) {
  historyPlan.value = row
  historyPage.value = nextPage
  historyDialog.value = true
  historyLoading.value = true
  try {
    const result = await listMaintenanceRecords(row.id, nextPage)
    historyRecords.value = result.items
    historyTotal.value = result.total
  } catch {
    // shared request interceptor displays the reason
  } finally {
    historyLoading.value = false
  }
}

async function downloadEvidence(row: MaintenanceRecordVO) {
  if (!row.evidenceUrl || !row.evidenceName) return
  try {
    await downloadMaintenanceEvidence(row.evidenceUrl, row.evidenceName)
  } catch {
    // shared request interceptor displays the reason
  }
}

async function toggleActive(row: MaintenancePlanVO) {
  try {
    await ElMessageBox.confirm(
      row.active
        ? '停用后将停止该计划的到期提醒和维护期限限制；设备若处于维修中等实体状态，仍不可预约。'
        : '重新启用该维护计划，并恢复维护期限校验与到期提醒？',
      row.active ? '停用维护计划' : '启用维护计划',
      { type: 'warning', confirmButtonText: row.active ? '停用' : '启用', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await updateMaintenancePlan(row.id, {
      planType: row.planType,
      title: row.title,
      intervalValue: row.intervalValue,
      intervalUnit: row.intervalUnit,
      dueDate: row.dueDate,
      downtimeStart: row.downtimeStart || null,
      downtimeEnd: row.downtimeEnd || null,
      active: !row.active,
    })
    await load()
    ElMessage.success(row.active ? '维护计划已停用' : '维护计划已启用')
  } catch {
    // shared request interceptor displays the reason
  }
}

function changePage(value: number) {
  page.value.current = value
  void load()
}

function changeSize(value: number) {
  page.value.size = value
  page.value.current = 1
  void load()
}

onMounted(async () => {
  await loadOptions()
  await load()
})
</script>

<template>
  <div class="maintenance-page">
    <PageHeader title="维护与校准" subtitle="把周期任务、计划停机和检查凭证纳入设备预约链路">
      <template #actions>
        <GradientButton type="primary" :disabled="devices.length === 0" @click="openCreate">新建维护计划</GradientButton>
      </template>
    </PageHeader>

    <section class="maintenance-hero">
      <div class="maintenance-hero__copy">
        <span class="maintenance-eyebrow">PREVENTIVE CARE / LAB EQUIPMENT</span>
        <h2>设备可预约，不只看“空闲”。</h2>
        <p>用周期保养、计量校准与安全检查留住设备状态。计划停机日期会参与预约冲突校验；必需校准逾期或不合格时，系统会阻止预约与交接。</p>
      </div>
      <div class="maintenance-hero__mark"><Tools /><span>CARE<br />CYCLE</span></div>
    </section>

    <section class="maintenance-policy-strip">
      <div><span class="policy-index">01</span><strong>按完成日顺延</strong><small>实际完成日期 + 计划周期 = 下次到期</small></div>
      <div><span class="policy-index">02</span><strong>到期日提醒一次</strong><small>提醒负责人；受影响的已审批预约同步告知用户</small></div>
      <div><span class="policy-index">03</span><strong>保留人工处置</strong><small>冲突不自动取消预约，先提示并由负责人协调</small></div>
    </section>

    <section class="maintenance-list" v-loading="loading">
      <header class="maintenance-list__head">
        <div><span class="maintenance-eyebrow">MAINTENANCE REGISTER</span><h3>设备维护计划</h3></div>
        <div class="maintenance-list__filters">
          <el-select v-model="deviceFilter" clearable filterable remote :remote-method="searchDeviceOptions" :loading="deviceLoading" placeholder="全部设备" @change="setFilter">
            <el-option v-for="device in devices" :key="device.id" :label="`${device.assetCode || `#${device.id}`} · ${device.name}`" :value="device.id" />
          </el-select>
          <SegmentedControl
            :model-value="statusFilter"
            :options="statusFilterOptions"
            label="维护计划状态"
            @update:model-value="setStatusFilter"
          />
        </div>
      </header>

      <div v-if="page.records.length" class="maintenance-table-wrap">
        <el-table :data="page.records" stripe row-key="id">
          <el-table-column label="设备 / 计划" min-width="250">
            <template #default="{ row }">
              <div class="plan-device"><span>{{ row.deviceAssetCode || `设备 #${row.deviceId}` }}</span><strong>{{ row.deviceName }}</strong><small>{{ row.title }}</small></div>
            </template>
          </el-table-column>
          <el-table-column label="检查类型" width="130"><template #default="{ row }"><Tag :variant="row.planType === 'ROUTINE' ? 'info' : 'warning'" size="small">{{ typeLabel(row.planType) }}</Tag></template></el-table-column>
          <el-table-column label="周期" width="120"><template #default="{ row }">每 {{ row.intervalValue }} {{ unitLabel(row.intervalUnit) }}</template></el-table-column>
          <el-table-column label="下次到期" width="150"><template #default="{ row }"><span :class="{ 'date-overdue': row.temporarilyUnbookable }">{{ row.dueDate }}</span><small v-if="row.temporarilyUnbookable" class="row-warning">{{ row.unbookableReason }}</small></template></el-table-column>
          <el-table-column label="计划停机" min-width="160"><template #default="{ row }">{{ row.downtimeStart && row.downtimeEnd ? `${row.downtimeStart} — ${row.downtimeEnd}` : '未安排' }}</template></el-table-column>
          <el-table-column label="状态" width="110"><template #default="{ row }"><Tag :variant="row.active ? 'success' : 'default'" size="small">{{ row.active ? '生效中' : '已停用' }}</Tag></template></el-table-column>
          <el-table-column label="操作" width="245" fixed="right">
            <template #default="{ row }">
              <TextButton @click="showHistory(row)">完成记录</TextButton>
              <TextButton @click="openEdit(row)">编辑</TextButton>
              <TextButton @click="toggleActive(row)">{{ row.active ? '停用' : '启用' }}</TextButton>
              <TextButton v-if="row.active" @click="openCompletion(row)">登记完成</TextButton>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <EmptyState v-else-if="!loading" icon="Tools" title="还没有维护计划" description="为设备建立独立的保养、校准或安全检查周期。" />
      <footer v-if="page.records.length" class="maintenance-list__foot">
        <PageDepthNotice v-if="page.truncated" :total="page.total" />
        <el-pagination :current-page="page.current" :page-size="page.size" :total="maxPage" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="changePage" @size-change="changeSize" />
      </footer>
    </section>

    <el-dialog v-model="planDialog" :title="planMode === 'edit' ? '编辑维护计划' : '新建维护计划'" width="min(700px, 94vw)" destroy-on-close>
      <el-form label-position="top">
        <div class="maintenance-form-grid">
          <el-form-item label="设备" required>
            <el-select v-model="planForm.deviceId" filterable remote :remote-method="searchDeviceOptions" :loading="deviceLoading" :disabled="planMode === 'edit'" placeholder="输入编号或名称搜索设备">
              <el-option v-for="device in planDeviceOptions" :key="device.id" :label="`${device.assetCode || `#${device.id}`} · ${device.name}${device.labName ? ` · ${device.labName}` : ''}`" :value="device.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="计划类型" required>
            <el-select v-model="planForm.planType"><el-option label="周期保养" value="ROUTINE" /><el-option label="仪器校准" value="CALIBRATION" /><el-option label="安全检查" value="SAFETY_CHECK" /></el-select>
          </el-form-item>
          <el-form-item label="计划名称" required><el-input v-model="planForm.title" maxlength="160" placeholder="例如：年度精度校准" /></el-form-item>
          <el-form-item label="执行周期" required><div class="interval-control"><el-input-number v-model="planForm.intervalValue" :min="1" :max="365" controls-position="right" /><el-select v-model="planForm.intervalUnit"><el-option label="天" value="DAY" /><el-option label="个月" value="MONTH" /><el-option label="年" value="YEAR" /></el-select></div></el-form-item>
          <el-form-item label="下次到期日" required><el-date-picker v-model="planForm.dueDate" type="date" value-format="YYYY-MM-DD" placeholder="选择自然日" /></el-form-item>
          <el-form-item label="计划状态"><el-switch v-model="planForm.active" active-text="启用提醒" inactive-text="停用" /></el-form-item>
          <el-form-item label="计划停机开始日"><el-date-picker v-model="planForm.downtimeStart" type="date" value-format="YYYY-MM-DD" placeholder="可选" /></el-form-item>
          <el-form-item label="计划停机结束日"><el-date-picker v-model="planForm.downtimeEnd" type="date" value-format="YYYY-MM-DD" placeholder="可选" /></el-form-item>
        </div>
        <el-alert title="计划停机若与待审批、已批准或使用中的预约重叠，系统会拒绝保存；请先协调预约。" type="info" :closable="false" show-icon />
      </el-form>
      <template #footer><GhostButton @click="planDialog = false">取消</GhostButton><GradientButton type="primary" :loading="submitting" @click="savePlan">保存计划</GradientButton></template>
    </el-dialog>

    <el-dialog v-model="completionDialog" title="登记维护完成" width="min(620px, 94vw)" destroy-on-close>
      <div v-if="completingPlan" class="completion-context">
        <span class="maintenance-eyebrow">{{ TYPE_LABELS[completingPlan.planType] }} / {{ completingPlan.deviceAssetCode || `#${completingPlan.deviceId}` }}</span>
        <strong>{{ completingPlan.deviceName }} · {{ completingPlan.title }}</strong>
        <small>本次维护周期到期日：{{ completingPlan.dueDate }}</small>
      </div>
      <el-form label-position="top">
        <el-form-item label="实际完成日期" required><el-date-picker v-model="completionForm.completedDate" type="date" value-format="YYYY-MM-DD" :disabled-date="disableFutureDate" /></el-form-item>
        <el-form-item label="检查结果" required><el-radio-group v-model="completionForm.result"><el-radio-button value="PASSED">通过</el-radio-button><el-radio-button value="FAILED">未通过</el-radio-button></el-radio-group></el-form-item>
        <el-form-item :label="evidenceRequired ? '校准证书 / 安全检查记录（必传）' : '完成凭证（可选）'">
          <label class="evidence-picker"><Upload /><span>{{ completionFile?.name || '选择 PDF、JPG 或 PNG' }}</span><input type="file" accept="application/pdf,image/jpeg,image/png" @change="onEvidenceChange" /></label>
          <small class="evidence-hint">文件会在提交前校验格式、大小与学院存储配额。</small>
        </el-form-item>
        <el-form-item :label="completionForm.result === 'FAILED' ? '未通过情况（必填）' : '维护备注'"><el-input v-model="completionForm.notes" type="textarea" :rows="4" maxlength="2000" show-word-limit :placeholder="completionForm.result === 'FAILED' ? '填写故障或不合格项目，系统会自动创建报修工单。' : '记录更换零件、检查结论等。'" /></el-form-item>
      </el-form>
      <el-alert v-if="completionForm.result === 'FAILED'" title="提交后设备会进入维护状态，并自动创建关联报修工单。" type="warning" :closable="false" show-icon />
      <template #footer><GhostButton @click="completionDialog = false">取消</GhostButton><GradientButton type="primary" :loading="completionSubmitting" @click="submitCompletion">提交完成记录</GradientButton></template>
    </el-dialog>

    <el-dialog v-model="historyDialog" :title="`${historyPlan?.title || '维护计划'} · 完成记录`" width="min(760px, 94vw)">
      <div v-loading="historyLoading" class="history-list">
        <article v-for="record in historyRecords" :key="record.id" class="history-card">
          <div class="history-card__top"><Tag :variant="record.result === 'PASSED' ? 'success' : 'danger'" size="small">{{ record.result === 'PASSED' ? '检查通过' : '检查未通过' }}</Tag><time>{{ record.completedDate }}</time></div>
          <p>{{ record.notes || '未填写备注' }}</p>
          <div class="history-card__foot"><span>{{ record.performedByName || `用户 #${record.performedBy}` }}</span><TextButton v-if="record.evidenceUrl" @click="downloadEvidence(record)">{{ record.evidenceName || '下载凭证' }}</TextButton><TextButton v-if="record.repairReportId" @click="router.push({ name: 'repairs-admin' })">报修工单 #{{ record.repairReportId }}</TextButton></div>
        </article>
        <EmptyState v-if="!historyLoading && historyRecords.length === 0" :icon="Document" title="暂无完成记录" description="每次保养或检查完成后，记录会保存在这里。" />
      </div>
      <template #footer><el-pagination v-if="historyTotal > 20" :current-page="historyPage" :page-size="20" :total="historyTotal" layout="prev, pager, next" @current-change="(value: number) => historyPlan && showHistory(historyPlan, value)" /></template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.maintenance-page { display: grid; gap: 20px; }
.maintenance-eyebrow { color: var(--accent); font-family: var(--font-mono); font-size: 10px; letter-spacing: .14em; }
.maintenance-hero { display: flex; align-items: center; justify-content: space-between; gap: 24px; min-height: 205px; padding: 28px 32px; border: 1px solid var(--border-default); border-radius: var(--radius-card); background: radial-gradient(circle at 85% 48%, color-mix(in srgb, var(--accent) 12%, transparent), transparent 29%), linear-gradient(112deg, color-mix(in srgb, var(--bg-surface) 90%, var(--accent) 10%), var(--bg-surface)); overflow: hidden; }
.maintenance-hero h2 { margin: 8px 0 10px; color: var(--text-primary); font-family: var(--font-display); font-size: clamp(24px, 3vw, 36px); letter-spacing: -.045em; }
.maintenance-hero p { max-width: 760px; margin: 0; color: var(--text-secondary); line-height: 1.75; }
.maintenance-hero__mark { display: grid; place-items: center; gap: 8px; width: 112px; height: 112px; flex: none; border: 1px solid color-mix(in srgb, var(--accent) 25%, var(--border-default)); border-radius: 34px; color: var(--accent); background: color-mix(in srgb, var(--accent) 6%, var(--bg-surface)); transform: rotate(6deg); }
.maintenance-hero__mark :deep(svg) { width: 28px; height: 28px; }
.maintenance-hero__mark span { font-family: var(--font-mono); font-size: 9px; line-height: 1.3; letter-spacing: .13em; text-align: center; }
.maintenance-policy-strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border: 1px solid var(--border-default); border-radius: var(--radius-card); background: var(--bg-surface); overflow: hidden; }
.maintenance-policy-strip > div { display: grid; grid-template-columns: 34px 1fr; gap: 3px 10px; align-content: center; min-height: 92px; padding: 16px 20px; border-right: 1px solid var(--border-subtle); }
.maintenance-policy-strip > div:last-child { border-right: 0; }
.policy-index { grid-row: span 2; align-self: center; color: var(--accent); font-family: var(--font-mono); font-size: 12px; }
.maintenance-policy-strip strong { color: var(--text-primary); font-size: 13px; }
.maintenance-policy-strip small { color: var(--text-tertiary); font-size: 11px; line-height: 1.5; }
.maintenance-list { min-width: 0; padding: 22px; border: 1px solid var(--border-default); border-radius: var(--radius-card); background: var(--bg-surface); }
.maintenance-list__head,.maintenance-list__filters,.maintenance-list__foot { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.maintenance-list__head { margin-bottom: 18px; }
.maintenance-list__head h3 { margin: 5px 0 0; color: var(--text-primary); font-size: 18px; }
.maintenance-list__filters { justify-content: flex-end; }
.maintenance-list__filters :deep(.el-select) { width: 280px; }
.maintenance-list__foot { justify-content: flex-end; margin-top: 16px; }
.plan-device { display: grid; gap: 3px; }
.plan-device > span,.plan-device small,.row-warning { color: var(--text-tertiary); font-size: 11px; }
.plan-device strong { color: var(--text-primary); font-size: 13px; }
.date-overdue { color: var(--color-danger, #f56c6c); }
.row-warning { display: block; margin-top: 3px; }
.maintenance-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 18px; }
.maintenance-form-grid :deep(.el-select),.maintenance-form-grid :deep(.el-date-editor) { width: 100%; }
.interval-control { display: flex; width: 100%; gap: 8px; }
.interval-control :deep(.el-input-number) { flex: 1; }
.interval-control :deep(.el-select) { width: 120px; }
.completion-context { display: grid; gap: 6px; margin-bottom: 18px; padding: 14px 16px; border-left: 2px solid var(--accent); background: color-mix(in srgb, var(--accent) 5%, var(--bg-surface)); }
.completion-context strong { color: var(--text-primary); }
.completion-context small,.evidence-hint { color: var(--text-tertiary); font-size: 12px; }
.evidence-picker { display: flex; align-items: center; gap: 9px; width: 100%; padding: 12px 14px; border: 1px dashed var(--border-default); border-radius: var(--radius-control); color: var(--text-secondary); cursor: pointer; }
.evidence-picker :deep(svg) { width: 17px; color: var(--accent); }
.evidence-picker input { display: none; }
.evidence-hint { display: block; margin-top: 6px; }
.history-list { display: grid; gap: 10px; min-height: 100px; }
.history-card { padding: 15px 16px; border: 1px solid var(--border-subtle); border-radius: 12px; background: color-mix(in srgb, var(--bg-surface) 94%, var(--text-primary) 6%); }
.history-card__top,.history-card__foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.history-card__top time,.history-card__foot { color: var(--text-tertiary); font-size: 12px; }
.history-card p { margin: 12px 0; color: var(--text-secondary); white-space: pre-wrap; }
.history-card__foot { justify-content: flex-start; flex-wrap: wrap; }
.history-card__foot span { margin-right: auto; }
@media (max-width: 800px) { .maintenance-policy-strip { grid-template-columns: 1fr; } .maintenance-policy-strip > div { border-right: 0; border-bottom: 1px solid var(--border-subtle); } .maintenance-policy-strip > div:last-child { border-bottom: 0; } .maintenance-list__head { align-items: flex-start; flex-direction: column; } .maintenance-list__filters { width: 100%; justify-content: flex-start; flex-wrap: wrap; } .maintenance-list__filters :deep(.el-select) { width: min(100%, 280px); } }
@media (max-width: 560px) { .maintenance-hero { padding: 22px; } .maintenance-hero__mark { display: none; } .maintenance-form-grid { grid-template-columns: 1fr; } .maintenance-list { padding: 15px; } }
</style>
