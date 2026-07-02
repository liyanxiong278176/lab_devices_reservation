<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import dayjs from 'dayjs'
import { getReservation } from '@/api/reservation'
import type { ReservationStatus, ReservationVO } from '@/types/reservation'
import { reservationStatusTag } from '@/composables/useDeviceStatus'

const route = useRoute()
const reservation = ref<ReservationVO | null>(null)
const loading = ref(false)

const id = computed(() => Number(route.params.id))

async function load() {
  loading.value = true
  try {
    reservation.value = await getReservation(id.value)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function fmt(t?: string): string {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'
}

/** 根据状态构造简易时间线（说明性，非完整审计日志）。 */
function timelineItems(status: ReservationStatus) {
  return [
    { name: '提交预约', state: 'done' },
    { name: '审批通过', state: ['APPROVED', 'IN_USE', 'COMPLETED'].includes(status) ? 'done' : status === 'REJECTED' ? 'error' : 'active' },
    { name: '签到使用', state: ['IN_USE', 'COMPLETED'].includes(status) ? 'done' : status === 'NO_SHOW' ? 'error' : 'pending' },
    { name: '归还完成', state: status === 'COMPLETED' ? 'done' : status === 'VIOLATED' ? 'error' : 'pending' },
  ]
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="rsv-detail">
    <div v-if="reservation" class="lab-card rsv-detail__main">
      <div class="rsv-detail__head">
        <div>
          <h1 class="rsv-detail__title">预约 #{{ reservation.id }}</h1>
          <p class="rsv-detail__sub">设备 #{{ reservation.deviceId }} · {{ fmt(reservation.createdAt) }} 创建</p>
        </div>
        <el-tag :type="reservationStatusTag(reservation.status).type" effect="light" round>
          {{ reservationStatusTag(reservation.status).label }}
        </el-tag>
      </div>

      <dl class="rsv-detail__grid">
        <div class="rsv-detail__field">
          <dt>开始时间</dt>
          <dd>{{ fmt(reservation.startTime) }}</dd>
        </div>
        <div class="rsv-detail__field">
          <dt>结束时间</dt>
          <dd>{{ fmt(reservation.endTime) }}</dd>
        </div>
        <div class="rsv-detail__field">
          <dt>时段数</dt>
          <dd>{{ reservation.slotCount }} 个（每段 15 分钟）</dd>
        </div>
        <div class="rsv-detail__field">
          <dt>申请人</dt>
          <dd>用户 #{{ reservation.userId }}</dd>
        </div>
      </dl>

      <section class="rsv-detail__purpose">
        <h3 class="rsv-detail__label">使用用途</h3>
        <p class="rsv-detail__purpose-text">{{ reservation.purpose || '—' }}</p>
      </section>
    </div>

    <!-- 状态时间线 -->
    <div v-if="reservation" class="lab-card rsv-detail__timeline">
      <h2 class="rsv-detail__section-title">状态流转</h2>
      <el-timeline class="rsv-detail__tl">
        <el-timeline-item
          v-for="(item, idx) in timelineItems(reservation.status)"
          :key="idx"
          :type="item.state === 'done' ? 'success' : item.state === 'error' ? 'danger' : item.state === 'active' ? 'primary' : 'info'"
          :hollow="item.state === 'pending'"
          :timestamp="''"
        >
          {{ item.name }}
        </el-timeline-item>
      </el-timeline>
    </div>
  </div>
</template>

<style scoped lang="scss">
.rsv-detail {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 24px;

  @media (max-width: 960px) {
    grid-template-columns: 1fr;
  }

  &__main,
  &__timeline {
    padding: 28px;
  }

  &__head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
    margin-bottom: 24px;
  }

  &__title {
    margin: 0;
    font-size: 24px;
    font-weight: 600;
    letter-spacing: -0.3px;
    color: var(--el-text-color-primary);
  }

  &__sub {
    margin: 6px 0 0;
    font-size: 14px;
    color: var(--el-text-color-secondary);
  }

  &__grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16px 24px;
    margin: 0 0 24px;
  }

  &__field {
    dt {
      margin: 0 0 4px;
      font-size: 12px;
      color: var(--el-text-color-secondary);
    }
    dd {
      margin: 0;
      font-size: 15px;
      font-variant-numeric: tabular-nums;
      color: var(--el-text-color-regular);
    }
  }

  &__label {
    margin: 0 0 8px;
    font-size: 13px;
    font-weight: 600;
    color: var(--el-text-color-secondary);
  }

  &__purpose-text {
    margin: 0;
    font-size: 15px;
    line-height: 1.6;
    color: var(--el-text-color-regular);
  }

  &__section-title {
    margin: 0 0 20px;
    font-size: 18px;
    font-weight: 600;
    color: var(--el-text-color-primary);
  }

  &__tl {
    padding-left: 4px;
  }
}
</style>
