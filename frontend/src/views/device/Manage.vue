<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import {
  createDevice,
  deleteDevice,
  patchDeviceStatus,
  searchDevices,
  updateDevice,
} from '@/api/device'
import { categoryTree } from '@/api/category'
import { listLabs } from '@/api/lab'
import type { DeviceCategoryNodeVO, DeviceQuery, DeviceStatus, DeviceVO } from '@/types/device'
import type { Lab } from '@/types/lab'
import type { Page } from '@/types/common'
import PageHeader from '@/components/ui/PageHeader.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import TextButton from '@/components/ui/TextButton.vue'
import Tag from '@/components/ui/Tag.vue'
import PageDepthNotice from '@/components/ui/PageDepthNotice.vue'

const loading = ref(false)
const page = ref<Page<DeviceVO>>({ records: [], total: 0, size: 10, current: 1 })
const query = ref<DeviceQuery>({ page: 1, size: 10, keyword: '' })

const categories = ref<DeviceCategoryNodeVO[]>([])
const labs = ref<Lab[]>([])
const router = useRouter()

// 编辑对话框
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const submitting = ref(false)
const form = ref({
  name: '',
  categoryId: undefined as number | undefined,
  labId: undefined as number | undefined,
  brand: '',
  model: '',
  specs: '',
  imageUrl: '',
  status: 'IDLE' as DeviceStatus,
  needApproval: 0,
  maxReservationDays: null as number | null,
  tagsText: '',
  accessoriesText: '',
  description: '',
})

const rules: FormRules = {
  name: [{ required: true, message: '请输入设备名称', trigger: 'blur' }],
  categoryId: [{ required: true, message: '请选择分类', trigger: 'change' }],
  labId: [{ required: true, message: '请选择实验室', trigger: 'change' }],
}

// 修改状态快捷下拉(只取 label/value;Tag variant 由 statusVariant 决定,不在此冗余)
const statusOptions: { label: string; value: DeviceStatus }[] = [
  { label: '空闲', value: 'IDLE' },
  { label: '维护中', value: 'MAINTENANCE' },
  { label: '已停用', value: 'DISABLED' },
  { label: '离线', value: 'OFFLINE' },
  { label: '已退役', value: 'RETIRED' },
]

function statusMeta(s: DeviceStatus) {
  return (
    statusOptions.find((o) => o.value === s) || {
      label: s === 'IN_USE' ? '使用中' : s,
      value: s,
    }
  )
}

// 状态 → Tag variant 语义色；IN_USE 由预约流程产生，不出现在负责人快捷修改项中。
function statusVariant(s: DeviceStatus): 'default' | 'accent' | 'warning' | 'danger' {
  if (s === 'IN_USE') return 'accent'
  if (s === 'MAINTENANCE') return 'warning'
  if (s === 'OFFLINE') return 'danger'
  return 'default'
}

async function load() {
  loading.value = true
  try {
    page.value = await searchDevices({ ...query.value, page: query.value.page || 1 })
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  try {
    const [c, l] = await Promise.all([categoryTree(), listLabs(1, 100)])
    categories.value = c
    labs.value = l.records
  } catch {
    // 拦截器已提示
  }
}

function onSearch() {
  query.value.page = 1
  void load()
}

function onPageChange(p: number) {
  query.value.page = p
  void load()
}
function onSizeChange(s: number) {
  query.value.size = s
  query.value.page = 1
  void load()
}

function resetForm() {
  form.value = {
    name: '',
    categoryId: undefined,
    labId: undefined,
    brand: '',
    model: '',
    specs: '',
    imageUrl: '',
    status: 'IDLE',
    needApproval: 0,
    maxReservationDays: null,
    tagsText: '',
    accessoriesText: '',
    description: '',
  }
}

function openCreate() {
  dialogMode.value = 'create'
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(row: DeviceVO) {
  dialogMode.value = 'edit'
  editingId.value = row.id
  form.value = {
    name: row.name,
    categoryId: row.categoryId ?? undefined,
    labId: row.labId ?? undefined,
    brand: row.brand || '',
    model: row.model || '',
    specs: row.specs || '',
    imageUrl: row.imageUrl || '',
    status: row.status,
    needApproval: row.needApproval,
    maxReservationDays: row.maxReservationDays ?? null,
    tagsText: (row.tags || []).join(', '),
    accessoriesText: (row.accessoryChecklist || []).join('\n'),
    description: row.description || '',
  }
  dialogVisible.value = true
}

function buildPayload() {
  const f = form.value
  const tags = f.tagsText
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  const accessoryChecklist = [...new Set(f.accessoriesText.split(/[\n,，]/).map((s) => s.trim()).filter(Boolean))]
  return {
    name: f.name.trim(),
    categoryId: f.categoryId!,
    labId: f.labId!,
    brand: f.brand || undefined,
    model: f.model || undefined,
    specs: f.specs || undefined,
    imageUrl: f.imageUrl || undefined,
    needApproval: f.needApproval,
    maxReservationDays: f.maxReservationDays ?? undefined,
    tags: tags.length ? tags : undefined,
    accessoryChecklist,
    description: f.description || undefined,
  }
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    const payload = buildPayload()
    if (dialogMode.value === 'create') {
      await createDevice(payload)
      ElMessage.success('已新建')
    } else if (editingId.value != null) {
      // PUT /devices?id=<id> — id 是 @RequestParam
      await updateDevice(editingId.value, payload)
      ElMessage.success('已更新')
    }
    dialogVisible.value = false
    query.value.page = 1
    await load()
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false
  }
}

async function onDelete(row: DeviceVO) {
  try {
    await ElMessageBox.confirm(`确认删除设备「${row.name}」？`, '删除设备', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteDevice(row.id)
    ElMessage.success('已删除')
    query.value.page = 1
    await load()
  } catch {
    // 拦截器已提示
  }
}

async function onChangeStatus(row: DeviceVO, status: DeviceStatus) {
  if (row.status === status) return
  try {
    await patchDeviceStatus(row.id, status)
    row.status = status
    ElMessage.success('状态已更新')
  } catch {
    // 拦截器已提示
  }
}

function fmt(t?: string): string {
  return t ? dayjs(t).format('YYYY-MM-DD') : '—'
}

const dialogTitle = computed(() => (dialogMode.value === 'create' ? '新建设备' : '编辑设备'))
const totalLabel = computed(() => `共 ${page.value.total} 条`)

onMounted(() => {
  loadOptions()
  load()
})
</script>

<template>
  <div class="dmanage">
    <PageHeader title="设备管理" subtitle="维护设备档案、状态与预约策略">
      <template #actions>
        <GhostButton @click="router.push({ name: 'reservation-rules' })">预约规则</GhostButton>
        <GradientButton v-permission="'device:manage'" @click="openCreate">
          新增设备
        </GradientButton>
      </template>
    </PageHeader>

    <div class="dmanage__toolbar">
      <el-input
        v-model="query.keyword"
        placeholder="按名称 / 品牌 / 型号检索"
        clearable
        class="dmanage__search"
        @keyup.enter="onSearch"
        @clear="onSearch"
      />
      <GhostButton @click="onSearch">查询</GhostButton>
    </div>

    <section class="dmanage__signal" aria-label="设备资产概览">
      <div>
        <span class="dmanage__eyebrow">资产档案</span>
        <strong>让每台设备的状态，都一眼可读。</strong>
      </div>
      <span class="dmanage__signal-count">{{ page.total }} <small>台设备</small></span>
    </section>

    <div class="dmanage__table">
      <el-table v-loading="loading" :data="page.records" stripe row-key="id">
        <el-table-column prop="id" label="编号" width="80" />
        <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
        <el-table-column prop="categoryName" label="分类" width="110" show-overflow-tooltip />
        <el-table-column prop="labName" label="实验室" width="120" show-overflow-tooltip />
        <el-table-column label="状态" width="140">
          <template #default="{ row }">
            <el-dropdown
              v-permission="'device:manage'"
              trigger="click"
              @command="(cmd: DeviceStatus) => onChangeStatus(row, cmd)"
            >
              <Tag :variant="statusVariant(row.status)" class="dmanage__status">
                {{ statusMeta(row.status).label }}
                <el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </Tag>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="o in statusOptions"
                    :key="o.value"
                    :command="o.value"
                  >
                    {{ o.label }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
        <el-table-column label="需审批" width="90" align="center">
          <template #default="{ row }">
            <Tag v-if="row.needApproval === 1" variant="warning">是</Tag>
            <span v-else class="dmanage__muted">否</span>
          </template>
        </el-table-column>
        <el-table-column prop="maxReservationDays" label="最长预约/天" width="110" align="right" />
        <el-table-column label="创建时间" width="120">
          <template #default="{ row }">{{ fmt(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <TextButton v-permission="'device:manage'" @click="openEdit(row)">
              编辑
            </TextButton>
            <el-button
              v-permission="'device:manage'"
              link
              type="danger"
              class="dmanage__delete"
              @click="onDelete(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <span class="dmanage__empty">暂无设备</span>
        </template>
      </el-table>

      <div class="dmanage__pager">
        <PageDepthNotice v-if="page.truncated" :total="page.total" />
        <el-pagination
          :current-page="page.current"
          :page-size="page.size"
          :total="page.truncated ? Math.min(page.total, (page.pages || 1) * page.size) : page.total"
          :page-sizes="[10, 20, 50]"
          :layout="`total, sizes, prev, pager, next`"
          :total-text="totalLabel"
          background
          @current-change="onPageChange"
          @size-change="onSizeChange"
        />
      </div>
    </div>

    <el-drawer
      v-model="dialogVisible"
      :with-header="false"
      direction="rtl"
      size="min(620px, 94vw)"
      modal-class="dmanage-drawer"
    >
      <div class="dmanage__drawer">
        <header class="dmanage__drawer-head">
          <div>
            <span class="dmanage__eyebrow">设备资产</span>
            <h2>{{ dialogTitle }}</h2>
          </div>
          <button class="dmanage__drawer-close" type="button" aria-label="关闭" @click="dialogVisible = false">×</button>
        </header>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="100px"
        label-position="right"
      >
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" maxlength="60" show-word-limit />
        </el-form-item>
        <el-form-item label="分类" prop="categoryId">
          <el-tree-select
            v-model="form.categoryId"
            :data="categories"
            :props="{ label: 'name', value: 'id', children: 'children' }"
            check-strictly
            placeholder="选择设备分类"
            filterable
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="实验室" prop="labId">
          <el-select v-model="form.labId" placeholder="选择所属实验室" filterable style="width: 100%">
            <el-option v-for="l in labs" :key="l.id" :label="l.name" :value="l.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="品牌">
          <el-input v-model="form.brand" />
        </el-form-item>
        <el-form-item label="型号">
          <el-input v-model="form.model" />
        </el-form-item>
        <el-form-item label="规格">
          <el-input v-model="form.specs" />
        </el-form-item>
        <el-form-item label="图片URL">
          <el-input v-model="form.imageUrl" />
        </el-form-item>
        <el-form-item label="初始状态">
          <el-select v-model="form.status" :disabled="dialogMode === 'edit'" style="width: 100%">
            <el-option v-for="o in statusOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="需审批">
          <el-switch v-model="form.needApproval" :active-value="1" :inactive-value="0" />
        </el-form-item>
        <el-form-item label="最长预约/天">
          <el-input-number v-model="form.maxReservationDays" :min="1" :max="31" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="form.tagsText" placeholder="多个标签用英文逗号分隔" />
        </el-form-item>
        <el-form-item label="交接配件">
          <el-input
            v-model="form.accessoriesText"
            type="textarea"
            :rows="3"
            maxlength="3000"
            placeholder="每行一个配件，例如：电源线、数据线；交接和归还时将逐项核对"
          />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" maxlength="300" show-word-limit />
        </el-form-item>
      </el-form>
      </div>
      <template #footer>
        <GhostButton @click="dialogVisible = false">取消</GhostButton>
        <GradientButton :loading="submitting" @click="onSubmit">保存</GradientButton>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped lang="scss">
// ============================================================================
// Device Manage 暗表(spec §7 设备管理行)
// 表底/表头/hover/stripe 全由 theme.dark.scss 全局 --el-table-* 桥接接管,
// 此处仅做页面级布局(toolbar / table 容器 / pager 间距 / 操作列微调)。
// ============================================================================

.dmanage {
  display: flex;
  flex-direction: column;
  gap: 20px;

  // ---- 工具栏:sunken 面 + hairline(同 R4.1 device/Index 筛选区模式)----------
  &__toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    padding: 14px 18px;
    background: var(--bg-sunken);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-card);
  }

  &__signal {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 18px;
    padding: 20px 22px;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-card);
    background: linear-gradient(110deg, color-mix(in srgb, var(--accent) 9%, var(--bg-surface)), var(--bg-surface));
  }

  &__eyebrow { display: block; margin-bottom: 8px; color: var(--text-tertiary); font-family: var(--font-mono); font-size: 10px; letter-spacing: .14em; text-transform: uppercase; }
  &__signal strong { color: var(--text-primary); font-family: var(--font-display); font-size: clamp(18px, 2vw, 24px); letter-spacing: -.04em; }
  &__signal-count { color: var(--accent); font-family: var(--font-display); font-size: 28px; font-weight: 700; }
  &__signal-count small { color: var(--text-tertiary); font-family: var(--font-sans); font-size: 12px; font-weight: 500; }

  &__search {
    width: 280px;
  }

  // ---- 表格容器:surface 卡面 + hairline(替代旧 .lab-card,与 R4 风格对齐)----
  &__table {
    padding: 8px;
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-soft);
  }

  &__status {
    cursor: pointer;
  }

  &__muted {
    color: var(--text-tertiary);
  }

  // 操作列:删除按钮 danger 红(保留语义,TextButton 默认 hover→青色不宜表删除)
  &__delete {
    font-weight: 500;
  }

  &__pager {
    display: flex;
    justify-content: flex-end;
    padding: 14px 16px 16px;
  }

  &__empty {
    color: var(--text-secondary);
  }
}

</style>

<style lang="scss">
.dmanage-drawer {
  --el-drawer-bg-color: var(--bg-surface);
  --el-drawer-padding-primary: 0;
}
.dmanage-drawer .el-drawer { background: var(--bg-surface); border-left: 1px solid var(--border-default); box-shadow: var(--shadow-soft); }
.dmanage-drawer .el-drawer__body { padding: 0; }
.dmanage-drawer .el-drawer__footer { display: flex; justify-content: flex-end; gap: 10px; padding: 16px 28px; border-top: 1px solid var(--border-subtle); }
.dmanage__drawer { display: flex; min-height: 100%; box-sizing: border-box; flex-direction: column; padding: 28px; }
.dmanage__drawer-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.dmanage__drawer-head h2 { margin: 5px 0 0; color: var(--text-primary); font-family: var(--font-display); font-size: 28px; letter-spacing: -.05em; }
.dmanage__drawer-close { width: 34px; height: 34px; border: 1px solid var(--border-default); border-radius: 50%; background: transparent; color: var(--text-tertiary); cursor: pointer; font-size: 22px; line-height: 1; }
.dmanage__drawer-close:hover { border-color: var(--border-accent); color: var(--accent); }
.dmanage__drawer .el-form { flex: 1; }
@media (max-width: 620px) {
  .dmanage__signal { align-items: flex-start; flex-direction: column; }
  .dmanage__drawer { padding: 22px 18px; }
}
</style>
