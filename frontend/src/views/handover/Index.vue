<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import {
  acceptReservationReturn,
  handoverReservation,
  pendingHandovers,
} from '@/api/reservation'
import type { ReservationVO } from '@/types/reservation'
import type { Page } from '@/types/common'
import { useCursorPageChain } from '@/composables/useCursorPageChain'
import PageHeader from '@/components/ui/PageHeader.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import GlowCard from '@/components/ui/GlowCard.vue'
import Tag from '@/components/ui/Tag.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

type HandoverTab = 'PENDING' | 'RETURN_PENDING'
const activeStatus = ref<HandoverTab>('PENDING')
const page = ref<Page<ReservationVO>>({ records: [], total: 0, size: 12, current: 1 })
const loading = ref(false)
const query = ref({ page: 1, size: 12 })
const cursorPager = useCursorPageChain<ReservationVO>((cursor) => pendingHandovers(
  activeStatus.value,
  1,
  query.value.size,
  cursor,
))
const dialogVisible = ref(false)
const dialogMode = ref<'handover' | 'return'>('handover')
const target = ref<ReservationVO | null>(null)
const condition = ref<'NORMAL' | 'DAMAGED' | 'MISSING'>('NORMAL')
const note = ref('')
const saving = ref(false)

const tabs = [
  { label: '待交接', value: 'PENDING' },
  { label: '待验收', value: 'RETURN_PENDING' },
]

const subtitle = computed(() => `当前范围内 ${page.value.total} 条记录`)

async function load() {
  loading.value = true
  try {
    page.value = await cursorPager.load(query.value.page)
  } finally {
    loading.value = false
  }
}

function switchTab(value: string | number) {
  activeStatus.value = value as HandoverTab
  query.value.page = 1
  cursorPager.reset()
  void load()
}

function openAction(row: ReservationVO, mode: 'handover' | 'return') {
  target.value = row
  dialogMode.value = mode
  condition.value = 'NORMAL'
  note.value = ''
  dialogVisible.value = true
}

async function submitAction() {
  if (!target.value) return
  if (condition.value !== 'NORMAL' && !note.value.trim()) {
    ElMessage.warning('发现损坏或缺失时，请补充验收说明')
    return
  }
  saving.value = true
  try {
    const payload = { condition: condition.value, note: note.value.trim() || undefined }
    if (dialogMode.value === 'handover') {
      await handoverReservation(target.value.id, payload)
      ElMessage.success('设备已完成交接，用户可以开始使用')
    } else {
      await acceptReservationReturn(target.value.id, payload)
      ElMessage.success('归还已验收，设备状态已更新')
    }
    dialogVisible.value = false
    cursorPager.reset()
    await load()
  } finally {
    saving.value = false
  }
}

async function markDamaged(row: ReservationVO) {
  try {
    await ElMessageBox.confirm('将设备标记为损坏并完成验收？', '异常验收', { type: 'warning' })
    target.value = row
    dialogMode.value = 'return'
    condition.value = 'DAMAGED'
    note.value = ''
    dialogVisible.value = true
  } catch {
    // cancelled
  }
}

function fmt(value?: string) {
  return value ? dayjs(value).format('YYYY-MM-DD') : '—'
}

onMounted(load)
</script>

<template>
  <div class="handover-page">
    <PageHeader title="设备交接" :subtitle="subtitle">
      <template #actions>
        <span class="handover-page__rule">外借设备才需要负责人现场交接与归还验收</span>
      </template>
    </PageHeader>

    <section class="handover-page__filter">
      <SegmentedControl :model-value="activeStatus" :options="tabs" size="sm" @update:model-value="switchTab" />
    </section>

    <div v-loading="loading" class="handover-page__grid">
      <GlowCard v-for="row in page.records" :key="row.id" as="article" class="handover-card">
        <header class="handover-card__head">
          <div>
            <span class="handover-card__eyebrow">RESERVATION #{{ row.id }}</span>
            <h2>#{{ row.deviceAssetCode || row.deviceId }} · {{ row.deviceName }}</h2>
          </div>
          <Tag :variant="activeStatus === 'PENDING' ? 'warning' : 'accent'" size="small" round>
            {{ activeStatus === 'PENDING' ? '待交接' : '待验收' }}
          </Tag>
        </header>
        <dl class="handover-card__facts">
          <div><dt>实验室</dt><dd>{{ row.deviceLabName || '—' }}</dd></div>
          <div><dt>预约人</dt><dd>#{{ row.userId }}</dd></div>
          <div><dt>预约日期</dt><dd>{{ fmt(row.startDate) }} 至 {{ fmt(row.endDate) }}</dd></div>
          <div><dt>用途</dt><dd>{{ row.purpose || '—' }}</dd></div>
        </dl>
        <footer class="handover-card__foot">
          <span>{{ activeStatus === 'PENDING' ? '请核对外观、配件与交接备注' : '请核对归还状态并完成验收' }}</span>
          <div>
            <GhostButton v-if="activeStatus === 'RETURN_PENDING'" size="small" @click="markDamaged(row)">异常验收</GhostButton>
            <GradientButton size="small" @click="openAction(row, activeStatus === 'PENDING' ? 'handover' : 'return')">
              {{ activeStatus === 'PENDING' ? '完成交接' : '确认验收' }}
            </GradientButton>
          </div>
        </footer>
      </GlowCard>
      <div v-if="!loading && page.records.length === 0" class="handover-page__empty">
        <EmptyState icon="Checked" :title="activeStatus === 'PENDING' ? '暂无待交接设备' : '暂无待验收设备'" description="设备交接状态会在预约审批后实时更新。" />
      </div>
    </div>

    <div v-if="page.records.length" class="handover-page__pager">
      <el-pagination
        :current-page="page.current"
        :page-size="page.size"
        :total="page.total"
        layout="total, prev, pager, next"
        background
        @current-change="(value: number) => { query.page = value; void load() }"
      />
    </div>

    <el-dialog v-model="dialogVisible" :title="dialogMode === 'handover' ? '完成设备交接' : '确认归还验收'" width="520px">
      <div class="handover-dialog">
        <p>设备：{{ target?.deviceName }}（{{ target?.deviceAssetCode || `#${target?.deviceId}` }}）</p>
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
.handover-card__foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 14px; border-top: 1px solid var(--border-subtle); color: var(--text-tertiary); font-size: 11px; }.handover-card__foot > div { display: flex; gap: 8px; }
.handover-dialog { display: grid; gap: 16px; }.handover-dialog p { margin: 0; color: var(--text-secondary); }.handover-page__pager { align-self: flex-end; }
@media (max-width: 620px) { .handover-card__facts { grid-template-columns: 1fr; }.handover-card__foot { align-items: flex-start; flex-direction: column; }.handover-card__foot > div { align-self: flex-end; } }
</style>
