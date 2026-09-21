<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listColleges } from '@/api/college'
import { listLabs } from '@/api/lab'
import { searchDevices } from '@/api/device'
import { createBlackout, deleteBlackout, listBlackouts, type BlackoutVO } from '@/api/scheduling'
import type { CollegeVO } from '@/types/college'
import type { Lab } from '@/types/lab'
import type { DeviceVO } from '@/types/device'
import PageHeader from '@/components/ui/PageHeader.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import TextButton from '@/components/ui/TextButton.vue'
import Tag from '@/components/ui/Tag.vue'

const loading = ref(false)
const submitting = ref(false)
const rows = ref<BlackoutVO[]>([])
const colleges = ref<CollegeVO[]>([])
const labs = ref<Lab[]>([])
const devices = ref<DeviceVO[]>([])
const form = ref({
  scopeType: 'COLLEGE' as BlackoutVO['scopeType'],
  scopeId: undefined as number | undefined,
  blockedDate: '',
  reason: '',
})

const scopeOptions = computed(() => {
  if (form.value.scopeType === 'COLLEGE') return colleges.value.map((row) => ({ id: row.id, name: row.name }))
  if (form.value.scopeType === 'LAB') return labs.value.map((row) => ({ id: row.id, name: row.name }))
  return devices.value.map((row) => ({ id: row.id, name: row.name }))
})

const scopeLabel = (row: BlackoutVO) => {
  const list = row.scopeType === 'COLLEGE' ? colleges.value : row.scopeType === 'LAB' ? labs.value : devices.value
  const found = list.find((item) => item.id === row.scopeId)
  return found ? ('name' in found ? found.name : '') : `#${row.scopeId}`
}

const typeLabel = (type: BlackoutVO['scopeType']) => ({ COLLEGE: '学院', LAB: '实验室', DEVICE: '设备' })[type]

async function loadOptions() {
  const [collegeResult, labResult, deviceResult] = await Promise.all([
    listColleges(),
    listLabs(1, 100),
    searchDevices({ page: 1, size: 100 }),
  ])
  colleges.value = collegeResult
  labs.value = labResult.records
  devices.value = deviceResult.records
  if (!form.value.scopeId) form.value.scopeId = scopeOptions.value[0]?.id
}

async function load() {
  loading.value = true
  try {
    await loadOptions()
    rows.value = await listBlackouts()
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function onScopeTypeChange() {
  form.value.scopeId = scopeOptions.value[0]?.id
}

async function submit() {
  if (!form.value.scopeId || !form.value.blockedDate || form.value.reason.trim().length < 2) {
    ElMessage.warning('请完整填写范围、日期和原因')
    return
  }
  submitting.value = true
  try {
    const created = await createBlackout({
      scopeType: form.value.scopeType,
      scopeId: form.value.scopeId,
      blockedDate: form.value.blockedDate,
      reason: form.value.reason.trim(),
    })
    rows.value = [...rows.value, created].sort((a, b) => a.blockedDate.localeCompare(b.blockedDate))
    form.value.blockedDate = ''
    form.value.reason = ''
    ElMessage.success('不可预约日期已生效')
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false
  }
}

async function remove(row: BlackoutVO) {
  try {
    await ElMessageBox.confirm(`确认解除 ${row.blockedDate} 的不可预约设置？`, '解除日期限制', {
      type: 'warning',
      confirmButtonText: '解除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteBlackout(row.id)
    rows.value = rows.value.filter((item) => item.id !== row.id)
    ElMessage.success('日期限制已解除')
  } catch {
    // 拦截器已提示
  }
}

onMounted(load)
</script>

<template>
  <div class="schedule-page" v-loading="loading">
    <PageHeader title="预约规则" subtitle="按学院、实验室或设备配置不可预约的自然日">
      <template #actions><Tag variant="info" effect="light" round>仅管理员可见</Tag></template>
    </PageHeader>

    <section class="schedule-page__intro">
      <div>
        <span class="schedule-page__eyebrow">BOOKING POLICY</span>
        <h2>把节假日、维护日和教学占用日提前写进规则。</h2>
        <p>规则会同时影响设备可用性预检和最终预约校验，避免只在页面上提示而未落库。</p>
      </div>
    </section>

    <section class="schedule-page__form">
      <div class="schedule-page__form-head"><span class="schedule-page__eyebrow">ADD BLACKOUT</span><strong>新增不可预约日</strong></div>
      <el-form label-position="top">
        <div class="schedule-page__form-grid">
          <el-form-item label="作用范围">
            <el-select v-model="form.scopeType" @change="onScopeTypeChange">
              <el-option label="学院" value="COLLEGE" />
              <el-option label="实验室" value="LAB" />
              <el-option label="设备" value="DEVICE" />
            </el-select>
          </el-form-item>
          <el-form-item label="范围对象">
            <el-select v-model="form.scopeId" filterable placeholder="选择对象">
              <el-option v-for="option in scopeOptions" :key="option.id" :label="option.name" :value="option.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="不可预约日期">
            <el-date-picker v-model="form.blockedDate" type="date" value-format="YYYY-MM-DD" placeholder="选择自然日" />
          </el-form-item>
          <el-form-item label="原因">
            <el-input v-model="form.reason" maxlength="500" placeholder="例如：国庆假期 / 设备年度检修" />
          </el-form-item>
        </div>
        <div class="schedule-page__form-actions"><GradientButton :loading="submitting" type="primary" @click="submit">保存规则</GradientButton></div>
      </el-form>
    </section>

    <section class="schedule-page__table">
      <div class="schedule-page__table-head"><strong>当前生效规则</strong><span>{{ rows.length }} 条</span></div>
      <el-table :data="rows" stripe row-key="id">
        <el-table-column label="范围" width="100"><template #default="{ row }">{{ typeLabel(row.scopeType) }}</template></el-table-column>
        <el-table-column label="对象" min-width="180"><template #default="{ row }">{{ scopeLabel(row) }}</template></el-table-column>
        <el-table-column prop="blockedDate" label="日期" width="140" />
        <el-table-column prop="reason" label="原因" min-width="240" show-overflow-tooltip />
        <el-table-column label="操作" width="100"><template #default="{ row }"><TextButton @click="remove(row)">解除</TextButton></template></el-table-column>
        <template #empty><span class="schedule-page__empty">暂无不可预约日期</span></template>
      </el-table>
    </section>
  </div>
</template>

<style scoped lang="scss">
.schedule-page { display: grid; gap: 20px; }
.schedule-page__intro { padding: 24px; border: 1px solid var(--border-default); border-radius: var(--radius-card); background: linear-gradient(110deg, color-mix(in srgb, var(--accent) 9%, var(--bg-surface)), var(--bg-surface)); }
.schedule-page__intro h2 { max-width: 700px; margin: 8px 0; color: var(--text-primary); font-family: var(--font-display); font-size: clamp(22px, 3vw, 34px); letter-spacing: -.04em; }
.schedule-page__intro p { max-width: 680px; margin: 0; color: var(--text-secondary); line-height: 1.7; }
.schedule-page__eyebrow { color: var(--accent); font-family: var(--font-mono); font-size: 10px; letter-spacing: .14em; }
.schedule-page__form,.schedule-page__table { padding: 20px; border: 1px solid var(--border-default); border-radius: var(--radius-card); background: var(--bg-surface); }
.schedule-page__form-head,.schedule-page__table-head { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 18px; color: var(--text-primary); }
.schedule-page__form-head { display: grid; gap: 6px; }
.schedule-page__form-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.schedule-page__form-grid :deep(.el-select),.schedule-page__form-grid :deep(.el-date-editor) { width: 100%; }
.schedule-page__form-actions { display: flex; justify-content: flex-end; padding-top: 4px; }
.schedule-page__table-head span { color: var(--text-tertiary); font-family: var(--font-mono); font-size: 12px; }
.schedule-page__empty { color: var(--text-tertiary); }
@media (max-width: 900px) { .schedule-page__form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px) { .schedule-page__form-grid { grid-template-columns: 1fr; } }
</style>
