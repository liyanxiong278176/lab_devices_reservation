<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import { listRepairs, rejectRepair, resolveRepair, takeRepair } from '@/api/repair'
import type { RepairReportVO, RepairStatus } from '@/types/repair'
import type { Page } from '@/types/common'
import { useNotificationStore } from '@/stores/notification'

const notifStore = useNotificationStore()

const loading = ref(false)
const page = ref<Page<RepairReportVO>>({ records: [], total: 0, size: 10, current: 1 })
const activeStatus = ref<RepairStatus | ''>('')
const query = ref<{ page: number; size: number }>({ page: 1, size: 10 })

// 处理对话框：resolve / reject 共用，靠 mode 区分
const handleVisible = ref(false)
const handleMode = ref<'resolve' | 'reject'>('resolve')
const handleTarget = ref<RepairReportVO | null>(null)
const handleNote = ref('')
const handling = ref(false)

const statusTabs: { label: string; value: RepairStatus | '' }[] = [
  { label: '全部', value: '' },
  { label: '待受理', value: 'PENDING' },
  { label: '处理中', value: 'PROCESSING' },
  { label: '已解决', value: 'RESOLVED' },
  { label: '已驳回', value: 'REJECTED' },
]

async function load() {
  loading.value = true
  try {
    page.value = await listRepairs(activeStatus.value, query.value.page, query.value.size)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function onTabChange() {
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

async function onTake(row: RepairReportVO) {
  try {
    await takeRepair(row.id)
    ElMessage.success('已受理')
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
      ElMessage.success('已标记解决')
    } else {
      await rejectRepair(handleTarget.value.id, handleNote.value.trim())
      ElMessage.success('已驳回')
    }
    handleVisible.value = false
    await load()
    notifStore.loadUnread()
  } catch {
    // 拦截器已提示
  } finally {
    handling.value = false
  }
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
const handleTitle = computed(() => (handleMode.value === 'resolve' ? '解决报修' : '驳回报修'))

onMounted(load)
</script>

<template>
  <div class="radmin">
    <div class="radmin__head">
      <h1 class="radmin__title">报修处理</h1>
      <p class="radmin__subtitle">受理并处理本实验室的设备报修工单</p>
    </div>

    <div class="lab-card radmin__tabs">
      <el-radio-group v-model="activeStatus" @change="onTabChange">
        <el-radio-button v-for="t in statusTabs" :key="t.value" :value="t.value">
          {{ t.label }}
        </el-radio-button>
      </el-radio-group>
    </div>

    <div class="lab-card radmin__table">
      <el-table v-loading="loading" :data="page.records" stripe row-key="id">
        <el-table-column prop="id" label="编号" width="80" />
        <el-table-column prop="deviceName" label="设备" min-width="140" show-overflow-tooltip />
        <el-table-column prop="reporterName" label="报修人" min-width="110" show-overflow-tooltip />
        <el-table-column prop="title" label="标题" min-width="150" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusMeta(row.status).type" effect="light" round>
              {{ statusMeta(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="resolutionNote" label="处理说明" min-width="140" show-overflow-tooltip />
        <el-table-column label="提交时间" width="160">
          <template #default="{ row }">{{ fmt(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'PENDING'"
              v-permission="'repair:handle'"
              link
              type="primary"
              @click="onTake(row)"
            >
              受理
            </el-button>
            <el-button
              v-if="row.status === 'PROCESSING'"
              v-permission="'repair:handle'"
              link
              type="success"
              @click="openResolve(row)"
            >
              解决
            </el-button>
            <el-button
              v-if="row.status === 'PENDING'"
              v-permission="'repair:handle'"
              link
              type="danger"
              @click="openReject(row)"
            >
              驳回
            </el-button>
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
          :layout="`total, sizes, prev, pager, next`"
          :total-text="totalLabel"
          background
          @current-change="onPageChange"
          @size-change="onSizeChange"
        />
      </div>
    </div>

    <el-dialog v-model="handleVisible" :title="handleTitle" width="440px">
      <el-form>
        <el-form-item :label="handleMode === 'resolve' ? '处理说明' : '驳回理由'" required>
          <el-input
            v-model="handleNote"
            type="textarea"
            :rows="3"
            :placeholder="handleMode === 'resolve' ? '说明处理方式与结果（必填）' : '说明驳回原因（必填）'"
            maxlength="200"
            show-word-limit
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="handleVisible = false">取消</el-button>
        <el-button type="primary" :loading="handling" @click="onHandleConfirm">
          确认
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.radmin {
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

  &__tabs {
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
