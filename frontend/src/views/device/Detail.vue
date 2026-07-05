<script setup lang="ts">
// 设备详情页(R4.2 重构):hero 头(展示名+StatusDot+spec chips)
// + sticky 操作栏(毛玻璃 + GradientButton 预约 / GhostButton 报修)
// + tabs(规格 / 预约日历,深色 el-tabs 覆盖)。
// 数据来源 / 日历逻辑 / 路由跳转——零改,仅换展示层 + 接 R1 ui 组件。
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { deviceCalendar, getDevice } from '@/api/device'
import type { DeviceCalendarItemVO, DeviceVO } from '@/types/device'
import PageHeader from '@/components/ui/PageHeader.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import Panel from '@/components/ui/Panel.vue'
import Tag from '@/components/ui/Tag.vue'

const route = useRoute()
const router = useRouter()

const device = ref<DeviceVO | null>(null)
const loading = ref(false)

const selectedDate = ref<Date>(new Date())
const activeTab = ref<'specs' | 'calendar'>('specs')

// 日历区间:选中日所在周的 ±7 天(满足后端 from/to ISO 日期)
const rangeFrom = computed(() => dayjs(selectedDate.value).startOf('week').format('YYYY-MM-DD'))
const rangeTo = computed(() => dayjs(selectedDate.value).endOf('week').format('YYYY-MM-DD'))

const calendar = ref<DeviceCalendarItemVO[]>([])
const calendarLoading = ref(false)

const id = computed(() => Number(route.params.id))

// hero 副标题:品牌 · 型号 · 实验室
const subtitle = computed(() => {
  const d = device.value
  if (!d) return ''
  const parts = [d.brand, d.model, d.labName].filter(Boolean)
  return parts.length > 0 ? parts.join(' · ') : '未填写品牌 / 型号'
})

// hero spec chip 行:几个关键规格钩子(分类 / 单价 / 最长预约 / 审批)
const keyChips = computed(() => {
  const d = device.value
  if (!d) return []
  return [
    { label: '分类', value: d.categoryName || '未分类' },
    { label: '单价', value: d.pricePerHour != null && d.pricePerHour !== '' ? `¥${d.pricePerHour}/时` : '—' },
    { label: '最长预约', value: d.maxReservationHours != null && d.maxReservationHours !== '' ? `${d.maxReservationHours} 小时` : '—' },
    { label: '审批', value: d.needApproval === 1 ? '需审批' : '免审批' },
  ]
})

// 规格 tab 全量字段(品牌/型号/实验室/分类/规格/单价/最长预约/审批)
const specRows = computed(() => {
  const d = device.value
  if (!d) return []
  return [
    { label: '品牌', value: d.brand || '—' },
    { label: '型号', value: d.model || '—' },
    { label: '实验室', value: d.labName || '—' },
    { label: '分类', value: d.categoryName || '—' },
    { label: '规格', value: d.specs || '—' },
    { label: '单价 / 时', value: d.pricePerHour != null && d.pricePerHour !== '' ? `¥${d.pricePerHour}` : '—' },
    { label: '最长预约', value: d.maxReservationHours != null && d.maxReservationHours !== '' ? `${d.maxReservationHours} 小时` : '—' },
    { label: '审批要求', value: d.needApproval === 1 ? '需审批' : '免审批' },
  ]
})

// 日历状态 → Tag variant + 中文标签(展示层增强,数据零改)
function calStatusVariant(s: string): 'success' | 'accent' | 'warning' | 'info' {
  if (s === 'IN_USE') return 'success'
  if (s === 'APPROVED') return 'accent'
  if (s === 'PENDING') return 'warning'
  return 'info'
}
const CAL_STATUS_LABELS: Record<string, string> = {
  IN_USE: '使用中',
  APPROVED: '已确认',
  PENDING: '待审批',
}
function calStatusLabel(s: string): string {
  return CAL_STATUS_LABELS[s] ?? s
}

async function loadDevice() {
  loading.value = true
  try {
    device.value = await getDevice(id.value)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

async function loadCalendar() {
  calendarLoading.value = true
  try {
    calendar.value = await deviceCalendar(id.value, rangeFrom.value, rangeTo.value)
  } catch {
    calendar.value = []
  } finally {
    calendarLoading.value = false
  }
}

watch(selectedDate, loadCalendar)

function goReserve() {
  router.push({ name: 'reservation-create', query: { deviceId: String(id.value) } })
}

function goRepair() {
  router.push({ name: 'repair-submit', query: { deviceId: String(id.value) } })
}

onMounted(async () => {
  await loadDevice()
  await loadCalendar()
})
</script>

<template>
  <div v-loading="loading" class="device-detail">
    <!-- hero 头:展示名 + 副标题 + StatusDot -->
    <PageHeader :title="device?.name ?? '—'" :subtitle="subtitle">
      <template #actions>
        <StatusDot v-if="device" :status="device.status" :label="true" />
      </template>
    </PageHeader>

    <!-- spec chip 行:关键规格钩子 -->
    <div v-if="device" class="device-detail__chips">
      <span v-for="chip in keyChips" :key="chip.label" class="spec-chip">
        <span class="spec-chip__label">{{ chip.label }}</span>
        <span class="spec-chip__value">{{ chip.value }}</span>
      </span>
    </div>

    <!-- sticky 操作栏:吸顶毛玻璃 + 预约 / 报修 -->
    <div v-if="device" class="device-detail__actionbar">
      <span class="device-detail__actionbar-hint">
        当前状态:<strong>{{ device.status }}</strong>
      </span>
      <div class="device-detail__actionbar-btns">
        <GradientButton :disabled="device.status !== 'IDLE'" @click="goReserve">
          立即预约
        </GradientButton>
        <GhostButton @click="goRepair">报修</GhostButton>
      </div>
    </div>

    <!-- tabs:规格参数 / 预约日历 -->
    <el-tabs v-model="activeTab" class="device-detail__tabs">
      <!-- 规格参数 -->
      <el-tab-pane label="规格参数" name="specs">
        <Panel class="device-detail__spec-panel">
          <dl class="spec-grid">
            <div v-for="row in specRows" :key="row.label" class="spec-grid__row">
              <dt>{{ row.label }}</dt>
              <dd>{{ row.value }}</dd>
            </div>
          </dl>

          <div v-if="device?.description" class="device-detail__desc">
            <h4 class="device-detail__desc-title">设备描述</h4>
            <p class="device-detail__desc-text">{{ device.description }}</p>
          </div>
        </Panel>
      </el-tab-pane>

      <!-- 预约日历(逻辑保留,样式深色) -->
      <el-tab-pane label="预约日历" name="calendar">
        <Panel class="device-detail__cal-panel">
          <div class="device-detail__cal-head">
            <div>
              <h3 class="device-detail__cal-title">占用日历</h3>
              <p class="device-detail__cal-hint">选择日期查看该周设备被占用的时段</p>
            </div>
            <el-date-picker
              v-model="selectedDate"
              type="date"
              placeholder="选择日期"
              format="YYYY-MM-DD"
              value-format="x"
              :clearable="false"
            />
          </div>

          <el-table
            v-loading="calendarLoading"
            :data="calendar"
            size="small"
            class="device-detail__cal-table"
          >
            <el-table-column prop="date" label="日期" width="130" />
            <el-table-column prop="slotIndex" label="时段序号" width="110" align="center" />
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <Tag :variant="calStatusVariant(row.status)" size="small">
                  {{ calStatusLabel(row.status) }}
                </Tag>
              </template>
            </el-table-column>
            <el-table-column prop="reservationId" label="预约 ID" />
            <template #empty>
              <span class="device-detail__cal-empty">该周无占用记录,时段空闲可预约</span>
            </template>
          </el-table>
        </Panel>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped lang="scss">
// ============================================================================
// Detail.vue 深色科技风 (spec §7 设备详情行)
// 全量走 token,scoped scss。结构:hero / chips / sticky 操作栏 / tabs。
// ============================================================================

.device-detail {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding-bottom: 40px;

  // ---- spec chip 行 -------------------------------------------------------
  &__chips {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }

  // ---- sticky 操作栏:吸顶毛玻璃 + GradientButton/GhostButton ---------------
  &__actionbar {
    position: sticky;
    top: 8px;
    z-index: 5;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
    padding: 10px 16px;
    // 半透明底 + 毛玻璃:透出底层氛围光
    background: rgba(17, 23, 34, 0.72); // --bg-surface 透明化
    backdrop-filter: blur(12px) saturate(140%);
    -webkit-backdrop-filter: blur(12px) saturate(140%);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-soft-light);
  }

  &__actionbar-hint {
    font-size: 13px;
    color: var(--text-secondary);

    strong {
      margin-left: 4px;
      font-weight: 600;
      color: var(--text-primary);
      font-family: var(--font-mono);
    }
  }

  &__actionbar-btns {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }

  // ---- 规格 tab -----------------------------------------------------------
  &__spec-panel {
    padding: 24px;
  }

  &__desc {
    margin-top: 20px;
    padding-top: 20px;
    border-top: 1px solid var(--border-subtle);
  }

  &__desc-title {
    margin: 0 0 8px;
    font-family: var(--font-display);
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    letter-spacing: 0.01em;
  }

  &__desc-text {
    margin: 0;
    font-size: 14px;
    line-height: 1.7;
    color: var(--text-secondary);
  }

  // ---- 预约日历 tab -------------------------------------------------------
  &__cal-panel {
    padding: 24px;
  }

  &__cal-head {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
    margin-bottom: 18px;
  }

  &__cal-title {
    margin: 0;
    font-family: var(--font-display);
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
  }

  &__cal-hint {
    margin: 4px 0 0;
    font-size: 13px;
    color: var(--text-tertiary);
  }

  &__cal-empty {
    color: var(--status-success);
    font-size: 13px;
  }
}

// ---- spec chip:hairline pill + 小标 + 强调值(青色 mono)-------------------
.spec-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
  padding: 6px 12px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-pill);
  transition:
    border-color var(--d-fast) var(--ease-out-expo),
    background-color var(--d-fast) var(--ease-out-expo);

  &:hover {
    border-color: var(--border-strong);
    background: rgba(34, 211, 238, 0.06);
  }

  &__label {
    font-size: 11px;
    font-weight: 500;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  &__value {
    font-family: var(--font-mono);
    font-size: 13px;
    font-weight: 600;
    color: var(--accent);
  }
}

// ---- 规格 grid:2 列 dt/dd,深色 hairline 分隔 ------------------------------
.spec-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0;
  margin: 0;

  @media (max-width: 720px) {
    grid-template-columns: 1fr;
  }

  &__row {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 14px 16px;
    border-bottom: 1px solid var(--border-subtle);

    // 第 1/3/5... 行右补 hairline(2 列视觉分隔)
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
      word-break: break-word;
    }
  }
}

// ============================================================================
// el-tabs 深色覆盖(spec §7 tabs + MainLayout el-menu 覆盖模式)
// 通过 :deep 改 --el-tabs-* 变量 + 直接选择器覆盖 inactive/active/bar/nav-wrap
// ============================================================================
:deep(.el-tabs) {
  --el-tabs-header-height: 48px;
  --el-tabs-tab-font-size: 15px;
}

:deep(.el-tabs__header) {
  margin: 0 0 20px;
}

:deep(.el-tabs__item) {
  color: var(--text-secondary);
  font-weight: 500;
  transition: color var(--d-fast) var(--ease-out-expo);

  &:hover {
    color: var(--text-primary);
  }

  &.is-active {
    color: var(--accent);
    font-weight: 600;
  }
}

// active 底线:青色 2px
:deep(.el-tabs__active-bar) {
  background-color: var(--accent);
  height: 2px;
  border-radius: 1px;
}

// tab header 底 hairline
:deep(.el-tabs__nav-wrap::after) {
  background-color: var(--border-subtle);
  height: 1px;
}

// 让 Panel hover 抬升不被 tabs content 裁切
:deep(.el-tabs__content) {
  overflow: visible;
}

// ============================================================================
// el-table 深色调(日历占用表)
// ============================================================================
:deep(.device-detail__cal-table) {
  --el-table-border-color: var(--border-subtle);
  --el-table-header-bg-color: var(--bg-elevated);
  --el-table-header-text-color: var(--text-secondary);
  --el-table-row-hover-bg-color: var(--bg-elevated);
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-text-color: var(--text-secondary);

  background: transparent;

  // 表头单元格:小号大写字 + 更深底
  th.el-table__cell {
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    background: var(--bg-elevated);
  }

  // 单元格文字稍亮以便在深底可读
  .el-table__cell {
    color: var(--text-primary);
    border-bottom-color: var(--border-subtle);
  }
}

// ============================================================================
// prefers-reduced-motion 兜底(spec §6.1 铁律)
// ============================================================================
@media (prefers-reduced-motion: reduce) {
  .spec-chip,
  :deep(.el-tabs__item) {
    transition: none;
  }
}
</style>
