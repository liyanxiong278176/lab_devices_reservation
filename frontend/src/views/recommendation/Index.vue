<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getRecommendations, type RecommendationItem } from '@/api/recommendation'

const router = useRouter()

const loading = ref(false)
const items = ref<RecommendationItem[]>([])

async function load() {
  loading.value = true
  try {
    items.value = await getRecommendations(10)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

/** score 为 0~1；仅当 > 0 时展示进度条（冷启动热门场景得分可能为 0）。 */
function scorePercent(item: RecommendationItem): number {
  if (!item.score || item.score <= 0) return 0
  return Math.round(item.score * 100)
}

function goReserve(item: RecommendationItem) {
  router.push({ name: 'reservation-create', query: { deviceId: String(item.deviceId) } })
}

function goDetail(item: RecommendationItem) {
  router.push({ name: 'device-detail', params: { id: item.deviceId } })
}

const hasItems = computed(() => items.value.length > 0)

onMounted(load)
</script>

<template>
  <div class="rec">
    <div class="rec__head">
      <h1 class="rec__title">为你推荐</h1>
      <p class="rec__subtitle">基于你的使用偏好与近期热门，为你挑选的设备</p>
    </div>

    <!-- 空状态 -->
    <div v-if="!loading && !hasItems" class="lab-card rec__empty">
      <el-empty description="暂无推荐">
        <span class="rec__empty-hint">去使用几次设备，推荐会越来越懂你</span>
      </el-empty>
    </div>

    <!-- 推荐卡片网格 -->
    <el-row v-else v-loading="loading" :gutter="24" class="rec__grid">
      <el-col
        v-for="item in items"
        :key="item.deviceId"
        :xs="24"
        :sm="12"
        :md="8"
        :lg="6"
      >
        <div class="lab-card rec__card">
          <!-- 可解释理由（hero 元素，蓝色高亮） -->
          <div class="rec__reason">
            <el-tag effect="dark" round size="default" class="rec__reason-tag">
              {{ item.reason || '为你推荐' }}
            </el-tag>
          </div>

          <!-- 设备名称 -->
          <h3 class="rec__name" :title="item.name">{{ item.name }}</h3>

          <!-- 分类 / 实验室（muted） -->
          <p class="rec__meta">
            <span v-if="item.categoryName">{{ item.categoryName }}</span>
            <span v-if="item.categoryName && item.labName" class="rec__dot">·</span>
            <span v-if="item.labName">{{ item.labName }}</span>
            <span v-if="!item.categoryName && !item.labName" class="rec__meta-empty">—</span>
          </p>

          <!-- 可选品牌/型号 -->
          <p v-if="item.brand || item.model" class="rec__brand">
            <span v-if="item.brand">{{ item.brand }}</span>
            <span v-if="item.brand && item.model"> </span>
            <span v-if="item.model">{{ item.model }}</span>
          </p>

          <!-- 匹配度进度条（score > 0 时展示） -->
          <div v-if="scorePercent(item) > 0" class="rec__score">
            <span class="rec__score-label">匹配度</span>
            <el-progress
              :percentage="scorePercent(item)"
              :stroke-width="6"
              :show-text="false"
              class="rec__score-bar"
            />
            <span class="rec__score-value">{{ scorePercent(item) }}%</span>
          </div>

          <!-- 操作 -->
          <div class="rec__actions">
            <el-button type="primary" class="rec__cta" @click="goReserve(item)">
              去预约
            </el-button>
            <el-button link type="primary" @click="goDetail(item)">详情</el-button>
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped lang="scss">
.rec {
  &__head {
    margin-bottom: 24px;
  }

  &__title {
    margin: 0;
    font-size: 28px; // display-sm
    font-weight: 600;
    line-height: 1.2;
    letter-spacing: -0.5px;
    color: var(--el-text-color-primary); // ink #111111
  }

  &__subtitle {
    margin: 8px 0 0;
    font-size: 14px;
    color: var(--el-text-color-secondary); // muted #6b7280
  }

  &__grid {
    // el-row gutter 已处理列间距
  }

  &__card {
    display: flex;
    flex-direction: column;
    height: 100%;
    padding: 24px; // spacing.lg
    margin-bottom: 24px;
    transition: box-shadow 0.15s ease;

    &:hover {
      box-shadow: var(--el-box-shadow); // 悬停轻微抬升
    }
  }

  // 可解释理由 — 蓝色品牌强调（DESIGN.md brand-accent #3b82f6）
  &__reason {
    margin-bottom: 16px;
  }

  &__reason-tag {
    // 覆盖 Element Plus 默认 primary 黑色，改用 Cal.com brand-accent 蓝
    background-color: #3b82f6 !important;
    border-color: #3b82f6 !important;
    color: #ffffff !important;
    font-weight: 500;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__name {
    margin: 0;
    font-size: 18px; // title-md
    font-weight: 600;
    line-height: 1.4;
    color: var(--el-text-color-primary); // #111111
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__meta {
    margin: 8px 0 0;
    font-size: 14px; // body-sm
    color: var(--el-text-color-secondary); // #6b7280
  }

  &__dot {
    margin: 0 6px;
  }

  &__meta-empty {
    color: var(--el-text-color-placeholder);
  }

  &__brand {
    margin: 4px 0 0;
    font-size: 13px; // caption
    color: var(--el-text-color-secondary);
  }

  &__score {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 16px;
  }

  &__score-label {
    font-size: 13px;
    color: var(--el-text-color-secondary);
    flex-shrink: 0;
  }

  &__score-bar {
    flex: 1;
    :deep(.el-progress-bar__outer) {
      background-color: var(--el-fill-color-light); // #f5f5f5
    }
    :deep(.el-progress-bar__inner) {
      // 进度条同样用 brand-accent 蓝，与理由 tag 呼应
      background-color: #3b82f6;
    }
  }

  &__score-value {
    font-size: 13px;
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    color: var(--el-text-color-primary);
    flex-shrink: 0;
  }

  &__actions {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: auto;
    padding-top: 20px;
  }

  // 黑色主 CTA（DESIGN.md button-primary #111111，已由 theme 映射）
  &__cta {
    flex-shrink: 0;
  }

  &__empty {
    padding: 48px 24px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  &__empty-hint {
    display: block;
    margin-top: 4px;
    font-size: 13px;
    color: var(--el-text-color-secondary); // muted
  }
}
</style>
