<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import { cancelReservation, myReservations } from '@/api/reservation'
import type { ReservationQuery, ReservationStatus, ReservationVO } from '@/types/reservation'
import type { Page } from '@/types/common'
import { reservationStatusTag } from '@/composables/useDeviceStatus'

const router = useRouter()

const activeStatus = ref<ReservationStatus | ''>('')
const query = ref<ReservationQuery>({ page: 1, size: 10 })
const loading = ref(false)
const page = ref<Page<ReservationVO>>({ records: [], total: 0, size: 10, current: 1 })

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

async function load() {
  loading.value = true
  try {
    page.value = await myReservations({ ...query.value, status: activeStatus.value })
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

/** 仅 PENDING / APPROVED 且未开始可取消。 */
function canCancel(row: ReservationVO): boolean {
  return row.status === 'PENDING' || row.status === 'APPROVED'
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
    load()
  } catch {
    // 拦截器已提示
  }
}

function goDetail(row: ReservationVO) {
  router.push({ name: 'reservation-detail', params: { id: row.id } })
}

function fmt(t: string): string {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'
}

const totalLabel = computed(() => `共 ${page.value.total} 条`)

onMounted(load)
</script>

<template>
  <div class="mine">
    <div class="mine__head">
      <h1 class="mine__title">我的预约</h1>
      <p class="mine__subtitle">查看与管理你的设备预约记录</p>
    </div>

    <!-- 状态 tabs -->
    <div class="lab-card mine__tabs">
      <el-radio-group v-model="activeStatus" @change="onTabChange">
        <el-radio-button v-for="t in tabs" :key="t.value" :value="t.value">
          {{ t.label }}
        </el-radio-button>
      </el-radio-group>
    </div>

    <!-- 列表 -->
    <div class="lab-card mine__table">
      <el-table v-loading="loading" :data="page.records" stripe row-key="id">
        <el-table-column prop="id" label="编号" width="80" />
        <el-table-column label="起止时间" min-width="240">
          <template #default="{ row }">
            <span class="mine__time">{{ fmt(row.startTime) }} → {{ fmt(row.endTime) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="deviceId" label="设备ID" width="90" align="center" />
        <el-table-column prop="purpose" label="用途" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="reservationStatusTag(row.status).type" effect="light" round>
              {{ reservationStatusTag(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="goDetail(row)">详情</el-button>
            <el-button
              v-if="canCancel(row)"
              link
              type="danger"
              @click="onCancel(row)"
            >
              取消
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <span class="mine__empty">暂无预约记录</span>
        </template>
      </el-table>

      <div class="mine__pager">
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
.mine {
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
