<script setup lang="ts">
// 审批队列页：PageHeader + 活动流 + 右侧详情/处理抽屉。
// 审批通过后预约进入负责人设备交接队列。
// reject(id, reason) 与批量 approve 契约不变，列表按钮保留给真实链路使用。
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import { approve, batchApprove, pendingApprovals, reject } from '@/api/approval'
import type { ApprovalItemVO } from '@/types/approval'
import type { Page } from '@/types/common'
import { useNotificationStore } from '@/stores/notification'
import { useStagger } from '@/composables/useStagger'
import PageHeader from '@/components/ui/PageHeader.vue'
import Tag from '@/components/ui/Tag.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PageDepthNotice from '@/components/ui/PageDepthNotice.vue'

const notifStore = useNotificationStore()

const loading = ref(false)
const page = ref<Page<ApprovalItemVO>>({ records: [], total: 0, size: 9, current: 1 })
const query = ref<{ page: number; size: number }>({ page: 1, size: 9 })

// 批量通过:选中 id 集合(原 selection: ApprovalItemVO[] → 简化为 id[],
// batchApprove 仍接收 ids,契约不变)
const selectedIds = ref<number[]>([])

// 驳回：同时只处理一张申请，表单放在右侧抽屉中。
const rejectingId = ref<number | null>(null)
const rejectReason = ref('')
const rejecting = ref(false)
const approvalDrawerVisible = ref(false)
const selectedApproval = ref<ApprovalItemVO | null>(null)

// 卡片错峰容器(同 R4 设备网格 / R5.2 我的预约):首次进入视口 60ms 错峰 fade+rise
const listRef = ref<HTMLElement | null>(null)
const { reveal } = useStagger(listRef, { delay: 60 })

async function load() {
  loading.value = true
  try {
    page.value = await pendingApprovals(query.value.page, query.value.size)
    // 翻页/重载后清掉离开当前页的选中,避免跨页误批量
    const live = new Set(page.value.records.map((r) => r.id))
    selectedIds.value = selectedIds.value.filter((id) => live.has(id))
    if (rejectingId.value !== null && !live.has(rejectingId.value)) {
      rejectingId.value = null
      rejectReason.value = ''
    }
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
  void load()
}
function onSizeChange(s: number) {
  query.value.size = s
  query.value.page = 1
  void load()
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

function openApproval(row: ApprovalItemVO) {
  selectedApproval.value = row
  approvalDrawerVisible.value = true
}

function closeApproval() {
  approvalDrawerVisible.value = false
  rejectingId.value = null
  rejectReason.value = ''
}

async function onApprove(row: ApprovalItemVO) {
  try {
    await approve(row.id)
    ElMessage.success('已通过，预约进入设备交接队列')
    if (selectedApproval.value?.id === row.id) closeApproval()
    await load()
    notifStore.loadUnread()
  } catch {
    // 拦截器已提示
  }
}

function openReject(row: ApprovalItemVO) {
  selectedApproval.value = row
  approvalDrawerVisible.value = true
  rejectingId.value = row.id
  rejectReason.value = ''
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
    closeApproval()
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
    ElMessage.success(`已批量通过 ${selectedIds.value.length} 条，预约进入设备交接队列`)
    selectedIds.value = []
    await load()
    notifStore.loadUnread()
  } catch {
    // 拦截器已提示
  }
}

function fmt(t?: string): string {
  return t ? dayjs(t).format('YYYY-MM-DD') : '—'
}

/** 申请人姓名优先 realName,fallback username。 */
function applicantName(row: ApprovalItemVO): string {
  return row.realName?.trim() || row.username?.trim() || `用户 #${row.userId}`
}

/** 头像首字:取姓名首个字符(中英文都取首字)。 */
function avatarChar(row: ApprovalItemVO): string {
  return applicantName(row).charAt(0).toUpperCase()
}

function durationLabel(slots?: number): string {
  return slots && slots > 0 ? `${slots} 天` : '—'
}

const subtitle = computed(() => `共 ${page.value.total} 条待处理`)

onMounted(load)
</script>

<template>
  <div class="approval">
    <PageHeader title="待审批" :subtitle="subtitle">
      <template v-if="page.records.length > 0" #actions>
        <GhostButton
          v-permission="'reservation:approve'"
          :disabled="selectedIds.length === 0"
          @click="onBatchApprove"
        >
          批量通过 ({{ selectedIds.length }})
        </GhostButton>
      </template>
    </PageHeader>

    <!-- 审批队列：按时间阅读的活动流，点击一条申请后在右侧完成处理 -->
    <div v-loading="loading" class="approval__grid" ref="listRef">
      <div
        v-for="row in page.records"
        :key="row.id"
        class="approval__cell"
        data-stagger
      >
        <article class="approval__card" @click="openApproval(row)">
          <!-- 卡头：批量选择 + 状态 + 编号 -->
          <header class="approval__card-head">
            <div class="approval__card-head-left">
              <el-checkbox
                v-permission="'reservation:approve'"
                :model-value="selectedIds.includes(row.id)"
                @click.stop
                @change="onRowCheck(row, $event)"
              />
              <Tag variant="warning" effect="light" size="small" round>待审批</Tag>
            </div>
            <span class="approval__card-id">#{{ row.id }}</span>
          </header>

          <div class="approval__row-grid">
            <!-- 申请人(头像 + 姓名) -->
            <div class="approval__applicant">
              <div class="approval__avatar" aria-hidden="true">{{ avatarChar(row) }}</div>
              <div class="approval__applicant-info">
                <span class="approval__applicant-name">{{ applicantName(row) }}</span>
                <span class="approval__applicant-sub">申请人</span>
              </div>
            </div>

            <div class="approval__device-block">
              <span class="approval__eyebrow">设备</span>
              <h3 class="approval__device">{{ row.deviceName }}</h3>
            </div>

            <div class="approval__date-block">
              <span class="approval__eyebrow">预约日期</span>
              <strong class="approval__date">{{ fmt(row.startTime) }}</strong>
              <span class="approval__date-range">至 {{ fmt(row.endTime) }}</span>
            </div>

            <div class="approval__purpose-block">
              <span class="approval__eyebrow">用途</span>
              <p class="approval__purpose">{{ row.purpose || '未填写用途' }}</p>
            </div>
          </div>

          <div class="approval__meta">
            <span class="approval__chip">{{ durationLabel(row.slotCount) }}</span>
            <span class="approval__chip approval__chip--muted">点击查看申请详情</span>
          </div>

          <!-- 卡脚：快捷处理保留在列表中，复杂信息放右侧抽屉 -->
          <footer class="approval__foot">
            <span class="approval__open-hint">查看申请详情 →</span>
            <div class="approval__actions">
              <GhostButton
                v-permission="'reservation:approve'"
                size="small"
                class="approval__reject-btn"
                :disabled="rejectingId === row.id"
                @click.stop="openReject(row)"
              >
                驳回
              </GhostButton>
              <GradientButton
                v-permission="'reservation:approve'"
                size="small"
                @click.stop="onApprove(row)"
              >
                通过
              </GradientButton>
            </div>
          </footer>
        </article>
      </div>

      <!-- 空态 -->
      <div v-if="!loading && page.records.length === 0" class="approval__empty">
        <EmptyState
          icon="Checked"
          title="暂无待审批申请"
          description="当前没有需要审批的预约；审批通过或自动确认的预约会进入设备交接队列。"
        />
      </div>
    </div>

    <!-- 分页(深色全局已桥接) -->
    <div v-if="page.records.length > 0" class="approval__pager">
      <PageDepthNotice v-if="page.truncated" :total="page.total" />
      <el-pagination
        :current-page="page.current"
        :page-size="page.size"
        :total="page.truncated ? Math.min(page.total, (page.pages || 1) * page.size) : page.total"
        :page-sizes="[9, 18, 36]"
        layout="total, sizes, prev, pager, next"
        background
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>

    <el-drawer
      v-model="approvalDrawerVisible"
      :with-header="false"
      direction="rtl"
      size="min(480px, 92vw)"
      class="approval-detail-drawer"
      @close="closeApproval"
    >
      <template v-if="selectedApproval">
        <div class="approval-drawer">
          <header class="approval-drawer__head">
            <div>
              <span class="approval-drawer__eyebrow">预约申请 #{{ selectedApproval.id }}</span>
              <h2>申请详情</h2>
            </div>
            <button class="approval-drawer__close" type="button" aria-label="关闭" @click="closeApproval">×</button>
          </header>

          <div class="approval-drawer__status">
            <Tag variant="warning" effect="light" size="small" round>待审批</Tag>
            <span>提交于 {{ fmt(selectedApproval.createdAt) }}</span>
          </div>

          <section class="approval-drawer__hero">
            <div class="approval__avatar approval-drawer__avatar" aria-hidden="true">{{ avatarChar(selectedApproval) }}</div>
            <div>
              <span class="approval-drawer__eyebrow">申请人</span>
              <strong>{{ applicantName(selectedApproval) }}</strong>
              <span>{{ selectedApproval.username }}</span>
            </div>
          </section>

          <dl class="approval-drawer__facts">
            <div><dt>预约设备</dt><dd>{{ selectedApproval.deviceName }}</dd></div>
            <div><dt>预约日期</dt><dd>{{ fmt(selectedApproval.startTime) }} 至 {{ fmt(selectedApproval.endTime) }}</dd></div>
            <div><dt>预约时长</dt><dd>{{ durationLabel(selectedApproval.slotCount) }}</dd></div>
            <div><dt>设备编号</dt><dd>#{{ selectedApproval.deviceId }}</dd></div>
            <div><dt>用户编号</dt><dd>#{{ selectedApproval.userId }}</dd></div>
          </dl>

          <section class="approval-drawer__purpose">
            <span class="approval-drawer__eyebrow">使用用途</span>
            <p>{{ selectedApproval.purpose || '申请人未填写用途。' }}</p>
          </section>

          <section v-if="rejectingId === selectedApproval.id" class="approval-drawer__reject">
            <label class="approval-drawer__eyebrow" for="approval-reason">驳回理由（必填）</label>
            <el-input
              id="approval-reason"
              v-model="rejectReason"
              type="textarea"
              :rows="5"
              placeholder="请填写驳回理由，将通知申请人"
              maxlength="200"
              show-word-limit
            />
            <div class="approval-drawer__actions">
              <GhostButton size="small" @click="cancelReject">取消</GhostButton>
              <GradientButton
                v-permission="'reservation:approve'"
                size="small"
                :loading="rejecting"
                @click="onRejectConfirm(selectedApproval)"
              >
                确认驳回
              </GradientButton>
            </div>
          </section>

          <footer v-else class="approval-drawer__footer">
            <GhostButton
              v-permission="'reservation:approve'"
              class="approval__reject-btn"
              @click="openReject(selectedApproval)"
            >
              驳回申请
            </GhostButton>
            <GradientButton v-permission="'reservation:approve'" @click="onApprove(selectedApproval)">
              通过申请
            </GradientButton>
          </footer>
        </div>
      </template>
    </el-drawer>
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
    background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 18%, transparent), color-mix(in srgb, var(--accent-blue) 18%, transparent));
    border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
    color: var(--accent-bright);
    font-family: var(--font-display);
    font-size: 15px;
    font-weight: 600;
    text-transform: uppercase;
    box-shadow: 0 0 12px color-mix(in srgb, var(--accent) 18%, transparent);
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
      box-shadow: 0 0 8px color-mix(in srgb, var(--accent) 45%, transparent);
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
  .approval__avatar,
  .approval__time-dot--start {
    box-shadow: none;
  }
}
</style>

<style scoped lang="scss">
/* 审批工作台覆盖：活动流 + 右侧详情抽屉，避免回到卡片墙。 */
.approval__grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.approval__cell { display: block; }

.approval__card {
  display: block;
  padding: 18px 20px;
  background: color-mix(in srgb, var(--bg-surface) 94%, var(--accent) 6%);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-card);
  cursor: pointer;
  transition: border-color .2s ease, transform .2s ease, background .2s ease, box-shadow .2s ease;
}

.approval__card:hover {
  background: var(--bg-elevated);
  border-color: var(--border-accent);
  box-shadow: var(--shadow-soft);
  transform: translateY(-2px);
}

.approval__row-grid {
  display: grid;
  grid-template-columns: minmax(150px, .8fr) minmax(200px, 1.35fr) minmax(170px, 1fr) minmax(180px, 1fr);
  align-items: center;
  gap: 18px;
  padding: 18px 0;
}

.approval__eyebrow,
.approval-drawer__eyebrow {
  display: block;
  margin-bottom: 7px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: .14em;
  text-transform: uppercase;
}

.approval__device-block,
.approval__date-block,
.approval__purpose-block { min-width: 0; }
.approval__device { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.approval__date { display: block; color: var(--text-primary); font-family: var(--font-mono); font-size: 14px; }
.approval__date-range { color: var(--text-secondary); font-family: var(--font-mono); font-size: 12px; }
.approval__purpose { margin: 0; overflow: hidden; color: var(--text-secondary); font-size: 13px; line-height: 1.6; text-overflow: ellipsis; white-space: nowrap; }
.approval__meta { padding: 0 0 14px; }
.approval__foot { padding-top: 14px; }
.approval__open-hint { color: var(--text-tertiary); font-size: 12px; }

@media (max-width: 1000px) {
  .approval__row-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 620px) {
  .approval__card { padding: 15px; }
  .approval__row-grid { grid-template-columns: 1fr; gap: 14px; }
  .approval__foot { align-items: flex-start; flex-direction: column; }
  .approval__actions { width: 100%; justify-content: flex-end; }
}
</style>

<style lang="scss">
.approval-detail-drawer {
  --el-drawer-bg-color: var(--bg-surface);
  --el-drawer-padding-primary: 0;
}

.approval-detail-drawer .el-drawer {
  background: var(--bg-surface);
  border-left: 1px solid var(--border-default);
  box-shadow: var(--shadow-soft);
}

.approval-detail-drawer .el-drawer__body { padding: 0; }

.approval-drawer {
  display: flex;
  min-height: 100%;
  box-sizing: border-box;
  flex-direction: column;
  gap: 22px;
  padding: 28px;
}

.approval-drawer__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.approval-drawer__head h2 { margin: 5px 0 0; color: var(--text-primary); font-family: var(--font-display); font-size: 28px; letter-spacing: -.05em; }
.approval-drawer__close { width: 34px; height: 34px; border: 1px solid var(--border-default); border-radius: 50%; background: transparent; color: var(--text-tertiary); cursor: pointer; font-size: 22px; line-height: 1; }
.approval-drawer__close:hover { border-color: var(--border-accent); color: var(--accent); }
.approval-drawer__status { display: flex; align-items: center; gap: 10px; color: var(--text-tertiary); font-size: 12px; }
.approval-drawer__hero { display: flex; align-items: center; gap: 13px; padding: 18px; border: 1px solid var(--border-subtle); border-radius: var(--radius-card); background: var(--bg-elevated); }
.approval-drawer__avatar { width: 44px; height: 44px; }
.approval-drawer__hero > div:last-child { display: grid; gap: 3px; }
.approval-drawer__hero strong { color: var(--text-primary); font-family: var(--font-display); font-size: 17px; }
.approval-drawer__hero span:last-child { color: var(--text-tertiary); font-family: var(--font-mono); font-size: 11px; }
.approval-drawer__facts { display: grid; gap: 0; margin: 0; border-top: 1px solid var(--border-subtle); }
.approval-drawer__facts > div { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; padding: 13px 0; border-bottom: 1px solid var(--border-subtle); }
.approval-drawer__facts dt { color: var(--text-tertiary); font-size: 12px; }
.approval-drawer__facts dd { margin: 0; color: var(--text-primary); font-family: var(--font-mono); font-size: 12px; text-align: right; }
.approval-drawer__purpose { padding: 16px; border: 1px solid var(--border-subtle); border-radius: var(--radius-control); background: var(--bg-sunken); }
.approval-drawer__purpose p { margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.75; }
.approval-drawer__reject { display: grid; gap: 12px; margin-top: auto; padding-top: 18px; border-top: 1px solid var(--border-subtle); }
.approval-drawer__actions, .approval-drawer__footer { display: flex; align-items: center; justify-content: flex-end; gap: 10px; margin-top: auto; padding-top: 18px; border-top: 1px solid var(--border-subtle); }
.approval-drawer__footer .gradient-button { flex: 1; }

@media (max-width: 620px) {
  .approval-drawer { padding: 22px 18px; }
  .approval-drawer__facts > div { align-items: flex-start; flex-direction: column; gap: 4px; }
  .approval-drawer__facts dd { text-align: left; }
  .approval-drawer__footer { align-items: stretch; flex-direction: column; }
}
</style>
