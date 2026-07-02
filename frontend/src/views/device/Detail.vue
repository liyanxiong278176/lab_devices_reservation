<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { deviceCalendar, getDevice } from '@/api/device'
import type { DeviceCalendarItemVO, DeviceVO } from '@/types/device'
import { deviceStatusTag } from '@/composables/useDeviceStatus'

const route = useRoute()
const router = useRouter()

const device = ref<DeviceVO | null>(null)
const loading = ref(false)

const selectedDate = ref<Date>(new Date())

// 日历区间：选中日所在周的 ±7 天（满足后端 from/to ISO 日期）
const rangeFrom = computed(() => dayjs(selectedDate.value).startOf('week').format('YYYY-MM-DD'))
const rangeTo = computed(() => dayjs(selectedDate.value).endOf('week').format('YYYY-MM-DD'))

const calendar = ref<DeviceCalendarItemVO[]>([])
const calendarLoading = ref(false)

const id = computed(() => Number(route.params.id))

async function loadDevice() {
  loading.value = true
  try {
    device.value = await getDevice(id.value)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

async function loadCalendar() {
  calendarLoading.value = true
  try {
    calendar.value = await deviceCalendar(id.value, rangeFrom.value, rangeTo.value)
  } catch {
    calendar.value = []
  } finally {
    calendarLoading.value = false
  }
}

watch(selectedDate, loadCalendar)

function goReserve() {
  router.push({ name: 'reservation-create', query: { deviceId: String(id.value) } })
}

onMounted(async () => {
  await loadDevice()
  await loadCalendar()
})
</script>

<template>
  <div v-loading="loading" class="device-detail">
    <div class="lab-card device-detail__info">
      <div class="device-detail__head">
        <div>
          <h1 class="device-detail__name">{{ device?.name ?? '—' }}</h1>
          <p class="device-detail__sub">
            {{ device?.brand ?? '' }} {{ device?.model ?? '' }}
            <span v-if="device?.labName"> · {{ device.labName }}</span>
          </p>
        </div>
        <el-tag v-if="device" :type="deviceStatusTag(device.status)" effect="light" round>
          {{ device.status }}
        </el-tag>
      </div>

      <dl class="device-detail__grid" v-if="device">
        <div class="device-detail__field">
          <dt>分类</dt>
          <dd>{{ device.categoryName || '—' }}</dd>
        </div>
        <div class="device-detail__field">
          <dt>规格</dt>
          <dd>{{ device.specs || '—' }}</dd>
        </div>
        <div class="device-detail__field">
          <dt>单价/时</dt>
          <dd>¥{{ device.pricePerHour ?? '—' }}</dd>
        </div>
        <div class="device-detail__field">
          <dt>最长预约</dt>
          <dd>{{ device.maxReservationHours ?? '—' }} 小时</dd>
        </div>
        <div class="device-detail__field">
          <dt>需审批</dt>
          <dd>{{ device.needApproval === 1 ? '是' : '否' }}</dd>
        </div>
      </dl>

      <p v-if="device?.description" class="device-detail__desc">{{ device.description }}</p>

      <div class="device-detail__actions">
        <el-button type="primary" :disabled="device?.status !== 'IDLE'" @click="goReserve">
          立即预约
        </el-button>
      </div>
    </div>

    <!-- 日历占用面板 -->
    <div class="lab-card device-detail__calendar">
      <div class="device-detail__calendar-head">
        <h2 class="device-detail__section-title">占用日历</h2>
        <p class="device-detail__hint">选择日期查看该周设备被占用的时段</p>
      </div>

      <el-date-picker
        v-model="selectedDate"
        type="date"
        placeholder="选择日期"
        format="YYYY-MM-DD"
        value-format="x"
        :clearable="false"
        style="margin-bottom: 16px"
      />

      <el-table v-loading="calendarLoading" :data="calendar" stripe size="small">
        <el-table-column prop="date" label="日期" width="130" />
        <el-table-column prop="slotIndex" label="时段序号" width="110" align="center" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="row.status === 'IN_USE' ? 'primary' : 'warning'" effect="light" round size="small">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="reservationId" label="预约ID" />
        <template #empty>
          <span class="device-detail__empty">该时段空闲，可预约</span>
        </template>
      </el-table>
    </div>
  </div>
</template>

<style scoped lang="scss">
.device-detail {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 24px;

  @media (max-width: 960px) {
    grid-template-columns: 1fr;
  }

  &__info,
  &__calendar {
    padding: 28px;
  }

  &__head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
    margin-bottom: 24px;
  }

  &__name {
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
    margin: 0 0 20px;
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
      color: var(--el-text-color-regular);
    }
  }

  &__desc {
    margin: 0 0 20px;
    font-size: 14px;
    line-height: 1.6;
    color: var(--el-text-color-regular);
  }

  &__actions {
    display: flex;
    gap: 12px;
  }

  &__section-title {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    color: var(--el-text-color-primary);
  }

  &__calendar-head {
    margin-bottom: 16px;
  }

  &__hint {
    margin: 6px 0 0;
    font-size: 13px;
    color: var(--el-text-color-secondary);
  }

  &__empty {
    color: var(--el-color-success);
    font-size: 13px;
  }
}
</style>
