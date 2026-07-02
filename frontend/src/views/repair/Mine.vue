<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import { myRepairs } from '@/api/repair'
import type { RepairReportVO, RepairStatus } from '@/types/repair'
import type { Page } from '@/types/common'

const loading = ref(false)
const page = ref<Page<RepairReportVO>>({ records: [], total: 0, size: 10, current: 1 })
const query = ref<{ page: number; size: number }>({ page: 1, size: 10 })

async function load() {
  loading.value = true
  try {
    page.value = await myRepairs(query.value.page, query.value.size)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
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

function statusMeta(s: RepairStatus): { label: string; type: 'info' | 'warning' | 'success' | 'danger' } {
  switch (s) {
    case 'PENDING':
      return { label: '待受理', type: 'warning' }
    case 'PROCESSING':
      return { label: '处理中', type: 'info' }
    case 'RESOLVED':
      return { label: '已解决', type: 'success' }
    case 'REJECTED':
      return { label: '已驳回', type: 'danger' }
    default:
      return { label: s, type: 'info' }
  }
}

function fmt(t?: string): string {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'
}

const totalLabel = computed(() => `共 ${page.value.total} 条`)

onMounted(load)
</script>

<template>
  <div class="rmine">
    <div class="rmine__head">
      <h1 class="rmine__title">我的报修</h1>
      <p class="rmine__subtitle">查看你提交的设备报修记录</p>
    </div>

    <div class="lab-card rmine__table">
      <el-table v-loading="loading" :data="page.records" stripe row-key="id">
        <el-table-column prop="id" label="编号" width="80" />
        <el-table-column prop="deviceName" label="设备" min-width="140" show-overflow-tooltip />
        <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusMeta(row.status).type" effect="light" round>
              {{ statusMeta(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="resolutionNote" label="处理说明" min-width="160" show-overflow-tooltip />
        <el-table-column label="提交时间" width="160">
          <template #default="{ row }">{{ fmt(row.createdAt) }}</template>
        </el-table-column>
        <template #empty>
          <span class="rmine__empty">暂无报修记录</span>
        </template>
      </el-table>

      <div class="rmine__pager">
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
.rmine {
  &__head {
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
