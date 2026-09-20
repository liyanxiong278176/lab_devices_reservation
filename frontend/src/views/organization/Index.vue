<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { createCollege, listColleges, listManagers, updateCollege } from '@/api/college'
import { createLab, listLabs, updateLab } from '@/api/lab'
import type { CollegeVO, ManagerVO } from '@/types/college'
import type { Lab } from '@/types/lab'
import PageHeader from '@/components/ui/PageHeader.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import TextButton from '@/components/ui/TextButton.vue'
import Tag from '@/components/ui/Tag.vue'

type Panel = 'colleges' | 'labs'

const activePanel = ref<Panel>('colleges')
const loading = ref(false)
const colleges = ref<CollegeVO[]>([])
const labs = ref<Lab[]>([])
const managers = ref<ManagerVO[]>([])

const dialogVisible = ref(false)
const dialogMode = ref<'college-create' | 'college-edit' | 'lab-create' | 'lab-edit'>('college-create')
const editingId = ref<number | null>(null)
const submitting = ref(false)
const formRef = ref<FormInstance>()
const collegeForm = ref({ code: '', name: '', managerId: undefined as number | undefined })
const labForm = ref({
  collegeId: undefined as number | undefined,
  name: '',
  location: '',
  managerId: undefined as number | undefined,
  description: '',
})

const rules: FormRules = {
  code: [{ required: true, message: '请输入学院编码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  collegeId: [{ required: true, message: '请选择所属学院', trigger: 'change' }],
}

const dialogTitle = computed(() => {
  if (dialogMode.value === 'college-create') return '新增学院'
  if (dialogMode.value === 'college-edit') return '编辑学院'
  if (dialogMode.value === 'lab-create') return '新增实验室'
  return '编辑实验室'
})

const isCollegeForm = computed(() => dialogMode.value.startsWith('college'))

async function load() {
  loading.value = true
  try {
    const [collegeRows, labPage] = await Promise.all([listColleges(), listLabs(1, 200)])
    colleges.value = collegeRows
    labs.value = labPage.records
    if (labForm.value.collegeId) await loadManagers(labForm.value.collegeId)
  } finally {
    loading.value = false
  }
}

async function loadManagers(collegeId?: number) {
  managers.value = collegeId ? await listManagers(collegeId) : []
}

watch(() => labForm.value.collegeId, (collegeId) => {
  labForm.value.managerId = undefined
  void loadManagers(collegeId)
})

function resetForms() {
  collegeForm.value = { code: '', name: '', managerId: undefined }
  labForm.value = {
    collegeId: colleges.value[0]?.id,
    name: '',
    location: '',
    managerId: undefined,
    description: '',
  }
  managers.value = []
}

function openCollegeCreate() {
  resetForms()
  dialogMode.value = 'college-create'
  editingId.value = null
  dialogVisible.value = true
}

function openCollegeEdit(row: CollegeVO) {
  collegeForm.value = { code: row.code, name: row.name, managerId: row.managerId ?? undefined }
  dialogMode.value = 'college-edit'
  editingId.value = row.id
  dialogVisible.value = true
  void loadManagers(row.id)
}

function openLabCreate() {
  resetForms()
  dialogMode.value = 'lab-create'
  editingId.value = null
  dialogVisible.value = true
  void loadManagers(labForm.value.collegeId)
}

function openLabEdit(row: Lab) {
  labForm.value = {
    collegeId: row.collegeId ?? undefined,
    name: row.name,
    location: row.location || '',
    managerId: row.managerId ?? undefined,
    description: row.description || '',
  }
  dialogMode.value = 'lab-edit'
  editingId.value = row.id
  dialogVisible.value = true
  void loadManagers(row.collegeId ?? undefined)
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    if (isCollegeForm.value) {
      if (dialogMode.value === 'college-create') {
        await createCollege({ ...collegeForm.value, managerId: collegeForm.value.managerId ?? null })
      } else if (editingId.value != null) {
        await updateCollege(editingId.value, { ...collegeForm.value, managerId: collegeForm.value.managerId ?? null })
      }
    } else if (labForm.value.collegeId) {
      if (dialogMode.value === 'lab-create') {
        await createLab({ ...labForm.value, collegeId: labForm.value.collegeId, managerId: labForm.value.managerId ?? null })
      } else if (editingId.value != null) {
        await updateLab(editingId.value, { ...labForm.value, collegeId: labForm.value.collegeId, managerId: labForm.value.managerId ?? null })
      }
    }
    ElMessage.success('组织配置已保存')
    dialogVisible.value = false
    await load()
  } finally {
    submitting.value = false
  }
}

function collegeName(id?: number | null) {
  return colleges.value.find((college) => college.id === id)?.name || '—'
}

onMounted(load)
</script>

<template>
  <div class="organization">
    <PageHeader title="组织管理" subtitle="配置学院、实验室和业务负责人，控制设备管理范围">
      <template #actions>
        <GradientButton v-if="activePanel === 'colleges'" @click="openCollegeCreate">新增学院</GradientButton>
        <GradientButton v-else @click="openLabCreate">新增实验室</GradientButton>
      </template>
    </PageHeader>

    <div class="organization__hint">
      <span class="organization__hint-dot" /> 每个学院和实验室设置一名主负责人；负责人可以同时负责多个实验室。
    </div>

    <el-tabs v-model="activePanel" class="organization__tabs">
      <el-tab-pane label="学院配置" name="colleges">
        <div v-loading="loading" class="organization__table panel-card">
          <el-table :data="colleges" stripe row-key="id">
            <el-table-column prop="code" label="编码" width="140" />
            <el-table-column prop="name" label="学院名称" min-width="180" />
            <el-table-column label="主负责人" min-width="180">
              <template #default="{ row }">
                <span>{{ row.managerName || '暂未配置' }}</span>
                <Tag v-if="row.managerId" variant="accent" size="small">主负责人</Tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }"><TextButton @click="openCollegeEdit(row)">编辑</TextButton></template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="实验室配置" name="labs">
        <div v-loading="loading" class="organization__table panel-card">
          <el-table :data="labs" stripe row-key="id">
            <el-table-column prop="name" label="实验室" min-width="180" />
            <el-table-column label="所属学院" min-width="160">
              <template #default="{ row }">{{ row.collegeName || collegeName(row.collegeId) }}</template>
            </el-table-column>
            <el-table-column prop="location" label="位置" min-width="160" show-overflow-tooltip />
            <el-table-column label="主负责人" min-width="160">
              <template #default="{ row }">{{ row.managerName || '暂未配置' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }"><TextButton @click="openLabEdit(row)">编辑</TextButton></template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="520px" :close-on-click-modal="false">
      <el-form ref="formRef" :model="isCollegeForm ? collegeForm : labForm" :rules="rules" label-width="100px">
        <template v-if="isCollegeForm">
          <el-form-item label="学院编码" prop="code"><el-input v-model="collegeForm.code" maxlength="64" /></el-form-item>
          <el-form-item label="学院名称" prop="name"><el-input v-model="collegeForm.name" maxlength="128" /></el-form-item>
          <el-form-item label="主负责人">
            <el-select v-model="collegeForm.managerId" clearable placeholder="可暂不配置" style="width: 100%">
              <el-option v-for="manager in managers" :key="manager.id" :label="`${manager.realName || manager.username} (${manager.username})`" :value="manager.id" />
            </el-select>
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="所属学院" prop="collegeId">
            <el-select v-model="labForm.collegeId" :disabled="dialogMode === 'lab-edit'" style="width: 100%">
              <el-option v-for="college in colleges" :key="college.id" :label="college.name" :value="college.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="实验室名称" prop="name"><el-input v-model="labForm.name" maxlength="100" /></el-form-item>
          <el-form-item label="位置"><el-input v-model="labForm.location" maxlength="200" /></el-form-item>
          <el-form-item label="主负责人">
            <el-select v-model="labForm.managerId" clearable placeholder="可暂不配置" style="width: 100%">
              <el-option v-for="manager in managers" :key="manager.id" :label="`${manager.realName || manager.username} (${manager.username})`" :value="manager.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="描述"><el-input v-model="labForm.description" type="textarea" :rows="3" maxlength="500" /></el-form-item>
        </template>
      </el-form>
      <template #footer>
        <GhostButton @click="dialogVisible = false">取消</GhostButton>
        <GradientButton :loading="submitting" @click="onSubmit">保存配置</GradientButton>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.organization { display: flex; flex-direction: column; gap: 18px; color: var(--text-primary); }
.organization__hint { display: flex; align-items: center; gap: 8px; padding: 12px 16px; color: var(--text-secondary); background: var(--bg-sunken); border: 1px solid var(--border-subtle); border-radius: var(--radius-control); font-size: 12px; }
.organization__hint-dot { width: 8px; height: 8px; flex: none; border-radius: 50%; background: var(--accent); box-shadow: 0 0 10px color-mix(in srgb, var(--accent) 60%, transparent); }
.organization__tabs :deep(.el-tabs__item) { color: var(--text-secondary); }.organization__tabs :deep(.el-tabs__item.is-active) { color: var(--accent); }.organization__tabs :deep(.el-tabs__active-bar) { background: var(--accent); }
.panel-card { padding: 8px; background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: var(--radius-card); box-shadow: var(--shadow-soft); }
.organization__table :deep(.el-tag) { margin-left: 8px; }
</style>
