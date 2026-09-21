<script setup lang="ts">
// 设备浏览页(R4.1 重构):SegmentedControl 状态筛选 + 关键词搜索 + GlowCard 网格 + 错峰入场。
// 数据/筛选/分页/路由逻辑零改——仅换展示层 + 接 R1 ui 组件。
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Cpu, Search } from '@element-plus/icons-vue'
import { getDevice, searchDevices } from '@/api/device'
import type { DeviceQuery, DeviceStatus, DeviceVO } from '@/types/device'
import type { Page } from '@/types/common'
import { useStagger } from '@/composables/useStagger'
import { useCursorPageChain } from '@/composables/useCursorPageChain'
import PageHeader from '@/components/ui/PageHeader.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import GlowCard from '@/components/ui/GlowCard.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import Tag from '@/components/ui/Tag.vue'
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
})

const loading = ref(false)
const page = ref<Page<DeviceVO>>({ records: [], total: 0, size: 24, current: 1 })
const detailVisible = ref(false)
const detailLoading = ref(false)
const selectedDevice = ref<DeviceVO | null>(null)
const cursorPager = useCursorPageChain<DeviceVO>((cursor) => searchDevices({
  ...query,
  page: 1,
  cursor,
}))

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
const { reveal } = useStagger(gridRef, { delay: 60 })

const subtitle = computed(() => `共 ${page.value.total} 台设备`)

async function load() {
  loading.value = true
  try {
    page.value = await cursorPager.load(query.page || 1)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
  await nextTick()
  reveal()
}

function onSearch() {
  query.page = 1
  cursorPager.reset()
  void load()
}

function onReset() {
  query.keyword = ''
  query.status = ''
  query.categoryId = undefined
  query.labId = undefined
  cursorPager.reset()
  onSearch()
}

// SegmentedControl 切换:写 status 后立即查询(等价原 el-select @change)
function onStatusChange(v: string | number) {
  query.status = (v as DeviceStatus | '') ?? ''
  onSearch()
}

function onPageChange(p: number) {
  query.page = p
  void load()
}

function onSizeChange(s: number) {
  query.size = s
  query.page = 1
  cursorPager.reset()
  void load()
}

async function openDetail(row: DeviceVO) {
  selectedDevice.value = row
  detailVisible.value = true
  detailLoading.value = true
  try {
    selectedDevice.value = await getDevice(row.id)
  } catch {
    // The list record is already enough to keep the drawer useful if detail loading fails.
  } finally {
    detailLoading.value = false
  }
}

function goFullDetail() {
  if (!selectedDevice.value) return
  router.push({ name: 'device-detail', params: { id: selectedDevice.value.id } })
}

function goReserve(row: DeviceVO) {
  router.push({ name: 'reservation-create', query: { deviceId: String(row.id) } })
}

function reserveSelected() {
  if (selectedDevice.value) goReserve(selectedDevice.value)
}

onMounted(load)
</script>

<template>
  <div class="device-page">
    <PageHeader title="设备浏览" :subtitle="subtitle" />

    <!-- 筛选区:状态 SegmentedControl + 关键词 + 重置 -->
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
        <GlowCard as="article" class="device-card" @click="openDetail(row)">
          <div class="device-card__media">
            <img v-if="row.imageUrl" :src="row.imageUrl" :alt="row.name" />
            <div v-else class="device-card__placeholder" aria-hidden="true">
              <Cpu />
              <span>{{ row.categoryName || 'LAB DEVICE' }}</span>
            </div>
            <span class="device-card__id">设备 {{ String(row.id).padStart(2, '0') }}</span>
          </div>
          <div class="device-card__top">
            <StatusDot :status="row.status" :label="true" />
            <div class="device-card__top-right">
              <Tag :variant="row.needApproval === 1 ? 'warning' : 'success'" size="small">
                {{ row.needApproval === 1 ? '需负责人审批' : '自动确认' }}
              </Tag>
              <span class="device-card__price">最多 {{ row.maxReservationDays ?? '—' }} 天</span>
            </div>
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

    <el-drawer
      v-model="detailVisible"
      :with-header="false"
      direction="rtl"
      size="min(480px, 92vw)"
      class="device-detail-drawer"
    >
      <div v-loading="detailLoading" class="device-drawer">
        <header class="device-drawer__head">
          <div>
            <span class="section-kicker">DEVICE PROFILE / {{ selectedDevice?.id ?? '—' }}</span>
            <h2>{{ selectedDevice?.name || '设备详情' }}</h2>
            <p>{{ [selectedDevice?.brand, selectedDevice?.model].filter(Boolean).join(' · ') || '实验室设备' }}</p>
          </div>
          <button type="button" class="device-drawer__close" aria-label="关闭设备详情" @click="detailVisible = false">×</button>
        </header>

        <div class="device-drawer__media">
          <img v-if="selectedDevice?.imageUrl" :src="selectedDevice.imageUrl" :alt="selectedDevice.name" />
          <div v-else class="device-drawer__placeholder" aria-hidden="true">
            <Cpu />
            <span>{{ selectedDevice?.categoryName || 'LAB DEVICE' }}</span>
          </div>
        </div>

        <div v-if="selectedDevice" class="device-drawer__status-row">
          <StatusDot :status="selectedDevice.status" :label="true" />
          <Tag :variant="selectedDevice.needApproval === 1 ? 'warning' : 'success'" size="small">
            {{ selectedDevice.needApproval === 1 ? '预约需负责人审批' : '预约自动确认' }}
          </Tag>
          <span class="device-drawer__limit">最多 {{ selectedDevice.maxReservationDays ?? '—' }} 天</span>
        </div>

        <section class="device-drawer__section">
          <span class="section-kicker">LOCATION</span>
          <div class="device-drawer__location">
            <strong>{{ selectedDevice?.labName || '未分配实验室' }}</strong>
            <span>{{ selectedDevice?.categoryName || '未分类设备' }}</span>
          </div>
        </section>

        <section class="device-drawer__section">
          <span class="section-kicker">SPECIFICATION</span>
          <p class="device-drawer__description">{{ selectedDevice?.description || selectedDevice?.specs || '暂无规格说明，可进入完整详情查看预约日历。' }}</p>
        </section>

        <footer class="device-drawer__actions">
          <TextButton @click="goFullDetail">查看完整详情</TextButton>
          <el-button type="primary" :disabled="selectedDevice?.status !== 'IDLE'" @click="reserveSelected">预约设备</el-button>
        </footer>
      </div>
    </el-drawer>
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

  &__media {
    position: relative;
    display: grid;
    place-items: center;
    min-height: 148px;
    overflow: hidden;
    background:
      radial-gradient(circle at 20% 20%, color-mix(in srgb, var(--accent) 16%, transparent), transparent 42%),
      linear-gradient(135deg, color-mix(in srgb, var(--bg-sunken) 86%, var(--accent)), var(--bg-sunken));
    border: 1px solid var(--border-subtle);
    border-radius: calc(var(--radius-card) - 5px);

    &::after {
      content: '';
      position: absolute;
      inset: 14px;
      border: 1px solid color-mix(in srgb, var(--accent) 18%, transparent);
      border-radius: 50%;
      transform: rotate(-12deg) scaleX(1.5);
      pointer-events: none;
    }

    img {
      position: relative;
      z-index: 1;
      width: 100%;
      height: 148px;
      object-fit: cover;
      filter: saturate(.78) contrast(.98);
    }
  }

  &__placeholder {
    position: relative;
    z-index: 1;
    display: grid;
    place-items: center;
    gap: 8px;
    color: var(--accent);
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: .12em;

    svg { width: 42px; height: 42px; stroke-width: 1.1; }
  }

  &__id {
    position: absolute;
    right: 11px;
    bottom: 10px;
    z-index: 2;
    padding: 4px 7px;
    color: var(--text-tertiary);
    background: color-mix(in srgb, var(--bg-surface) 76%, transparent);
    border: 1px solid var(--border-subtle);
    border-radius: 999px;
    font-family: var(--font-mono);
    font-size: 9px;
    letter-spacing: .04em;
    backdrop-filter: blur(10px);
  }

  &__top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  &__top-right {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
    min-width: 0;
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

.device-detail-drawer :deep(.el-drawer) {
  background: var(--bg-surface);
  border-left: 1px solid var(--border-default);
}

.device-drawer {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  padding: 28px;
  box-sizing: border-box;
}

.device-drawer__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 22px;
}

.device-drawer__head h2 {
  margin: 9px 0 4px;
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: 28px;
  letter-spacing: -.05em;
}

.device-drawer__head p { margin: 0; color: var(--text-secondary); font-size: 13px; }

.device-drawer__close {
  width: 34px;
  height: 34px;
  color: var(--text-tertiary);
  background: transparent;
  border: 1px solid var(--border-default);
  border-radius: 50%;
  cursor: pointer;
  font-size: 22px;
  line-height: 1;
}

.device-drawer__close:hover { color: var(--accent); border-color: var(--border-accent); }

.device-drawer__media {
  display: grid;
  place-items: center;
  min-height: 210px;
  overflow: hidden;
  background:
    radial-gradient(circle at 25% 20%, color-mix(in srgb, var(--accent) 16%, transparent), transparent 45%),
    var(--bg-sunken);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-card);
}

.device-drawer__media img { width: 100%; height: 210px; object-fit: cover; }
.device-drawer__placeholder { display: grid; place-items: center; gap: 10px; color: var(--accent); font-family: var(--font-mono); font-size: 10px; letter-spacing: .14em; }
.device-drawer__placeholder svg { width: 56px; height: 56px; stroke-width: 1; }

.device-drawer__status-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 18px 0; border-bottom: 1px solid var(--border-subtle); }
.device-drawer__limit { margin-left: auto; color: var(--accent); font-family: var(--font-mono); font-size: 11px; }
.device-drawer__section { display: grid; gap: 10px; padding: 22px 0; border-bottom: 1px solid var(--border-subtle); }
.device-drawer__location { display: grid; gap: 4px; }
.device-drawer__location strong { color: var(--text-primary); font-size: 16px; }
.device-drawer__location span, .device-drawer__description { margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.7; }
.device-drawer__actions { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-top: auto; padding-top: 24px; }

@media (max-width: 760px) {
  .device-drawer { padding: 22px 18px; }
  .device-drawer__actions { align-items: stretch; flex-direction: column; }
}
</style>
