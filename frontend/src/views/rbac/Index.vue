<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createRole, deleteRole, listPermissions, listRoles, renameRole, updateRolePermissions } from '@/api/rbac'
import type { PermissionVO, RoleVO } from '@/api/rbac'
import PageHeader from '@/components/ui/PageHeader.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'

const loading = ref(false)
const roles = ref<RoleVO[]>([])
const permissions = ref<PermissionVO[]>([])
const editorVisible = ref(false)
const editorMode = ref<'create' | 'permissions' | 'rename'>('create')
const activeRole = ref<RoleVO | null>(null)
const selectedPermissions = ref<string[]>([])
const saving = ref(false)
const form = reactive({ role_code: '', role_name: '' })

const permissionsByModule = computed(() => {
  const grouped = new Map<string, PermissionVO[]>()
  for (const permission of permissions.value) {
    const items = grouped.get(permission.module) || []
    items.push(permission)
    grouped.set(permission.module, items)
  }
  return [...grouped.entries()].map(([module, items]) => ({ module, items }))
})

async function load() {
  loading.value = true
  try {
    ;[roles.value, permissions.value] = await Promise.all([listRoles(), listPermissions()])
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editorMode.value = 'create'
  activeRole.value = null
  selectedPermissions.value = []
  form.role_code = ''
  form.role_name = ''
  editorVisible.value = true
}

function openPermissions(role: RoleVO) {
  if (role.code === 'SYS_ADMIN') return
  editorMode.value = 'permissions'
  activeRole.value = role
  selectedPermissions.value = [...role.permissions]
  editorVisible.value = true
}

function openRename(role: RoleVO) {
  if (role.is_system) return
  editorMode.value = 'rename'
  activeRole.value = role
  form.role_name = role.name
  editorVisible.value = true
}

async function save() {
  saving.value = true
  try {
    if (editorMode.value === 'create') {
      await createRole({
        role_code: form.role_code.trim().toUpperCase(),
        role_name: form.role_name.trim(),
        permission_codes: selectedPermissions.value,
      })
      ElMessage.success('角色已创建')
    } else if (editorMode.value === 'rename' && activeRole.value) {
      await renameRole(activeRole.value.id, form.role_name.trim())
      ElMessage.success('角色名称已更新')
    } else if (editorMode.value === 'permissions' && activeRole.value) {
      await updateRolePermissions(activeRole.value.id, selectedPermissions.value)
      ElMessage.success('角色权限已更新，用户下次请求立即生效')
    }
    editorVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function remove(role: RoleVO) {
  if (role.is_system) return
  try {
    await ElMessageBox.confirm(`删除角色“${role.name}”？已分配给用户的角色不能删除。`, '删除角色', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await deleteRole(role.id)
    ElMessage.success('角色已删除')
    await load()
  } catch {
    // Cancel and API errors are handled by the shared request layer.
  }
}

onMounted(() => void load())
</script>

<template>
  <section class="rbac-page">
    <PageHeader title="角色与权限" subtitle="集中配置角色能力，服务端权限变更会立即刷新生效。">
      <template #actions>
        <GradientButton @click="openCreate">新建角色</GradientButton>
      </template>
    </PageHeader>

    <div class="rbac-page__notice">
      系统管理员角色不可删除或修改权限；内置角色不可改名。更改角色权限后，所有会话会重新读取数据库中的授权版本。
    </div>

    <el-table :data="roles" v-loading="loading" row-key="id" class="rbac-page__table">
      <el-table-column label="角色" min-width="220">
        <template #default="{ row }">
          <div class="rbac-page__role">
            <strong>{{ row.name }}</strong>
            <code>{{ row.code }}</code>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="130">
        <template #default="{ row }">{{ row.is_system ? '系统角色' : '自定义角色' }}</template>
      </el-table-column>
      <el-table-column label="权限数" width="110">
        <template #default="{ row }">{{ row.permissions.length }}</template>
      </el-table-column>
      <el-table-column label="主要权限" min-width="320">
        <template #default="{ row }">
          <div class="rbac-page__chips">
            <span v-for="code in row.permissions.slice(0, 5)" :key="code">{{ code }}</span>
            <span v-if="row.permissions.length > 5">+{{ row.permissions.length - 5 }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="250" fixed="right">
        <template #default="{ row }">
          <div class="rbac-page__actions">
            <GhostButton :disabled="row.code === 'SYS_ADMIN'" @click="openPermissions(row)">权限</GhostButton>
            <GhostButton :disabled="row.is_system" @click="openRename(row)">改名</GhostButton>
            <button class="rbac-page__delete" :disabled="row.is_system" @click="remove(row)">删除</button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="editorVisible"
      :title="editorMode === 'create' ? '新建角色' : editorMode === 'rename' ? '修改角色名称' : `配置权限 · ${activeRole?.name || ''}`"
      width="min(760px, 92vw)"
      append-to-body
    >
      <el-form v-if="editorMode !== 'permissions'" label-position="top">
        <el-form-item v-if="editorMode === 'create'" label="角色代码">
          <el-input v-model="form.role_code" placeholder="如：SAFETY_OFFICER" maxlength="50" />
        </el-form-item>
        <el-form-item label="角色名称">
          <el-input v-model="form.role_name" maxlength="50" placeholder="输入便于识别的名称" />
        </el-form-item>
      </el-form>
      <div v-else class="rbac-page__permission-groups">
        <section v-for="group in permissionsByModule" :key="group.module">
          <h3>{{ group.module }}</h3>
          <el-checkbox-group v-model="selectedPermissions">
            <el-checkbox v-for="permission in group.items" :key="permission.code" :value="permission.code">
              <span>{{ permission.name }}</span>
              <code>{{ permission.code }}</code>
            </el-checkbox>
          </el-checkbox-group>
        </section>
      </div>
      <template #footer>
        <GhostButton @click="editorVisible = false">取消</GhostButton>
        <GradientButton :loading="saving" @click="save">保存</GradientButton>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped lang="scss">
.rbac-page { display: grid; gap: 20px; }
.rbac-page__notice { padding: 14px 18px; border-left: 3px solid var(--accent); color: var(--text-secondary); background: var(--bg-elevated); border-radius: 10px; }
.rbac-page__table { width: 100%; }
.rbac-page__role { display: grid; gap: 5px; }
.rbac-page__role code, .rbac-page__chips code, .rbac-page__permission-groups code { color: var(--text-tertiary); font-size: 12px; }
.rbac-page__chips { display: flex; flex-wrap: wrap; gap: 6px; }
.rbac-page__chips span { padding: 4px 8px; border-radius: 999px; background: var(--bg-elevated); color: var(--text-secondary); font-size: 12px; }
.rbac-page__actions { display: flex; align-items: center; gap: 6px; }
.rbac-page__delete { border: 0; background: transparent; color: var(--danger); cursor: pointer; }
.rbac-page__delete:disabled { color: var(--text-tertiary); cursor: not-allowed; }
.rbac-page__permission-groups { display: grid; gap: 20px; max-height: min(60vh, 640px); overflow: auto; }
.rbac-page__permission-groups section { padding-bottom: 16px; border-bottom: 1px solid var(--border-subtle); }
.rbac-page__permission-groups h3 { margin: 0 0 12px; text-transform: capitalize; }
.rbac-page__permission-groups :deep(.el-checkbox-group) { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.rbac-page__permission-groups :deep(.el-checkbox) { height: auto; align-items: flex-start; }
.rbac-page__permission-groups :deep(.el-checkbox__label) { display: grid; gap: 3px; white-space: normal; }
</style>
