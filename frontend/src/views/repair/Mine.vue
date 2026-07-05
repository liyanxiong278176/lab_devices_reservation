<script setup lang="ts">
// 我的报修页(R5 重构):PageHeader + GlowCard 卡片列表 + 每卡内嵌 Timeline 进度
// + 状态 Tag + EmptyState + 深色分页。数据来源(API)/分页逻辑零改——仅换展示层;
// Timeline items 由既有 status + 时间字段 computed 组装(思路同 reservation/Detail.vue)。
import { computed, nextTick, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import { myRepairs } from '@/api/repair'
import type { RepairReportVO, RepairStatus } from '@/types/repair'
import type { Page } from '@/types/common'
import { useStagger } from '@/composables/useStagger'
import PageHeader from '@/components/ui/PageHeader.vue'
import GlowCard from '@/components/ui/GlowCard.vue'
import Tag from '@/components/ui/Tag.vue'
import Timeline from '@/components/ui/Timeline.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

type TimelineStatus = 'done' | 'current' | 'todo'
interface TimelineItem {
  id: string
  title: string
  desc?: string
  time?: string
  status: TimelineStatus
}

const loading = ref(false)
const page = ref<Page<RepairReportVO>>({ records: [], total: 0, size: 10, current: 1 })
const query = ref<{ page: number; size: number }>({ page: 1, size: 9 })

// 卡片错峰容器(同 R5 reservation/Mine):首次进入视口 60ms 错峰 fade+rise
const listRef = ref<HTMLElement | null>(null)
const { reveal } = useStagger(listRef, { delay: 60 })

async function load() {
  loading.value = true
  try {
    page.value = await myRepairs(query.value.page, query.value.size)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
  await nextTick()
  reveal()
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

// ---- 状态 → Tag variant 语义色(spec: PENDING=warning / PROCESSING=accent /
// RESOLVED=success / REJECTED=danger)------------------------------------------
function statusVariant(s: RepairStatus): 'warning' | 'accent' | 'success' | 'danger' {
  switch (s) {
    case 'PENDING':
      return 'warning'
    case 'PROCESSING':
      return 'accent'
    case 'RESOLVED':
      return 'success'
    case 'REJECTED':
      return 'danger'
  }
}

function statusLabel(s: RepairStatus): string {
  switch (s) {
    case 'PENDING':
      return '待受理'
    case 'PROCESSING':
      return '处理中'
    case 'RESOLVED':
      return '已解决'
    case 'REJECTED':
      return '已驳回'
    default:
      return s
  }
}

// ============================================================================
// Timeline 生命周期:由既有 status + 时间字段组装,done/current/todo 三态
// (R1 Timeline 仅支持此三态;REJECTED 在受理节点中止)。
// 顺序:提交 → 受理 → 处理 → 结果
//   PENDING:   提交(done) → 待受理(current) → 处理(todo) → 结果(todo)
//   PROCESSING:提交(done) → 已受理(done) → 处理中(current) → 结果(todo)
//   RESOLVED:  提交(done) → 已受理(done) → 已处理(done) → 已解决(done)
//   REJECTED:  提交(done) → 已驳回(done) [中止]
// ============================================================================
function buildTimeline(r: RepairReportVO): TimelineItem[] {
  const items: TimelineItem[] = []
  const s = r.status

  // 1. 提交(恒发生)
  items.push({
    id: 'created',
    title: '提交报修',
    desc: `工单 #${r.id} · 设备 #${r.deviceId}`,
    time: r.createdAt ? fmt(r.createdAt) : undefined,
    status: 'done',
  })

  // 2. 受理
  if (s === 'PENDING') {
    items.push({
      id: 'take',
      title: '等待受理',
      desc: '管理员即将处理',
      status: 'current',
    })
  } else if (s === 'REJECTED') {
    items.push({
      id: 'reject',
      title: '已驳回',
      desc: r.resolutionNote || '管理员驳回报修',
      time: r.resolvedAt ? fmt(r.resolvedAt) : undefined,
      status: 'done',
    })
    return items
  } else {
    // PROCESSING / RESOLVED —— 已受理
    items.push({
      id: 'take',
      title: '已受理',
      status: 'done',
    })
  }

  // 3. 处理
  if (s === 'PROCESSING') {
    items.push({
      id: 'process',
      title: '处理中',
      desc: '管理员正在处理',
      status: 'current',
    })
  } else if (s === 'RESOLVED') {
    items.push({
      id: 'process',
      title: '已处理',
      status: 'done',
    })
  } else {
    items.push({
      id: 'process',
      title: '处理',
      status: 'todo',
    })
  }

  // 4. 结果
  if (s === 'RESOLVED') {
    items.push({
      id: 'resolve',
      title: '已解决',
      desc: r.resolutionNote || '故障已修复',
      time: r.resolvedAt ? fmt(r.resolvedAt) : undefined,
      status: 'done',
    })
  } else {
    items.push({
      id: 'resolve',
      title: '解决',
      status: 'todo',
    })
  }

  return items
}

function fmt(t?: string): string {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'
}

const subtitle = computed(() => `共 ${page.value.total} 条报修`)

onMounted(load)
</script>

<template>
  <div class="rmine">
    <PageHeader title="我的报修" :subtitle="subtitle" />

    <!-- 卡片列表 -->
    <div v-loading="loading" class="rmine__grid" ref="listRef">
      <div
        v-for="row in page.records"
        :key="row.id"
        class="rmine__cell"
        data-stagger
      >
        <GlowCard as="article" class="rmine__card">
          <!-- 卡头:状态 Tag + 编号 -->
          <header class="rmine__card-head">
            <Tag :variant="statusVariant(row.status)" effect="light" size="small" round>
              {{ statusLabel(row.status) }}
            </Tag>
            <span class="rmine__card-id">#{{ row.id }}</span>
          </header>

          <!-- 标题 + 设备 -->
          <div class="rmine__card-body">
            <h3 class="rmine__card-title">{{ row.title }}</h3>
            <div class="rmine__card-row">
              <span class="rmine__card-label">设备</span>
              <span class="rmine__card-value">
                {{ row.deviceName || `设备 #${row.deviceId}` }}
              </span>
            </div>
            <p v-if="row.description" class="rmine__card-desc">{{ row.description }}</p>
          </div>

          <!-- 处理说明(已解决/已驳回时展示) -->
          <div
            v-if="row.resolutionNote && (row.status === 'RESOLVED' || row.status === 'REJECTED')"
            class="rmine__card-note"
            :class="{
              'rmine__card-note--resolved': row.status === 'RESOLVED',
              'rmine__card-note--rejected': row.status === 'REJECTED',
            }"
          >
            <span class="rmine__card-note-label">
              {{ row.status === 'RESOLVED' ? '处理说明' : '驳回理由' }}
            </span>
            <p class="rmine__card-note-text">{{ row.resolutionNote }}</p>
          </div>

          <!-- Timeline 进度 -->
          <div class="rmine__card-timeline">
            <div class="rmine__card-timeline-head">
              <h4 class="rmine__card-timeline-title">处理进度</h4>
            </div>
            <Timeline :items="buildTimeline(row)" />
          </div>

          <!-- 卡脚:提交时间 -->
          <footer class="rmine__card-foot">
            <span class="rmine__card-time">提交于 {{ fmt(row.createdAt) }}</span>
          </footer>
        </GlowCard>
      </div>

      <!-- 空态 -->
      <div v-if="!loading && page.records.length === 0" class="rmine__empty">
        <EmptyState
          icon="Warning"
          title="暂无报修记录"
          description="尚未提交任何设备报修。发现故障时请在「提交报修」页发起。"
        />
      </div>
    </div>

    <!-- 分页(深色全局已桥接) -->
    <div v-if="page.records.length > 0" class="rmine__pager">
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
// ============================================================================
// 我的报修 深色科技风(spec §7 报修行)
// 全量走 token,scoped scss。卡片网格(auto-fill 320px),每卡内嵌 Timeline。
// ============================================================================

.rmine {
  display: flex;
  flex-direction: column;
  gap: 20px;

  // ---- 卡片网格 ------------------------------------------------------------
  &__grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 16px;
    min-height: 120px;
    position: relative;

    & > .rmine__empty {
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

  // ---- 卡身:标题 + 设备 + 描述 --------------------------------------------
  &__card-body {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  &__card-title {
    margin: 0;
    font-family: var(--font-display);
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
    line-height: 1.4;
    letter-spacing: -0.1px;
  }

  &__card-row {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }

  &__card-label {
    font-size: 11px;
    font-weight: 500;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  &__card-value {
    font-size: 13px;
    font-weight: 500;
    color: var(--text-secondary);
  }

  &__card-desc {
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

  // ---- 处理说明块(已解决/已驳回)------------------------------------------
  &__card-note {
    padding: 10px 12px;
    border-radius: var(--radius-control);
    border: 1px solid var(--border-subtle);
    background: var(--bg-elevated);

    &--resolved {
      background: color-mix(in srgb, var(--status-success) 6%, transparent);
      border-color: color-mix(in srgb, var(--status-success) 20%, transparent);
    }

    &--rejected {
      background: color-mix(in srgb, var(--status-danger) 6%, transparent);
      border-color: color-mix(in srgb, var(--status-danger) 20%, transparent);
    }
  }

  &__card-note-label {
    display: block;
    font-size: 11px;
    font-weight: 500;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 4px;
  }

  &__card-note-text {
    margin: 0;
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-primary);
    word-break: break-word;
  }

  // ---- Timeline 区 ---------------------------------------------------------
  &__card-timeline {
    padding-top: 12px;
    border-top: 1px solid var(--border-subtle);
  }

  &__card-timeline-head {
    margin-bottom: 12px;
  }

  &__card-timeline-title {
    margin: 0;
    font-family: var(--font-display);
    font-size: 12px;
    font-weight: 600;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  // ---- 卡脚 ----------------------------------------------------------------
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

  &__card-time {
    font-size: 12px;
    color: var(--text-tertiary);
    font-variant-numeric: tabular-nums;
    font-family: var(--font-mono);
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
</style>
