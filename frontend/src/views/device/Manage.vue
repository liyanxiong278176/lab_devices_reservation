<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
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

const loading = ref(false)
const page = ref<Page<DeviceVO>>({ records: [], total: 0, size: 10, current: 1 })
const query = ref<DeviceQuery>({ page: 1, size: 10, keyword: '' })

const categories = ref<DeviceCategoryNodeVO[]>([])
const labs = ref<Lab[]>([])

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
  maxReservationHours: '' as number | string,
  pricePerHour: '' as number | string,
  tagsText: '',
  description: '',
})

const rules: FormRules = {
  name: [{ required: true, message: '请输入设备名称', trigger: 'blur' }],
  categoryId: [{ required: true, message: '请选择分类', trigger: 'change' }],
  labId: [{ required: true, message: '请选择实验室', trigger: 'change' }],
}

// 修改状态快捷下拉
const statusOptions: { label: string; value: DeviceStatus; type: 'success' | 'warning' | 'info' }[] = [
  { label: '空闲', value: 'IDLE', type: 'success' },
  { label: '使用中', value: 'IN_USE', type: 'warning' },
  { label: '维护中', value: 'MAINTENANCE', type: 'info' },
]

function statusMeta(s: DeviceStatus) {
  return statusOptions.find((o) => o.value === s) || statusOptions[0]
}

async function load() {
  loading.value = true
  try {
    page.value = await searchDevices(query.value)
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
  load()
}

function onPageChange(p: number) {
  query.value.page = p
  load()
}
function onSizeChange(s: number) {
  query.value.size = s
  query.value.page = 1
  load()
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
    maxReservationHours: '',
    pricePerHour: '',
    tagsText: '',
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
    maxReservationHours: row.maxReservationHours ?? '',
    pricePerHour: row.pricePerHour ?? '',
    tagsText: (row.tags || []).join(', '),
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
  return {
    name: f.name.trim(),
    categoryId: f.categoryId!,
    labId: f.labId!,
    brand: f.brand || undefined,
    model: f.model || undefined,
    specs: f.specs || undefined,
    imageUrl: f.imageUrl || undefined,
    needApproval: f.needApproval,
    maxReservationHours: f.maxReservationHours === '' ? undefined : f.maxReservationHours,
    pricePerHour: f.pricePerHour === '' ? undefined : f.pricePerHour,
    tags: tags.length ? tags : undefined,
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
    load()
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
    <div class="dmanage__head">
      <h1 class="dmanage__title">设备管理</h1>
      <p class="dmanage__subtitle">维护设备档案、状态与预约策略</p>
    </div>

    <div class="lab-card dmanage__toolbar">
      <el-input
        v-model="query.keyword"
        placeholder="按名称/品牌/型号检索"
        clearable
        style="width: 280px"
        @keyup.enter="onSearch"
        @clear="onSearch"
      />
      <el-button type="primary" @click="onSearch">查询</el-button>
      <div class="dmanage__spacer" />
      <el-button v-permission="'device:manage'" type="primary" @click="openCreate">新增设备</el-button>
    </div>

    <div class="lab-card dmanage__table">
      <el-table v-loading="loading" :data="page.records" stripe row-key="id">
        <el-table-column prop="id" label="编号" width="80" />
        <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
        <el-table-column prop="categoryName" label="分类" width="110" show-overflow-tooltip />
        <el-table-column prop="labName" label="实验室" width="120" show-overflow-tooltip />
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-dropdown
              v-permission="'device:manage'"
              trigger="click"
              @command="(cmd: DeviceStatus) => onChangeStatus(row, cmd)"
            >
              <el-tag :type="statusMeta(row.status).type" effect="light" round class="dmanage__status">
                {{ statusMeta(row.status).label }}
                <el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-tag>
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
            <el-tag v-if="row.needApproval === 1" type="warning" effect="plain" round>是</el-tag>
            <span v-else class="dmanage__muted">否</span>
          </template>
        </el-table-column>
        <el-table-column prop="pricePerHour" label="单价/时" width="100" align="right" />
        <el-table-column label="创建时间" width="120">
          <template #default="{ row }">{{ fmt(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button v-permission="'device:manage'" link type="primary" @click="openEdit(row)">
              编辑
            </el-button>
            <el-button v-permission="'device:manage'" link type="danger" @click="onDelete(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <span class="dmanage__empty">暂无设备</span>
        </template>
      </el-table>

      <div class="dmanage__pager">
        <el-pagination
          :current-page="page.current"
          :page-size="page.size"
          :total="page.total"
          :page-sizes="[10, 20, 50]"
          :layout="`total, sizes, prev, pager, next`"
          :total-text="totalLabel"
          background
          @current-change="onPageChange"
          @size-change="onSizeChange"
        />
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="640px">
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
        <el-form-item label="最长预约/时">
          <el-input v-model="form.maxReservationHours" placeholder="如 4" />
        </el-form-item>
        <el-form-item label="单价/时">
          <el-input v-model="form.pricePerHour" placeholder="如 10.00" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="form.tagsText" placeholder="多个标签用英文逗号分隔" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" maxlength="300" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.dmanage {
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

  &__toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 20px;
    margin-bottom: 16px;
  }

  &__spacer {
    flex: 1;
  }

  &__table {
    padding: 8px;
  }

  &__status {
    cursor: pointer;
  }

  &__muted {
    color: var(--el-text-color-secondary);
  }

  &__pager {
    display: flex;
    justify-content: flex-end;
    padding: 16px;
  }

  &__empty {
    color: var(--el-text-color-secondary);
  }
}
</style>
