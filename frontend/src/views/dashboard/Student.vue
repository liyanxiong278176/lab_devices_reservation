<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { dashboardMe, type DashboardMeVO } from '@/api/dashboard'
import StatCard from '@/components/ui/StatCard.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
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
    <div class="dashboard-aura" aria-hidden="true" />
    <PageHeader title="我的驾驶舱" subtitle="个人预约与报修概览" />

    <!-- 数字卡片 -->
    <el-row :gutter="16" class="dash__row">
      <el-col :xs="24" :sm="12">
        <StatCard label="未读通知" :value="data?.unreadCount ?? 0" icon="Bell" />
      </el-col>
      <el-col :xs="24" :sm="12">
        <StatCard label="我的报修单" :value="data?.myRepairCount ?? 0" icon="Tools" />
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
  position: relative;

  // PageHeader 替代原 .dash__head(标题走 Space Grotesk,自带底 hairline)
  .page-header {
    margin-bottom: 24px;
  }

  &__row {
    margin-bottom: 16px;

    .el-col {
      margin-bottom: 16px;
    }
  }
}

// 内容(标题/卡片行/图表)压在局部 aura 之上
.dash > :not(.dashboard-aura) {
  position: relative;
  z-index: 1;
}

// 局部 aurora hero 带(spec §7 dashboard 氛围):仅在 dashboard 顶部一条,
// 比 App.vue 全局 .aurora-bg 稍强(alpha 0.07-0.09 vs 全局 0.04-0.05),给驾驶舱
// 独立氛围感;absolute + pointer-events:none,不抢布局/不挡交互。
.dashboard-aura {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 240px;
  pointer-events: none;
  z-index: 0;
  background:
    radial-gradient(ellipse 60% 100% at 20% 0%, rgba(64, 224, 208, 0.09), transparent 70%),
    radial-gradient(ellipse 50% 100% at 80% 10%, rgba(34, 211, 238, 0.07), transparent 65%);
}
</style>
