<script setup lang="ts">
// 审批队列页(R5.3 重构):PageHeader + GlowCard 卡片队列 + 行内展开详情 +
// 行内驳回理由表单 + EmptyState + 深色分页(全局桥接)。
// 数据来源(API)/approve/reject/batch-approve 逻辑零改 —— 仅换展示层。
// 驳回从原 el-dialog 迁移为「行内展开表单」(spec §7:行内展开),reject(id, reason)
// 调用契约不变;批量通过保留(header actions + 每卡 checkbox,沿用 batchApprove(ids))。
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import { approve, batchApprove, pendingApprovals, reject } from '@/api/approval'
import type { ApprovalItemVO } from '@/types/approval'
import type { Page } from '@/types/common'
import { useNotificationStore } from '@/stores/notification'
import { useStagger } from '@/composables/useStagger'
import PageHeader from '@/components/ui/PageHeader.vue'
import GlowCard from '@/components/ui/GlowCard.vue'
import Tag from '@/components/ui/Tag.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import TextButton from '@/components/ui/TextButton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const notifStore = useNotificationStore()

const loading = ref(false)
const page = ref<Page<ApprovalItemVO>>({ records: [], total: 0, size: 9, current: 1 })
const query = ref<{ page: number; size: number }>({ page: 1, size: 9 })

// 批量通过:选中 id 集合(原 selection: ApprovalItemVO[] → 简化为 id[],
// batchApprove 仍接收 ids,契约不变)
const selectedIds = ref<number[]>([])

// 行内展开:展开的卡 id 集合(详情字段;可多张同时展开)
const expandedIds = ref<Set<number>>(new Set())

// 行内驳回:同时只驳回一张;reject 表单复用 expandedIds 容器,自动展开目标卡
const rejectingId = ref<number | null>(null)
const rejectReason = ref('')
const rejecting = ref(false)

// 卡片错峰容器(同 R4 设备网格 / R5.2 我的预约):首次进入视口 60ms 错峰 fade+rise
const listRef = ref<HTMLElement | null>(null)
useStagger(listRef, { delay: 60 })
let firstLoad = true

async function load() {
  loading.value = true
  try {
    page.value = await pendingApprovals(query.value.page, query.value.size)
    // 翻页/重载后清掉离开当前页的选中,避免跨页误批量
    const live = new Set(page.value.records.map((r) => r.id))
    selectedIds.value = selectedIds.value.filter((id) => live.has(id))
    // 已不在当前页的展开/驳回态也清掉,避免回到空态残留
    expandedIds.value = new Set([...expandedIds.value].filter((id) => live.has(id)))
    if (rejectingId.value !== null && !live.has(rejectingId.value)) {
      rejectingId.value = null
      rejectReason.value = ''
    }
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

function onPageChange(p: number) {
  query.value.page = p
  load()
}
function onSizeChange(s: number) {
  query.value.size = s
  query.value.page = 1
  load()
}

// ---- 选择(批量通过用)-----------------------------------------------------
function onRowCheck(row: ApprovalItemVO, val: string | number | boolean) {
  const checked = val === true
  if (checked) {
    if (!selectedIds.value.includes(row.id)) selectedIds.value.push(row.id)
  } else {
    selectedIds.value = selectedIds.value.filter((x) => x !== row.id)
  }
}

// ---- 行内展开(详情 / 驳回表单共用 expandedIds 容器)-----------------------
function toggleExpand(id: number) {
  const next = new Set(expandedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedIds.value = next
}

async function onApprove(row: ApprovalItemVO) {
  try {
    await approve(row.id)
    ElMessage.success('已通过')
    await load()
    notifStore.loadUnread()
  } catch {
    // 拦截器已提示
  }
}

function openReject(row: ApprovalItemVO) {
  rejectingId.value = row.id
  rejectReason.value = ''
  // 驳回时自动展开卡片以承载表单(若未展开)
  if (!expandedIds.value.has(row.id)) {
    const next = new Set(expandedIds.value)
    next.add(row.id)
    expandedIds.value = next
  }
}

function cancelReject() {
  rejectingId.value = null
  rejectReason.value = ''
}

async function onRejectConfirm(row: ApprovalItemVO) {
  if (!rejectReason.value.trim()) {
    ElMessage.warning('请填写驳回理由')
    return
  }
  rejecting.value = true
  try {
    await reject(row.id, rejectReason.value.trim())
    ElMessage.success('已驳回')
    rejectingId.value = null
    rejectReason.value = ''
    await load()
    notifStore.loadUnread()
  } catch {
    // 拦截器已提示
  } finally {
    rejecting.value = false
  }
}

async function onBatchApprove() {
  if (selectedIds.value.length === 0) {
    ElMessage.warning('请先勾选要批量通过的预约')
    return
  }
  try {
    await batchApprove([...selectedIds.value])
    ElMessage.success(`已批量通过 ${selectedIds.value.length} 条`)
    selectedIds.value = []
    await load()
    notifStore.loadUnread()
  } catch {
    // 拦截器已提示
  }
}

function fmt(t?: string): string {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'
}

/** 申请人姓名优先 realName,fallback username。 */
function applicantName(row: ApprovalItemVO): string {
  return row.realName?.trim() || row.username || `用户 #${row.userId}`
}

/** 头像首字:取姓名首个字符(中英文都取首字)。 */
function avatarChar(row: ApprovalItemVO): string {
  return applicantName(row).charAt(0).toUpperCase()
}

/** 时长(slotCount × 15min)→ "X 小时 Y 分"。 */
function durationLabel(slots?: number): string {
  if (!slots || slots <= 0) return '—'
  const mins = slots * 15
  const h = Math.floor(mins / 60)
  const m = mins % 60
  if (h === 0) return `${m} 分`
  if (m === 0) return `${h} 小时`
  return `${h} 小时 ${m} 分`
}

const subtitle = computed(() => `共 ${page.value.total} 条待处理`)

onMounted(load)
</script>

<template>
  <div class="approval">
    <PageHeader title="待审批" :subtitle="subtitle">
      <template v-if="page.records.length > 0" #actions>
        <GhostButton
          v-permission="'device:approve'"
          :disabled="selectedIds.length === 0"
          @click="onBatchApprove"
        >
          批量通过 ({{ selectedIds.length }})
        </GhostButton>
      </template>
    </PageHeader>

    <!-- 审批队列(卡片列表,非表格——审批适合纵向阅读) -->
    <div v-loading="loading" class="approval__grid" ref="listRef">
      <div
        v-for="row in page.records"
        :key="row.id"
        class="approval__cell"
        data-stagger
      >
        <GlowCard as="article" class="approval__card">
          <!-- 卡头:全选 checkbox + PENDING Tag + 编号 -->
          <header class="approval__card-head">
            <div class="approval__card-head-left">
              <el-checkbox
                v-permission="'device:approve'"
                :model-value="selectedIds.includes(row.id)"
                @change="onRowCheck(row, $event)"
              />
              <Tag variant="warning" effect="light" size="small" round>待审批</Tag>
            </div>
            <span class="approval__card-id">#{{ row.id }}</span>
          </header>

          <!-- 申请人(头像 + 姓名) -->
          <div class="approval__applicant">
            <div class="approval__avatar" aria-hidden="true">{{ avatarChar(row) }}</div>
            <div class="approval__applicant-info">
              <span class="approval__applicant-name">{{ applicantName(row) }}</span>
              <span class="approval__applicant-sub">申请使用</span>
            </div>
          </div>

          <!-- 设备名(主标题) -->
          <h3 class="approval__device">{{ row.deviceName }}</h3>

          <!-- 时段(双端点 + 连接线,沿用 Mine 模式) -->
          <div class="approval__time">
            <div class="approval__time-row">
              <span class="approval__time-dot approval__time-dot--start" />
              <span class="approval__time-text">{{ fmt(row.startTime) }}</span>
            </div>
            <div class="approval__time-line" aria-hidden="true" />
            <div class="approval__time-row">
              <span class="approval__time-dot approval__time-dot--end" />
              <span class="approval__time-text">{{ fmt(row.endTime) }}</span>
            </div>
          </div>

          <!-- 时长 + 时段数 chips -->
          <div class="approval__meta">
            <span class="approval__chip">{{ durationLabel(row.slotCount) }}</span>
            <span class="approval__chip approval__chip--muted">
              {{ row.slotCount ?? 0 }} 时段
            </span>
          </div>

          <!-- 用途/理由 -->
          <p v-if="row.purpose" class="approval__purpose">{{ row.purpose }}</p>

          <!-- 行内展开:驳回表单(优先)或详情字段 -->
          <div v-if="expandedIds.has(row.id)" class="approval__expand">
            <div v-if="rejectingId === row.id" class="approval__reject">
              <label class="approval__reject-label">驳回理由（必填）</label>
              <el-input
                v-model="rejectReason"
                type="textarea"
                :rows="3"
                placeholder="请填写驳回理由，将通知申请人"
                maxlength="200"
                show-word-limit
              />
              <div class="approval__reject-actions">
                <TextButton size="small" @click="cancelReject">取消</TextButton>
                <GradientButton
                  v-permission="'device:approve'"
                  size="small"
                  :loading="rejecting"
                  @click="onRejectConfirm(row)"
                >
                  确认驳回
                </GradientButton>
              </div>
            </div>
            <dl v-else class="approval__details">
              <div class="approval__detail-row">
                <dt>登录账号</dt>
                <dd>{{ row.username }}</dd>
              </div>
              <div class="approval__detail-row">
                <dt>用户编号</dt>
                <dd>#{{ row.userId }}</dd>
              </div>
              <div class="approval__detail-row">
                <dt>设备编号</dt>
                <dd>#{{ row.deviceId }}</dd>
              </div>
              <div class="approval__detail-row">
                <dt>提交时间</dt>
                <dd>{{ fmt(row.createdAt) }}</dd>
              </div>
            </dl>
          </div>

          <!-- 卡脚:详情切换 + 通过/驳回 -->
          <footer class="approval__foot">
            <TextButton size="small" @click="toggleExpand(row.id)">
              {{ expandedIds.has(row.id) ? '收起' : '详情' }}
            </TextButton>
            <div class="approval__actions">
              <GhostButton
                v-permission="'device:approve'"
                size="small"
                class="approval__reject-btn"
                :disabled="rejectingId === row.id"
                @click="openReject(row)"
              >
                驳回
              </GhostButton>
              <GradientButton
                v-permission="'device:approve'"
                size="small"
                @click="onApprove(row)"
              >
                通过
              </GradientButton>
            </div>
          </footer>
        </GlowCard>
      </div>

      <!-- 空态 -->
      <div v-if="!loading && page.records.length === 0" class="approval__empty">
        <EmptyState
          icon="Checked"
          title="暂无待审批申请"
          description="所有预约申请都已处理完毕。"
        />
      </div>
    </div>

    <!-- 分页(深色全局已桥接) -->
    <div v-if="page.records.length > 0" class="approval__pager">
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
.approval {
  display: flex;
  flex-direction: column;
  gap: 20px;

  // ---- 卡片队列网格 --------------------------------------------------------
  // 审批卡信息量大(申请人 + 设备 + 时段 + 用途 + 操作),最小列宽 420px;
  // 窄屏 1 列、宽屏(>1100px)自动 2 列,纵向阅读舒适。
  &__grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
    gap: 16px;
    min-height: 120px;
    position: relative;

    // 空态跨满整行
    & > .approval__empty {
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
    gap: 12px;
    height: 100%;
  }

  &__card-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
  }

  &__card-head-left {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  &__card-id {
    font-family: var(--font-mono);
    font-size: 13px;
    font-weight: 600;
    color: var(--text-tertiary);
    letter-spacing: 0.02em;
  }

  // ---- 申请人(头像 + 姓名) ----------------------------------------------
  &__applicant {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  &__avatar {
    width: 36px;
    height: 36px;
    flex-shrink: 0;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: linear-gradient(135deg, rgba(34, 211, 238, 0.18), rgba(59, 130, 246, 0.18));
    border: 1px solid rgba(34, 211, 238, 0.35);
    color: var(--accent-bright);
    font-family: var(--font-display);
    font-size: 15px;
    font-weight: 600;
    text-transform: uppercase;
    box-shadow: 0 0 12px rgba(34, 211, 238, 0.18);
  }

  &__applicant-info {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
  }

  &__applicant-name {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__applicant-sub {
    font-size: 11px;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  // ---- 设备主标题 ----------------------------------------------------------
  &__device {
    margin: 0;
    font-family: var(--font-display);
    font-size: 18px;
    font-weight: 600;
    line-height: 1.3;
    letter-spacing: -0.2px;
    color: var(--text-primary);
  }

  // ---- 时段(双端点 + 连接线,沿用 Mine 模式)-------------------------------
  &__time {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 10px 12px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-control);
  }

  &__time-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  &__time-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;

    &--start {
      background: var(--accent);
      box-shadow: 0 0 8px rgba(34, 211, 238, 0.45);
    }

    &--end {
      background: var(--text-tertiary);
    }
  }

  &__time-text {
    font-family: var(--font-mono);
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
  }

  &__time-line {
    width: 1px;
    height: 8px;
    margin-left: 3.5px;
    background: var(--border-default);
  }

  // ---- meta chips(时长 + 时段数)------------------------------------------
  &__meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  &__chip {
    display: inline-flex;
    align-items: center;
    padding: 3px 10px;
    background: rgba(34, 211, 238, 0.08);
    border: 1px solid rgba(34, 211, 238, 0.2);
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

  &__purpose {
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

  // ---- 行内展开(详情 / 驳回表单)-----------------------------------------
  &__expand {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px;
    background: var(--bg-sunken);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-control);
  }

  &__details {
    display: grid;
    grid-template-columns: 1fr;
    gap: 6px 16px;
    margin: 0;
  }

  &__detail-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;

    dt {
      font-size: 12px;
      color: var(--text-tertiary);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    dd {
      margin: 0;
      font-family: var(--font-mono);
      font-size: 13px;
      color: var(--text-secondary);
      font-variant-numeric: tabular-nums;
    }
  }

  // ---- 驳回表单(行内) ----------------------------------------------------
  &__reject {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  &__reject-label {
    font-size: 12px;
    font-weight: 600;
    color: var(--status-danger);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  &__reject-actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 6px;
  }

  // ---- 卡脚 ----------------------------------------------------------------
  &__foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: auto;
    padding-top: 12px;
    border-top: 1px solid var(--border-subtle);
  }

  &__actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  // 驳回按钮:hover 转 danger 描边(覆盖 GhostButton 默认青色 hover)
  &__reject-btn {
    color: var(--status-danger) !important;
    border-color: rgba(248, 113, 113, 0.4) !important;

    &:hover,
    &:focus {
      background: rgba(248, 113, 113, 0.08) !important;
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
  .approval__avatar,
  .approval__time-dot--start {
    box-shadow: none;
  }
}
</style>
