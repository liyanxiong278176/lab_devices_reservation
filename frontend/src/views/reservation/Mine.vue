<script setup lang="ts">
// 我的预约页(R5.2 重构):PageHeader + SegmentedControl 状态筛选 + GlowCard 卡片列表
// + EmptyState + 深色分页(全局桥接)。数据来源(API)/状态筛选/取消/签到/归还逻辑零改
// ——仅换展示层,并补齐既有 check-in/check-out API 的 UI 入口(按状态显隐)。
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import {
  cancelReservation,
  checkInReservation,
  checkOutReservation,
  myReservations,
} from '@/api/reservation'
import type { ReservationQuery, ReservationStatus, ReservationVO } from '@/types/reservation'
import type { Page } from '@/types/common'
import { reservationStatusTag } from '@/composables/useDeviceStatus'
import { useStagger } from '@/composables/useStagger'
import PageHeader from '@/components/ui/PageHeader.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import GlowCard from '@/components/ui/GlowCard.vue'
import Tag from '@/components/ui/Tag.vue'
import TextButton from '@/components/ui/TextButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const router = useRouter()

const activeStatus = ref<ReservationStatus | ''>('')
const query = ref<ReservationQuery>({ page: 1, size: 9 })
const loading = ref(false)
const page = ref<Page<ReservationVO>>({ records: [], total: 0, size: 9, current: 1 })

// SegmentedControl 选项:沿用既有 8 状态 + 全部,1:1 映射后端 status,
// 不做多状态聚合(避免改 API 单状态契约 / 避免客户端过滤破坏分页)。
const tabs: { label: string; value: ReservationStatus | '' }[] = [
  { label: '全部', value: '' },
  { label: '待审批', value: 'PENDING' },
  { label: '已通过', value: 'APPROVED' },
  { label: '使用中', value: 'IN_USE' },
  { label: '已完成', value: 'COMPLETED' },
  { label: '已取消', value: 'CANCELLED' },
  { label: '已拒绝', value: 'REJECTED' },
  { label: '已违规', value: 'VIOLATED' },
  { label: '已爽约', value: 'NO_SHOW' },
]

// 卡片错峰容器(同 R4 设备网格):首次进入视口 60ms 错峰 fade+rise
const listRef = ref<HTMLElement | null>(null)
useStagger(listRef, { delay: 60 })
let firstLoad = true

async function load() {
  loading.value = true
  try {
    page.value = await myReservations({ ...query.value, status: activeStatus.value })
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
  if (firstLoad) {
    firstLoad = false
    return
  }
  // 筛选/翻页后 stagger observer 已 stop,补显新渲染卡片(不错峰,避免卡初始态)
  await nextTick()
  listRef.value
    ?.querySelectorAll<HTMLElement>('[data-stagger]:not(.stagger-in)')
    .forEach((el) => el.classList.add('stagger-in'))
}

function onStatusChange(v: string | number) {
  activeStatus.value = (v as ReservationStatus | '') ?? ''
  query.value.page = 1
  load()
}

function onPageChange(p: number) {
  query.value.page = p
  load()
}

function onSizeChange(s: number) {
  query.value.size = s
  query.value.page = 1
  load()
}

// ---- 状态 → Tag variant 映射(把既有 reservationStatusTag 的 type 桥到 Tag)------
function statusVariant(s: ReservationStatus): 'success' | 'warning' | 'danger' | 'info' | 'accent' {
  const t = reservationStatusTag(s).type
  if (t === 'primary') return 'accent' // APPROVED 用青色 accent
  return t // success / warning / danger / info 直映射
}

function statusLabel(s: ReservationStatus): string {
  return reservationStatusTag(s).label
}

// ---- 操作权限(按状态显隐;实际时间窗由后端校验)-------------------------------
/** 仅 PENDING / APPROVED 可取消(开始前)。 */
function canCancel(row: ReservationVO): boolean {
  return row.status === 'PENDING' || row.status === 'APPROVED'
}

/** APPROVED 可签到(后端校验时间窗)。 */
function canCheckIn(row: ReservationVO): boolean {
  return row.status === 'APPROVED'
}

/** IN_USE 可归还。 */
function canCheckOut(row: ReservationVO): boolean {
  return row.status === 'IN_USE'
}

async function onCancel(row: ReservationVO) {
  try {
    await ElMessageBox.confirm(`确认取消预约 #${row.id}？`, '取消预约', {
      type: 'warning',
      confirmButtonText: '确认取消',
      cancelButtonText: '保留',
    })
  } catch {
    return // 用户放弃
  }
  try {
    await cancelReservation(row.id)
    ElMessage.success('已取消')
    load()
  } catch {
    // 拦截器已提示
  }
}

async function onCheckIn(row: ReservationVO) {
  try {
    await checkInReservation(row.id)
    ElMessage.success('签到成功')
    load()
  } catch {
    // 拦截器已提示(时间窗 / 状态不符等由后端返回)
  }
}

async function onCheckOut(row: ReservationVO) {
  try {
    await ElMessageBox.confirm(`确认归还设备(预约 #${row.id})？`, '归还确认', {
      type: 'warning',
      confirmButtonText: '确认归还',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await checkOutReservation(row.id)
    ElMessage.success('归还成功')
    load()
  } catch {
    // 拦截器已提示
  }
}

function goDetail(row: ReservationVO) {
  router.push({ name: 'reservation-detail', params: { id: row.id } })
}

function fmt(t?: string): string {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'
}

/** 时长(slotCount × 15min)→ "X 小时 Y 分" 简洁展示。 */
function durationLabel(slots: number): string {
  const mins = slots * 15
  const h = Math.floor(mins / 60)
  const m = mins % 60
  if (h === 0) return `${m} 分`
  if (m === 0) return `${h} 小时`
  return `${h} 小时 ${m} 分`
}

const subtitle = computed(() => `共 ${page.value.total} 条预约`)

onMounted(load)
</script>

<template>
  <div class="mine">
    <PageHeader title="我的预约" :subtitle="subtitle" />

    <!-- 状态筛选:SegmentedControl(沿用既有 8 状态 + 全部) -->
    <div class="mine__filter">
      <SegmentedControl
        :model-value="activeStatus"
        :options="tabs"
        size="sm"
        @update:model-value="onStatusChange"
      />
    </div>

    <!-- 卡片列表 -->
    <div v-loading="loading" class="mine__grid" ref="listRef">
      <div
        v-for="row in page.records"
        :key="row.id"
        class="mine__cell"
        data-stagger
      >
        <GlowCard as="article" class="mine__card">
          <!-- 卡头:状态 Tag + 编号 -->
          <header class="mine__card-head">
            <Tag :variant="statusVariant(row.status)" effect="light" size="small" round>
              {{ statusLabel(row.status) }}
            </Tag>
            <span class="mine__card-id">#{{ row.id }}</span>
          </header>

          <!-- 设备 + 时段 -->
          <div class="mine__card-body">
            <div class="mine__card-row mine__card-row--device">
              <span class="mine__card-label">设备</span>
              <span class="mine__card-value">设备 #{{ row.deviceId }}</span>
            </div>

            <div class="mine__card-time">
              <div class="mine__card-time-row">
                <span class="mine__card-time-dot mine__card-time-dot--start" />
                <span class="mine__card-time-text">{{ fmt(row.startTime) }}</span>
              </div>
              <div class="mine__card-time-line" aria-hidden="true" />
              <div class="mine__card-time-row">
                <span class="mine__card-time-dot mine__card-time-dot--end" />
                <span class="mine__card-time-text">{{ fmt(row.endTime) }}</span>
              </div>
            </div>

            <div class="mine__card-meta">
              <span class="mine__card-chip">
                {{ durationLabel(row.slotCount) }}
              </span>
              <span class="mine__card-chip mine__card-chip--muted">
                {{ row.slotCount }} 时段
              </span>
            </div>

            <p v-if="row.purpose" class="mine__card-purpose">{{ row.purpose }}</p>
          </div>

          <!-- 卡脚:创建时间 + 操作 -->
          <footer class="mine__card-foot">
            <span class="mine__card-created">
              创建于 {{ fmt(row.createdAt) }}
            </span>
            <div class="mine__card-actions">
              <TextButton size="small" @click="goDetail(row)">详情</TextButton>
              <GhostButton
                v-if="canCheckIn(row)"
                size="small"
                @click="onCheckIn(row)"
              >
                签到
              </GhostButton>
              <GhostButton
                v-if="canCheckOut(row)"
                size="small"
                @click="onCheckOut(row)"
              >
                归还
              </GhostButton>
              <GhostButton
                v-if="canCancel(row)"
                size="small"
                class="mine__cancel-btn"
                @click="onCancel(row)"
              >
                取消
              </GhostButton>
            </div>
          </footer>
        </GlowCard>
      </div>

      <!-- 空态 -->
      <div v-if="!loading && page.records.length === 0" class="mine__empty">
        <EmptyState
          icon="Calendar"
          title="暂无预约记录"
          description="尚未有任何设备预约。前往设备浏览页立即预约吧。"
        />
      </div>
    </div>

    <!-- 分页(深色全局已桥接) -->
    <div v-if="page.records.length > 0" class="mine__pager">
      <el-pagination
        :current-page="page.current"
        :page-size="page.size"
        :total="page.total"
        :page-sizes="[9, 18, 36]"
        layout="total, sizes, prev, pager, next"
        background
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>
  </div>
</template>

<style scoped lang="scss">
.mine {
  display: flex;
  flex-direction: column;
  gap: 20px;

  // ---- 筛选区 -------------------------------------------------------------
  &__filter {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
    padding: 12px 16px;
    background: var(--bg-sunken);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-card);
  }

  // ---- 卡片网格 -----------------------------------------------------------
  &__grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 16px;
    min-height: 120px;
    position: relative;

    // 空态跨满整行
    & > .mine__empty {
      grid-column: 1 / -1;
    }
  }

  &__cell {
    display: block;
  }

  // ---- 卡片 ----------------------------------------------------------------
  &__card {
    display: flex;
    flex-direction: column;
    gap: 14px;
    height: 100%;
  }

  &__card-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
  }

  &__card-id {
    font-family: var(--font-mono);
    font-size: 13px;
    font-weight: 600;
    color: var(--text-tertiary);
    letter-spacing: 0.02em;
  }

  &__card-body {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  &__card-row {
    display: flex;
    align-items: baseline;
    gap: 8px;

    &--device {
      .mine__card-value {
        font-family: var(--font-display);
        font-size: 16px;
        font-weight: 600;
        color: var(--text-primary);
      }
    }
  }

  &__card-label {
    font-size: 11px;
    font-weight: 500;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  // ---- 时段(双端点 + 连接线,深色科技风)-----------------------------------
  &__card-time {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 10px 12px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-control);
  }

  &__card-time-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  &__card-time-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;

    &--start {
      background: var(--accent);
      box-shadow: 0 0 8px color-mix(in srgb, var(--accent) 45%, transparent);
    }

    &--end {
      background: var(--text-tertiary);
    }
  }

  &__card-time-text {
    font-family: var(--font-mono);
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
  }

  &__card-time-line {
    width: 1px;
    height: 8px;
    margin-left: 3.5px;
    background: var(--border-default);
  }

  // ---- meta chip 行(时长 + 时段数)-----------------------------------------
  &__card-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  &__card-chip {
    display: inline-flex;
    align-items: center;
    padding: 3px 10px;
    background: color-mix(in srgb, var(--accent) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 20%, transparent);
    border-radius: var(--radius-pill);
    font-family: var(--font-mono);
    font-size: 12px;
    font-weight: 500;
    color: var(--accent);

    &--muted {
      background: var(--bg-elevated);
      border-color: var(--border-default);
      color: var(--text-tertiary);
    }
  }

  &__card-purpose {
    margin: 0;
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-secondary);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  // ---- 卡脚:创建时间 + 操作 ----------------------------------------------
  &__card-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: auto;
    padding-top: 12px;
    border-top: 1px solid var(--border-subtle);
  }

  &__card-created {
    font-size: 12px;
    color: var(--text-tertiary);
    font-variant-numeric: tabular-nums;
  }

  &__card-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  // 取消按钮:danger 描边(局部覆盖 GhostButton 的 hover 青色)
  &__cancel-btn {
    color: var(--status-danger) !important;
    border-color: color-mix(in srgb, var(--status-danger) 40%, transparent) !important;

    &:hover,
    &:focus {
      background: color-mix(in srgb, var(--status-danger) 8%, transparent) !important;
      color: var(--status-danger) !important;
      border-color: var(--status-danger) !important;
    }
  }

  // ---- 分页 ----------------------------------------------------------------
  &__pager {
    display: flex;
    justify-content: flex-end;
    padding-top: 4px;
  }

  &__empty {
    display: flex;
    justify-content: center;
  }
}

// ============================================================================
// prefers-reduced-motion 兜底(spec §6.1 铁律)
// ============================================================================
@media (prefers-reduced-motion: reduce) {
  .mine__card-time-dot--start {
    box-shadow: none;
  }
}
</style>
