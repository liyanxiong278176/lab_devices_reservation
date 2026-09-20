<script setup lang="ts">
// 提交报修页(R5 重构):PageHeader + GlowCard 表单 + GradientButton 提交 / GhostButton 取消。
// 表单校验与 /api/v2 报修请求契约保持一致。
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { createRepair } from '@/api/repair'
import { searchDevices } from '@/api/device'
import type { DeviceVO } from '@/types/device'
import PageHeader from '@/components/ui/PageHeader.vue'
import GlowCard from '@/components/ui/GlowCard.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'

const router = useRouter()

const MIN_TITLE_LENGTH = 2
const MAX_IMAGE_URLS = 6

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
  deviceId: [
    { required: true, message: '请选择设备', trigger: ['change', 'blur'] },
  ],
  title: [
    { required: true, message: '请输入标题', trigger: ['blur', 'change'] },
    {
      min: MIN_TITLE_LENGTH,
      max: 200,
      message: `标题长度为 ${MIN_TITLE_LENGTH}-200 个字符`,
      trigger: ['blur', 'change'],
    },
  ],
}

async function loadDevices() {
  try {
    // The v2 endpoint caps page_size at 100. Load the remaining pages in
    // parallel so the repair selector still contains every visible idle
    // device instead of failing on page entry or silently truncating options.
    const pageSize = 100
    const firstPage = await searchDevices({ page: 1, size: pageSize, status: 'IDLE' })
    const totalPages = firstPage.pages ?? Math.ceil(firstPage.total / pageSize)
    const remainingPages = await Promise.all(
      Array.from({ length: Math.max(0, totalPages - 1) }, (_, index) =>
        searchDevices({ page: index + 2, size: pageSize, status: 'IDLE' }),
      ),
    )
    devices.value = [firstPage, ...remainingPages].flatMap((item) => item.records)
  } catch {
    // 拦截器已提示
  }
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  // Keep the client-side guard aligned with RepairCreateRequest.  This also
  // covers whitespace-only titles and protects against a select value being
  // missing when a user clicks submit before the form has finished updating.
  const deviceId = form.value.deviceId
  const title = form.value.title.trim()
  if (typeof deviceId !== 'number' || !Number.isInteger(deviceId) || deviceId <= 0) {
    ElMessage.warning('请选择需要报修的设备')
    return
  }
  if (title.length < MIN_TITLE_LENGTH) {
    ElMessage.warning(`标题至少填写 ${MIN_TITLE_LENGTH} 个字符`)
    return
  }

  const imageUrls = form.value.imageUrlsText
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  if (imageUrls.length > MAX_IMAGE_URLS) {
    ElMessage.warning(`图片 URL 最多填写 ${MAX_IMAGE_URLS} 个`)
    return
  }

  submitting.value = true
  try {
    await createRepair({
      deviceId,
      title,
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

function onCancel() {
  router.back()
}

onMounted(loadDevices)
</script>

<template>
  <div class="rsubmit">
    <PageHeader title="提交报修" subtitle="设备出现故障时,请如实填写并提交" />

    <div class="rsubmit__layout">
      <!-- 主表单 GlowCard -->
      <GlowCard as="section" accent class="rsubmit__form">
        <h2 class="rsubmit__form-title">故障信息</h2>
        <p class="rsubmit__form-hint">带 * 为必填项</p>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          class="rsubmit__el-form"
        >
          <el-form-item label="设备" prop="deviceId" required>
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
          <el-form-item label="标题" prop="title" required>
            <el-input
              v-model="form.title"
              placeholder="一句话描述故障"
              maxlength="60"
              show-word-limit
            />
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
              placeholder="多个 URL 用英文逗号分隔(可选)"
            />
          </el-form-item>
        </el-form>

        <!-- 底部操作区 -->
        <div class="rsubmit__actions">
          <GhostButton @click="onCancel">取消</GhostButton>
          <GradientButton :loading="submitting" @click="onSubmit">
            提交报修
          </GradientButton>
        </div>
      </GlowCard>

      <!-- 右侧提示 GlowCard -->
      <GlowCard as="aside" class="rsubmit__aside">
        <h3 class="rsubmit__aside-title">提交须知</h3>
        <ul class="rsubmit__aside-list">
          <li>请选择出现故障的设备(仅显示空闲设备)。</li>
          <li>标题应一句话概括故障现象,便于快速分流。</li>
          <li>详细描述中请说明故障现象与复现步骤。</li>
          <li>提交后可在「我的报修」跟踪处理进度。</li>
        </ul>
      </GlowCard>
    </div>
  </div>
</template>

<style scoped lang="scss">
// ============================================================================
// 提交报修 深色科技风(spec §7 报修行)
// 全量走 token,scoped scss。双列布局:主表单 / 右侧提示;窄屏堆叠。
// ============================================================================

.rsubmit {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding-bottom: 40px;

  &__layout {
    display: grid;
    grid-template-columns: 1.6fr 1fr;
    gap: 20px;
    align-items: start;

    @media (max-width: 960px) {
      grid-template-columns: 1fr;
    }
  }

  // ---- 主表单卡 ------------------------------------------------------------
  &__form {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 28px;
  }

  &__form-title {
    margin: 0;
    font-family: var(--font-display);
    font-size: 18px;
    font-weight: 600;
    color: var(--text-primary);
    letter-spacing: -0.1px;
  }

  &__form-hint {
    margin: 0 0 12px;
    font-size: 12px;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  &__el-form {
    width: 100%;
  }

  // ---- 底部操作区 ----------------------------------------------------------
  &__actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 12px;
    padding-top: 18px;
    border-top: 1px solid var(--border-subtle);
  }

  // ---- 右侧提示卡 ----------------------------------------------------------
  &__aside {
    padding: 24px;
    position: sticky;
    top: 8px;
  }

  &__aside-title {
    margin: 0 0 14px;
    padding-bottom: 12px;
    font-family: var(--font-display);
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary);
    letter-spacing: -0.05px;
    border-bottom: 1px solid var(--border-subtle);
  }

  &__aside-list {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 12px;

    li {
      position: relative;
      padding-left: 18px;
      font-size: 13px;
      line-height: 1.6;
      color: var(--text-secondary);

      &::before {
        content: '';
        position: absolute;
        left: 0;
        top: 8px;
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--accent);
        box-shadow: 0 0 8px color-mix(in srgb, var(--accent) 45%, transparent);
      }
    }
  }
}
</style>
