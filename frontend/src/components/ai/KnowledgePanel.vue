<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Document, Refresh, Upload, View, CircleCheck, Clock } from '@element-plus/icons-vue'
import {
  createKnowledgeDocument,
  deleteKnowledgeDocument,
  getKnowledgeDocument,
  listKnowledgeDocuments,
  previewKnowledgeChunks,
  publishKnowledgeDocument,
  requestKnowledgeParse,
  reviewKnowledgeDocument,
  uploadKnowledgeDocument,
} from '@/api/aiV2'
import { useUserStore } from '@/stores/user'
import type { KnowledgeChunkPreview, KnowledgeDocument } from '@/types/aiWorkbench'

const userStore = useUserStore()
const documents = ref<KnowledgeDocument[]>([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const editorVisible = ref(false)
const editorLoading = ref(false)
const editorDocumentId = ref<number | null>(null)
const chunks = ref<KnowledgeChunkPreview[]>([])
const fileRef = ref<HTMLInputElement | null>(null)
const createVisible = ref(false)
const createMode = ref<'file' | 'text'>('file')
const selectedFile = ref<File | null>(null)
const createForm = reactive({ title: '', source_type: 'SOP', college_id: '', body: '' })
const reviewText = ref('')
const selectedDocument = computed(() => documents.value.find((item) => item.id === editorDocumentId.value))
let pollTimer: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  void refresh()
  pollTimer = setInterval(() => {
    if (documents.value.some((item) => ['QUEUED', 'SUBMITTING', 'PROCESSING'].includes(item.parse_status))) {
      void refresh()
    }
  }, 5000)
})
onBeforeUnmount(() => { if (pollTimer) clearInterval(pollTimer) })

async function refresh() {
  loading.value = true
  error.value = ''
  try { documents.value = await listKnowledgeDocuments() }
  catch (cause) { error.value = (cause as Error).message || '知识库加载失败' }
  finally { loading.value = false }
}

function startCreate(mode: 'file' | 'text') {
  createMode.value = mode
  createForm.title = ''
  createForm.source_type = mode === 'file' ? 'SOP' : 'FAQ'
  createForm.college_id = ''
  createForm.body = ''
  selectedFile.value = null
  createVisible.value = true
}

function selectFile(event: Event) {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0] || null
}

async function createDocument() {
  if (!createForm.title.trim()) return ElMessage.warning('请填写文档标题')
  saving.value = true
  try {
    const collegeId = createForm.college_id ? Number(createForm.college_id) : undefined
    if (createMode.value === 'file') {
      if (!selectedFile.value) return ElMessage.warning('请选择要上传的文件')
      await uploadKnowledgeDocument({
        title: createForm.title.trim(),
        source_type: createForm.source_type,
        college_id: collegeId,
        file: selectedFile.value,
      })
    } else {
      await createKnowledgeDocument({
        title: createForm.title.trim(),
        source_type: createForm.source_type,
        college_id: collegeId,
        body: createForm.body.trim(),
      })
    }
    createVisible.value = false
    ElMessage.success('知识文档已保存为草稿')
    await refresh()
  } catch (cause) { ElMessage.error((cause as Error).message || '保存失败') }
  finally { saving.value = false }
}

async function parseDocument(document: KnowledgeDocument) {
  try {
    await requestKnowledgeParse(document.id)
    ElMessage.success('已提交 MinerU 解析，完成后可审核提取内容')
    await refresh()
  } catch (cause) { ElMessage.error((cause as Error).message || '无法启动解析') }
}

async function openReview(document: KnowledgeDocument) {
  editorDocumentId.value = document.id
  editorVisible.value = true
  editorLoading.value = true
  chunks.value = []
  try {
    const detail = await getKnowledgeDocument(document.id)
    reviewText.value = detail.reviewed_text || detail.extracted_text || detail.body || ''
  } catch (cause) { ElMessage.error((cause as Error).message || '无法读取文档内容') }
  finally { editorLoading.value = false }
}

async function preview() {
  if (!editorDocumentId.value) return
  try { chunks.value = await previewKnowledgeChunks(editorDocumentId.value) }
  catch (cause) { ElMessage.error((cause as Error).message || '切块预览失败') }
}

async function saveReview() {
  if (!editorDocumentId.value) return
  saving.value = true
  try {
    await reviewKnowledgeDocument(editorDocumentId.value, reviewText.value)
    ElMessage.success('审核内容已保存，当前仍未发布')
    await refresh()
  } catch (cause) { ElMessage.error((cause as Error).message || '审核内容保存失败') }
  finally { saving.value = false }
}

async function publish(document: KnowledgeDocument) {
  try {
    await ElMessageBox.confirm('发布后，用户才可以在 AI 回答中检索这份内容。', '发布到知识库', { type: 'warning' })
    await publishKnowledgeDocument(document.id)
    ElMessage.success('文档已发布并建立向量索引')
    await refresh()
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') ElMessage.error((cause as Error).message || '发布失败')
  }
}

async function remove(document: KnowledgeDocument) {
  try {
    await ElMessageBox.confirm('将清除原始文件、审核文本和向量索引；标题与校验摘要会保留作最小审计记录。', '删除知识文档', { type: 'warning' })
    await deleteKnowledgeDocument(document.id)
    ElMessage.success('知识文档及索引已清理')
    await refresh()
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') ElMessage.error((cause as Error).message || '删除失败')
  }
}

function statusLabel(document: KnowledgeDocument) {
  const labels: Record<string, string> = {
    NOT_REQUESTED: '待处理', UPLOADED: '待解析', QUEUED: '排队中', SUBMITTING: '提交中',
    PROCESSING: '解析中', PARSED: '待审核', REVIEWED: '待发布', PUBLISHED: '已发布', FAILED: '解析失败',
  }
  return labels[document.parse_status] || document.status
}

function statusTone(document: KnowledgeDocument) {
  if (document.parse_status === 'PUBLISHED') return 'success'
  if (document.parse_status === 'FAILED') return 'danger'
  if (['QUEUED', 'SUBMITTING', 'PROCESSING'].includes(document.parse_status)) return 'busy'
  return 'pending'
}
</script>

<template>
  <section class="knowledge-panel panel-surface">
    <header class="knowledge-panel__head">
      <div>
        <span class="section-kicker">CURATED KNOWLEDGE</span>
        <h2>知识库</h2>
        <p>原文不会自动进入回答：解析后先人工核对，再预览切块并显式发布。</p>
      </div>
      <div class="knowledge-panel__actions">
        <el-button :icon="Refresh" :loading="loading" @click="refresh">刷新</el-button>
        <el-button :icon="Document" @click="startCreate('text')">新建文本</el-button>
        <el-button type="primary" :icon="Upload" @click="startCreate('file')">上传文档</el-button>
      </div>
    </header>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-loading="loading" class="knowledge-grid">
      <article v-for="document in documents" :key="document.id" class="knowledge-card">
        <div class="knowledge-card__top">
          <span class="knowledge-card__kind">{{ document.source_type }}</span>
          <span class="knowledge-status" :class="`knowledge-status--${statusTone(document)}`">
            <i></i>{{ statusLabel(document) }}
          </span>
        </div>
        <h3>{{ document.title }}</h3>
        <p class="knowledge-card__file">{{ document.source_file_name || '文本知识' }} · v{{ document.version }}</p>
        <p v-if="document.parse_error" class="knowledge-card__error">{{ document.parse_error }}</p>
        <div class="knowledge-card__meta">
          <span>{{ document.chunk_count }} 个已索引片段</span>
          <span v-if="document.published_at">发布于 {{ new Date(document.published_at).toLocaleDateString('zh-CN') }}</span>
        </div>
        <div class="knowledge-card__actions">
          <el-button v-if="['UPLOADED', 'FAILED'].includes(document.parse_status) && document.source_file_name" text type="primary" :icon="Refresh" @click="parseDocument(document)">解析</el-button>
          <el-button v-if="['PARSED', 'REVIEWED', 'PUBLISHED', 'NOT_REQUESTED'].includes(document.parse_status)" text type="primary" :icon="View" @click="openReview(document)">审核 / 预览</el-button>
          <el-button v-if="document.parse_status === 'REVIEWED'" text type="success" :icon="CircleCheck" @click="publish(document)">发布</el-button>
          <el-button text type="danger" :icon="Delete" @click="remove(document)">删除</el-button>
        </div>
      </article>
      <div v-if="!documents.length && !loading" class="knowledge-empty">
        <Document />
        <strong>知识库还没有文档</strong>
        <span>上传设备 SOP、安全须知或 FAQ，再经过审核后发布。</span>
      </div>
    </div>

    <el-dialog v-model="createVisible" :title="createMode === 'file' ? '添加知识文档' : '新建文本知识'" width="560px" destroy-on-close>
      <el-form label-position="top" class="knowledge-form">
        <el-form-item label="文档标题"><el-input v-model="createForm.title" maxlength="200" show-word-limit /></el-form-item>
        <div class="knowledge-form__row">
          <el-form-item label="类型"><el-select v-model="createForm.source_type"><el-option label="设备 SOP" value="SOP" /><el-option label="安全须知" value="SAFETY" /><el-option label="常见问题" value="FAQ" /></el-select></el-form-item>
          <el-form-item v-if="userStore.hasRole('SYS_ADMIN')" label="学院 ID（留空为全校）"><el-input v-model="createForm.college_id" inputmode="numeric" placeholder="可选" /></el-form-item>
        </div>
        <template v-if="createMode === 'file'">
          <input ref="fileRef" type="file" accept=".pdf,.doc,.docx,.ppt,.pptx,.png,.jpg,.jpeg,.jp2,.webp,.gif,.bmp" hidden @change="selectFile" />
          <button class="file-picker" type="button" @click="fileRef?.click()"><Upload /><span>{{ selectedFile?.name || '选择 PDF、Office 文档或图片' }}</span></button>
          <small class="knowledge-form__hint">上传后只保存原件草稿；点击“解析”后才会提交给 MinerU，单文件上限 20 MB。</small>
        </template>
        <el-form-item v-else label="内容"><el-input v-model="createForm.body" type="textarea" :rows="8" maxlength="200000" show-word-limit placeholder="输入至少 20 个字符的知识内容" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="createVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="createDocument">保存草稿</el-button></template>
    </el-dialog>

    <el-dialog v-model="editorVisible" :title="selectedDocument?.title || '内容审核'" width="min(900px, 92vw)" top="6vh" destroy-on-close>
      <div v-loading="editorLoading" class="review-editor">
        <div class="review-editor__notice"><Clock /> 提取文本只作为草稿。核对内容并保存后，仍需单独点击“发布”才会进入 RAG 检索。</div>
        <el-input v-model="reviewText" type="textarea" :rows="16" maxlength="500000" show-word-limit placeholder="解析结果或文本知识内容" />
        <div v-if="chunks.length" class="chunk-preview">
          <h3>切块预览 <span>{{ chunks.length }} 段</span></h3>
          <article v-for="chunk in chunks" :key="chunk.index"><small>片段 {{ chunk.index + 1 }} · {{ chunk.characters }} 字</small><p>{{ chunk.content }}</p></article>
        </div>
      </div>
      <template #footer><el-button @click="preview">预览切块</el-button><el-button type="primary" :loading="saving" @click="saveReview">保存审核内容</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped lang="scss">
.knowledge-panel { min-height: 0; padding: clamp(18px, 2.2vw, 28px); border-radius: var(--radius-card); }
.knowledge-panel__head { display:flex; align-items:flex-start; justify-content:space-between; gap:20px; padding-bottom:22px; border-bottom:1px solid var(--border-subtle); }
.knowledge-panel__head h2 { margin:7px 0 5px; font-family:var(--font-display); font-size:23px; }
.knowledge-panel__head p { margin:0; color:var(--text-secondary); font-size:12px; }
.knowledge-panel__actions { display:flex; flex-wrap:wrap; gap:8px; }
.knowledge-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:12px; padding-top:20px; }
.knowledge-card { display:flex; flex-direction:column; min-height:205px; padding:16px; background:var(--bg-elevated); border:1px solid var(--border-subtle); border-radius:var(--radius-card); }
.knowledge-card__top,.knowledge-card__meta { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.knowledge-card__kind { color:var(--text-tertiary); font-family:var(--font-mono); font-size:9px; letter-spacing:.1em; }
.knowledge-status { display:inline-flex; align-items:center; gap:6px; color:var(--text-secondary); font-size:10px; }
.knowledge-status i { width:6px; height:6px; border-radius:50%; background:var(--text-tertiary); }
.knowledge-status--success i { background:var(--status-success); }.knowledge-status--danger { color:var(--status-danger); }.knowledge-status--danger i { background:var(--status-danger); }.knowledge-status--busy i { background:var(--accent); animation:pulse 1.4s infinite; }
.knowledge-card h3 { margin:17px 0 5px; font-size:15px; }.knowledge-card__file,.knowledge-card__meta { color:var(--text-tertiary); font-size:10px; }
.knowledge-card__error { color:var(--status-danger); font-size:11px; }.knowledge-card__meta { margin-top:auto; padding:12px 0 8px; border-bottom:1px solid var(--border-subtle); }
.knowledge-card__actions { display:flex; flex-wrap:wrap; justify-content:flex-end; padding-top:7px; }
.knowledge-empty { display:grid; place-items:center; gap:8px; grid-column:1/-1; padding:70px 20px; color:var(--text-tertiary); text-align:center; }.knowledge-empty svg { width:28px; height:28px; color:var(--accent); }.knowledge-empty strong { color:var(--text-primary); }
.knowledge-form :deep(.el-select) { width:100%; }.knowledge-form__row { display:grid; grid-template-columns:1fr 1fr; gap:14px; }.file-picker { display:flex; align-items:center; gap:10px; width:100%; padding:15px; color:var(--text-secondary); background:var(--bg-elevated); border:1px dashed var(--border-strong); border-radius:9px; cursor:pointer; text-align:left; }.file-picker svg { width:17px; color:var(--accent); }.knowledge-form__hint { display:block; margin-top:8px; color:var(--text-tertiary); font-size:11px; }
.review-editor { display:grid; gap:13px; }.review-editor__notice { display:flex; align-items:center; gap:8px; padding:10px 12px; color:var(--text-secondary); background:var(--accent-soft); border-radius:8px; font-size:11px; }.review-editor__notice svg { flex:none; color:var(--accent); }
.chunk-preview { max-height:260px; overflow:auto; }.chunk-preview h3 { display:flex; justify-content:space-between; font-size:13px; }.chunk-preview h3 span,.chunk-preview small { color:var(--text-tertiary); font-family:var(--font-mono); font-size:10px; }.chunk-preview article { padding:10px 12px; margin:8px 0; background:var(--bg-elevated); border:1px solid var(--border-subtle); border-radius:8px; }.chunk-preview p { white-space:pre-wrap; color:var(--text-secondary); font-size:11px; line-height:1.6; }
@keyframes pulse { 50% { opacity:.35; } }
@media(max-width:720px) { .knowledge-panel__head { flex-direction:column; }.knowledge-form__row { grid-template-columns:1fr; } }
</style>
