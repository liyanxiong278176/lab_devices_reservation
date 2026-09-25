<script setup lang="ts">
// 通知中心(R6 重构):PageHeader + SegmentedControl(全部/未读)+ 通知行列表和详情抽屉
// 点击通知打开详情；未读项同时标记已读，但保留在当前列表和筛选结果中。
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import { markAllRead, markRead, myNotifications } from '@/api/notification'
import type { NotificationVO } from '@/types/notification'
import type { Page } from '@/types/common'
import { useNotificationStore } from '@/stores/notification'
import { useStagger } from '@/composables/useStagger'
import PageHeader from '@/components/ui/PageHeader.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import Tag from '@/components/ui/Tag.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import PageDepthNotice from '@/components/ui/PageDepthNotice.vue'

const notifStore = useNotificationStore()

const loading = ref(false)
const onlyUnread = ref(false)
const page = ref<Page<NotificationVO>>({ records: [], total: 0, size: 10, current: 1 })
const query = ref<{ page: number; size: number }>({ page: 1, size: 10 })
const selectedNotification = ref<NotificationVO | null>(null)
const detailVisible = ref(false)
const markingRead = new Set<number>()

// SegmentedControl 选项:全部 / 未读(对齐既有 onlyUnread 布尔;API 仅支持 all/unread,
// 不强行加"已读"以免改查询逻辑——守住"逻辑零改")
const filterOptions = [
  { label: '全部', value: 'all' },
  { label: '未读', value: 'unread' },
]

// SegmentedControl 双向值(派生自 onlyUnread,保持布尔契约给 API)
const filterValue = computed<'all' | 'unread'>(() => (onlyUnread.value ? 'unread' : 'all'))

// 列表错峰容器:首次进入视口时各行按 50ms 错峰 fade+rise(R3/R4 同款)。
const listRef = ref<HTMLElement | null>(null)
const { reveal } = useStagger(listRef, { delay: 50 })

async function load(targetPage = query.value.page) {
  loading.value = true
  try {
    page.value = await myNotifications({
      onlyUnread: onlyUnread.value || undefined,
      page: targetPage,
      size: query.value.size,
    })
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
  await nextTick()
  reveal()
}

function onFilterChange() {
  query.value.page = 1
  void load()
}

// SegmentedControl 切换:写 onlyUnread 后立即查询(等价原 el-checkbox @change)
function onFilterSegment(v: string | number) {
  onlyUnread.value = v === 'unread'
  onFilterChange()
}

function onPageChange(p: number) {
  query.value.page = p
  void load(p)
}
function onSizeChange(s: number) {
  query.value.size = s
  query.value.page = 1
  void load()
}

async function onMarkRead(row: NotificationVO) {
  if (row.isRead !== 0 || markingRead.has(row.id)) return
  markingRead.add(row.id)
  try {
    await markRead(row.id)
    row.isRead = 1
    notifStore.decreaseUnread()
    // 保留当前行，只更新已读样式；避免用户点击后通知突然从当前列表消失。
    // 切换筛选条件或手动刷新时，再按服务端最新状态重新查询。
    await notifStore.loadUnread()
  } catch {
    // 拦截器已提示
  } finally {
    markingRead.delete(row.id)
  }
}

async function onMarkAllRead() {
  try {
    await markAllRead()
    ElMessage.success('已全部标记为已读')
    page.value.records.forEach((row) => {
      row.isRead = 1
    })
    notifStore.clearUnread()
    await notifStore.loadUnread()
  } catch {
    // 拦截器已提示
  }
}

// 点击任意通知查看完整详情；未读通知打开时自动标记已读。
function onRowClick(row: NotificationVO) {
  selectedNotification.value = row
  detailVisible.value = true
  if (row.isRead === 0) void onMarkRead(row)
}

function typeLabel(t: string): string {
  switch (t) {
    case 'APPROVAL':
    case 'RESERVATION_APPROVED':
    case 'RESERVATION_REJECTED':
      return '审批'
    case 'RESERVATION':
    case 'RESERVATION_CREATED':
      return '预约'
    case 'REPAIR':
    case 'REPAIR_UPDATE':
      return '报修'
    case 'SYSTEM':
      return '系统'
    default:
      return t
  }
}

// 类型 → Tag variant 映射:预约=青(主家)/审批=警示/报修=危险/系统=信息/其它=默认
function typeVariant(t: string): 'default' | 'success' | 'warning' | 'danger' | 'info' | 'accent' {
  switch (t) {
    case 'APPROVAL':
    case 'RESERVATION_APPROVED':
    case 'RESERVATION_REJECTED':
      return 'warning'
    case 'RESERVATION':
    case 'RESERVATION_CREATED':
      return 'accent'
    case 'REPAIR':
    case 'REPAIR_UPDATE':
      return 'danger'
    case 'SYSTEM':
      return 'info'
    default:
      return 'default'
  }
}

function fmt(t?: string): string {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'
}

const totalLabel = computed(() => `共 ${page.value.total} 条`)

onMounted(() => {
  void Promise.all([load(), notifStore.loadUnread()])
})
</script>

<template>
  <div class="notif-page">
    <PageHeader title="通知中心" subtitle="审批结果、预约提醒、报修进展等站内消息">
      <template #actions>
        <GhostButton @click="onMarkAllRead">全部已读</GhostButton>
      </template>
    </PageHeader>

    <section class="notif-overview">
      <div>
        <span class="section-kicker">INBOX / ACTIVITY</span>
        <h2>重要的事，会一直留在这里。</h2>
        <p>点击未读消息只会更新状态，不会从通知流中消失。</p>
      </div>
      <div class="notif-overview__count">
        <strong>{{ notifStore.unread }}</strong>
        <span>未读提醒</span>
      </div>
    </section>

    <!-- 筛选:SegmentedControl(全部/未读)-->
    <div class="notif-page__filter">
      <SegmentedControl
        :model-value="filterValue"
        :options="filterOptions"
        size="sm"
        orientation="vertical"
        @update:model-value="onFilterSegment"
      />
    </div>

    <!-- 通知列表 -->
    <div v-loading="loading" class="notif-list" ref="listRef">
      <article
        v-for="row in page.records"
        :key="row.id"
        class="notif-row"
        :class="{ 'notif-row--unread': row.isRead === 0 }"
        :data-read="row.isRead === 1 ? 'read' : 'unread'"
        data-stagger
        tabindex="0"
        role="button"
        :aria-label="`${row.title}（${row.isRead === 0 ? '未读' : '已读'}，点击查看详情）`"
        @click="onRowClick(row)"
        @keydown.enter.prevent="onRowClick(row)"
        @keydown.space.prevent="onRowClick(row)"
      >
        <div class="notif-row__main">
          <div class="notif-row__head">
            <Tag :variant="typeVariant(row.type)" round>{{ typeLabel(row.type) }}</Tag>
            <span class="notif-row__title">{{ row.title }}</span>
          </div>
          <p v-if="row.content" class="notif-row__content">{{ row.content }}</p>
        </div>

        <div class="notif-row__meta">
          <time class="notif-row__time">{{ fmt(row.createdAt) }}</time>
        </div>
      </article>

      <!-- 空态 -->
      <div v-if="!loading && page.records.length === 0" class="notif-list__empty">
        <EmptyState
          icon="Bell"
          title="暂无通知"
          description="新的审批结果、预约提醒和报修进展会在这里显示。"
        />
      </div>
    </div>

    <!-- 分页(EP pagination 已由 theme.dark.scss 桥接深色)-->
    <div v-if="page.records.length > 0" class="notif-page__pager">
      <PageDepthNotice v-if="page.truncated" :total="page.total" />
      <el-pagination
        :current-page="page.current"
        :page-size="page.size"
        :total="page.truncated ? Math.min(page.total, (page.pages || 1) * page.size) : page.total"
        :page-sizes="[10, 20, 50]"
        :layout="`total, sizes, prev, pager, next`"
        :total-text="totalLabel"
        background
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>

    <el-drawer
      v-model="detailVisible"
      :title="selectedNotification?.title || '通知详情'"
      size="520px"
      direction="rtl"
      modal-class="notification-detail-drawer"
      :close-on-click-modal="true"
    >
      <div v-if="selectedNotification" class="notif-detail">
        <div class="notif-detail__heading">
          <Tag :variant="typeVariant(selectedNotification.type)" round>
            {{ typeLabel(selectedNotification.type) }}
          </Tag>
          <span :class="['notif-detail__status', { 'notif-detail__status--unread': selectedNotification.isRead === 0 }]">
            {{ selectedNotification.isRead === 0 ? '未读' : '已读' }}
          </span>
        </div>

        <section class="notif-detail__message" aria-label="通知内容">
          <p>{{ selectedNotification.content || '暂无详细内容。' }}</p>
        </section>

        <dl class="notif-detail__facts">
          <div>
            <dt>通知时间</dt>
            <dd>{{ fmt(selectedNotification.createdAt) }}</dd>
          </div>
          <div v-if="selectedNotification.relatedType || selectedNotification.relatedId">
            <dt>关联业务</dt>
            <dd>
              {{ selectedNotification.relatedType || '业务记录' }}
              <template v-if="selectedNotification.relatedId">#{{ selectedNotification.relatedId }}</template>
            </dd>
          </div>
        </dl>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped lang="scss">
.notif-page {
  display: flex;
  flex-direction: column;
  gap: 20px;

  &__filter {
    display: flex;
    align-items: center;
    justify-content: flex-start;
  }

  &__pager {
    display: flex;
    justify-content: flex-end;
    padding-top: 4px;
  }
}

.notif-overview {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  padding: 20px 0 24px;
  border-top: 1px solid var(--border-default);
  border-bottom: 1px solid var(--border-default);
}

.notif-overview h2 { margin: 9px 0 5px; color: var(--text-primary); font-family: var(--font-display); font-size: clamp(24px, 3vw, 36px); letter-spacing: -.05em; }
.notif-overview p { margin: 0; color: var(--text-secondary); font-size: 13px; }
.notif-overview__count { display: grid; gap: 2px; min-width: 110px; padding-left: 18px; border-left: 1px solid var(--border-default); }
.notif-overview__count strong { color: var(--accent); font-family: var(--font-mono); font-size: 32px; font-weight: 500; letter-spacing: -.08em; }
.notif-overview__count span { color: var(--text-tertiary); font-size: 11px; }

// ---- 通知列表 ---------------------------------------------------------------
.notif-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 120px;
  position: relative;
}

// ---- 通知行 -----------------------------------------------------------------
.notif-row {
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px 14px 22px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-soft-lighter);
  // overflow:hidden 让左侧 ::before 青条被卡的圆角裁剪,顶部/底部不冒尖
  overflow: hidden;
  transition:
    background-color var(--d-fast) var(--ease-out-expo),
    border-color var(--d-fast) var(--ease-out-expo),
    color var(--d-med) var(--ease-out-expo);

  // 未读项:左侧 2px 青色指示条(::before 比 border-left 更可控,不影响盒模型/圆角)
  // 全高 top:0/bottom:0,与 MainLayout 侧栏 active 指示条视觉一致(spec §4)。
  &--unread::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--accent);
    box-shadow: 0 0 8px color-mix(in srgb, var(--accent) 45%, transparent);
  }

  // 所有通知都可打开详情；未读状态仅由上方青色指示条表达。
  // hover/焦点时抬升面并轻微强化青边。
  cursor: pointer;

  &:hover,
  &:focus-visible {
    background: var(--bg-elevated);
    border-color: color-mix(in srgb, var(--accent) 35%, transparent);
    outline: none;
  }

  // 已读项:整体弱化(无青条 + 三级文字)
  &[data-read='read'] {
    color: var(--text-tertiary);

    .notif-row__title,
    .notif-row__content {
      color: var(--text-tertiary);
    }
  }

  &__main {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  &__head {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  &__title {
    font-family: var(--font-display);
    font-size: 15px;
    font-weight: 600;
    line-height: 1.4;
    color: var(--text-primary);
    // 长标题限 2 行,行高整齐
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    transition: color var(--d-med) var(--ease-out-expo);
  }

  &__content {
    margin: 0;
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-secondary);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    transition: color var(--d-med) var(--ease-out-expo);
  }

  &__meta {
    flex: 0 0 auto;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 4px;
    white-space: nowrap;
  }

  &__time {
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--text-tertiary);
  }
}

.notif-detail {
  display: flex;
  flex-direction: column;
  gap: 22px;
  padding: 8px 4px 24px;

  &__heading {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  &__status {
    color: var(--text-tertiary);
    font-size: 12px;

    &--unread { color: var(--accent); }
  }

  &__message {
    padding: 18px;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-control);
    background: var(--bg-sunken);

    p {
      margin: 0;
      color: var(--text-primary);
      font-size: 14px;
      line-height: 1.8;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
  }

  &__facts {
    display: grid;
    gap: 0;
    margin: 0;
    border-top: 1px solid var(--border-subtle);

    div {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 13px 0;
      border-bottom: 1px solid var(--border-subtle);
    }

    dt { color: var(--text-tertiary); font-size: 12px; }
    dd { margin: 0; color: var(--text-primary); font-size: 12px; text-align: right; }
  }
}

@media (max-width: 720px) {
  .notif-overview { align-items: flex-start; flex-direction: column; }
  .notif-overview__count { padding: 10px 0 0; border-top: 1px solid var(--border-default); border-left: 0; }
}

// reduced-motion 守卫(spec §6.1 铁律 #3):transition 在 reduce 时关闭
@media (prefers-reduced-motion: reduce) {
  .notif-row {
    transition: none !important;
  }
}
</style>

<style lang="scss">
.notification-detail-drawer {
  --el-drawer-bg-color: var(--bg-surface);
  --el-drawer-title-text-color: var(--text-primary);

  .el-drawer {
    background: var(--bg-surface);
    border-left: 1px solid var(--border-default);
    box-shadow: var(--shadow-soft);
  }

  .el-drawer__header {
    margin-bottom: 0;
    padding: 20px 24px;
    border-bottom: 1px solid var(--border-subtle);
    color: var(--text-primary);
  }

  .el-drawer__title {
    color: var(--text-primary);
    font-family: var(--font-display);
    font-size: 18px;
    font-weight: 600;
  }

  .el-drawer__close-btn {
    color: var(--text-secondary);

    &:hover { color: var(--accent); }
  }

  .el-drawer__body { padding: 24px; }
}
</style>
