<script setup lang="ts">
// 报修管理页(R5 重构):PageHeader + SegmentedControl 状态筛选 + el-table 暗表
// + 状态 Tag + 处理操作(TextButton 受理/解决/驳回) + 处理对话框 + 深色分页。
// 数据来源(API)/受理/解决/驳回/通知逻辑零改——仅换展示层。
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import { listRepairs, rejectRepair, resolveRepair, takeRepair } from '@/api/repair'
import type { RepairReportVO, RepairStatus } from '@/types/repair'
import type { Page } from '@/types/common'
import { useCursorPageChain } from '@/composables/useCursorPageChain'
import { useNotificationStore } from '@/stores/notification'
import PageHeader from '@/components/ui/PageHeader.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import Tag from '@/components/ui/Tag.vue'
import TextButton from '@/components/ui/TextButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import GradientButton from '@/components/ui/GradientButton.vue'

const notifStore = useNotificationStore()

const loading = ref(false)
const page = ref<Page<RepairReportVO>>({ records: [], total: 0, size: 10, current: 1 })
const activeStatus = ref<RepairStatus | ''>('')
const query = ref<{ page: number; size: number }>({ page: 1, size: 10 })
const cursorPager = useCursorPageChain<RepairReportVO>((cursor) => listRepairs(
  activeStatus.value,
  1,
  query.value.size,
  cursor,
))

// 处理对话框:resolve / reject 共用,靠 mode 区分
const handleVisible = ref(false)
const handleMode = ref<'resolve' | 'reject'>('resolve')
const handleTarget = ref<RepairReportVO | null>(null)
const handleNote = ref('')
const handling = ref(false)

// SegmentedControl 选项(沿用既有 5 状态 + 全部,1:1 映射后端 status)
const statusTabs: { label: string; value: RepairStatus | '' }[] = [
  { label: '全部', value: '' },
  { label: '待受理', value: 'PENDING' },
  { label: '处理中', value: 'PROCESSING' },
  { label: '待用户确认', value: 'RESOLVED' },
  { label: '已完成', value: 'COMPLETED' },
  { label: '已驳回', value: 'REJECTED' },
]

async function load() {
  loading.value = true
  try {
    page.value = await cursorPager.load(query.value.page)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function onTabChange(v: string | number) {
  activeStatus.value = (v as RepairStatus | '') ?? ''
  query.value.page = 1
  cursorPager.reset()
  void load()
}

function onPageChange(p: number) {
  query.value.page = p
  load()
}
function onSizeChange(s: number) {
  query.value.size = s
  query.value.page = 1
  cursorPager.reset()
  void load()
}

async function onTake(row: RepairReportVO) {
  try {
    await takeRepair(row.id)
    ElMessage.success('已受理')
    cursorPager.reset()
    await load()
    notifStore.loadUnread()
  } catch {
    // 拦截器已提示
  }
}

function openResolve(row: RepairReportVO) {
  handleMode.value = 'resolve'
  handleTarget.value = row
  handleNote.value = ''
  handleVisible.value = true
}

function openReject(row: RepairReportVO) {
  handleMode.value = 'reject'
  handleTarget.value = row
  handleNote.value = ''
  handleVisible.value = true
}

async function onHandleConfirm() {
  if (!handleTarget.value) return
  if (!handleNote.value.trim()) {
    ElMessage.warning(handleMode.value === 'resolve' ? '请填写处理说明' : '请填写驳回理由')
    return
  }
  handling.value = true
  try {
    if (handleMode.value === 'resolve') {
      await resolveRepair(handleTarget.value.id, handleNote.value.trim())
      ElMessage.success('已标记解决，等待用户确认')
    } else {
      await rejectRepair(handleTarget.value.id, handleNote.value.trim())
      ElMessage.success('已驳回')
    }
    handleVisible.value = false
    cursorPager.reset()
    await load()
    notifStore.loadUnread()
  } catch {
    // 拦截器已提示
  } finally {
    handling.value = false
  }
}

// 状态 → Tag variant 语义色(PENDING=warning / PROCESSING=accent /
// RESOLVED=success / REJECTED=danger)
function statusVariant(s: RepairStatus): 'warning' | 'accent' | 'success' | 'danger' {
  switch (s) {
    case 'PENDING':
      return 'warning'
    case 'PROCESSING':
      return 'accent'
    case 'RESOLVED':
      return 'warning'
    case 'REJECTED':
      return 'danger'
    case 'COMPLETED':
      return 'success'
    default:
      return 'accent'
  }
}

function statusLabel(s: RepairStatus): string {
  switch (s) {
    case 'PENDING':
      return '待受理'
    case 'PROCESSING':
      return '处理中'
    case 'RESOLVED':
      return '待用户确认'
    case 'REJECTED':
      return '已驳回'
    case 'COMPLETED':
      return '已完成'
    default:
      return s
  }
}

function fmt(t?: string): string {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'
}

const subtitle = computed(() => `共 ${page.value.total} 条工单`)
const handleTitle = computed(() => (handleMode.value === 'resolve' ? '解决报修' : '驳回报修'))
const handleLabel = computed(() =>
  handleMode.value === 'resolve' ? '处理说明' : '驳回理由',
)
const handlePlaceholder = computed(() =>
  handleMode.value === 'resolve' ? '说明处理方式与结果(必填)' : '说明驳回原因(必填)',
)

onMounted(load)
</script>

<template>
  <div class="radmin">
    <PageHeader title="报修管理" :subtitle="subtitle" />

    <!-- 状态筛选:SegmentedControl(沿用既有 5 状态 + 全部) -->
    <div class="radmin__filter">
      <SegmentedControl
        :model-value="activeStatus"
        :options="statusTabs"
        size="sm"
        @update:model-value="onTabChange"
      />
    </div>

    <section class="radmin__signal" aria-label="报修队列概览">
      <div>
        <span class="radmin__eyebrow">维修队列</span>
        <strong>把每一条故障，推进到一个明确结果。</strong>
      </div>
      <span class="radmin__signal-count">{{ page.total }} <small>条工单</small></span>
    </section>

    <!-- 暗表(el-table 全局深色桥接,R4.4 已建) -->
    <div class="radmin__table">
      <el-table v-loading="loading" :data="page.records" stripe row-key="id">
        <el-table-column prop="id" label="编号" width="80" />
        <el-table-column prop="deviceName" label="设备" min-width="140" show-overflow-tooltip />
        <el-table-column prop="reporterName" label="报修人" min-width="110" show-overflow-tooltip />
        <el-table-column prop="title" label="标题" min-width="150" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <Tag :variant="statusVariant(row.status)" effect="light" size="small" round>
              {{ statusLabel(row.status) }}
            </Tag>
          </template>
        </el-table-column>
        <el-table-column prop="resolutionNote" label="处理说明" min-width="140" show-overflow-tooltip />
        <el-table-column label="提交时间" width="160">
          <template #default="{ row }">{{ fmt(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <TextButton
              v-if="row.status === 'PENDING'"
              v-permission="'repair:handle'"
              size="small"
              @click="onTake(row)"
            >
              受理
            </TextButton>
            <TextButton
              v-if="row.status === 'PROCESSING'"
              v-permission="'repair:handle'"
              size="small"
              @click="openResolve(row)"
            >
              解决
            </TextButton>
            <TextButton
              v-if="row.status === 'PENDING'"
              v-permission="'repair:handle'"
              size="small"
              class="radmin__reject"
              @click="openReject(row)"
            >
              驳回
            </TextButton>
          </template>
        </el-table-column>
        <template #empty>
          <span class="radmin__empty">暂无报修工单</span>
        </template>
      </el-table>

      <div class="radmin__pager">
        <el-pagination
          :current-page="page.current"
          :page-size="page.size"
          :total="page.total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="onPageChange"
          @size-change="onSizeChange"
        />
      </div>
    </div>

    <!-- 处理抽屉(resolve / reject 共用)：保留当前列表上下文 -->
    <el-drawer
      v-model="handleVisible"
      :with-header="false"
      direction="rtl"
      size="min(480px, 92vw)"
      modal-class="repair-handle-drawer"
    >
      <div v-if="handleTarget" class="radmin__drawer">
        <header class="radmin__drawer-head">
          <div>
            <span class="radmin__eyebrow">工单 #{{ handleTarget.id }}</span>
            <h2>{{ handleTitle }}</h2>
          </div>
          <button class="radmin__drawer-close" type="button" aria-label="关闭" @click="handleVisible = false">×</button>
        </header>

        <section class="radmin__drawer-hero">
          <Tag :variant="statusVariant(handleTarget.status)" effect="light" size="small" round>
            {{ statusLabel(handleTarget.status) }}
          </Tag>
          <h3>{{ handleTarget.title }}</h3>
          <p>{{ handleTarget.deviceName || `设备 #${handleTarget.deviceId}` }}</p>
        </section>

        <dl class="radmin__drawer-facts">
          <div><dt>报修人</dt><dd>{{ handleTarget.reporterName || '—' }}</dd></div>
          <div><dt>提交时间</dt><dd>{{ fmt(handleTarget.createdAt) }}</dd></div>
          <div><dt>设备编号</dt><dd>#{{ handleTarget.deviceId }}</dd></div>
        </dl>

        <section class="radmin__drawer-description">
          <span class="radmin__eyebrow">故障描述</span>
          <p>{{ handleTarget.description || '报修人未填写详细描述。' }}</p>
        </section>

        <el-form class="radmin__drawer-form">
          <el-form-item :label="handleLabel" required>
          <el-input
            v-model="handleNote"
            type="textarea"
            :rows="3"
            :placeholder="handlePlaceholder"
            maxlength="200"
            show-word-limit
          />
          </el-form-item>
        </el-form>
        <footer class="radmin__drawer-actions">
          <GhostButton @click="handleVisible = false">取消</GhostButton>
          <GradientButton :loading="handling" @click="onHandleConfirm">确认处理</GradientButton>
        </footer>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped lang="scss">
// ============================================================================
// 报修管理 暗表(spec §7 报修行)
// 表底/表头/hover/stripe 全由 theme.dark.scss 全局 --el-table-* 桥接接管,
// 此处仅做页面级布局(筛选区 / table 容器 / pager 间距 / 操作列微调)。
// ============================================================================

.radmin {
  display: flex;
  flex-direction: column;
  gap: 20px;

  // ---- 筛选区:sunken 面 + hairline(同 R5 reservation/Mine 模式)------------
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

  &__signal {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 18px;
    padding: 20px 22px;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-card);
    background: linear-gradient(110deg, color-mix(in srgb, var(--accent) 9%, var(--bg-surface)), var(--bg-surface));
  }

  &__eyebrow { display: block; margin-bottom: 8px; color: var(--text-tertiary); font-family: var(--font-mono); font-size: 10px; letter-spacing: .14em; text-transform: uppercase; }
  &__signal strong { color: var(--text-primary); font-family: var(--font-display); font-size: clamp(18px, 2vw, 24px); letter-spacing: -.04em; }
  &__signal-count { color: var(--accent); font-family: var(--font-display); font-size: 28px; font-weight: 700; }
  &__signal-count small { color: var(--text-tertiary); font-family: var(--font-sans); font-size: 12px; font-weight: 500; }

  // ---- 表格容器:surface 卡面 + hairline(同 R4.4 device/Manage)------------
  &__table {
    padding: 8px;
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-soft);
  }

  &__pager {
    display: flex;
    justify-content: flex-end;
    padding: 14px 16px 16px;
  }

  &__empty {
    color: var(--text-secondary);
  }

  // 驳回按钮:hover 红(局部覆盖 TextButton 默认 hover→青色,语义对齐 danger)
  &__reject {
    &:hover,
    &:focus {
      color: var(--status-danger) !important;
    }
  }
}

</style>

<style lang="scss">
.repair-handle-drawer {
  --el-drawer-bg-color: var(--bg-surface);
  --el-drawer-padding-primary: 0;
}
.repair-handle-drawer .el-drawer { background: var(--bg-surface); border-left: 1px solid var(--border-default); box-shadow: var(--shadow-soft); }
.repair-handle-drawer .el-drawer__body { padding: 0; }
.radmin__drawer { display: flex; min-height: 100%; box-sizing: border-box; flex-direction: column; gap: 22px; padding: 28px; }
.radmin__drawer-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.radmin__drawer-head h2 { margin: 5px 0 0; color: var(--text-primary); font-family: var(--font-display); font-size: 28px; letter-spacing: -.05em; }
.radmin__drawer-close { width: 34px; height: 34px; border: 1px solid var(--border-default); border-radius: 50%; background: transparent; color: var(--text-tertiary); cursor: pointer; font-size: 22px; line-height: 1; }
.radmin__drawer-close:hover { border-color: var(--border-accent); color: var(--accent); }
.radmin__drawer-hero { padding: 18px; border: 1px solid var(--border-subtle); border-radius: var(--radius-card); background: var(--bg-elevated); }
.radmin__drawer-hero h3 { margin: 14px 0 5px; color: var(--text-primary); font-family: var(--font-display); font-size: 19px; }
.radmin__drawer-hero p { margin: 0; color: var(--text-secondary); font-size: 13px; }
.radmin__drawer-facts { display: grid; gap: 0; margin: 0; border-top: 1px solid var(--border-subtle); }
.radmin__drawer-facts div { display: flex; justify-content: space-between; gap: 14px; padding: 12px 0; border-bottom: 1px solid var(--border-subtle); }
.radmin__drawer-facts dt { color: var(--text-tertiary); font-size: 12px; }
.radmin__drawer-facts dd { margin: 0; color: var(--text-primary); font-size: 12px; text-align: right; }
.radmin__drawer-description { padding: 16px; border: 1px solid var(--border-subtle); border-radius: var(--radius-control); background: var(--bg-sunken); }
.radmin__drawer-description p { margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.75; }
.radmin__drawer-form { margin-top: auto; }
.radmin__drawer-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: auto; padding-top: 18px; border-top: 1px solid var(--border-subtle); }
@media (max-width: 620px) {
  .radmin__signal { align-items: flex-start; flex-direction: column; }
  .radmin__drawer { padding: 22px 18px; }
}
</style>
