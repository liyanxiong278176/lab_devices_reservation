<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import { markAllRead, markRead, myNotifications } from '@/api/notification'
import type { NotificationVO } from '@/types/notification'
import type { Page } from '@/types/common'
import { useNotificationStore } from '@/stores/notification'

const notifStore = useNotificationStore()

const loading = ref(false)
const onlyUnread = ref(false)
const page = ref<Page<NotificationVO>>({ records: [], total: 0, size: 10, current: 1 })
const query = ref<{ page: number; size: number }>({ page: 1, size: 10 })

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
}

function onFilterChange() {
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

function fmt(t?: string): string {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'
}

const totalLabel = computed(() => `共 ${page.value.total} 条`)

onMounted(load)
</script>

<template>
  <div class="notif">
    <div class="notif__head">
      <div>
        <h1 class="notif__title">我的通知</h1>
        <p class="notif__subtitle">审批结果、预约提醒、报修进展等站内消息</p>
      </div>
      <el-button type="primary" plain @click="onMarkAllRead">全部已读</el-button>
    </div>

    <div class="lab-card notif__filter">
      <el-checkbox v-model="onlyUnread" @change="onFilterChange">仅看未读</el-checkbox>
    </div>

    <div class="lab-card notif__table">
      <el-table v-loading="loading" :data="page.records" stripe row-key="id">
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag effect="light" round>{{ typeLabel(row.type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
        <el-table-column prop="content" label="内容" min-width="240" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.isRead === 1" type="info" effect="plain" round>已读</el-tag>
            <el-tag v-else type="warning" effect="light" round>未读</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ fmt(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.isRead === 0"
              link
              type="primary"
              @click="onMarkRead(row)"
            >
              标记已读
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <span class="notif__empty">暂无通知</span>
        </template>
      </el-table>

      <div class="notif__pager">
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
  </div>
</template>

<style scoped lang="scss">
.notif {
  &__head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 24px;
  }

  &__title {
    margin: 0;
    font-size: 28px;
    font-weight: 600;
    letter-spacing: -0.5px;
    color: var(--el-text-color-primary);
  }

  &__subtitle {
    margin: 8px 0 0;
    font-size: 14px;
    color: var(--el-text-color-secondary);
  }

  &__filter {
    padding: 16px 20px;
    margin-bottom: 16px;
  }

  &__table {
    padding: 8px;
  }

  &__pager {
    display: flex;
    justify-content: flex-end;
    padding: 16px;
  }

  &__empty {
    color: var(--el-text-color-secondary);
  }
}
</style>
