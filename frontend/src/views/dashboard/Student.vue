<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { dashboardMe, type DashboardMeVO } from '@/api/dashboard'
import StatCard from '@/components/charts/StatCard.vue'
import PieWidget from '@/components/charts/PieWidget.vue'
import BarWidget from '@/components/charts/BarWidget.vue'
import LineWidget from '@/components/charts/LineWidget.vue'
import {
  RESERVATION_STATUS_ORDER,
  RESERVATION_STATUS_LABELS,
  RESERVATION_STATUS_COLORS,
  toStatusData,
} from '@/components/charts/palette'

const loading = ref(false)
const data = ref<DashboardMeVO | null>(null)

async function load() {
  loading.value = true
  try {
    data.value = await dashboardMe()
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

const statusData = computed(() =>
  toStatusData(
    data.value?.myReservationsByStatus,
    RESERVATION_STATUS_ORDER,
    RESERVATION_STATUS_LABELS,
    RESERVATION_STATUS_COLORS,
  ),
)
const categoryData = computed(
  () =>
    data.value?.myCategoryDist.map((c) => ({ name: c.categoryName, value: c.count })) ?? [],
)

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="dash">
    <div class="dash__head">
      <h1 class="dash__title">我的驾驶舱</h1>
      <p class="dash__subtitle">个人预约与报修概览</p>
    </div>

    <!-- 数字卡片 -->
    <el-row :gutter="16" class="dash__row">
      <el-col :xs="24" :sm="12">
        <StatCard label="未读通知" :value="data?.unreadCount ?? 0" />
      </el-col>
      <el-col :xs="24" :sm="12">
        <StatCard label="我的报修单" :value="data?.myRepairCount ?? 0" />
      </el-col>
    </el-row>

    <!-- 趋势 + 状态分布 -->
    <el-row :gutter="16" class="dash__row">
      <el-col :xs="24" :lg="16">
        <LineWidget title="近 30 天我的预约趋势" :data="data?.myTrend30d ?? []" />
      </el-col>
      <el-col :xs="24" :lg="8">
        <PieWidget title="我的预约状态分布" :data="statusData" />
      </el-col>
    </el-row>

    <!-- 常用品类 -->
    <el-row :gutter="16" class="dash__row">
      <el-col :span="24">
        <BarWidget title="我常用品类" :data="categoryData" :horizontal="true" />
      </el-col>
    </el-row>
  </div>
</template>

<style scoped lang="scss">
.dash {
  &__head {
    margin-bottom: 24px;
  }

  &__title {
    margin: 0;
    font-size: 28px;
    font-weight: 600;
    line-height: 1.2;
    letter-spacing: -0.5px;
    color: var(--el-text-color-primary);
  }

  &__subtitle {
    margin: 8px 0 0;
    font-size: 14px;
    color: var(--el-text-color-secondary);
  }

  &__row {
    margin-bottom: 16px;

    .el-col {
      margin-bottom: 16px;
    }
  }
}
</style>
