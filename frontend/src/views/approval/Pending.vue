<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import { approve, batchApprove, pendingApprovals, reject } from '@/api/approval'
import type { ApprovalItemVO } from '@/types/approval'
import type { Page } from '@/types/common'
import { useNotificationStore } from '@/stores/notification'

const notifStore = useNotificationStore()

const loading = ref(false)
const page = ref<Page<ApprovalItemVO>>({ records: [], total: 0, size: 10, current: 1 })
const query = ref<{ page: number; size: number }>({ page: 1, size: 10 })

// 多选 + 批量通过
const selection = ref<ApprovalItemVO[]>([])

// 拒绝对话框
const rejectVisible = ref(false)
const rejectTarget = ref<ApprovalItemVO | null>(null)
const rejectReason = ref('')
const rejecting = ref(false)

async function load() {
  loading.value = true
  try {
    page.value = await pendingApprovals(query.value.page, query.value.size)
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

function onSelectionChange(rows: ApprovalItemVO[]) {
  selection.value = rows
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
  rejectTarget.value = row
  rejectReason.value = ''
  rejectVisible.value = true
}

async function onRejectConfirm() {
  if (!rejectTarget.value) return
  if (!rejectReason.value.trim()) {
    ElMessage.warning('请填写拒绝理由')
    return
  }
  rejecting.value = true
  try {
    await reject(rejectTarget.value.id, rejectReason.value.trim())
    ElMessage.success('已拒绝')
    rejectVisible.value = false
    await load()
    notifStore.loadUnread()
  } catch {
    // 拦截器已提示
  } finally {
    rejecting.value = false
  }
}

async function onBatchApprove() {
  if (selection.value.length === 0) {
    ElMessage.warning('请先勾选要批量通过的预约')
    return
  }
  try {
    await batchApprove(selection.value.map((r) => r.id))
    ElMessage.success(`已批量通过 ${selection.value.length} 条`)
    await load()
    notifStore.loadUnread()
  } catch {
    // 拦截器已提示
  }
}

function fmt(t?: string): string {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'
}

const totalLabel = computed(() => `共 ${page.value.total} 条`)

onMounted(load)
</script>

<template>
  <div class="approval">
    <div class="approval__head">
      <h1 class="approval__title">待审批</h1>
      <p class="approval__subtitle">审核本实验室待审批的设备预约</p>
    </div>

    <div class="lab-card approval__toolbar">
      <el-button
        v-permission="'device:approve'"
        type="primary"
        :disabled="selection.length === 0"
        @click="onBatchApprove"
      >
        批量通过 ({{ selection.length }})
      </el-button>
    </div>

    <div class="lab-card approval__table">
      <el-table
        v-loading="loading"
        :data="page.records"
        stripe
        row-key="id"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="48" />
        <el-table-column prop="id" label="编号" width="80" />
        <el-table-column prop="deviceName" label="设备" min-width="140" show-overflow-tooltip />
        <el-table-column label="申请人" min-width="120">
          <template #default="{ row }">
            <span>{{ row.realName || row.username }}</span>
          </template>
        </el-table-column>
        <el-table-column label="时段" min-width="240">
          <template #default="{ row }">
            <span class="approval__time">{{ fmt(row.startTime) }} → {{ fmt(row.endTime) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="purpose" label="用途" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button v-permission="'device:approve'" link type="primary" @click="onApprove(row)">
              通过
            </el-button>
            <el-button v-permission="'device:approve'" link type="danger" @click="openReject(row)">
              拒绝
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <span class="approval__empty">暂无待审批预约</span>
        </template>
      </el-table>

      <div class="approval__pager">
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

    <el-dialog v-model="rejectVisible" title="拒绝预约" width="440px">
      <el-form>
        <el-form-item label="拒绝理由" required>
          <el-input
            v-model="rejectReason"
            type="textarea"
            :rows="3"
            placeholder="请填写拒绝理由（必填）"
            maxlength="200"
            show-word-limit
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rejectVisible = false">取消</el-button>
        <el-button type="primary" :loading="rejecting" @click="onRejectConfirm">
          确认拒绝
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.approval {
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

  &__toolbar {
    padding: 16px 20px;
    margin-bottom: 16px;
  }

  &__table {
    padding: 8px;
  }

  &__time {
    font-variant-numeric: tabular-nums;
    font-size: 13px;
    color: var(--el-text-color-regular);
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
