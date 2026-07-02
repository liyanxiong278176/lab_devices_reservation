<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { searchDevices } from '@/api/device'
import type { DeviceQuery, DeviceStatus, DeviceVO } from '@/types/device'
import type { Page } from '@/types/common'
import { deviceStatusTag } from '@/composables/useDeviceStatus'

const router = useRouter()

const query = reactive<DeviceQuery>({
  page: 1,
  size: 10,
  keyword: '',
  status: '',
  minPrice: undefined,
  maxPrice: undefined,
})

const loading = ref(false)
const page = ref<Page<DeviceVO>>({ records: [], total: 0, size: 10, current: 1 })

const statusOptions: { label: string; value: DeviceStatus | '' }[] = [
  { label: '全部状态', value: '' },
  { label: '空闲', value: 'IDLE' },
  { label: '使用中', value: 'IN_USE' },
  { label: '维护中', value: 'MAINTENANCE' },
]

async function load() {
  loading.value = true
  try {
    page.value = await searchDevices(query)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function onSearch() {
  query.page = 1
  load()
}

function onReset() {
  query.keyword = ''
  query.status = ''
  query.minPrice = undefined
  query.maxPrice = undefined
  query.categoryId = undefined
  query.labId = undefined
  onSearch()
}

function onPageChange(p: number) {
  query.page = p
  load()
}

function onSizeChange(s: number) {
  query.size = s
  query.page = 1
  load()
}

function goDetail(row: DeviceVO) {
  router.push({ name: 'device-detail', params: { id: row.id } })
}

function goReserve(row: DeviceVO) {
  router.push({ name: 'reservation-create', query: { deviceId: String(row.id) } })
}

onMounted(load)
</script>

<template>
  <div class="device-page">
    <div class="device-page__head">
      <h1 class="device-page__title">设备</h1>
      <p class="device-page__subtitle">浏览实验室设备并预约使用时段</p>
    </div>

    <!-- 搜索栏 -->
    <div class="lab-card device-page__filter">
      <el-form :inline="true" :model="query" @submit.prevent>
        <el-form-item label="关键词">
          <el-input
            v-model="query.keyword"
            placeholder="设备名称"
            clearable
            style="width: 200px"
            @keyup.enter="onSearch"
          />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="query.status" placeholder="全部" style="width: 140px">
            <el-option
              v-for="opt in statusOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="价格区间">
          <el-input-number
            v-model="query.minPrice"
            :min="0"
            placeholder="最低"
            controls-position="right"
            style="width: 110px"
          />
          <span class="device-page__dash">—</span>
          <el-input-number
            v-model="query.maxPrice"
            :min="0"
            placeholder="最高"
            controls-position="right"
            style="width: 110px"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="onSearch">查询</el-button>
          <el-button @click="onReset">重置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 列表 -->
    <div class="lab-card device-page__table">
      <el-table v-loading="loading" :data="page.records" stripe row-key="id">
        <el-table-column prop="name" label="设备名称" min-width="140" />
        <el-table-column prop="brand" label="品牌" min-width="100" />
        <el-table-column prop="model" label="型号" min-width="100" />
        <el-table-column prop="labName" label="实验室" min-width="110" />
        <el-table-column prop="categoryName" label="分类" min-width="100" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="deviceStatusTag(row.status)" effect="light" round>
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="单价/时" width="110" align="right">
          <template #default="{ row }">
            <span class="device-page__price">¥{{ row.pricePerHour ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="goDetail(row)">查看</el-button>
            <el-button link type="primary" @click="goReserve(row)">预约</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <span class="device-page__empty">暂无设备</span>
        </template>
      </el-table>

      <div class="device-page__pager">
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
  </div>
</template>

<style scoped lang="scss">
.device-page {
  &__head {
    margin-bottom: 24px;
  }

  &__title {
    margin: 0;
    font-size: 28px; // display-sm
    font-weight: 600;
    line-height: 1.2;
    letter-spacing: -0.5px;
    color: var(--el-text-color-primary); // #111111
  }

  &__subtitle {
    margin: 8px 0 0;
    font-size: 14px;
    color: var(--el-text-color-secondary); // #6b7280
  }

  &__filter {
    padding: 20px 24px;
    margin-bottom: 16px;

    :deep(.el-form-item) {
      margin-bottom: 0;
    }
  }

  &__dash {
    margin: 0 8px;
    color: var(--el-text-color-secondary);
  }

  &__table {
    padding: 8px;
  }

  &__price {
    font-variant-numeric: tabular-nums;
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
