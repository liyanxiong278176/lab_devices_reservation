<script setup lang="ts">
// 通知中心(R6 重构):PageHeader + SegmentedControl(全部/未读)+ 通知行列表
// 未读左侧 2px 青色指示条 + 已读弱化(--text-tertiary)+ 点击未读标记已读 + 空态。
// 数据/筛选/markRead/markAllRead/未读计数——逻辑零改,仅换展示层。
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

const notifStore = useNotificationStore()

const loading = ref(false)
const onlyUnread = ref(false)
const page = ref<Page<NotificationVO>>({ records: [], total: 0, size: 10, current: 1 })
const query = ref<{ page: number; size: number }>({ page: 1, size: 10 })

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
useStagger(listRef, { delay: 50 })

// 首屏错峰交给 useStagger 的 IntersectionObserver;筛选/翻页后 observer 已 stop,
// 新渲染的 [data-stagger] 行缺 stagger-in 会卡在初始态,这里立即补显(不错峰)。
let firstLoad = true

async function load() {
  loading.value = true
  try {
    page.value = await myNotifications({
      onlyUnread: onlyUnread.value || undefined,
      page: query.value.page,
      size: query.value.size,
    })
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
  if (firstLoad) {
    firstLoad = false
    return
  }
  await nextTick()
  listRef.value
    ?.querySelectorAll<HTMLElement>('[data-stagger]:not(.stagger-in)')
    .forEach((el) => el.classList.add('stagger-in'))
}

function onFilterChange() {
  query.value.page = 1
  load()
}

// SegmentedControl 切换:写 onlyUnread 后立即查询(等价原 el-checkbox @change)
function onFilterSegment(v: string | number) {
  onlyUnread.value = v === 'unread'
  onFilterChange()
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

async function onMarkRead(row: NotificationVO) {
  try {
    await markRead(row.id)
    row.isRead = 1
    notifStore.loadUnread()
  } catch {
    // 拦截器已提示
  }
}

async function onMarkAllRead() {
  try {
    await markAllRead()
    ElMessage.success('已全部标记为已读')
    await load()
    notifStore.loadUnread()
  } catch {
    // 拦截器已提示
  }
}

// 行点击:未读 → 标记已读(已读项无操作)。回车键可达性同效。
function onRowClick(row: NotificationVO) {
  if (row.isRead === 0) onMarkRead(row)
}

function typeLabel(t: string): string {
  switch (t) {
    case 'APPROVAL':
      return '审批'
    case 'RESERVATION':
      return '预约'
    case 'REPAIR':
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
      return 'warning'
    case 'RESERVATION':
      return 'accent'
    case 'REPAIR':
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

onMounted(load)
</script>

<template>
  <div class="notif-page">
    <PageHeader title="通知中心" subtitle="审批结果、预约提醒、报修进展等站内消息">
      <template #actions>
        <GhostButton @click="onMarkAllRead">全部已读</GhostButton>
      </template>
    </PageHeader>

    <!-- 筛选:SegmentedControl(全部/未读)-->
    <div class="notif-page__filter">
      <SegmentedControl
        :model-value="filterValue"
        :options="filterOptions"
        size="sm"
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
        :tabindex="row.isRead === 0 ? 0 : undefined"
        :role="row.isRead === 0 ? 'button' : undefined"
        :aria-label="row.isRead === 0 ? `${row.title}（未读，点击标记已读）` : undefined"
        @click="onRowClick(row)"
        @keydown.enter.prevent="onRowClick(row)"
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
      <el-pagination
        :current-page="page.current"
        :page-size="page.size"
        :total="page.total"
        :page-sizes="[10, 20, 50]"
        :layout="`total, sizes, prev, pager, next`"
        :total-text="totalLabel"
        background
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>
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
    box-shadow: 0 0 8px rgba(34, 211, 238, 0.45);
  }

  // 未读项 hover/焦点:抬升面 + 青边轻微强化(可点信号)
  &--unread {
    cursor: pointer;

    &:hover,
    &:focus-visible {
      background: var(--bg-elevated);
      border-color: rgba(34, 211, 238, 0.35);
      outline: none;
    }
  }

  // 已读项:整体弱化(无青条 + 三级文字 + 默认光标)
  &[data-read='read'] {
    cursor: default;
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

// reduced-motion 守卫(spec §6.1 铁律 #3):transition 在 reduce 时关闭
@media (prefers-reduced-motion: reduce) {
  .notif-row {
    transition: none !important;
  }
}
</style>
