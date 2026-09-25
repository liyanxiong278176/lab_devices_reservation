<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import {
  acceptReservationReturn,
  cancelHandoverException,
  handoverReservation,
  pendingHandovers,
} from '@/api/reservation'
import { uploadRepairImage } from '@/api/repair'
import type { AccessoryCheckPayload } from '@/api/reservation'
import type { ReservationVO } from '@/types/reservation'
import type { Page } from '@/types/common'
import PageHeader from '@/components/ui/PageHeader.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import GlowCard from '@/components/ui/GlowCard.vue'
import Tag from '@/components/ui/Tag.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PageDepthNotice from '@/components/ui/PageDepthNotice.vue'

type HandoverTab = 'PENDING' | 'RETURN_PENDING' | 'EXCEPTION'
const activeStatus = ref<HandoverTab>('PENDING')
const page = ref<Page<ReservationVO>>({ records: [], total: 0, size: 12, current: 1 })
const loading = ref(false)
const query = ref({ page: 1, size: 12 })
const dialogVisible = ref(false)
const dialogMode = ref<'handover' | 'return'>('handover')
const target = ref<ReservationVO | null>(null)
const condition = ref<'NORMAL' | 'DAMAGED' | 'MISSING'>('NORMAL')
const note = ref('')
const saving = ref(false)
const evidenceFiles = ref<File[]>([])
const checklist = ref<AccessoryCheckPayload[]>([])

const tabs = [
  { label: '待交接', value: 'PENDING' },
  { label: '待验收', value: 'RETURN_PENDING' },
  { label: '交接异常', value: 'EXCEPTION' },
]

const subtitle = computed(() => `当前范围内 ${page.value.total} 条记录`)

async function load() {
  loading.value = true
  try {
    page.value = await pendingHandovers(activeStatus.value, query.value.page, query.value.size)
  } finally {
    loading.value = false
  }
}

function switchTab(value: string | number) {
  activeStatus.value = value as HandoverTab
  query.value.page = 1
  void load()
}

function openAction(row: ReservationVO, mode: 'handover' | 'return') {
  target.value = row
  dialogMode.value = mode
  condition.value = 'NORMAL'
  note.value = ''
  evidenceFiles.value = []
  checklist.value = (row.accessorySnapshot || []).map((name) => ({ name, condition: 'NORMAL' }))
  dialogVisible.value = true
}

function onEvidenceChange(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  const allowed = ['image/jpeg', 'image/png', 'image/webp']
  if (files.length < 1 || files.length > 6) {
    ElMessage.warning('请上传 1 至 6 张现场照片')
    evidenceFiles.value = []
    input.value = ''
    return
  }
  if (files.some((file) => file.size > 5 * 1024 * 1024 || !allowed.includes(file.type))) {
    ElMessage.warning('照片仅支持 5 MB 以内 JPG、PNG 或 WebP')
    evidenceFiles.value = []
    input.value = ''
    return
  }
  evidenceFiles.value = files
}

async function submitAction() {
  if (!target.value) return
  if (condition.value !== 'NORMAL' && !note.value.trim()) {
    ElMessage.warning('发现损坏或缺失时，请补充验收说明')
    return
  }
  saving.value = true
  try {
    if (dialogMode.value === 'handover' && evidenceFiles.value.length === 0) {
      ElMessage.warning('办理交接前必须上传现场照片')
      return
    }
    const payload = {
      condition: condition.value,
      note: note.value.trim() || undefined,
      checklist: checklist.value,
    }
    if (dialogMode.value === 'handover') {
      const uploads = await Promise.all(evidenceFiles.value.map((file) => uploadRepairImage(file)))
      await handoverReservation(target.value.id, {
        ...payload,
        imageUrls: uploads.map((image) => image.url),
      })
      if (condition.value === 'NORMAL' && checklist.value.every((item) => item.condition === 'NORMAL')) {
        ElMessage.success('设备已完成交接，用户可以开始使用')
      } else {
        ElMessage.warning('已记录交接异常，设备已转维修并生成关联工单')
      }
    } else {
      await acceptReservationReturn(target.value.id, payload)
      ElMessage.success(condition.value === 'NORMAL' ? '归还已验收，预约已完成' : '异常已记录，设备已转维修并生成关联工单')
    }
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function cancelException(row: ReservationVO) {
  try {
    await ElMessageBox.confirm(
      `设备已转维修，是否取消预约 #${row.id} 并释放对应日期？维修单 #${row.faultRepairId || '—'} 将保留。`,
      '处理交接异常',
      { type: 'warning', confirmButtonText: '取消预约', cancelButtonText: '暂不处理' },
    )
    await cancelHandoverException(row.id, '领用交接发现设备异常，取消预约并释放日期；关联报修工单继续处理')
    ElMessage.success('预约已取消并释放日期，关联设备已保持维修状态')
    await load()
  } catch {
    // 用户取消或接口错误已提示
  }
}

function fmt(value?: string) {
  return value ? dayjs(value).format('YYYY-MM-DD') : '—'
}

function canHandover(row: ReservationVO): boolean {
  return fmt(row.startDate) === dayjs().format('YYYY-MM-DD')
}

onMounted(load)
</script>

<template>
  <div class="handover-page">
    <PageHeader title="设备交接" :subtitle="subtitle">
      <template #actions>
        <span class="handover-page__rule">所有预约均需负责人完成领用交接与归还验收</span>
      </template>
    </PageHeader>

    <section class="handover-page__filter">
      <SegmentedControl :model-value="activeStatus" :options="tabs" size="sm" orientation="vertical" @update:model-value="switchTab" />
    </section>

    <div v-loading="loading" class="handover-page__grid">
      <GlowCard v-for="row in page.records" :key="row.id" as="article" class="handover-card">
        <header class="handover-card__head">
          <div>
            <span class="handover-card__eyebrow">RESERVATION #{{ row.id }}</span>
            <h2>#{{ row.deviceAssetCode || row.deviceId }} · {{ row.deviceName }}</h2>
          </div>
          <Tag :variant="activeStatus === 'EXCEPTION' ? 'danger' : activeStatus === 'PENDING' ? 'warning' : 'accent'" size="small" round>
            {{ activeStatus === 'PENDING' ? '待交接' : activeStatus === 'EXCEPTION' ? '交接异常' : '待验收' }}
          </Tag>
        </header>
        <dl class="handover-card__facts">
          <div><dt>实验室</dt><dd>{{ row.deviceLabName || '—' }}</dd></div>
          <div><dt>预约人</dt><dd>#{{ row.userId }}</dd></div>
          <div><dt>预约日期</dt><dd>{{ fmt(row.startDate) }} 至 {{ fmt(row.endDate) }}</dd></div>
          <div><dt>用途</dt><dd>{{ row.purpose || '—' }}</dd></div>
        </dl>
        <section v-if="activeStatus === 'RETURN_PENDING' && row.returnImageUrls?.length" class="handover-card__evidence">
          <strong>用户归还现场（{{ row.returnImageUrls.length }} 张）</strong>
          <div><a v-for="url in row.returnImageUrls" :key="url" :href="url" target="_blank" rel="noreferrer">查看照片</a></div>
        </section>
        <section v-if="activeStatus === 'EXCEPTION'" class="handover-card__exception">
          <strong>预约尚未开始，设备已转入维修</strong>
          <span>关联报修单：#{{ row.faultRepairId || '处理中' }}；请取消预约释放日期，或先联系用户协商本学院同类设备。</span>
        </section>
        <footer class="handover-card__foot">
          <span>{{ activeStatus === 'PENDING' ? (canHandover(row) ? '请核对设备、配件并完成领用交接' : `预约开始日 ${fmt(row.startDate)} 才能办理交接`) : activeStatus === 'EXCEPTION' ? '待负责人处理异常预约' : '请核对用户归还照片、设备和配件' }}</span>
          <div>
            <GhostButton v-if="activeStatus === 'EXCEPTION'" size="small" @click="cancelException(row)">取消预约并释放日期</GhostButton>
            <GradientButton v-if="activeStatus !== 'EXCEPTION'" size="small" :disabled="activeStatus === 'PENDING' && !canHandover(row)" @click="openAction(row, activeStatus === 'PENDING' ? 'handover' : 'return')">
              {{ activeStatus === 'PENDING' ? '核对并完成交接' : '核对并确认验收' }}
            </GradientButton>
          </div>
        </footer>
      </GlowCard>
      <div v-if="!loading && page.records.length === 0" class="handover-page__empty">
        <EmptyState icon="Checked" :title="activeStatus === 'PENDING' ? '暂无待交接设备' : activeStatus === 'EXCEPTION' ? '暂无待处理交接异常' : '暂无待验收设备'" description="设备交接状态会在预约审批后实时更新。" />
      </div>
    </div>

    <div v-if="page.records.length" class="handover-page__pager">
      <PageDepthNotice v-if="page.truncated" :total="page.total" />
      <el-pagination
        :current-page="page.current"
        :page-size="page.size"
        :total="page.truncated ? Math.min(page.total, (page.pages || 1) * page.size) : page.total"
        layout="total, prev, pager, next"
        background
        @current-change="(value: number) => { query.page = value; void load() }"
      />
    </div>

    <el-dialog v-model="dialogVisible" :title="dialogMode === 'handover' ? '完成设备交接' : '确认归还验收'" width="620px">
      <div class="handover-dialog">
        <p>设备：{{ target?.deviceName }}（{{ target?.deviceAssetCode || `#${target?.deviceId}` }}）</p>
        <section v-if="dialogMode === 'handover'" class="handover-dialog__photos">
          <label>交接现场照片（必填，1–6 张，每张不超过 5 MB）</label>
          <input type="file" accept="image/jpeg,image/png,image/webp" multiple @change="onEvidenceChange" />
          <small>{{ evidenceFiles.length }} 张已选择</small>
        </section>
        <section v-else class="handover-dialog__photos">
          <label>用户归还现场照片</label>
          <div v-if="target?.returnImageUrls?.length" class="handover-dialog__evidence-links">
            <a v-for="url in target.returnImageUrls" :key="url" :href="url" target="_blank" rel="noreferrer">打开照片</a>
          </div>
          <small v-else>缺少照片，后端将阻止验收完成。</small>
        </section>
        <section v-if="checklist.length" class="handover-dialog__checklist">
          <strong>设备配件逐项核对</strong>
          <div v-for="item in checklist" :key="item.name" class="handover-dialog__check">
            <span>{{ item.name }}</span>
            <el-select v-model="item.condition" aria-label="配件状态" style="width: 130px">
              <el-option label="正常" value="NORMAL" />
              <el-option label="损坏" value="DAMAGED" />
              <el-option label="缺失" value="MISSING" />
            </el-select>
            <el-input v-if="item.condition !== 'NORMAL'" v-model="item.note" maxlength="300" placeholder="异常说明" />
          </div>
        </section>
        <p v-else class="handover-dialog__empty-checklist">该设备未配置配件清单，仍需上传现场照片并记录设备状态。</p>
        <el-radio-group v-model="condition">
          <el-radio value="NORMAL">状态正常</el-radio>
          <el-radio value="DAMAGED">发现损坏</el-radio>
          <el-radio value="MISSING">配件/设备缺失</el-radio>
        </el-radio-group>
        <el-input v-model="note" type="textarea" :rows="4" maxlength="1000" show-word-limit placeholder="补充交接或验收说明" />
      </div>
      <template #footer>
        <GhostButton @click="dialogVisible = false">取消</GhostButton>
        <GradientButton :loading="saving" @click="submitAction">确认</GradientButton>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.handover-page { display: flex; flex-direction: column; gap: 20px; }
.handover-page__rule { color: var(--text-tertiary); font-size: 12px; }
.handover-page__filter { padding: 12px 16px; background: var(--bg-sunken); border: 1px solid var(--border-subtle); border-radius: var(--radius-card); }
.handover-page__grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; min-height: 180px; }
.handover-page__empty { grid-column: 1 / -1; }
.handover-card { display: grid; gap: 18px; height: 100%; }
.handover-card__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.handover-card__eyebrow { color: var(--text-tertiary); font-family: var(--font-mono); font-size: 10px; letter-spacing: .12em; }
.handover-card h2 { margin: 6px 0 0; color: var(--text-primary); font-family: var(--font-display); font-size: 17px; }
.handover-card__facts { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin: 0; }
.handover-card__facts div { display: grid; gap: 4px; padding: 10px; background: var(--bg-elevated); border-radius: var(--radius-control); }
.handover-card__facts dt { color: var(--text-tertiary); font-size: 10px; }.handover-card__facts dd { margin: 0; color: var(--text-secondary); font-size: 12px; }
.handover-card__evidence,.handover-card__exception { display: grid; gap: 8px; padding: 12px; background: var(--bg-elevated); border-radius: var(--radius-control); color: var(--text-secondary); font-size: 11px; }
.handover-card__evidence > div,.handover-dialog__evidence-links { display: flex; flex-wrap: wrap; gap: 10px; }
.handover-card__evidence a,.handover-dialog__evidence-links a { color: var(--accent); }
.handover-card__exception strong { color: var(--status-warning); }.handover-card__exception span { color: var(--text-tertiary); line-height: 1.5; }
.handover-card__foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 14px; border-top: 1px solid var(--border-subtle); color: var(--text-tertiary); font-size: 11px; }.handover-card__foot > div { display: flex; gap: 8px; }
.handover-dialog { display: grid; gap: 16px; }.handover-dialog p { margin: 0; color: var(--text-secondary); }.handover-dialog__photos,.handover-dialog__checklist { display: grid; gap: 8px; padding: 12px; background: var(--bg-elevated); border-radius: var(--radius-control); color: var(--text-secondary); font-size: 12px; }.handover-dialog__photos small,.handover-dialog__empty-checklist { color: var(--text-tertiary); font-size: 11px; }.handover-dialog__checklist > strong { color: var(--text-primary); }.handover-dialog__check { display: grid; grid-template-columns: minmax(90px,1fr) 130px minmax(120px,1fr); align-items: center; gap: 8px; }.handover-page__pager { align-self: flex-end; }
@media (max-width: 620px) { .handover-card__facts { grid-template-columns: 1fr; }.handover-card__foot { align-items: flex-start; flex-direction: column; }.handover-card__foot > div { align-self: flex-end; } }
</style>
