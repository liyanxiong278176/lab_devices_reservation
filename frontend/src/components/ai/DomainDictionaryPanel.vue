<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Refresh, Reading } from '@element-plus/icons-vue'
import { createAiDomainTerm, deleteAiDomainTerm, listAiDomainTerms } from '@/api/aiV2'
import { useUserStore } from '@/stores/user'
import type { AiDomainTerm } from '@/types/aiWorkbench'

const userStore = useUserStore()
const rows = ref<AiDomainTerm[]>([])
const loading = ref(false)
const saving = ref(false)
const form = reactive({ term: '', canonical: '', kind: 'SYNONYM' as AiDomainTerm['kind'], collegeId: '' })

onMounted(() => void refresh())

async function refresh() {
  loading.value = true
  try { rows.value = await listAiDomainTerms() }
  catch (error) { ElMessage.error((error as Error).message || '领域词典加载失败') }
  finally { loading.value = false }
}

async function submit() {
  if (!form.term.trim()) return ElMessage.warning('请填写用户常用词')
  if (form.kind === 'SYNONYM' && !form.canonical.trim()) return ElMessage.warning('请填写标准词')
  saving.value = true
  try {
    await createAiDomainTerm({
      term: form.term.trim(),
      canonical: form.kind === 'SYNONYM' ? form.canonical.trim() : undefined,
      kind: form.kind,
      college_id: form.collegeId ? Number(form.collegeId) : undefined,
    })
    form.term = ''
    form.canonical = ''
    ElMessage.success('词条已加入检索词典')
    await refresh()
  } catch (error) { ElMessage.error((error as Error).message || '保存词条失败') }
  finally { saving.value = false }
}

async function remove(row: AiDomainTerm) {
  try {
    await ElMessageBox.confirm(`确定删除“${row.term}”词条吗？`, '删除领域词条', { type: 'warning' })
    await deleteAiDomainTerm(row.id)
    ElMessage.success('词条已删除')
    await refresh()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error((error as Error).message || '删除词条失败')
  }
}
</script>

<template>
  <section class="domain-dictionary">
    <header class="domain-dictionary__head">
      <div>
        <span class="section-kicker">RETRIEVAL VOCABULARY</span>
        <h2>领域词典</h2>
        <p>把实验室俗称、缩写和忽略词整理成可审查的检索规则。词典仅影响检索，不改变业务名称。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="refresh">刷新</el-button>
    </header>

    <div class="domain-dictionary__form panel-surface">
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="词条类型">
          <el-select v-model="form.kind">
            <el-option label="同义词（用户说法 → 标准词）" value="SYNONYM" />
            <el-option label="忽略词（检索时过滤）" value="IGNORE" />
          </el-select>
        </el-form-item>
        <el-form-item label="用户说法 / 忽略词">
          <el-input v-model="form.term" maxlength="100" placeholder="例如：电镜、离心机小超" />
        </el-form-item>
        <el-form-item v-if="form.kind === 'SYNONYM'" label="标准词">
          <el-input v-model="form.canonical" maxlength="100" placeholder="例如：电子显微镜" />
        </el-form-item>
        <el-form-item v-if="userStore.hasRole('SYS_ADMIN')" label="学院 ID（留空为全校）">
          <el-input v-model="form.collegeId" inputmode="numeric" placeholder="可选，仅填写数字 ID" />
        </el-form-item>
        <el-button type="primary" :loading="saving" :icon="Reading" @click="submit">加入词典</el-button>
      </el-form>
      <p class="domain-dictionary__note">负责人新增的词条仅作用于本学院；系统管理员可创建全校词条或指定学院词条。</p>
    </div>

    <div v-loading="loading" class="domain-dictionary__table panel-surface">
      <el-table :data="rows" empty-text="暂无审核词条">
        <el-table-column prop="term" label="用户说法" min-width="180" />
        <el-table-column label="检索处理" min-width="220">
          <template #default="scope">
            <span>{{ scope.row.kind === 'SYNONYM' ? `映射为「${scope.row.canonical}」` : '检索时忽略' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="范围" width="150">
          <template #default="scope">{{ scope.row.college_id ? `学院 ${scope.row.college_id}` : '全校' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="86" align="right">
          <template #default="scope">
            <el-button text type="danger" :icon="Delete" title="删除词条" @click="remove(scope.row)" />
          </template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<style scoped>
.domain-dictionary { display:grid; gap:18px; }
.domain-dictionary__head { display:flex; align-items:flex-start; justify-content:space-between; gap:20px; padding:8px 2px; }
.domain-dictionary__head h2 { margin:8px 0; color:var(--text-primary); font-size:26px; }
.domain-dictionary__head p,.domain-dictionary__note { max-width:680px; color:var(--text-tertiary); font-size:13px; line-height:1.7; }
.domain-dictionary__form,.domain-dictionary__table { padding:20px; }
.domain-dictionary__form :deep(.el-form) { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px 16px; align-items:end; }
.domain-dictionary__form :deep(.el-form-item) { margin:0; }
.domain-dictionary__form :deep(.el-button) { align-self:end; justify-self:start; }
.domain-dictionary__note { margin:14px 0 0; }
@media (max-width:760px) { .domain-dictionary__form :deep(.el-form) { grid-template-columns:1fr; } .domain-dictionary__head { flex-direction:column; } }
</style>
