<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import { ElMessage } from 'element-plus'
import {
  createReportExport,
  downloadReport,
  downloadReportExport,
  getReportExport,
  getReportSummary,
  type ExportTaskVO,
  type ReportExportType,
  type ReportSummaryVO,
} from '@/api/reports'
import PageHeader from '@/components/ui/PageHeader.vue'
import GlowCard from '@/components/ui/GlowCard.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import TextButton from '@/components/ui/TextButton.vue'
import Tag from '@/components/ui/Tag.vue'

const today = dayjs().format('YYYY-MM-DD')
const monthStart = dayjs().startOf('month').format('YYYY-MM-DD')
const startDate = ref(monthStart)
const endDate = ref(today)
const loading = ref(false)
const exporting = ref<ReportExportType | null>(null)
const summary = ref<ReportSummaryVO | null>(null)
const task = ref<ExportTaskVO | null>(null)
let pollTimer: ReturnType<typeof setTimeout> | null = null
const exportOptions: { type: ReportExportType; label: string }[] = [
  { type: 'devices', label: '设备台账' },
  { type: 'reservations', label: '预约记录' },
  { type: 'repairs', label: '报修记录' },
]

const reportFilters = computed(() => ({ startDate: startDate.value, endDate: endDate.value }))

const metrics = computed(() => {
  const value = summary.value
  if (!value) return []
  return [
    { label: '可管理设备', value: value.deviceCount, unit: '台', tone: 'accent' },
    { label: '预约记录', value: value.reservationCount, unit: '条', tone: 'blue' },
    { label: '报修工单', value: value.repairCount, unit: '条', tone: 'amber' },
    { label: '设备利用率', value: formatPercent(value.utilizationRate), unit: '', tone: 'green' },
  ]
})

function formatPercent(value: number) {
  return `${(value * 100).toFixed(1)}%`
}

function statusLabel(value: string) {
  const labels: Record<string, string> = {
    PENDING: '待处理',
    APPROVED: '已通过',
    IN_USE: '使用中',
    RETURN_PENDING: '待验收',
    COMPLETED: '已完成',
    CANCELLED: '已取消',
    REJECTED: '已拒绝',
    NO_SHOW: '爽约',
    VIOLATED: '违规',
    PROCESSING: '处理中',
    RESOLVED: '待确认',
  }
  return labels[value] || value
}

async function load() {
  if (!startDate.value || !endDate.value || endDate.value < startDate.value) {
    ElMessage.warning('请选择有效的日期范围')
    return
  }
  loading.value = true
  try {
    summary.value = await getReportSummary(reportFilters.value)
  } catch {
    summary.value = null
  } finally {
    loading.value = false
  }
}

async function directExport(type: ReportExportType) {
  exporting.value = type
  try {
    await downloadReport(type, reportFilters.value)
    ElMessage.success('报表已下载')
  } catch {
    // 超过同步阈值时由管理员改用异步导出。
  } finally {
    exporting.value = null
  }
}

function stopPolling() {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}

async function pollExport(id: number) {
  try {
    task.value = await getReportExport(id)
    if (task.value.status === 'COMPLETED' || task.value.status === 'FAILED') {
      if (task.value.status === 'COMPLETED') ElMessage.success('异步报表已生成')
      else ElMessage.error(task.value.error || '异步报表生成失败')
      return
    }
    pollTimer = setTimeout(() => void pollExport(id), 1200)
  } catch {
    stopPolling()
  }
}

async function asyncExport(type: ReportExportType) {
  exporting.value = type
  stopPolling()
  try {
    task.value = await createReportExport(type, reportFilters.value)
    void pollExport(task.value.id)
    ElMessage.success('已提交异步导出任务')
  } finally {
    exporting.value = null
  }
}

async function downloadTask() {
  if (!task.value || task.value.status !== 'COMPLETED') return
  await downloadReportExport(task.value.id, task.value.export_type)
  ElMessage.success('报表已下载')
}

onMounted(load)
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="reports-page">
    <PageHeader title="运营报表" subtitle="只展示当前负责人可管理范围内的数据，支持自然日统计与 CSV 导出。" />

    <section class="reports-page__toolbar" aria-label="报表筛选">
      <div class="reports-page__field">
        <label for="report-start">开始日期</label>
        <input id="report-start" v-model="startDate" type="date" />
      </div>
      <div class="reports-page__field">
        <label for="report-end">结束日期</label>
        <input id="report-end" v-model="endDate" type="date" />
      </div>
      <GradientButton :loading="loading" @click="load">刷新统计</GradientButton>
    </section>

    <section v-loading="loading" class="reports-page__metrics">
      <GlowCard v-for="metric in metrics" :key="metric.label" class="report-metric" :class="`report-metric--${metric.tone}`">
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}<small>{{ metric.unit }}</small></strong>
      </GlowCard>
      <div v-if="!loading && !summary" class="reports-page__empty">选择日期范围后刷新报表。</div>
    </section>

    <section v-if="summary" class="reports-page__columns">
      <GlowCard class="reports-panel">
        <header class="reports-panel__head">
          <div><span class="reports-page__eyebrow">RESERVATIONS</span><h2>预约状态分布</h2></div>
          <span>{{ summary.reservationCount }} 条</span>
        </header>
        <div class="reports-panel__status-list">
          <div v-for="(count, name) in summary.reservationStatus" :key="name" class="reports-panel__status-row">
            <span>{{ statusLabel(name) }}</span><strong>{{ count }}</strong>
          </div>
        </div>
        <p class="reports-panel__note">爽约率 {{ formatPercent(summary.noShowRate) }} · 违规率 {{ formatPercent(summary.violationRate) }}</p>
      </GlowCard>
      <GlowCard class="reports-panel">
        <header class="reports-panel__head">
          <div><span class="reports-page__eyebrow">REPAIRS</span><h2>报修状态分布</h2></div>
          <span>{{ summary.repairCount }} 条</span>
        </header>
        <div class="reports-panel__status-list">
          <div v-for="(count, name) in summary.repairStatus" :key="name" class="reports-panel__status-row">
            <span>{{ statusLabel(name) }}</span><strong>{{ count }}</strong>
          </div>
        </div>
        <p class="reports-panel__note">统计周期：{{ summary.range.startDate }} 至 {{ summary.range.endDate }}</p>
      </GlowCard>
    </section>

    <GlowCard class="reports-panel reports-panel--exports">
      <header class="reports-panel__head">
        <div><span class="reports-page__eyebrow">EXPORTS</span><h2>数据导出</h2></div>
        <span>默认同步导出，超大数据量使用异步任务</span>
      </header>
      <div class="reports-page__exports">
        <div v-for="item in exportOptions" :key="item.type" class="reports-page__export-item">
          <div><strong>{{ item.label }}</strong><span>CSV · 当前日期范围</span></div>
          <div class="reports-page__export-actions">
            <GhostButton size="small" :loading="exporting === item.type" @click="directExport(item.type)">直接下载</GhostButton>
            <GradientButton size="small" :loading="exporting === item.type" @click="asyncExport(item.type)">异步生成</GradientButton>
          </div>
        </div>
      </div>
      <div v-if="task" class="reports-page__task">
        <Tag :variant="task.status === 'COMPLETED' ? 'success' : task.status === 'FAILED' ? 'danger' : 'warning'" size="small" round>
          {{ task.status === 'COMPLETED' ? '已完成' : task.status === 'FAILED' ? '失败' : '处理中' }}
        </Tag>
        <span>任务 #{{ task.id }} · {{ task.row_count }} 行</span>
        <TextButton v-if="task.status === 'COMPLETED'" size="small" @click="downloadTask">下载文件</TextButton>
      </div>
    </GlowCard>
  </div>
</template>

<style scoped lang="scss">
.reports-page { display: flex; flex-direction: column; gap: 20px; }
.reports-page__toolbar { display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap; padding: 16px 18px; border: 1px solid var(--border-subtle); border-radius: var(--radius-card); background: var(--bg-surface); }
.reports-page__field { display: grid; gap: 6px; min-width: 170px; }.reports-page__field label { color: var(--text-tertiary); font-size: 11px; }.reports-page__field input { height: 36px; padding: 0 10px; border: 1px solid var(--border-default); border-radius: var(--radius-control); color: var(--text-primary); background: var(--bg-elevated); }
.reports-page__metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; min-height: 118px; }.report-metric { display: grid; gap: 14px; }.report-metric > span { color: var(--text-tertiary); font-size: 12px; }.report-metric strong { color: var(--text-primary); font-family: var(--font-display); font-size: 34px; letter-spacing: -.05em; }.report-metric small { margin-left: 5px; color: var(--text-tertiary); font-family: var(--font-sans); font-size: 12px; font-weight: 500; }.report-metric--accent { box-shadow: inset 0 2px 0 var(--accent), var(--shadow-soft-light); }.report-metric--blue { box-shadow: inset 0 2px 0 var(--accent-blue), var(--shadow-soft-light); }.report-metric--amber { box-shadow: inset 0 2px 0 var(--status-warning), var(--shadow-soft-light); }.report-metric--green { box-shadow: inset 0 2px 0 var(--status-success), var(--shadow-soft-light); }
.reports-page__empty { grid-column: 1 / -1; display: grid; place-items: center; min-height: 100px; color: var(--text-tertiary); }.reports-page__columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }.reports-panel { display: grid; gap: 16px; }.reports-panel__head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }.reports-panel__head h2 { margin: 5px 0 0; color: var(--text-primary); font-family: var(--font-display); font-size: 18px; }.reports-panel__head > span { color: var(--text-tertiary); font-size: 12px; }.reports-page__eyebrow { color: var(--text-tertiary); font-family: var(--font-mono); font-size: 10px; letter-spacing: .13em; }.reports-panel__status-list { display: grid; gap: 8px; }.reports-panel__status-row { display: flex; justify-content: space-between; padding: 10px 12px; border-radius: var(--radius-control); background: var(--bg-elevated); color: var(--text-secondary); font-size: 13px; }.reports-panel__status-row strong { color: var(--text-primary); font-family: var(--font-mono); }.reports-panel__note { margin: 0; color: var(--text-tertiary); font-size: 12px; }.reports-panel--exports { margin-top: 0; }.reports-page__exports { display: grid; gap: 8px; }.reports-page__export-item { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px; border-radius: var(--radius-control); background: var(--bg-elevated); }.reports-page__export-item div:first-child { display: grid; gap: 4px; }.reports-page__export-item strong { color: var(--text-primary); font-size: 13px; }.reports-page__export-item span { color: var(--text-tertiary); font-size: 11px; }.reports-page__export-actions { display: flex; gap: 8px; }.reports-page__task { display: flex; align-items: center; gap: 10px; color: var(--text-secondary); font-size: 12px; }.reports-page__task .text-button { margin-left: auto; }
@media (max-width: 900px) { .reports-page__metrics { grid-template-columns: repeat(2, 1fr); }.reports-page__columns { grid-template-columns: 1fr; } }
@media (max-width: 620px) { .reports-page__metrics { grid-template-columns: 1fr; }.reports-page__toolbar { align-items: stretch; flex-direction: column; }.reports-page__field { min-width: 0; }.reports-page__export-item { align-items: flex-start; flex-direction: column; }.reports-page__export-actions { align-self: flex-end; } }
</style>
