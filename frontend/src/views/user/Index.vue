<script setup lang="ts">
// 用户管理(R6 重构):PageHeader + 暗表 + 角色 Tag + 状态 Tag + 深色 el-drawer 表单。
// 数据/CRUD/启停/分页——逻辑零改,仅换展示层。
// 表底/表头/hover/stripe 由 theme.dark.scss 全局 --el-table-* 桥接;drawer 深色由本页
// 非 scoped style 块(因 drawer 默认 append-to-body,scoped 选不到)通过 modal-class 圈定。
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import dayjs from 'dayjs'
import { listColleges } from '@/api/college'
import { createUser, deleteUser, listUsers, patchUserStatus, updateUser } from '@/api/user'
import type { CollegeVO } from '@/types/college'
import type { UserCreatePayload, UserQuery, UserVO } from '@/types/user'
import type { Page } from '@/types/common'
import PageHeader from '@/components/ui/PageHeader.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import TextButton from '@/components/ui/TextButton.vue'
import Tag from '@/components/ui/Tag.vue'
import { useCursorPageChain } from '@/composables/useCursorPageChain'

const loading = ref(false)
const page = ref<Page<UserVO>>({ records: [], total: 0, size: 10, current: 1 })
const query = ref<UserQuery>({ page: 1, size: 10, username: '', realName: '' })
const colleges = ref<CollegeVO[]>([])
const cursorPager = useCursorPageChain<UserVO>((cursor) => listUsers({
  ...query.value,
  page: 1,
  cursor,
}))

// 角色选项(表单下拉用)
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

// 角色 code → 中文标签 + Tag variant(行内展示用;SYS_ADMIN=danger 最高权 / LAB_ADMIN=accent
// 实验室管 / TEACHER=info / STAFF=warning / STUDENT=默认中性,留 success 给状态列避免歧义)
const roleLabelMap: Record<string, string> = {
  SYS_ADMIN: '系统管理员',
  LAB_ADMIN: '实验室管理员',
  TEACHER: '教师',
  STUDENT: '学生',
  STAFF: '职工',
}
function roleLabel(code: string): string {
  return roleLabelMap[code] || code
}
function roleVariant(code: string): 'default' | 'accent' | 'warning' | 'danger' | 'info' {
  switch (code) {
    case 'SYS_ADMIN':
      return 'danger'
    case 'LAB_ADMIN':
      return 'accent'
    case 'TEACHER':
      return 'info'
    case 'STAFF':
      return 'warning'
    default:
      return 'default'
  }
}

// 编辑抽屉
const drawerVisible = ref(false)
const drawerMode = ref<'create' | 'edit'>('create')
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
  collegeId: undefined as number | undefined,
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    {
      validator: (_r, _v, cb) => {
        if (drawerMode.value === 'create' && !form.value.password) {
          cb(new Error('请输入密码'))
        } else {
          cb()
        }
      },
      trigger: 'blur',
    },
  ],
  collegeId: [
    {
      validator: (_r, _v, cb) => {
        if (!form.value.collegeId && !form.value.roleCodes.includes('SYS_ADMIN')) {
          cb(new Error('业务用户必须绑定学院'))
        } else {
          cb()
        }
      },
      trigger: 'change',
    },
  ],
}

async function load(targetPage = query.value.page || 1) {
  loading.value = true
  try {
    const users = await cursorPager.load(targetPage)
    page.value = users
    if (!colleges.value.length) colleges.value = await listColleges()
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function onSearch() {
  query.value.page = 1
  cursorPager.reset()
  void load()
}

function onPageChange(p: number) {
  query.value.page = p
  void load(p)
}
function onSizeChange(s: number) {
  query.value.size = s
  query.value.page = 1
  cursorPager.reset()
  void load()
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
    collegeId: undefined,
  }
}

function openCreate() {
  drawerMode.value = 'create'
  editingId.value = null
  resetForm()
  drawerVisible.value = true
}

function openEdit(row: UserVO) {
  drawerMode.value = 'edit'
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
    collegeId: row.collegeId ?? undefined,
  }
  drawerVisible.value = true
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
    collegeId: f.collegeId,
  }
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    const payload = buildPayload()
    if (drawerMode.value === 'create') {
      await createUser(payload)
      ElMessage.success('已创建')
    } else if (editingId.value != null) {
      await updateUser(editingId.value, payload)
      ElMessage.success('已更新')
    }
    drawerVisible.value = false
    await load()
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false
  }
}

async function onToggleStatus(row: UserVO) {
  const next = row.status === 1 ? 0 : 1
  const verb = next === 1 ? '启用' : '禁用'
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

const drawerTitle = computed(() => (drawerMode.value === 'create' ? '新增用户' : '编辑用户'))
const totalLabel = computed(() => `共 ${page.value.total} 条`)

onMounted(load)
</script>

<template>
  <div class="umanage">
    <PageHeader title="用户管理" subtitle="管理系统账号、角色与启用状态">
      <template #actions>
        <GradientButton @click="openCreate">新增用户</GradientButton>
      </template>
    </PageHeader>

    <div class="umanage__toolbar">
      <el-input
        v-model="query.username"
        placeholder="用户名"
        clearable
        class="umanage__search"
        @keyup.enter="onSearch"
        @clear="onSearch"
      />
      <el-input
        v-model="query.realName"
        placeholder="真实姓名"
        clearable
        class="umanage__search"
        @keyup.enter="onSearch"
        @clear="onSearch"
      />
      <GhostButton @click="onSearch">查询</GhostButton>
    </div>

    <section class="umanage__signal" aria-label="用户目录概览">
      <div>
        <span class="umanage__eyebrow">身份目录</span>
        <strong>账号、角色和学院边界，在同一个工作面维护。</strong>
      </div>
      <span class="umanage__signal-count">{{ page.total }} <small>个账号</small></span>
    </section>

    <div class="umanage__table">
      <el-table v-loading="loading" :data="page.records" stripe row-key="id">
        <el-table-column label="用户" min-width="200">
          <template #default="{ row }">
            <div class="umanage__user">
              <span class="umanage__username">{{ row.username }}</span>
              <span v-if="row.realName" class="umanage__realname">{{ row.realName }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="角色" min-width="200">
          <template #default="{ row }">
            <div v-if="row.roles && row.roles.length" class="umanage__roles">
              <Tag
                v-for="r in row.roles"
                :key="r"
                :variant="roleVariant(r)"
                effect="light"
                round
              >
                {{ roleLabel(r) }}
              </Tag>
            </div>
            <span v-else class="umanage__muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <Tag v-if="row.status === 1" variant="success" effect="light" round>启用</Tag>
            <Tag v-else variant="danger" effect="light" round>禁用</Tag>
          </template>
        </el-table-column>
        <el-table-column label="联系 / 部门" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="umanage__contact">
              <span v-if="row.deptName" class="umanage__dept">{{ row.deptName }}</span>
              <span class="umanage__contact-line">
                <span v-if="row.phone">{{ row.phone }}</span>
                <span v-if="row.phone && row.email" class="umanage__sep">·</span>
                <span v-if="row.email">{{ row.email }}</span>
              </span>
              <span v-if="!row.deptName && !row.phone && !row.email" class="umanage__muted">—</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="所属学院" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">
            {{ colleges.find((college) => college.id === row.collegeId)?.name || '全局' }}
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="120">
          <template #default="{ row }">{{ fmt(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <TextButton @click="openEdit(row)">编辑</TextButton>
            <TextButton @click="onToggleStatus(row)">
              {{ row.status === 1 ? '禁用' : '启用' }}
            </TextButton>
            <el-button link type="danger" class="umanage__delete" @click="onDelete(row)">
              删除
            </el-button>
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

    <el-drawer
      v-model="drawerVisible"
      :title="drawerTitle"
      size="520px"
      direction="rtl"
      modal-class="umanage-drawer"
      :close-on-click-modal="false"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="90px"
        label-position="right"
      >
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="drawerMode === 'edit'" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="drawerMode === 'edit' ? '留空表示不改密码' : '请输入密码'"
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
        <el-form-item label="所属学院" prop="collegeId">
          <el-select
            v-model="form.collegeId"
            clearable
            placeholder="系统管理员可不绑定学院"
            style="width: 100%"
          >
            <el-option
              v-for="college in colleges"
              :key="college.id"
              :label="`${college.name} (${college.code})`"
              :value="college.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.roleCodes" multiple placeholder="分配角色" style="width: 100%">
            <el-option v-for="o in roleOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <GhostButton @click="drawerVisible = false">取消</GhostButton>
        <GradientButton :loading="submitting" @click="onSubmit">保存</GradientButton>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped lang="scss">
// ============================================================================
// User Manage 暗表(spec §7 用户行)
// 表底/表头/hover/stripe 全由 theme.dark.scss 全局 --el-table-* 桥接接管,
// 此处仅做页面级布局(toolbar / table 容器 / pager 间距 / 单元格内排版)。
// ============================================================================

.umanage {
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
    background: linear-gradient(110deg, color-mix(in srgb, var(--accent-blue) 9%, var(--bg-surface)), var(--bg-surface));
  }

  &__eyebrow { display: block; margin-bottom: 8px; color: var(--text-tertiary); font-family: var(--font-mono); font-size: 10px; letter-spacing: .14em; text-transform: uppercase; }
  &__signal strong { color: var(--text-primary); font-family: var(--font-display); font-size: clamp(18px, 2vw, 24px); letter-spacing: -.04em; }
  &__signal-count { color: var(--accent); font-family: var(--font-display); font-size: 28px; font-weight: 700; }
  &__signal-count small { color: var(--text-tertiary); font-family: var(--font-sans); font-size: 12px; font-weight: 500; }

  &__search {
    width: 200px;
  }

  // ---- 表格容器:surface 卡面 + hairline(替代旧 .lab-card,与 R4/R5 风格对齐)--
  &__table {
    padding: 8px;
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-soft);
  }

  // ---- 用户列:主标 username + 副标 realName 纵向堆叠 ------------------------
  &__user {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  &__username {
    font-family: var(--font-display);
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__realname {
    font-size: 12px;
    color: var(--text-tertiary);
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  // ---- 角色列:Tag chips 间留 4px -----------------------------------------
  &__roles {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  // ---- 联系/部门列:纵向堆叠 ----------------------------------------------
  &__contact {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  &__dept {
    font-size: 13px;
    color: var(--text-primary);
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__contact-line {
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--text-tertiary);
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__sep {
    margin: 0 4px;
    opacity: 0.6;
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

<!-- ============================================================================
  非 scoped:el-drawer 默认 append-to-body(teleport 到 <body>),scoped 选不到。
  用 modal-class="umanage-drawer" 圈定本页 drawer 作用域,不污染其它 drawer。
  覆盖 EP 的 --el-drawer-* 变量 + header/body/footer 局部细节,实现深色管理抽屉。
============================================================================ -->
<style lang="scss">
.umanage-drawer {
  // ---- 深色 token 覆盖(变量下传到子节点 .el-drawer)-----------------------
  --el-drawer-bg-color: var(--bg-surface);
  --el-drawer-title-text-color: var(--text-primary);

  // 抽屉根:surface 卡面 + 左侧 1px hairline 强调边(R5/R6 抽屉风格)
  .el-drawer {
    background: var(--bg-surface);
    border-left: 1px solid var(--border-default);
    box-shadow: var(--shadow-soft);
  }

  // 头:底部 hairline + 主标用 display 字体
  .el-drawer__header {
    align-items: center;
    margin-bottom: 0;
    padding: 20px 24px;
    border-bottom: 1px solid var(--border-subtle);
    color: var(--text-primary);

    .el-drawer__title {
      font-family: var(--font-display);
      font-size: 18px;
      font-weight: 600;
      letter-spacing: -0.2px;
      color: var(--text-primary);
    }
  }

  // 关闭按钮:默认 secondary,hover 转 accent
  .el-drawer__close-btn {
    color: var(--text-secondary);

    &:hover {
      color: var(--accent);
    }
  }

  // 体:留 24px 内边距,表单标签/输入由全局 EP 暗色桥接接管
  .el-drawer__body {
    padding: 24px;
  }

  // 脚:顶部 hairline + 右对齐按钮组(GhostButton 取消 + GradientButton 保存)
  .el-drawer__footer {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    padding: 16px 24px;
    border-top: 1px solid var(--border-subtle);
  }
}
</style>
