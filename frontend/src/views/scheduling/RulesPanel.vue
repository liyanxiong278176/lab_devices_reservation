<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listColleges } from '@/api/college'
import { listAllLabs } from '@/api/lab'
import { useRemoteDeviceOptions } from '@/composables/useRemoteDeviceOptions'
import {
  deleteReservationRule,
  listReservationRules,
  saveReservationRule,
  type ReservationRuleCategory,
  type ReservationRuleScope,
  type ReservationRuleVO,
} from '@/api/reservationRules'
import { useUserStore } from '@/stores/user'
import type { CollegeVO } from '@/types/college'
import type { Lab } from '@/types/lab'
import GradientButton from '@/components/ui/GradientButton.vue'
import TextButton from '@/components/ui/TextButton.vue'
import Tag from '@/components/ui/Tag.vue'

const userStore = useUserStore()
const loading = ref(false)
const saving = ref(false)
const rows = ref<ReservationRuleVO[]>([])
const page = ref(1)
const pageSize = 20
const total = ref(0)
const pages = ref(0)
const truncated = ref(false)
const reachableTotal = computed(() => Math.min(total.value, pages.value * pageSize))
const filterScopeType = ref<ReservationRuleScope | undefined>()
const filterUserCategory = ref<ReservationRuleCategory | undefined>()
const filterScopeId = ref('')
const scopeFilterOptions: Array<{ value: ReservationRuleScope; label: string }> = [
  { value: 'GLOBAL', label: '全校' },
  { value: 'COLLEGE', label: '学院' },
  { value: 'LAB', label: '实验室' },
  { value: 'DEVICE', label: '设备' },
]
const categoryFilterOptions: Array<{ value: ReservationRuleCategory; label: string }> = [
  { value: 'ALL', label: '所有用户' },
  { value: 'STUDENT', label: '普通用户' },
  { value: 'LAB_ADMIN', label: '实验室负责人' },
]
const colleges = ref<CollegeVO[]>([])
const labs = ref<Lab[]>([])
const {
  options: deviceOptions,
  loading: deviceSearchLoading,
  loadInitial: loadDeviceOptions,
  search: searchRuleDevices,
} = useRemoteDeviceOptions()
const isSystemAdmin = computed(() => userStore.roles.includes('SYS_ADMIN'))
const form = reactive<{
  scopeType: ReservationRuleScope
  scopeId: number | undefined
  userCategory: ReservationRuleCategory
  maxBookingDays: number | undefined
  maxAdvanceDays: number | undefined
  approvalRequired: boolean | undefined
}>({
  scopeType: 'COLLEGE',
  scopeId: undefined,
  userCategory: 'STUDENT',
  maxBookingDays: undefined,
  maxAdvanceDays: undefined,
  approvalRequired: undefined,
})

const visibleColleges = computed(() => {
  if (isSystemAdmin.value) return colleges.value
  return colleges.value.filter((row) => row.managerId === userStore.userId)
})
const visibleLabs = computed(() => {
  if (isSystemAdmin.value) return labs.value
  const collegeIds = new Set(visibleColleges.value.map((row) => row.id))
  return labs.value.filter((row) => row.managerId === userStore.userId || collegeIds.has(row.collegeId || 0))
})
const visibleDevices = computed(() => {
  if (isSystemAdmin.value) return deviceOptions.value
  const collegeIds = new Set(visibleColleges.value.map((row) => row.id))
  const labIds = new Set(visibleLabs.value.map((row) => row.id))
  return deviceOptions.value.filter(
    (row) =>
      (row.collegeId !== null && row.collegeId !== undefined && collegeIds.has(row.collegeId)) ||
      (row.labId !== null && row.labId !== undefined && labIds.has(row.labId)),
  )
})
const scopeOptions = computed(() => {
  if (form.scopeType === 'GLOBAL') return [{ id: 0, name: '全校默认' }]
  if (form.scopeType === 'COLLEGE') return visibleColleges.value.map((row) => ({ id: row.id, name: row.name }))
  if (form.scopeType === 'LAB') return visibleLabs.value.map((row) => ({ id: row.id, name: row.name }))
  const available = visibleDevices.value.map((row) => ({
    id: row.id,
    name: `${row.assetCode || `设备 #${row.id}`} · ${row.name} · ${row.labName || '未分配实验室'}`,
  }))
  const configured = rows.value
    .filter((row) => row.scopeType === 'DEVICE')
    .map((row) => ({ id: row.scopeId, name: row.scopeName }))
  return [...new Map([...available, ...configured].map((option) => [option.id, option])).values()]
})

const categoryLabel = (value: ReservationRuleCategory) => ({
  ALL: '所有用户',
  STUDENT: '普通用户',
  LAB_ADMIN: '实验室负责人',
})[value]

const scopeLabel = (value: ReservationRuleScope) => ({
  GLOBAL: '全校',
  COLLEGE: '学院',
  LAB: '实验室',
  DEVICE: '设备',
})[value]

async function load(targetPage = page.value) {
  loading.value = true
  try {
    const [collegeRows, labRows, rules] = await Promise.all([
      listColleges(),
      listAllLabs(),
      listReservationRules(targetPage, pageSize, {
        scopeType: filterScopeType.value,
        userCategory: filterUserCategory.value,
        scopeId: filterScopeId.value ? Number(filterScopeId.value) : undefined,
      }),
      loadDeviceOptions(),
    ])
    colleges.value = collegeRows
    labs.value = labRows
    rows.value = rules.items
    page.value = rules.page
    total.value = rules.total
    pages.value = rules.pages
    truncated.value = rules.truncated
    if (form.scopeType === 'GLOBAL' && !isSystemAdmin.value) form.scopeType = 'COLLEGE'
    if (!isSystemAdmin.value && form.scopeType === 'COLLEGE' && visibleColleges.value.length === 0) {
      form.scopeType = 'LAB'
    }
    if (!scopeOptions.value.some((option) => option.id === form.scopeId)) {
      form.scopeId = scopeOptions.value[0]?.id
    }
  } catch {
    // The shared request interceptor presents the API error.
  } finally {
    loading.value = false
  }
}

function onScopeChange() {
  form.scopeId = scopeOptions.value[0]?.id
}

function edit(row: ReservationRuleVO) {
  form.scopeType = row.scopeType
  form.scopeId = row.scopeId
  form.userCategory = row.userCategory
  form.maxBookingDays = row.maxBookingDays ?? undefined
  form.maxAdvanceDays = row.maxAdvanceDays ?? undefined
  form.approvalRequired = row.approvalRequired ?? undefined
}

function clearForm() {
  if (isSystemAdmin.value) form.scopeType = 'GLOBAL'
  else if (visibleColleges.value.length > 0) form.scopeType = 'COLLEGE'
  else form.scopeType = 'LAB'
  form.scopeId = scopeOptions.value[0]?.id
  form.userCategory = 'STUDENT'
  form.maxBookingDays = undefined
  form.maxAdvanceDays = undefined
  form.approvalRequired = undefined
}

async function save() {
  if (form.scopeId === undefined) {
    ElMessage.warning('当前范围没有可配置对象')
    return
  }
  if (form.maxBookingDays === undefined && form.maxAdvanceDays === undefined && form.approvalRequired === undefined) {
    ElMessage.warning('至少设置一项规则，未设置的项目会继承上级')
    return
  }
  saving.value = true
  try {
    await saveReservationRule({
      scopeType: form.scopeType,
      scopeId: form.scopeId,
      userCategory: form.userCategory,
      maxBookingDays: form.maxBookingDays ?? null,
      maxAdvanceDays: form.maxAdvanceDays ?? null,
      approvalRequired: form.approvalRequired ?? null,
    })
    await load(1)
    ElMessage.success('预约规则已保存')
  } catch {
    // Shared interceptor presents API errors.
  } finally {
    saving.value = false
  }
}

async function remove(row: ReservationRuleVO) {
  try {
    await ElMessageBox.confirm(`删除「${row.scopeName} · ${categoryLabel(row.userCategory)}」规则？`, '移除预约规则', {
      type: 'warning',
      confirmButtonText: '删除规则',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteReservationRule(row.id)
    await load(rows.value.length === 1 && page.value > 1 ? page.value - 1 : page.value)
    ElMessage.success('规则已移除，预约将继承上级设置')
  } catch {
    // Shared interceptor presents API errors.
  }
}

function onPageChange(nextPage: number) {
  void load(nextPage)
}

function onFilterChange() {
  if (filterScopeId.value && !/^\d+$/.test(filterScopeId.value)) {
    ElMessage.warning('范围 ID 只能填写非负整数')
    return
  }
  void load(1)
}

onMounted(load)
</script>

<template>
  <div class="rules-panel" v-loading="loading">
    <section class="rules-panel__note">
      <span class="rules-panel__eyebrow">POLICY PRECEDENCE</span>
      <h2>规则按用户身份与设备范围逐层生效</h2>
      <p>先匹配普通用户或实验室负责人，再按设备 → 实验室 → 学院 → 全校默认查找。留空的字段继承上级规则；身份专属限制不会被“所有用户”规则放宽。</p>
      <div class="rules-panel__chips">
        <Tag variant="info" size="small">单次连续预约天数</Tag>
        <Tag variant="info" size="small">最早可提前预约天数</Tag>
        <Tag variant="info" size="small">是否需要审批</Tag>
        <Tag variant="success" size="small">不限制预约数量</Tag>
      </div>
    </section>

    <section class="rules-panel__editor">
      <header class="rules-panel__section-head">
        <div><span class="rules-panel__eyebrow">RULE EDITOR</span><strong>配置预约规则</strong></div>
        <TextButton @click="clearForm">清空表单</TextButton>
      </header>
      <el-form label-position="top">
        <div class="rules-panel__grid">
          <el-form-item label="资源范围">
            <el-select v-model="form.scopeType" @change="onScopeChange">
              <el-option v-if="isSystemAdmin" label="全校默认" value="GLOBAL" />
              <el-option label="学院" value="COLLEGE" />
              <el-option label="实验室" value="LAB" />
              <el-option label="设备" value="DEVICE" />
            </el-select>
          </el-form-item>
          <el-form-item label="范围对象">
            <el-select
              v-model="form.scopeId"
              filterable
              :remote="form.scopeType === 'DEVICE'"
              :remote-method="searchRuleDevices"
              :loading="deviceSearchLoading"
              placeholder="选择资源范围"
            >
              <el-option v-for="option in scopeOptions" :key="option.id" :label="option.name" :value="option.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="用户类别">
            <el-select v-model="form.userCategory">
              <el-option label="普通用户" value="STUDENT" />
              <el-option label="实验室负责人" value="LAB_ADMIN" />
              <el-option label="所有用户" value="ALL" />
            </el-select>
          </el-form-item>
          <el-form-item label="单次最多连续预约">
            <el-input-number v-model="form.maxBookingDays" :min="1" :max="31" controls-position="right" />
            <button v-if="form.maxBookingDays !== undefined" class="rules-panel__inherit" type="button" @click="form.maxBookingDays = undefined">继承上级</button>
            <small v-else class="rules-panel__hint">继承上级规则</small>
          </el-form-item>
          <el-form-item label="最多提前预约">
            <el-input-number v-model="form.maxAdvanceDays" :min="1" :max="365" controls-position="right" />
            <button v-if="form.maxAdvanceDays !== undefined" class="rules-panel__inherit" type="button" @click="form.maxAdvanceDays = undefined">继承上级</button>
            <small v-else class="rules-panel__hint">继承上级规则</small>
          </el-form-item>
          <el-form-item label="审批方式">
            <el-select v-model="form.approvalRequired" clearable placeholder="继承上级规则">
              <el-option label="需要负责人审批" :value="true" />
              <el-option label="无需审批，自动确认" :value="false" />
            </el-select>
          </el-form-item>
        </div>
        <footer class="rules-panel__actions">
          <GradientButton :loading="saving" type="primary" @click="save">保存规则</GradientButton>
        </footer>
      </el-form>
    </section>

    <section class="rules-panel__table">
      <header class="rules-panel__section-head">
        <div><span class="rules-panel__eyebrow">ACTIVE POLICIES</span><strong>已配置规则</strong></div>
        <span class="rules-panel__count">共 {{ total }} 条</span>
      </header>
      <div class="rules-panel__filters">
        <el-select
          v-model="filterScopeType"
          clearable
          placeholder="全部范围"
          @change="onFilterChange"
        >
          <el-option
            v-for="option in scopeFilterOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-select
          v-model="filterUserCategory"
          clearable
          placeholder="全部用户类别"
          @change="onFilterChange"
        >
          <el-option
            v-for="option in categoryFilterOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-input
          v-model="filterScopeId"
          clearable
          placeholder="范围 ID（可选）"
          @change="onFilterChange"
          @keyup.enter="onFilterChange"
        />
        <TextButton @click="onFilterChange">筛选</TextButton>
      </div>
      <el-table :data="rows" stripe row-key="id">
        <el-table-column label="范围" width="100"><template #default="{ row }">{{ scopeLabel(row.scopeType) }}</template></el-table-column>
        <el-table-column prop="scopeName" label="对象" min-width="180" show-overflow-tooltip />
        <el-table-column label="适用用户" width="140"><template #default="{ row }"><Tag variant="info" size="small">{{ categoryLabel(row.userCategory) }}</Tag></template></el-table-column>
        <el-table-column label="连续预约" width="130"><template #default="{ row }">{{ row.maxBookingDays ? `${row.maxBookingDays} 天` : '继承' }}</template></el-table-column>
        <el-table-column label="提前期" width="120"><template #default="{ row }">{{ row.maxAdvanceDays ? `${row.maxAdvanceDays} 天` : '继承' }}</template></el-table-column>
        <el-table-column label="审批" width="140"><template #default="{ row }">{{ row.approvalRequired === null ? '继承' : row.approvalRequired ? '需审批' : '自动确认' }}</template></el-table-column>
        <el-table-column label="操作" width="150"><template #default="{ row }"><TextButton @click="edit(row)">编辑</TextButton><TextButton @click="remove(row)">删除</TextButton></template></el-table-column>
        <template #empty><span class="rules-panel__empty">当前范围尚无显式规则，预约使用系统默认设置。</span></template>
      </el-table>
      <p v-if="truncated" class="rules-panel__limit-hint">列表为保护查询性能限制了最深可访问页，请使用上方条件缩小结果范围。</p>
      <el-pagination
        v-if="pages > 1"
        class="rules-panel__pagination"
        background
        layout="prev, pager, next, jumper"
        :current-page="page"
        :page-size="pageSize"
        :total="reachableTotal"
        :pager-count="7"
        @current-change="onPageChange"
      />
    </section>
  </div>
</template>

<style scoped lang="scss">
.rules-panel { display: grid; gap: 18px; }
.rules-panel__note,.rules-panel__editor,.rules-panel__table { padding: 22px; border: 1px solid var(--border-default); border-radius: var(--radius-card); background: var(--bg-surface); }
.rules-panel__note { background: linear-gradient(112deg, color-mix(in srgb, var(--accent) 9%, var(--bg-surface)), var(--bg-surface) 66%); }
.rules-panel__eyebrow { display: block; color: var(--accent); font-family: var(--font-mono); font-size: 10px; letter-spacing: .14em; }
.rules-panel__note h2 { margin: 8px 0; color: var(--text-primary); font-family: var(--font-display); font-size: clamp(20px, 2.5vw, 28px); letter-spacing: -.035em; }
.rules-panel__note p { max-width: 900px; margin: 0; color: var(--text-secondary); line-height: 1.7; }
.rules-panel__chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.rules-panel__section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 18px; color: var(--text-primary); }
.rules-panel__section-head strong { display: block; margin-top: 5px; font-size: 16px; }
.rules-panel__grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px 16px; }
.rules-panel__grid :deep(.el-select),.rules-panel__grid :deep(.el-input-number) { width: 100%; }
.rules-panel__inherit { margin: 5px 0 0; padding: 0; border: 0; color: var(--accent); background: none; font-size: 12px; cursor: pointer; }
.rules-panel__hint { display: block; margin-top: 5px; color: var(--text-tertiary); font-size: 12px; }
.rules-panel__actions { display: flex; justify-content: flex-end; padding-top: 8px; }
.rules-panel__count,.rules-panel__empty { color: var(--text-tertiary); font-size: 13px; }
.rules-panel__pagination { justify-content: flex-end; margin-top: 18px; }
.rules-panel__limit-hint { margin: 12px 0 0; color: var(--text-tertiary); font-size: 12px; }
.rules-panel__filters { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 0 0 14px; }
.rules-panel__filters :deep(.el-select) { width: 180px; }
.rules-panel__filters :deep(.el-input) { width: 160px; }
@media (max-width: 900px) { .rules-panel__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px) { .rules-panel__grid { grid-template-columns: 1fr; } }
</style>
