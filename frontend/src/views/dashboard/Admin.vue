<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { dashboardOverview, type DashboardOverviewVO } from '@/api/dashboard'
import StatCard from '@/components/ui/StatCard.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import GlowCard from '@/components/ui/GlowCard.vue'
import PieWidget from '@/components/charts/PieWidget.vue'
import BarWidget from '@/components/charts/BarWidget.vue'
import LineWidget from '@/components/charts/LineWidget.vue'
import HeatmapWidget from '@/components/charts/HeatmapWidget.vue'
import { useStagger } from '@/composables/useStagger'
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

// 图表网格错峰入场容器(spec §6.2):首次进入视口时,内部 [data-stagger] 图表卡
// 按 60ms 错峰 fade+rise;reduced-motion 由 useStagger 内部短路(守铁律 §6.1)。
const chartGridRef = ref<HTMLElement | null>(null)
useStagger(chartGridRef, { delay: 60 })

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
    <div class="dashboard-aura" aria-hidden="true" />
    <PageHeader title="驾驶舱" subtitle="实验室运营富指标概览（按角色范围自动过滤）">
      <template #actions>
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
      </template>
    </PageHeader>

    <!-- 数字卡片 -->
    <el-row :gutter="16" class="dash__row">
      <el-col :xs="24" :sm="8">
        <StatCard label="今日预约" :value="cards?.todayReservations ?? 0" icon="Calendar" />
      </el-col>
      <el-col :xs="24" :sm="8">
        <StatCard label="待审批" :value="cards?.pendingApprovals ?? 0" icon="Clock" />
      </el-col>
      <el-col :xs="24" :sm="8">
        <StatCard label="近 7 天违规" :value="cards?.weeklyViolations ?? 0" icon="Warning" />
      </el-col>
    </el-row>

    <!-- 图表网格:GlowCard 包裹 + 错峰入场(spec §7 dashboard) -->
    <div class="chart-grid" ref="chartGridRef">
      <!-- 趋势 + 设备状态 -->
      <el-row :gutter="16" class="dash__row">
        <el-col :xs="24" :lg="16">
          <div class="chart-cell" data-stagger>
            <GlowCard>
              <LineWidget title="近 30 天预约趋势" :data="data?.trend30d ?? []" />
            </GlowCard>
          </div>
        </el-col>
        <el-col :xs="24" :lg="8">
          <div class="chart-cell" data-stagger>
            <GlowCard>
              <PieWidget title="设备状态分布" :data="deviceStatusData" />
            </GlowCard>
          </div>
        </el-col>
      </el-row>

      <!-- 利用率 / 分类 / 报修 -->
      <el-row :gutter="16" class="dash__row">
        <el-col :xs="24" :md="12" :lg="8">
          <div class="chart-cell" data-stagger>
            <GlowCard>
              <BarWidget
                title="利用率（%）"
                :data="utilizationData"
                :percent="true"
                :horizontal="true"
              />
            </GlowCard>
          </div>
        </el-col>
        <el-col :xs="24" :md="12" :lg="8">
          <div class="chart-cell" data-stagger>
            <GlowCard>
              <PieWidget title="设备分类分布" :data="categoryDistData" />
            </GlowCard>
          </div>
        </el-col>
        <el-col :xs="24" :md="24" :lg="8">
          <div class="chart-cell" data-stagger>
            <GlowCard>
              <BarWidget title="报修状态分布" :data="repairStatsData" />
            </GlowCard>
          </div>
        </el-col>
      </el-row>

      <!-- 热力图 -->
      <el-row :gutter="16" class="dash__row">
        <el-col :span="24">
          <div class="chart-cell" data-stagger>
            <GlowCard>
              <HeatmapWidget title="预约密度热力图（星期 × 时段）" :data="data?.heatmap ?? []" />
            </GlowCard>
          </div>
        </el-col>
      </el-row>
    </div>
  </div>
</template>

<style scoped lang="scss">
.dash {
  position: relative;

  // PageHeader 替代原 .dash__head(标题走 Space Grotesk,自带底 hairline);
  // toolbar 进 #actions slot,窄屏由 PageHeader 的 flex-wrap 自动折行
  .page-header {
    margin-bottom: 24px;
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
}

// 图表网格(错峰入场容器)
.chart-grid {
  // 仅作 useStagger 容器(ref);内部 [data-stagger] 由 _motion.scss 兜底初始态。
}

// 图表单元:撑满 el-col 高度(el-row 默认 align-items:stretch),让同行 GlowCard 等高
.chart-cell {
  height: 100%;
}

// hover 时抬升该 el-col 的 stacking(el-col 默认无 stacking context,DOM 后续的邻居
// 会盖住当前卡的 cyan glow)。被悬停列置顶,辉光不被同行相邻卡遮挡。
.chart-grid :deep(.el-col) {
  position: relative;
  &:hover {
    z-index: 1;
  }
}

// GlowCard 包裹图表 widget:内层 .lab-card.chart-card 退化为透明(避免双框/双底),
// 卡片感由 GlowCard 统一提供(bg-surface + hairline + hover glow + padding:20)。
.chart-cell :deep(.glow-card) {
  height: 100%;
}

.chart-cell :deep(.lab-card.chart-card) {
  background: transparent;
  border: 0;
  box-shadow: none;
  border-radius: 0;
  padding: 0; // GlowCard 已提供 padding:20
}

// 内容(标题/toolbar/卡片行/图表)压在局部 aura 之上
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
