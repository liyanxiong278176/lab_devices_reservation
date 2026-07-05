<script setup lang="ts">
// 智能推荐页(R5.5 重构):GlowCard 推荐网格 + 理由 Tag chips + Score + 冷启动提示 + 错峰入场。
// 推荐数据来源(/recommendations,含冷启动降级)、reason 字段、跳详情——逻辑零改,仅换展示层。
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getRecommendations, type RecommendationItem } from '@/api/recommendation'
import { useStagger } from '@/composables/useStagger'
import PageHeader from '@/components/ui/PageHeader.vue'
import GlowCard from '@/components/ui/GlowCard.vue'
import Tag from '@/components/ui/Tag.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import TextButton from '@/components/ui/TextButton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

// StatusDot 期望的联合(本组件仅用于把 string 状态收拢到合法值;后端仅推 IDLE 设备)
type DotStatus = 'IDLE' | 'IN_USE' | 'MAINTENANCE' | 'BROKEN'

const router = useRouter()

const loading = ref(false)
const items = ref<RecommendationItem[]>([])

// 冷启动判定:所有候选项都落到"近30天热门设备"兜底理由 → 无个人历史,纯热门推荐。
// (后端 pickReason 在 cat/lab/tag 贡献全 0 时返回该文案,与 RecommendationServiceImpl 对齐。)
const COLD_START_REASON = '近30天热门设备'
const isColdStart = computed(
  () =>
    items.value.length > 0 &&
    items.value.every((it) => !it.reason || it.reason === COLD_START_REASON),
)

const subtitle = computed(() =>
  isColdStart.value
    ? '暂无使用历史,先基于近 30 天全站热门为你推荐'
    : '基于你的使用偏好与近期热门,为你挑选的设备',
)

// 网格错峰容器(spec §6.2 / 同 R3 dashboard / R4 browse):首入视口时 [data-stagger]
// 卡片按 60ms 错峰 fade+rise;reduced-motion 由 useStagger 内部短路。
const gridRef = ref<HTMLElement | null>(null)
useStagger(gridRef, { delay: 60 })

// 首屏错峰交给 useStagger 的 IntersectionObserver;后续若需重渲染(observer 已 stop),
// 新出现的 [data-stagger] 卡片缺 stagger-in 会卡初始态,这里立即补显(不错峰)。当前推荐页
// 一次性加载、无翻页/筛选,分支保留以与 R3/R4 模式一致,防御未来扩展。
let firstLoad = true

async function load() {
  loading.value = true
  try {
    items.value = await getRecommendations(10)
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

/** score 为 0~1;> 0 才展示(冷启动某些设备热门度归一后仍可能为 0)。 */
function scorePercent(item: RecommendationItem): number {
  if (!item.score || item.score <= 0) return 0
  return Math.round(item.score * 100)
}

/** 理由 chips:主理由(后端 reason 文案) + 派生上下文(类目/实验室,均为真实字段,非杜撰)。 */
function reasonChips(item: RecommendationItem): { text: string; variant: 'accent' | 'default' }[] {
  const chips: { text: string; variant: 'accent' | 'default' }[] = []
  if (item.reason) chips.push({ text: item.reason, variant: 'accent' })
  if (item.categoryName) chips.push({ text: item.categoryName, variant: 'default' })
  if (item.labName) chips.push({ text: item.labName, variant: 'default' })
  return chips
}

function dotStatus(item: RecommendationItem): DotStatus {
  return (item.status as DotStatus | undefined) ?? 'IDLE'
}

function goDetail(item: RecommendationItem) {
  router.push({ name: 'device-detail', params: { id: item.deviceId } })
}

function goReserve(item: RecommendationItem) {
  router.push({ name: 'reservation-create', query: { deviceId: String(item.deviceId) } })
}

const hasItems = computed(() => items.value.length > 0)

onMounted(load)
</script>

<template>
  <div class="rec-page">
    <PageHeader title="智能推荐" :subtitle="subtitle" />

    <!-- 冷启动提示条(仅冷启动且有数据时显示) -->
    <div v-if="hasItems && isColdStart" class="rec-page__hint">
      还没有历史数据帮我们读懂你 —— 多预约几次,推荐会越来越准。
    </div>

    <!-- 推荐网格 -->
    <div v-loading="loading" class="rec-grid" ref="gridRef">
      <div
        v-for="item in items"
        :key="item.deviceId"
        class="rec-cell"
        data-stagger
      >
        <GlowCard as="article" accent class="rec-card" @click="goDetail(item)">
          <!-- 顶:状态 + 推荐分数 -->
          <div class="rec-card__top">
            <StatusDot :status="dotStatus(item)" :label="true" />
            <span v-if="scorePercent(item) > 0" class="rec-card__score">
              <small>Score</small>
              <span class="rec-card__score-num">{{ scorePercent(item) }}%</span>
            </span>
          </div>

          <!-- 标题:品牌(eyebrow) + 型号(主) -->
          <h3 class="rec-card__title" :title="item.name">
            <span v-if="item.brand" class="rec-card__brand">{{ item.brand }}</span>
            <span class="rec-card__model">{{ item.model || item.name }}</span>
          </h3>

          <!-- 推荐理由 chips:主理由(accent)+ 类目/实验室(default) -->
          <div v-if="reasonChips(item).length" class="rec-card__reasons">
            <Tag
              v-for="(chip, idx) in reasonChips(item)"
              :key="idx"
              :variant="chip.variant"
              round
              size="default"
            >
              {{ chip.text }}
            </Tag>
          </div>

          <!-- 价格摘要 -->
          <p v-if="item.pricePerHour != null" class="rec-card__price">
            ¥{{ item.pricePerHour }}<small>/时</small>
          </p>

          <!-- 操作 -->
          <div class="rec-card__foot">
            <span class="rec-card__meta">查看详情</span>
            <TextButton size="small" @click.stop="goReserve(item)">去预约</TextButton>
          </div>
        </GlowCard>
      </div>

      <!-- 空态(冷启动或异常导致无任何推荐) -->
      <div v-if="!loading && !hasItems" class="rec-grid__empty">
        <EmptyState
          icon="MagicStick"
          title="暂无推荐"
          description="去使用几次设备,推荐会越来越懂你。"
        />
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.rec-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

// ---- 冷启动提示条 -----------------------------------------------------------
.rec-page__hint {
  padding: 10px 16px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--accent);
  background: rgba(34, 211, 238, 0.06);
  border: 1px solid rgba(34, 211, 238, 0.18);
  border-radius: var(--radius-card);
}

// ---- 推荐网格 ---------------------------------------------------------------
// auto-fill 自适应:minmax(300px, 1fr) → 窄屏 1 列、宽屏多列,推荐列表 top10 控量。
.rec-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  min-height: 120px;
  position: relative;

  &__empty {
    grid-column: 1 / -1;
  }
}

// data-stagger 落 cell(不落 GlowCard):reveal 的 opacity/transform 与 GlowCard 的
// hover transform 分离,避免特异性压住 hover(spec §6.1 / R3/R4 模式)。
.rec-cell {
  display: block;
  cursor: pointer;
}

// ---- 推荐卡 -----------------------------------------------------------------
.rec-card {
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

  &__score {
    display: inline-flex;
    align-items: baseline;
    gap: 4px;
    white-space: nowrap;

    small {
      font-size: 11px;
      font-weight: 500;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--text-tertiary);
    }
  }

  &__score-num {
    font-family: var(--font-mono);
    font-size: 15px;
    font-weight: 600;
    color: var(--accent);
    font-variant-numeric: tabular-nums;
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
    overflow: hidden;
  }

  &__brand {
    font-size: 12px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-tertiary);
  }

  &__model {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  // ---- 理由 chips ----------------------------------------------------------
  &__reasons {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  &__price {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 15px;
    font-weight: 600;
    color: var(--accent);

    small {
      margin-left: 2px;
      font-family: var(--font-sans);
      font-size: 12px;
      font-weight: 400;
      color: var(--text-tertiary);
    }
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
  }
}
</style>
