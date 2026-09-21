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
  cancelWaitlist,
  myWaitlist,
  myReservations,
} from '@/api/reservation'
import type { ReservationQuery, ReservationStatus, ReservationVO } from '@/types/reservation'
import type { WaitlistVO } from '@/api/reservation'
import type { Page } from '@/types/common'
import { useCursorPageChain } from '@/composables/useCursorPageChain'
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
const cursorPager = useCursorPageChain<ReservationVO>((cursor) => myReservations({
  page: 1,
  size: query.value.size,
  status: activeStatus.value,
  cursor,
}))
const waitlist = ref<WaitlistVO[]>([])
const returnDialogVisible = ref(false)
const returningRow = ref<ReservationVO | null>(null)
const returnCondition = ref<'NORMAL' | 'DAMAGED' | 'MISSING'>('NORMAL')
const returnNote = ref('')

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
const { reveal } = useStagger(listRef, { delay: 60 })

async function load(targetPage = query.value.page || 1) {
  loading.value = true
  try {
    page.value = await cursorPager.load(targetPage)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
  await nextTick()
  reveal()
}

function onStatusChange(v: string | number) {
  activeStatus.value = (v as ReservationStatus | '') ?? ''
  query.value.page = 1
  cursorPager.reset()
  void load()
}

async function loadWaitlist() {
  try {
    waitlist.value = await myWaitlist()
  } catch {
    waitlist.value = []
  }
}

async function onCancelWaitlist(row: WaitlistVO) {
  try {
    await ElMessageBox.confirm(`确认取消 ${row.reservationDate} 的候补申请？`, '取消候补', {
      type: 'warning',
      confirmButtonText: '确认取消',
      cancelButtonText: '保留',
    })
  } catch {
    return
  }
  try {
    await cancelWaitlist(row.id)
    waitlist.value = waitlist.value.filter((item) => item.id !== row.id)
    ElMessage.success('候补申请已取消')
  } catch {
    // 拦截器已提示
  }
}

function onPageChange(p: number) {
  query.value.page = p
  void load(p)
}

function onSizeChange(s: number) {
  query.value.size = s
  query.value.page = 1
  cursorPager.reset()
  void load()
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
    cursorPager.reset()
    await load()
  } catch {
    // 拦截器已提示
  }
}

async function onCheckIn(row: ReservationVO) {
  try {
    await checkInReservation(row.id)
    ElMessage.success('签到成功')
    cursorPager.reset()
    await load()
  } catch {
    // 拦截器已提示(时间窗 / 状态不符等由后端返回)
  }
}

async function onCheckOut(row: ReservationVO) {
  returningRow.value = row
  returnCondition.value = 'NORMAL'
  returnNote.value = ''
  returnDialogVisible.value = true
}

async function submitReturn() {
  const row = returningRow.value
  if (!row) return
  try {
    await checkOutReservation(row.id, {
      condition: returnCondition.value,
      note: returnNote.value.trim() || undefined,
    })
    returnDialogVisible.value = false
    returningRow.value = null
    ElMessage.success('归还成功')
    cursorPager.reset()
    await load()
  } catch {
    // 拦截器已提示
  }
}

function goDetail(row: ReservationVO) {
  router.push({ name: 'reservation-detail', params: { id: row.id } })
}

function fmt(t?: string): string {
  return t ? dayjs(t).format('YYYY-MM-DD') : '—'
}

const subtitle = computed(() => `共 ${page.value.total} 条预约`)

onMounted(() => {
  void load()
  void loadWaitlist()
})
</script>

<template>
  <div class="mine">
    <PageHeader title="我的预约" :subtitle="subtitle" />

    <section class="mine__overview" aria-label="预约概览">
      <div>
        <span class="mine__eyebrow">预约时间线</span>
        <h2>把接下来的实验安排，放在手边。</h2>
        <p>从待审批到归还设备，每条预约都保留完整的日期和状态轨迹。</p>
      </div>
      <div class="mine__overview-mark"><span />{{ page.total }}<small>条记录</small></div>
    </section>

    <!-- 状态筛选:SegmentedControl(沿用既有 8 状态 + 全部) -->
    <div class="mine__filter">
      <SegmentedControl
        :model-value="activeStatus"
        :options="tabs"
        size="sm"
        @update:model-value="onStatusChange"
      />
    </div>

    <section v-if="waitlist.length" class="mine__waitlist" aria-label="我的候补申请">
      <div class="mine__waitlist-head">
        <div>
          <span class="mine__eyebrow">WAITLIST</span>
          <h3>我的候补申请</h3>
        </div>
        <span>{{ waitlist.length }} 条</span>
      </div>
      <div class="mine__waitlist-list">
        <div v-for="row in waitlist" :key="row.id" class="mine__waitlist-row">
          <div>
            <strong>{{ row.deviceName || `设备 #${row.deviceId}` }}</strong>
            <span>{{ row.reservationDate }} · {{ row.purpose }}</span>
          </div>
          <div class="mine__waitlist-actions">
            <Tag :variant="row.status === 'NOTIFIED' ? 'success' : 'warning'" size="small" round>
              {{ row.status === 'NOTIFIED' ? '已释放，请重新预约' : '排队中' }}
            </Tag>
            <TextButton size="small" @click="onCancelWaitlist(row)">取消</TextButton>
          </div>
        </div>
      </div>
    </section>

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
                <span class="mine__card-value">{{ row.deviceName || `设备 #${row.deviceId}` }}</span>
            </div>

            <div class="mine__card-time">
              <div class="mine__card-time-row">
                <span class="mine__card-time-dot mine__card-time-dot--start" />
                <span class="mine__card-time-text">{{ fmt(row.startDate || row.startTime) }}</span>
              </div>
              <div class="mine__card-time-line" aria-hidden="true" />
              <div class="mine__card-time-row">
                <span class="mine__card-time-dot mine__card-time-dot--end" />
                <span class="mine__card-time-text">{{ fmt(row.endDate || row.endTime) }}</span>
              </div>
            </div>

            <div class="mine__card-meta">
              <span class="mine__card-chip">共 {{ row.slotCount }} 天</span>
              <span class="mine__card-chip mine__card-chip--muted">
                自然日预约
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

    <el-dialog v-model="returnDialogVisible" title="归还验收" width="520px">
      <div class="mine__return-form">
        <p class="mine__return-hint">
          请选择设备归还时的状态；如发现损坏或缺失，请填写处理备注。
        </p>
        <el-radio-group v-model="returnCondition">
          <el-radio value="NORMAL">验收正常</el-radio>
          <el-radio value="DAMAGED">发现损坏</el-radio>
          <el-radio value="MISSING">设备缺失</el-radio>
        </el-radio-group>
        <el-input
          v-model="returnNote"
          type="textarea"
          :rows="4"
          maxlength="1000"
          show-word-limit
          placeholder="补充验收备注（可选）"
        />
      </div>
      <template #footer>
        <GhostButton @click="returnDialogVisible = false">取消</GhostButton>
        <GhostButton @click="submitReturn">确认归还</GhostButton>
      </template>
    </el-dialog>
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

  &__waitlist {
    display: grid;
    gap: 14px;
    padding: 18px 20px;
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-card);
  }

  &__waitlist-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;

    h3 {
      margin: 5px 0 0;
      color: var(--text-primary);
      font-family: var(--font-display);
      font-size: 16px;
    }

    & > span {
      color: var(--text-tertiary);
      font-family: var(--font-mono);
      font-size: 12px;
    }
  }

  &__waitlist-list {
    display: grid;
    gap: 8px;
  }

  &__waitlist-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    padding: 12px 14px;
    background: var(--bg-elevated);
    border-radius: var(--radius-control);

    & > div:first-child {
      display: grid;
      gap: 4px;
      min-width: 0;
    }

    strong { overflow: hidden; color: var(--text-primary); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
    span { color: var(--text-tertiary); font-size: 11px; }
  }

  &__waitlist-actions {
    display: flex;
    align-items: center;
    flex: none;
    gap: 10px;
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

  @media (max-width: 620px) {
    &__waitlist-row { align-items: flex-start; flex-direction: column; }
    &__waitlist-actions { align-self: flex-end; }
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

  &__return-form {
    display: grid;
    gap: 16px;
  }

  &__return-hint {
    margin: 0;
    color: var(--text-secondary);
    font-size: 13px;
    line-height: 1.6;
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

<style scoped lang="scss">
/* 预约页采用纵向时间线工作区，避免大量预约时形成卡片墙。 */
.mine__overview {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding: 24px 26px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-card);
  background: linear-gradient(108deg, color-mix(in srgb, var(--accent) 9%, var(--bg-surface)), var(--bg-surface));
}
.mine__eyebrow { display: block; margin-bottom: 8px; color: var(--text-tertiary); font-family: var(--font-mono); font-size: 10px; letter-spacing: .14em; text-transform: uppercase; }
.mine__overview h2 { margin: 0 0 7px; color: var(--text-primary); font-family: var(--font-display); font-size: clamp(22px, 3vw, 32px); letter-spacing: -.06em; }
.mine__overview p { margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.mine__overview-mark { display: flex; align-items: baseline; gap: 7px; color: var(--accent); font-family: var(--font-display); font-size: 40px; font-weight: 700; white-space: nowrap; }
.mine__overview-mark span { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 14px var(--accent); }
.mine__overview-mark small { color: var(--text-tertiary); font-family: var(--font-sans); font-size: 12px; font-weight: 500; }
.mine__grid { display: flex; flex-direction: column; gap: 12px; }
.mine__cell { display: block; }
.mine__card { display: grid; grid-template-columns: minmax(180px, .8fr) minmax(280px, 1.4fr) minmax(240px, 1fr); align-items: center; gap: 22px; padding: 18px 22px; }
.mine__card-head { align-self: start; }
.mine__card-body { min-width: 0; }
.mine__card-time { max-width: 260px; }
.mine__card-foot { grid-column: 1 / -1; margin-top: 0; }
.mine__card-purpose { max-width: 520px; }
@media (max-width: 980px) { .mine__card { grid-template-columns: minmax(160px, .7fr) minmax(260px, 1.3fr); } .mine__card-foot { grid-column: 1 / -1; } }
@media (max-width: 680px) { .mine__overview { align-items: flex-start; flex-direction: column; padding: 20px; } .mine__overview-mark { font-size: 32px; } .mine__card { display: flex; align-items: stretch; flex-direction: column; gap: 14px; padding: 16px; } .mine__card-time { max-width: none; } }
</style>
