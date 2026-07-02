<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import dayjs from 'dayjs'
import { createUser, deleteUser, listUsers, patchUserStatus, updateUser } from '@/api/user'
import type { UserCreatePayload, UserQuery, UserVO } from '@/types/user'
import type { Page } from '@/types/common'

const loading = ref(false)
const page = ref<Page<UserVO>>({ records: [], total: 0, size: 10, current: 1 })
const query = ref<UserQuery>({ page: 1, size: 10, username: '', realName: '' })

// 角色选项
const roleOptions = [
  { label: '系统管理员', value: 'SYS_ADMIN' },
  { label: '实验室管理员', value: 'LAB_ADMIN' },
  { label: '教师', value: 'TEACHER' },
  { label: '学生', value: 'STUDENT' },
  { label: '职工', value: 'STAFF' },
]
const userTypeOptions = [
  { label: '学生', value: 'STUDENT' },
  { label: '教师', value: 'TEACHER' },
  { label: '职工', value: 'STAFF' },
]

// 编辑对话框
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const submitting = ref(false)
const form = ref({
  username: '',
  password: '',
  realName: '',
  phone: '',
  email: '',
  userType: 'STUDENT',
  deptName: '',
  roleCodes: [] as string[],
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    {
      validator: (_r, _v, cb) => {
        if (dialogMode.value === 'create' && !form.value.password) {
          cb(new Error('请输入密码'))
        } else {
          cb()
        }
      },
      trigger: 'blur',
    },
  ],
}

async function load() {
  loading.value = true
  try {
    page.value = await listUsers(query.value)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
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
    username: '',
    password: '',
    realName: '',
    phone: '',
    email: '',
    userType: 'STUDENT',
    deptName: '',
    roleCodes: [],
  }
}

function openCreate() {
  dialogMode.value = 'create'
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(row: UserVO) {
  dialogMode.value = 'edit'
  editingId.value = row.id
  form.value = {
    username: row.username,
    password: '',
    realName: row.realName || '',
    phone: row.phone || '',
    email: row.email || '',
    userType: row.userType || 'STUDENT',
    deptName: row.deptName || '',
    roleCodes: row.roles || [],
  }
  dialogVisible.value = true
}

function buildPayload(): UserCreatePayload {
  const f = form.value
  return {
    username: f.username.trim(),
    password: f.password || undefined,
    realName: f.realName || undefined,
    phone: f.phone || undefined,
    email: f.email || undefined,
    userType: f.userType,
    deptName: f.deptName || undefined,
    roleCodes: f.roleCodes,
  }
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    const payload = buildPayload()
    if (dialogMode.value === 'create') {
      await createUser(payload)
      ElMessage.success('已创建')
    } else if (editingId.value != null) {
      await updateUser(editingId.value, payload)
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

async function onToggleStatus(row: UserVO) {
  const next = row.status === 1 ? 0 : 1
  const verb = next === 1 ? '解封' : '封禁'
  try {
    await ElMessageBox.confirm(`确认${verb}用户「${row.username}」？`, verb, {
      type: 'warning',
      confirmButtonText: '确认',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await patchUserStatus(row.id, next)
    row.status = next
    ElMessage.success('已' + verb)
  } catch {
    // 拦截器已提示
  }
}

async function onDelete(row: UserVO) {
  try {
    await ElMessageBox.confirm(`确认删除用户「${row.username}」？`, '删除用户', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteUser(row.id)
    ElMessage.success('已删除')
    load()
  } catch {
    // 拦截器已提示
  }
}

function fmt(t?: string): string {
  return t ? dayjs(t).format('YYYY-MM-DD') : '—'
}

const dialogTitle = computed(() => (dialogMode.value === 'create' ? '新建用户' : '编辑用户'))
const totalLabel = computed(() => `共 ${page.value.total} 条`)

onMounted(load)
</script>

<template>
  <div class="umanage">
    <div class="umanage__head">
      <h1 class="umanage__title">用户管理</h1>
      <p class="umanage__subtitle">管理系统账号、角色与启用状态</p>
    </div>

    <div class="lab-card umanage__toolbar">
      <el-input
        v-model="query.username"
        placeholder="用户名"
        clearable
        style="width: 180px"
        @keyup.enter="onSearch"
        @clear="onSearch"
      />
      <el-input
        v-model="query.realName"
        placeholder="真实姓名"
        clearable
        style="width: 180px"
        @keyup.enter="onSearch"
        @clear="onSearch"
      />
      <el-button type="primary" @click="onSearch">查询</el-button>
      <div class="umanage__spacer" />
      <el-button type="primary" @click="openCreate">新增用户</el-button>
    </div>

    <div class="lab-card umanage__table">
      <el-table v-loading="loading" :data="page.records" stripe row-key="id">
        <el-table-column prop="id" label="编号" width="70" />
        <el-table-column prop="username" label="用户名" min-width="120" show-overflow-tooltip />
        <el-table-column prop="realName" label="姓名" min-width="110" show-overflow-tooltip />
        <el-table-column prop="userType" label="类型" width="90" />
        <el-table-column prop="deptName" label="院系" min-width="120" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.status === 1" type="success" effect="light" round>启用</el-tag>
            <el-tag v-else type="danger" effect="light" round>禁用</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="角色" min-width="160">
          <template #default="{ row }">
            <el-tag
              v-for="r in row.roles"
              :key="r"
              type="info"
              effect="plain"
              round
              style="margin-right: 4px"
            >
              {{ r }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="120">
          <template #default="{ row }">{{ fmt(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button
              link
              :type="row.status === 1 ? 'warning' : 'success'"
              @click="onToggleStatus(row)"
            >
              {{ row.status === 1 ? '封禁' : '解封' }}
            </el-button>
            <el-button link type="danger" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <span class="umanage__empty">暂无用户</span>
        </template>
      </el-table>

      <div class="umanage__pager">
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

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="560px">
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="90px"
        label-position="right"
      >
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="dialogMode === 'edit'" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="dialogMode === 'edit' ? '留空表示不改密码' : '请输入密码'"
          />
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="form.realName" />
        </el-form-item>
        <el-form-item label="手机">
          <el-input v-model="form.phone" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" />
        </el-form-item>
        <el-form-item label="用户类型">
          <el-select v-model="form.userType" style="width: 100%">
            <el-option v-for="o in userTypeOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="院系">
          <el-input v-model="form.deptName" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.roleCodes" multiple placeholder="分配角色" style="width: 100%">
            <el-option v-for="o in roleOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
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
.umanage {
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
