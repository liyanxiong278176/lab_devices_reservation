<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { dashboardOverview, type DashboardOverviewVO } from '@/api/dashboard'
import StatCard from '@/components/charts/StatCard.vue'
import PieWidget from '@/components/charts/PieWidget.vue'
import BarWidget from '@/components/charts/BarWidget.vue'
import LineWidget from '@/components/charts/LineWidget.vue'
import HeatmapWidget from '@/components/charts/HeatmapWidget.vue'
import {
  DEVICE_STATUS_ORDER,
  DEVICE_STATUS_LABELS,
  DEVICE_STATUS_COLORS,
  REPAIR_STATUS_ORDER,
  REPAIR_STATUS_LABELS,
  REPAIR_STATUS_COLORS,
  toStatusData,
} from '@/components/charts/palette'

const loading = ref(false)
const data = ref<DashboardOverviewVO | null>(null)

const groupBy = ref<'device' | 'category'>('device')
const days = ref(30)

async function load() {
  loading.value = true
  try {
    data.value = await dashboardOverview({ groupBy: groupBy.value, days: days.value })
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function onRefresh() {
  load()
  ElMessage.success('已刷新')
}

// ---- 视图层数据转换 ----
const cards = computed(() => data.value?.cards)
const deviceStatusData = computed(() =>
  toStatusData(
    data.value?.deviceStatus,
    DEVICE_STATUS_ORDER,
    DEVICE_STATUS_LABELS,
    DEVICE_STATUS_COLORS,
  ),
)
const utilizationData = computed(
  () =>
    data.value?.utilization.map((u) => ({
      name: u.label,
      // 利用率按百分比展示（数据已乘 100 取整）
      value: Math.round(u.utilizationRate * 100),
    })) ?? [],
)
const categoryDistData = computed(
  () =>
    data.value?.categoryDist.map((c) => ({
      name: c.categoryName,
      value: c.deviceCount,
    })) ?? [],
)
const repairStatsData = computed(() =>
  toStatusData(
    data.value?.repairStats,
    REPAIR_STATUS_ORDER,
    REPAIR_STATUS_LABELS,
    REPAIR_STATUS_COLORS,
  ),
)

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="dash">
    <div class="dash__head">
      <div>
        <h1 class="dash__title">驾驶舱</h1>
        <p class="dash__subtitle">实验室运营富指标概览（按角色范围自动过滤）</p>
      </div>
      <div class="dash__toolbar lab-card">
        <span class="dash__tool-label">聚合</span>
        <el-radio-group v-model="groupBy" size="small" @change="load">
          <el-radio-button value="device">按设备</el-radio-button>
          <el-radio-button value="category">按分类</el-radio-button>
        </el-radio-group>
        <span class="dash__tool-label">周期</span>
        <el-radio-group v-model.number="days" size="small" @change="load">
          <el-radio-button :value="7">近 7 天</el-radio-button>
          <el-radio-button :value="30">近 30 天</el-radio-button>
        </el-radio-group>
        <el-button :icon="Refresh" size="small" @click="onRefresh">刷新</el-button>
      </div>
    </div>

    <!-- 数字卡片 -->
    <el-row :gutter="16" class="dash__row">
      <el-col :xs="24" :sm="8">
        <StatCard label="今日预约" :value="cards?.todayReservations ?? 0" />
      </el-col>
      <el-col :xs="24" :sm="8">
        <StatCard label="待审批" :value="cards?.pendingApprovals ?? 0" />
      </el-col>
      <el-col :xs="24" :sm="8">
        <StatCard label="近 7 天违规" :value="cards?.weeklyViolations ?? 0" />
      </el-col>
    </el-row>

    <!-- 趋势 + 设备状态 -->
    <el-row :gutter="16" class="dash__row">
      <el-col :xs="24" :lg="16">
        <LineWidget title="近 30 天预约趋势" :data="data?.trend30d ?? []" />
      </el-col>
      <el-col :xs="24" :lg="8">
        <PieWidget title="设备状态分布" :data="deviceStatusData" />
      </el-col>
    </el-row>

    <!-- 利用率 / 分类 / 报修 -->
    <el-row :gutter="16" class="dash__row">
      <el-col :xs="24" :md="12" :lg="8">
        <BarWidget
          title="利用率（%）"
          :data="utilizationData"
          :percent="true"
          :horizontal="true"
        />
      </el-col>
      <el-col :xs="24" :md="12" :lg="8">
        <PieWidget title="设备分类分布" :data="categoryDistData" />
      </el-col>
      <el-col :xs="24" :md="24" :lg="8">
        <BarWidget title="报修状态分布" :data="repairStatsData" />
      </el-col>
    </el-row>

    <!-- 热力图 -->
    <el-row :gutter="16" class="dash__row">
      <el-col :span="24">
        <HeatmapWidget title="预约密度热力图（星期 × 时段）" :data="data?.heatmap ?? []" />
      </el-col>
    </el-row>
  </div>
</template>

<style scoped lang="scss">
.dash {
  &__head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 16px;
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

  &__toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 16px;
    flex-wrap: wrap;
  }

  &__tool-label {
    font-size: 13px;
    color: var(--el-text-color-secondary);
  }

  &__row {
    margin-bottom: 16px;

    // el-col 之间在窄屏堆叠时留出垂直间距
    .el-col {
      margin-bottom: 16px;
    }
  }

  // 窄屏下 toolbar 折行后与标题对齐
  @media (max-width: 768px) {
    &__head {
      flex-direction: column;
    }
  }
}
</style>
