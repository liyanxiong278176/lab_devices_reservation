<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { createRepair } from '@/api/repair'
import { searchDevices } from '@/api/device'
import type { DeviceVO } from '@/types/device'

const router = useRouter()

const formRef = ref<FormInstance>()
const form = ref({
  deviceId: undefined as number | undefined,
  title: '',
  description: '',
  imageUrlsText: '',
})
const submitting = ref(false)
const devices = ref<DeviceVO[]>([])

const rules: FormRules = {
  deviceId: [{ required: true, message: '请选择设备', trigger: 'change' }],
  title: [{ required: true, message: '请输入标题', trigger: 'blur' }],
}

async function loadDevices() {
  try {
    const page = await searchDevices({ page: 1, size: 200, status: 'IDLE' })
    devices.value = page.records
  } catch {
    // 拦截器已提示
  }
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    const imageUrls = form.value.imageUrlsText
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    await createRepair({
      deviceId: form.value.deviceId!,
      title: form.value.title.trim(),
      description: form.value.description.trim() || undefined,
      imageUrls: imageUrls.length ? imageUrls : undefined,
    })
    ElMessage.success('报修已提交')
    router.push({ name: 'repair-mine' })
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false
  }
}

onMounted(loadDevices)
</script>

<template>
  <div class="rsubmit">
    <div class="rsubmit__head">
      <h1 class="rsubmit__title">提交报修</h1>
      <p class="rsubmit__subtitle">设备出现故障时，请如实填写并提交</p>
    </div>

    <div class="lab-card rsubmit__form">
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="90px"
        label-position="right"
      >
        <el-form-item label="设备" prop="deviceId">
          <el-select
            v-model="form.deviceId"
            placeholder="选择需报修的设备"
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="d in devices"
              :key="d.id"
              :label="`${d.name}${d.labName ? ' · ' + d.labName : ''}`"
              :value="d.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="标题" prop="title">
          <el-input v-model="form.title" placeholder="一句话描述故障" maxlength="60" show-word-limit />
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="4"
            placeholder="故障现象、复现步骤等"
            maxlength="500"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="图片URL">
          <el-input
            v-model="form.imageUrlsText"
            placeholder="多个 URL 用英文逗号分隔（可选）"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="onSubmit">提交报修</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<style scoped lang="scss">
.rsubmit {
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

  &__form {
    padding: 28px;
    max-width: 640px;
  }
}
</style>
