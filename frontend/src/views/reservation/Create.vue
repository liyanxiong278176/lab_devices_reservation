<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import dayjs from 'dayjs'
import { getDevice } from '@/api/device'
import { createReservation } from '@/api/reservation'
import type { DeviceVO } from '@/types/device'
import type { ReservationCreatePayload } from '@/types/reservation'

const route = useRoute()
const router = useRouter()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const deviceLoading = ref(false)
const device = ref<DeviceVO | null>(null)

// [startTime, endTime] — datetimerange
const range = ref<[Date, Date] | null>(null)
const form = reactive({
  purpose: '',
})

const rules: FormRules = {
  purpose: [{ required: true, message: '请填写使用用途', trigger: 'blur' }],
}

const deviceId = computed(() => Number(route.query.deviceId))

async function loadDevice() {
  if (!deviceId.value || Number.isNaN(deviceId.value)) return
  deviceLoading.value = true
  try {
    device.value = await getDevice(deviceId.value)
  } catch {
    // 拦截器已提示
  } finally {
    deviceLoading.value = false
  }
}

function toIso(d: Date): string {
  // 后端接收 LocalDateTime（ISO yyyy-MM-ddTHH:mm:ss）
  return dayjs(d).format('YYYY-MM-DDTHH:mm:ss')
}

async function onSubmit() {
  if (!formRef.value) return
  if (!range.value || range.value.length !== 2) {
    ElMessage.warning('请选择预约起止时间')
    return
  }
  if (!deviceId.value) {
    ElMessage.warning('缺少设备信息')
    return
  }
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    submitting.value = true
    const payload: ReservationCreatePayload = {
      deviceId: deviceId.value,
      startTime: toIso(range.value![0]),
      endTime: toIso(range.value![1]),
      purpose: form.purpose,
    }
    try {
      const newId = await createReservation(payload)
      ElMessage.success(`预约提交成功（#${newId}）`)
      router.push({ name: 'reservation-mine' })
    } catch {
      // 拦截器已提示（含冲突/防超约错误）
    } finally {
      submitting.value = false
    }
  })
}

function onCancel() {
  router.back()
}

onMounted(loadDevice)
</script>

<template>
  <div class="reserve-create">
    <div class="reserve-create__head">
      <h1 class="reserve-create__title">创建预约</h1>
      <p class="reserve-create__subtitle">选择时段并填写用途，提交后系统将进行冲突检测</p>
    </div>

    <div v-loading="deviceLoading" class="lab-card reserve-create__card">
      <!-- 设备信息 -->
      <section v-if="device" class="reserve-create__device">
        <h2 class="reserve-create__device-name">{{ device.name }}</h2>
        <p class="reserve-create__device-sub">
          {{ device.brand }} {{ device.model }}
          <span v-if="device.labName"> · {{ device.labName }}</span>
          <span> · 单价 ¥{{ device.pricePerHour ?? '—' }}/时</span>
        </p>
      </section>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent
      >
        <el-form-item label="预约时段（15 分钟对齐，工作时段 08:00-22:00）" required>
          <el-date-picker
            v-model="range"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            format="YYYY-MM-DD HH:mm"
            value-format="x"
            :step="{ hours: 1, minutes: 15, seconds: 0 }"
            style="width: 100%; max-width: 520px"
          />
        </el-form-item>

        <el-form-item label="使用用途" prop="purpose">
          <el-input
            v-model="form.purpose"
            type="textarea"
            :rows="4"
            placeholder="请简述本次预约的使用用途"
            maxlength="300"
            show-word-limit
          />
        </el-form-item>

        <div class="reserve-create__actions">
          <el-button type="primary" :loading="submitting" @click="onSubmit">
            提交预约
          </el-button>
          <el-button @click="onCancel">取消</el-button>
        </div>
      </el-form>
    </div>
  </div>
</template>

<style scoped lang="scss">
.reserve-create {
  max-width: 760px;

  &__head {
    margin-bottom: 24px;
  }

  &__title {
    margin: 0;
    font-size: 28px;
    font-weight: 600;
    letter-spacing: -0.5px;
    color: var(--el-text-color-primary);
  }

  &__subtitle {
    margin: 8px 0 0;
    font-size: 14px;
    color: var(--el-text-color-secondary);
  }

  &__card {
    padding: 32px;
  }

  &__device {
    padding-bottom: 20px;
    margin-bottom: 24px;
    border-bottom: 1px solid var(--el-border-color-light);
  }

  &__device-name {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    color: var(--el-text-color-primary);
  }

  &__device-sub {
    margin: 6px 0 0;
    font-size: 14px;
    color: var(--el-text-color-secondary);
  }

  &__actions {
    display: flex;
    gap: 12px;
    margin-top: 8px;
  }
}
</style>
