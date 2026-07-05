<script setup lang="ts">
// 设备浏览页(R4.1 重构):SegmentedControl 状态筛选 + 关键词搜索 + GlowCard 网格 + 错峰入场。
// 数据/筛选/分页/路由逻辑零改——仅换展示层 + 接 R1 ui 组件。
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { searchDevices } from '@/api/device'
import type { DeviceQuery, DeviceStatus, DeviceVO } from '@/types/device'
import type { Page } from '@/types/common'
import { useStagger } from '@/composables/useStagger'
import PageHeader from '@/components/ui/PageHeader.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import GlowCard from '@/components/ui/GlowCard.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import TextButton from '@/components/ui/TextButton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const router = useRouter()

const query = reactive<DeviceQuery>({
  page: 1,
  // 网格视图默认一页 24 卡(原表格 10 → 24),page-sizes 同步上调,270 设备服务端分页,
  // 客户端最多渲染 96 卡,性能可控(spec §6.1 铁律)。
  size: 24,
  keyword: '',
  status: '',
  minPrice: undefined,
  maxPrice: undefined,
})

const loading = ref(false)
const page = ref<Page<DeviceVO>>({ records: [], total: 0, size: 24, current: 1 })

// SegmentedControl 选项:status ''=全部
const statusOptions: { label: string; value: DeviceStatus | '' }[] = [
  { label: '全部', value: '' },
  { label: '空闲', value: 'IDLE' },
  { label: '使用中', value: 'IN_USE' },
  { label: '维护中', value: 'MAINTENANCE' },
]

// 网格错峰容器(spec §6.2 / 同 R3 dashboard):首次进入视口时,内部 [data-stagger]
// 卡片按 60ms 错峰 fade+rise;reduced-motion 由 useStagger 内部短路。
const gridRef = ref<HTMLElement | null>(null)
useStagger(gridRef, { delay: 60 })

// 首屏错峰交给 useStagger 的 IntersectionObserver;后续筛选/翻页后 observer 已 stop,
// 新渲染的 [data-stagger] 卡片缺 stagger-in 会卡在初始态,这里立即补显(不错峰)。
let firstLoad = true

const subtitle = computed(() => `共 ${page.value.total} 台设备`)

async function load() {
  loading.value = true
  try {
    page.value = await searchDevices(query)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
  if (firstLoad) {
    firstLoad = false
    return
  }
  await nextTick()
  gridRef.value
    ?.querySelectorAll<HTMLElement>('[data-stagger]:not(.stagger-in)')
    .forEach((el) => el.classList.add('stagger-in'))
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

// SegmentedControl 切换:写 status 后立即查询(等价原 el-select @change)
function onStatusChange(v: string | number) {
  query.status = (v as DeviceStatus | '') ?? ''
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
    <PageHeader title="设备浏览" :subtitle="subtitle" />

    <!-- 筛选区:状态 SegmentedControl + 关键词 + 价格区间 + 重置 -->
    <div class="device-page__filter">
      <SegmentedControl
        :model-value="query.status ?? ''"
        :options="statusOptions"
        size="sm"
        @update:model-value="onStatusChange"
      />

      <div class="device-page__filter-right">
        <el-input
          v-model="query.keyword"
          class="device-page__search"
          placeholder="搜索设备名称 / 型号"
          clearable
          :prefix-icon="Search"
          @keyup.enter="onSearch"
          @clear="onSearch"
        />
        <el-input-number
          v-model="query.minPrice"
          class="device-page__price"
          :min="0"
          placeholder="最低"
          controls-position="right"
        />
        <span class="device-page__dash">—</span>
        <el-input-number
          v-model="query.maxPrice"
          class="device-page__price"
          :min="0"
          placeholder="最高"
          controls-position="right"
        />
        <TextButton @click="onReset">重置</TextButton>
      </div>
    </div>

    <!-- 设备网格 -->
    <div
      v-loading="loading"
      class="device-grid"
      ref="gridRef"
    >
      <div
        v-for="row in page.records"
        :key="row.id"
        class="device-cell"
        data-stagger
      >
        <GlowCard as="article" class="device-card" @click="goDetail(row)">
          <div class="device-card__top">
            <StatusDot :status="row.status" :label="true" />
            <span class="device-card__price">
              ¥{{ row.pricePerHour ?? '—' }}<small>/时</small>
            </span>
          </div>

          <h3 class="device-card__title">
            <span class="device-card__brand">{{ row.brand || '未填品牌' }}</span>
            <span class="device-card__model">{{ row.model || row.name }}</span>
          </h3>

          <p class="device-card__specs">{{ row.specs || '暂无规格信息' }}</p>

          <div class="device-card__foot">
            <span class="device-card__meta">
              {{ [row.labName, row.categoryName].filter(Boolean).join(' · ') || '未分配' }}
            </span>
            <TextButton size="small" @click.stop="goReserve(row)">预约</TextButton>
          </div>
        </GlowCard>
      </div>

      <!-- 空态 -->
      <div v-if="!loading && page.records.length === 0" class="device-grid__empty">
        <EmptyState
          icon="Search"
          title="未找到匹配的设备"
          description="试试调整状态筛选或清空关键词后重试。"
        />
      </div>
    </div>

    <!-- 分页 -->
    <div v-if="page.records.length > 0" class="device-page__pager">
      <el-pagination
        :current-page="page.current"
        :page-size="page.size"
        :total="page.total"
        :page-sizes="[24, 48, 96]"
        layout="total, sizes, prev, pager, next"
        background
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>
  </div>
</template>

<style scoped lang="scss">
.device-page {
  display: flex;
  flex-direction: column;
  gap: 24px;

  // ---- 筛选区 -------------------------------------------------------------
  &__filter {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
    padding: 14px 18px;
    background: var(--bg-sunken);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-card);
  }

  &__filter-right {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  &__search {
    width: 240px;
  }

  &__price {
    width: 110px;
  }

  &__dash {
    color: var(--text-tertiary);
  }

  &__pager {
    display: flex;
    justify-content: flex-end;
    padding-top: 4px;
  }
}

// ---- 设备网格 ---------------------------------------------------------------
// auto-fill 自适应:minmax(280px, 1fr) → 窄屏 1 列、宽屏多列,270 设备靠服务端分页
// 控量,客户端最多渲染当前页(24~96 卡),性能可控。
.device-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  min-height: 120px;
  position: relative;

  // 空态跨满整行(grid 自动放第一个子元素到第一格,强制 spanning)
  &__empty {
    grid-column: 1 / -1;
  }
}

// data-stagger 落在 cell 父元素(不落 GlowCard),reveal 的 opacity/transform
// 与 GlowCard 的 hover transform 分离,避免特异性压住 hover(spec §6.1 / R3 模式)。
.device-cell {
  display: block;
  cursor: pointer;
}

// ---- 设备卡 -----------------------------------------------------------------
.device-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;

  &__top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  &__price {
    font-family: var(--font-mono);
    font-size: 15px;
    font-weight: 600;
    color: var(--accent);
    white-space: nowrap;

    small {
      margin-left: 2px;
      font-family: var(--font-sans);
      font-size: 12px;
      font-weight: 400;
      color: var(--text-tertiary);
    }
  }

  &__title {
    margin: 0;
    font-family: var(--font-display);
    font-size: 17px;
    font-weight: 600;
    line-height: 1.3;
    letter-spacing: -0.2px;
    color: var(--text-primary);
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  &__brand {
    font-size: 12px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-tertiary);
  }

  &__model {
    // 型号作为主标题感(品牌降为 eyebrow)
  }

  &__specs {
    margin: 0;
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-secondary);
    // 摘录:限 2 行,超出省略,卡高整齐
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  &__foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-top: auto;
    padding-top: 4px;
    border-top: 1px solid var(--border-subtle);
  }

  &__meta {
    font-size: 12px;
    color: var(--text-tertiary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}
</style>
