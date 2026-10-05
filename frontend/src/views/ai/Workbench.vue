<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ArrowDown,
  Reading,
  Check,
  CircleCheck,
  Clock,
  Cpu,
  Coin,
  Document,
  Delete,
  Plus,
  Promotion,
  Refresh,
  Lock,
  VideoPause,
  Setting,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import {
  getAiCitation,
  getAiModelConfigs,
  getLatestAiEmbeddingRebuild,
  getAiReadiness,
  rollbackAiEmbeddingRebuild,
  startAiEmbeddingRebuild,
  testAiModelConfig,
} from '@/api/aiV2'
import KnowledgePanel from '@/components/ai/KnowledgePanel.vue'
import DomainDictionaryPanel from '@/components/ai/DomainDictionaryPanel.vue'
import UsagePanel from '@/components/ai/UsagePanel.vue'
import { useAiWorkbenchStore } from '@/stores/aiWorkbench'
import { useUserStore } from '@/stores/user'
import type {
  AiCitation,
  AiCitationDetail,
  AiEmbeddingRebuildJob,
  AiModelConfig,
  AiReadiness,
  AiMessage,
  AiMemoryCandidate,
} from '@/types/aiWorkbench'

const store = useAiWorkbenchStore()
const userStore = useUserStore()
const input = ref('')
const chatRef = ref<HTMLElement | null>(null)
let followChatBottom = true
const bootError = ref('')
const aiStatusError = ref('')
const aiReadiness = ref<AiReadiness | null>(null)
const historyOpen = ref(false)
const contextOpen = ref(false)
const activeView = ref<'chat' | 'knowledge' | 'domain' | 'usage'>('chat')
const citationVisible = ref(false)
const citationLoading = ref(false)
const citationError = ref('')
const selectedCitation = ref<AiCitationDetail | null>(null)

const isSystemAdmin = computed(() => userStore.hasRole('SYS_ADMIN'))
const isLabAdmin = computed(() => userStore.hasRole('LAB_ADMIN') || isSystemAdmin.value)
const modelConfigVisible = ref(false)
const modelConfigLoading = ref(false)
const modelConfigTesting = ref(false)
const modelConfigError = ref('')
const modelTestMessage = ref('')
const modelTestSuccess = ref(false)
const modelConfigs = ref<Record<string, Awaited<ReturnType<typeof getAiModelConfigs>>[number]>>({})
const modelComponent = ref<AiModelConfig['component']>('chat')
const activeModelConfig = computed(() => modelConfigs.value[modelComponent.value])
const keyEnvironmentName = computed(() => ({
  chat: 'LAB_AI_API_KEY',
  embedding: 'LAB_AI_EMBEDDING_API_KEY',
  mineru: 'LAB_AI_MINERU_API_KEY',
})[modelComponent.value])
const embeddingRebuild = ref<AiEmbeddingRebuildJob | null>(null)
const embeddingRebuildLoading = ref(false)
const embeddingRebuildTimer = ref<number | undefined>()

const hasMessages = computed(() => store.messages.length > 0)
const pending = computed(() => store.pendingConfirmation)
const aiReady = computed(() => aiReadiness.value?.available === true)
const aiStatusLabel = computed(() => {
  if (aiStatusError.value) return '状态检查失败'
  if (!aiReadiness.value) return '检查 AI 状态'
  return aiReady.value ? 'AI 服务就绪' : '等待模型配置'
})

function memoryCandidates(message: AiMessage): AiMemoryCandidate[] {
  const value = message.metadata?.memory_candidates
  return Array.isArray(value) ? value as AiMemoryCandidate[] : []
}

onMounted(async () => {
  const statusTask = refreshAiReadiness()
  try { await store.loadConversations() }
  catch (err) { bootError.value = (err as Error).message || '无法加载 AI 工作台' }
  await statusTask
})

async function refreshAiReadiness() {
  try {
    aiReadiness.value = await getAiReadiness()
    aiStatusError.value = ''
  } catch (err) {
    aiStatusError.value = (err as Error).message || '暂时无法检查 AI 服务状态'
  }
}

onBeforeUnmount(() => {
  store.detach()
  if (embeddingRebuildTimer.value !== undefined) window.clearInterval(embeddingRebuildTimer.value)
})

watch(modelConfigVisible, (visible) => {
  if (!visible && embeddingRebuildTimer.value !== undefined) {
    window.clearInterval(embeddingRebuildTimer.value)
    embeddingRebuildTimer.value = undefined
  } else if (visible) {
    updateEmbeddingRebuildPolling()
  }
})

async function send() {
  const text = input.value.trim()
  if (!text || store.loading || !aiReady.value) return
  input.value = ''
  await store.send(text)
  requestAnimationFrame(() => {
    if (chatRef.value) chatRef.value.scrollTop = chatRef.value.scrollHeight
  })
}

async function openModelConfig() {
  if (!isSystemAdmin.value) return
  modelConfigVisible.value = true
  modelConfigLoading.value = true
  modelConfigError.value = ''
  try {
    const [configs, rebuild] = await Promise.all([
      getAiModelConfigs(),
      getLatestAiEmbeddingRebuild(),
    ])
    modelConfigs.value = Object.fromEntries(configs.map((item) => [item.component, item]))
    embeddingRebuild.value = rebuild
    modelTestMessage.value = ''
    modelTestSuccess.value = false
    updateEmbeddingRebuildPolling()
  } catch (err) {
    modelConfigError.value = (err as Error).message || '无法加载模型配置'
  } finally {
    modelConfigLoading.value = false
  }
}

function updateEmbeddingRebuildPolling() {
  if (embeddingRebuildTimer.value !== undefined) {
    window.clearInterval(embeddingRebuildTimer.value)
    embeddingRebuildTimer.value = undefined
  }
  if (!modelConfigVisible.value || !embeddingRebuild.value ||
      !['QUEUED', 'RUNNING'].includes(embeddingRebuild.value.status)) return
  embeddingRebuildTimer.value = window.setInterval(() => { void refreshEmbeddingRebuild() }, 2000)
}

async function refreshEmbeddingRebuild() {
  if (embeddingRebuildLoading.value) return
  embeddingRebuildLoading.value = true
  try {
    embeddingRebuild.value = await getLatestAiEmbeddingRebuild()
    updateEmbeddingRebuildPolling()
  } catch (err) {
    modelConfigError.value = (err as Error).message || '无法获取索引任务进度'
  } finally {
    embeddingRebuildLoading.value = false
  }
}

async function rebuildEmbeddingIndex() {
  if (embeddingRebuildLoading.value) return
  embeddingRebuildLoading.value = true
  modelConfigError.value = ''
  try {
    embeddingRebuild.value = await startAiEmbeddingRebuild()
    updateEmbeddingRebuildPolling()
    ElMessage.success('索引重建已进入后台，页面会自动更新进度')
  } catch (err) {
    modelConfigError.value = (err as Error).message || '无法启动索引重建'
  } finally {
    embeddingRebuildLoading.value = false
  }
}

async function rollbackEmbeddingIndex() {
  if (!embeddingRebuild.value || embeddingRebuildLoading.value) return
  embeddingRebuildLoading.value = true
  try {
    embeddingRebuild.value = await rollbackAiEmbeddingRebuild(embeddingRebuild.value.id)
    ElMessage.success('已切回上一版向量索引')
    await openModelConfig()
  } catch (err) {
    modelConfigError.value = (err as Error).message || '索引回滚失败'
  } finally {
    embeddingRebuildLoading.value = false
  }
}

async function testModelConfig() {
  modelConfigTesting.value = true
  modelTestMessage.value = ''
  modelConfigError.value = ''
  try {
    const result = await testAiModelConfig(modelComponent.value)
    modelTestSuccess.value = result.success
    modelTestMessage.value = `${result.message} · ${result.latency_ms} ms`
  } catch (err) {
    modelTestSuccess.value = false
    modelTestMessage.value = (err as Error).message || '连接测试失败'
  } finally { modelConfigTesting.value = false }
}

function onComponentChange(value: string | number) {
  if (value === 'chat' || value === 'embedding' || value === 'mineru') {
    modelComponent.value = value
    modelTestMessage.value = ''
    modelTestSuccess.value = false
  }
}

async function removeConversation(id: number) {
  try { await store.removeConversation(id) }
  catch (err) { ElMessage.error((err as Error).message || '删除对话失败') }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void send()
  }
}

function previewText(value: unknown) {
  return JSON.stringify(value, null, 2)
}

function formatTime(value?: string) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(
    new Date(value),
  )
}

const dlpCategoryLabels: Record<string, string> = {
  credential: '凭据',
  password: '密码',
  email: '邮箱',
  phone: '手机号',
  identity_number: '身份证号',
  sensitive_field: '敏感字段',
}

function scrollChatToBottom() {
  const chat = chatRef.value
  if (chat) chat.scrollTop = chat.scrollHeight
}

function updateChatFollowState() {
  const chat = chatRef.value
  if (!chat) return
  followChatBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 96
}

function messageText(message: AiMessage) {
  return message.content.replace(/\s*\[citation:[^\]]+\]/g, '').trim()
}

function messageCitations(message: AiMessage): AiCitation[] {
  const citations = message.metadata?.citations
  return Array.isArray(citations) ? citations as AiCitation[] : []
}

watch(() => store.activeConversationId, async () => {
  followChatBottom = true
  await nextTick()
  scrollChatToBottom()
}, { flush: 'post' })

watch(() => store.messages.map((message) => `${message.id}:${message.content?.length || 0}`), async () => {
  await nextTick()
  if (followChatBottom) scrollChatToBottom()
}, { flush: 'post' })

async function openCitation(citation: AiCitation) {
  if (!citation.point_id && !citation.citation_id) return
  citationVisible.value = true
  citationLoading.value = true
  citationError.value = ''
  selectedCitation.value = null
  try {
    selectedCitation.value = await getAiCitation(citation)
  } catch (err) {
    citationError.value = (err as Error).message || '引用已下架或当前账号无权查看'
  } finally {
    citationLoading.value = false
  }
}

function formatToolMessage(content: string) {
  try { return JSON.stringify(JSON.parse(content), null, 2) }
  catch { return content }
}

async function confirm() {
  if (await store.confirm()) ElMessage.success('操作已执行')
}
</script>

<template>
  <main class="ai-workbench">
    <header class="ai-workbench__hero">
      <div>
        <div class="ai-workbench__eyebrow">
          <span class="ai-workbench__signal"></span>
          AGENT HARNESS · AGENTIC RAG
        </div>
        <h1>AI 工作台</h1>
        <p>把设备知识、实时预约状态和可控操作放进同一个实验台。</p>
      </div>
      <div class="ai-workbench__hero-meta">
        <el-button
          v-if="isSystemAdmin"
          class="model-config-button"
          type="primary"
          plain
          :icon="Setting"
          @click="openModelConfig"
        >
          模型配置
        </el-button>
        <span class="ai-workbench__mode" :class="{ 'is-unavailable': !aiReady }">
          <component :is="aiReady ? CircleCheck : Clock" /> {{ aiStatusLabel }}
        </span>
        <span class="ai-workbench__date">自然日预约 · 学院隔离</span>
      </div>
    </header>

    <nav class="ai-workbench__nav" aria-label="AI 工作台模块">
      <button type="button" :class="{ 'is-active': activeView === 'chat' }" @click="activeView = 'chat'"><Cpu /> 对话工作区</button>
      <button v-if="isLabAdmin" type="button" :class="{ 'is-active': activeView === 'knowledge' }" @click="activeView = 'knowledge'"><Document /> 知识库</button>
      <button v-if="isLabAdmin" type="button" :class="{ 'is-active': activeView === 'domain' }" @click="activeView = 'domain'"><Reading /> 领域词典</button>
      <button type="button" :class="{ 'is-active': activeView === 'usage' }" @click="activeView = 'usage'"><Coin /> 用量与额度</button>
    </nav>

    <template v-if="activeView === 'chat'">
    <div class="ai-workbench__grid">
      <aside class="ai-history panel-surface" :class="{ 'is-open': historyOpen }">
        <div class="ai-history__head">
          <div>
            <span class="section-kicker">WORKSPACE</span>
            <h2>对话</h2>
          </div>
          <el-button class="icon-button" text circle :icon="Plus" title="新建对话" @click="store.createConversation" />
        </div>
        <button class="new-chat" type="button" @click="store.createConversation">
          <Plus />
          <span>发起新任务</span>
        </button>
        <div v-loading="store.loadingHistory" class="ai-history__list">
          <div
            v-for="conversation in store.conversations"
            :key="conversation.id"
            class="conversation-entry"
          >
            <button type="button" class="conversation-item" :class="{ 'is-active': conversation.id === store.activeConversationId }" @click="store.selectConversation(conversation.id)">
              <span class="conversation-item__dot"></span>
              <span class="conversation-item__copy"><strong>{{ conversation.title }}</strong><small>{{ formatTime(conversation.updated_at) || '刚刚' }}</small></span>
              <ArrowDown class="conversation-item__chevron" />
            </button>
            <el-button class="conversation-delete" text circle :icon="Delete" title="删除对话" @click="removeConversation(conversation.id)" />
          </div>
          <div v-if="!store.conversations.length && !store.loadingHistory" class="history-empty">
            <Coin />
            <span>还没有对话</span>
          </div>
        </div>
        <div class="ai-history__foot">
          <Lock />
          <span>工具权限按学院范围实时校验</span>
        </div>
      </aside>

      <section class="ai-chat panel-surface">
        <header class="ai-chat__head">
          <div class="ai-chat__identity">
            <div class="agent-avatar"><Cpu /></div>
            <div>
              <span class="section-kicker">LABFLOW AGENT</span>
              <h2>{{ store.activeConversation?.title || '实验室运营助手' }}</h2>
            </div>
          </div>
          <div class="ai-chat__head-actions">
            <button
              type="button"
              class="ai-head-tool"
              :class="{ 'is-active': historyOpen }"
              :aria-pressed="historyOpen"
              title="打开对话记录"
              @click="historyOpen = !historyOpen"
            >
              <ArrowDown class="ai-head-tool__icon ai-head-tool__icon--history" />
              <span>对话记录</span>
            </button>
            <button
              type="button"
              class="ai-head-tool"
              :class="{ 'is-active': contextOpen }"
              :aria-pressed="contextOpen"
              title="打开运行详情"
              @click="contextOpen = !contextOpen"
            >
              <Reading />
              <span>运行详情</span>
            </button>
          <div class="ai-chat__head-status" :class="{ 'is-unavailable': !aiReady }"><span></span>{{ aiReady ? 'READY' : 'CONFIG REQUIRED' }}</div>
          </div>
        </header>

        <div ref="chatRef" class="ai-chat__body" @scroll="updateChatFollowState">
          <div v-if="store.dlpNotice.length" class="dlp-notice" role="status">
            <Lock />
            <span>敏感信息已在保存和发送前脱敏：{{ store.dlpNotice.map((item) => dlpCategoryLabels[item] || item).join('、') }}</span>
          </div>
          <div v-if="aiStatusError" class="workbench-alert" role="alert">
            <span>{{ aiStatusError }}。为避免请求失败，暂时停用发送。</span>
            <el-button text :icon="Refresh" @click="refreshAiReadiness">重试</el-button>
          </div>
          <div v-else-if="aiReadiness && !aiReady" class="ai-config-required" role="status">
            <div class="ai-config-required__mark"><Setting /></div>
            <div>
              <strong>{{ aiReadiness.message }}</strong>
              <p>模型未完成配置和连通性测试前，AI 对话与知识检索不可用。</p>
            </div>
            <el-button v-if="isSystemAdmin" type="primary" plain @click="openModelConfig">查看配置状态</el-button>
            <span v-else>请联系系统管理员检查根目录 .env 配置并重启服务</span>
          </div>
          <div v-if="bootError || store.error" class="workbench-alert">
            <span>{{ bootError || store.error }}</span>
            <el-button text :icon="Refresh" @click="store.loadConversations">重试</el-button>
          </div>

          <div v-if="!hasMessages" class="chat-empty">
            <div class="chat-empty__mark"><Cpu /></div>
            <span class="section-kicker">OPERATIONS COPILOT</span>
            <h3>从一个具体问题开始</h3>
            <p>{{ aiReady ? '我会先检索知识库，再调用实时业务工具；任何写操作都需要你的确认。' : '配置聊天与知识检索模型后，这里即可开始使用智能助手。' }}</p>
            <div class="prompt-grid">
              <button type="button" @click="input = '帮我找当前学院空闲的显微镜'">找一台空闲显微镜 <Promotion /></button>
              <button type="button" @click="input = '我的预约有哪些？'">查看我的预约 <Promotion /></button>
              <button type="button" @click="input = '怎么做离心机的日常检查？'">查询设备 SOP <Promotion /></button>
              <button type="button" @click="input = '设备 1 在 2026-09-10 到 2026-09-11 可用吗？'">检查日期可用性 <Promotion /></button>
            </div>
          </div>

          <article
            v-for="message in store.messages"
            :key="message.id"
            class="chat-message"
            :class="`chat-message--${message.role}`"
          >
            <div v-if="message.role === 'assistant' || message.role === 'tool'" class="message-avatar"><Cpu /></div>
            <div class="chat-message__content">
              <div class="chat-message__meta">
                {{ message.role === 'user' ? '你' : message.role === 'tool' ? `工具结果 · ${message.metadata?.tool_name || ''}` : 'LabFlow Agent' }}
              </div>
              <div class="chat-message__bubble" :class="{ 'chat-message__bubble--tool': message.role === 'tool' }">
                <pre v-if="message.role === 'tool'">{{ formatToolMessage(message.content) }}</pre>
                <span v-else-if="message.content">{{ messageText(message) }}</span>
                <span v-else class="typing-indicator"><i></i><i></i><i></i></span>
              </div>
              <div v-if="message.role === 'assistant' && messageCitations(message).length" class="message-citations">
                <button
                  v-for="citation in messageCitations(message)"
                  :key="citation.point_id || citation.citation_id"
                  type="button"
                  class="message-citation"
                  :aria-label="`查看引用：${citation.title}`"
                  @click="openCitation(citation)"
                >
                  <Reading /> {{ citation.title }} <span>查看来源</span>
                </button>
              </div>
              <div
                v-for="candidate in memoryCandidates(message)"
                :key="candidate.id"
                class="memory-suggestion"
              >
                <div>
                  <strong>记住这个长期偏好吗？</strong>
                  <p>{{ candidate.content }}</p>
                </div>
                <template v-if="!candidate.status || candidate.status === 'PENDING_CONFIRMATION'">
                  <el-button size="small" @click="store.resolveMemory(candidate, false)">忽略</el-button>
                  <el-button size="small" type="primary" @click="store.resolveMemory(candidate, true)">记住</el-button>
                </template>
                <span v-else class="memory-suggestion__status">
                  {{ candidate.status === 'ACTIVE' ? '已记住' : '已忽略' }}
                </span>
              </div>
            </div>
          </article>

          <section v-if="pending" class="confirmation-card">
            <div class="confirmation-card__head">
              <div class="confirmation-card__icon"><Lock /></div>
              <div>
                <span class="section-kicker section-kicker--amber">CONFIRMATION REQUIRED</span>
                <h3>{{ pending.tool_name === 'forget_ai_memories' ? '删除这些长期记忆？' : `执行 ${pending.tool_name}？` }}</h3>
              </div>
            </div>
            <p>{{ pending.reason }}</p>
            <div class="confirmation-card__facts">
              <div><span>风险</span><strong>{{ pending.risk_summary }}</strong></div>
              <div><span>影响</span><strong>{{ pending.estimated_impact }}</strong></div>
            </div>
            <pre>{{ previewText(pending.preview) }}</pre>
            <div class="confirmation-card__actions">
              <el-button plain @click="store.cancelConfirmation">取消</el-button>
              <el-button type="primary" :loading="store.loading" :icon="Check" @click="confirm">确认执行</el-button>
            </div>
          </section>
        </div>

        <footer class="ai-composer">
          <textarea
            v-model="input"
            rows="2"
            :disabled="store.loading || !aiReady"
            :placeholder="aiReady ? '描述你的设备或预约任务… Enter 发送，Shift + Enter 换行' : 'AI 模型未配置，暂不可发送'"
            @keydown="onKeydown"
          ></textarea>
          <div class="ai-composer__bottom">
            <span><Reading /> 知识库 + 实时工具</span>
            <div>
              <el-button v-if="store.loading" text :icon="VideoPause" @click="store.stop">停止</el-button>
              <el-button type="primary" :icon="Promotion" :disabled="!input.trim() || store.loading || !aiReady" @click="send">发送</el-button>
            </div>
          </div>
        </footer>
      </section>

      <aside class="ai-context panel-surface" :class="{ 'is-open': contextOpen }">
        <div class="context-block">
          <div class="context-block__title"><span class="section-kicker">RUN STATUS</span><Clock /></div>
          <div class="run-status"><span class="run-status__dot"></span><strong>{{ store.loading ? '执行中' : '等待任务' }}</strong></div>
          <div class="run-stats">
            <span><b>{{ store.steps.length }}</b> 个步骤</span>
            <span><b>{{ store.citations.length }}</b> 个来源</span>
          </div>
        </div>

        <div class="context-block context-block--trace">
          <div class="context-block__title"><span class="section-kicker">AGENT TRACE</span><span class="trace-line"></span></div>
          <div v-if="!store.steps.length" class="context-muted">发送任务后显示检索、规划与工具轨迹。</div>
          <div v-for="(step, index) in store.steps" :key="`${step.name}-${index}`" class="trace-step">
            <span class="trace-step__index">0{{ index + 1 }}</span>
            <span class="trace-step__copy"><strong>{{ step.name }}</strong><small>{{ step.status }}</small></span>
            <CircleCheck class="trace-step__ok" />
          </div>
        </div>

        <div class="context-block context-block--sources">
          <div class="context-block__title"><span class="section-kicker">CITED KNOWLEDGE</span><Document /></div>
          <div v-if="!store.citations.length" class="context-muted">回答引用会出现在这里，并且已按学院范围过滤。</div>
          <button
            v-for="citation in store.citations"
            :key="citation.point_id || citation.document_id"
            type="button"
            class="citation citation__button"
            @click="openCitation(citation)"
          >
            <Reading /><span>{{ citation.title }}</span><small>{{ citation.section || '查看原文' }}</small>
          </button>
        </div>

        <div class="context-security"><Lock /><span>写操作默认预览<br />确认后才会落库</span></div>
      </aside>
    </div>

    <footer class="ai-workbench__footer">
      <span>LABFLOW / SCIENTIFIC OPERATIONS CONSOLE</span>
      <span class="ai-workbench__footer-note">实验室知识与操作工作区</span>
    </footer>
    </template>
    <KnowledgePanel v-else-if="activeView === 'knowledge' && isLabAdmin" />
    <DomainDictionaryPanel v-else-if="activeView === 'domain' && isLabAdmin" />
    <UsagePanel v-else />

    <el-dialog
      v-model="modelConfigVisible"
      title="全局模型配置"
      width="560px"
      align-center
      destroy-on-close
      class="model-config-dialog"
    >
      <div v-loading="modelConfigLoading" class="model-config">
        <div class="model-config__notice">
          <Setting />
          <div>
            <strong>管理员全局配置</strong>
            <p>模型参数和密钥由项目根目录 `.env` 提供；修改后重启后端生效，数据库不保存服务密钥。</p>
          </div>
        </div>
        <el-alert
          v-if="modelConfigError"
          :title="modelConfigError"
          type="error"
          :closable="false"
          show-icon
        />
        <el-tabs v-model="modelComponent" class="model-config__tabs" @tab-change="onComponentChange">
          <el-tab-pane label="聊天模型" name="chat" />
          <el-tab-pane label="向量 Embedding" name="embedding" />
          <el-tab-pane label="文档解析" name="mineru" />
        </el-tabs>
        <div class="model-config__state">
          <span :class="activeModelConfig?.configured ? 'is-configured' : ''"></span>
          {{ activeModelConfig?.configured ? '已从 .env 加载密钥' : '尚未配置密钥' }}
          <small>{{ activeModelConfig?.enabled ? '服务已启用' : '服务不可用' }}</small>
        </div>
        <div class="model-config__details">
          <div><span>服务商</span><strong>{{ activeModelConfig?.provider || '未设置' }}</strong></div>
          <div><span>模型</span><strong>{{ activeModelConfig?.model || '未设置' }}</strong></div>
          <div><span>API 地址</span><strong>{{ activeModelConfig?.base_url || '未设置' }}</strong></div>
          <div><span>密钥变量</span><strong>{{ keyEnvironmentName }}</strong></div>
          <template v-if="modelComponent === 'chat'">
            <div><span>个人每日 Token 上限</span><strong>{{ activeModelConfig?.user_daily_token_cap?.toLocaleString() || 0 }}</strong></div>
            <div><span>学院每日 Token 上限</span><strong>{{ activeModelConfig?.college_daily_token_cap?.toLocaleString() || 0 }}</strong></div>
            <div><span>全校每日 Token 上限</span><strong>{{ activeModelConfig?.global_daily_token_cap?.toLocaleString() || 0 }}</strong></div>
          </template>
        </div>
          <section v-if="modelComponent === 'embedding'" class="embedding-rebuild">
            <div class="embedding-rebuild__heading">
              <div>
                <strong>蓝绿索引重建</strong>
                <p>使用当前 `.env` 中的 Embedding 配置重算向量，校验后切换；原集合保留，支持回滚。</p>
              </div>
              <el-button
                v-if="!embeddingRebuild || !['QUEUED', 'RUNNING'].includes(embeddingRebuild.status)"
                type="primary"
                plain
                :loading="embeddingRebuildLoading"
                :disabled="!modelConfigs.embedding?.configured"
                @click="rebuildEmbeddingIndex"
              >重建索引</el-button>
            </div>
            <div v-if="embeddingRebuild" class="embedding-rebuild__job">
              <div class="embedding-rebuild__job-head">
                <span>最近任务 #{{ embeddingRebuild.id }}</span>
                <el-tag size="small" :type="embeddingRebuild.status === 'COMPLETED' ? 'success' : embeddingRebuild.status === 'FAILED' ? 'danger' : 'info'">{{ embeddingRebuild.status }}</el-tag>
              </div>
              <el-progress
                :percentage="embeddingRebuild.total_points ? Math.min(100, Math.round(embeddingRebuild.indexed_points / embeddingRebuild.total_points * 100)) : (embeddingRebuild.status === 'COMPLETED' ? 100 : 0)"
                :status="embeddingRebuild.status === 'FAILED' ? 'exception' : embeddingRebuild.status === 'COMPLETED' ? 'success' : undefined"
              />
              <small>{{ embeddingRebuild.indexed_points.toLocaleString() }} / {{ embeddingRebuild.total_points.toLocaleString() }} chunks · {{ embeddingRebuild.model }}</small>
              <el-button v-if="embeddingRebuild.status === 'COMPLETED'" text type="warning" :loading="embeddingRebuildLoading" @click="rollbackEmbeddingIndex">回滚到上一版索引</el-button>
              <small v-if="embeddingRebuild.error_code" class="embedding-rebuild__error">重建失败（{{ embeddingRebuild.error_code }}），当前索引未切换。</small>
            </div>
            <div v-else class="embedding-rebuild__empty">重建前会先测试模型连通性，不会影响当前在线检索。</div>
          </section>
        <el-alert v-if="modelTestMessage" :title="modelTestMessage" :type="modelTestSuccess ? 'success' : 'error'" :closable="false" show-icon />
        <p class="model-config__hint">此页面仅展示服务状态和环境变量名称，不会读取或回显密钥。修改项目根目录 .env 后需重启后端。</p>
      </div>
      <template #footer>
        <el-button @click="modelConfigVisible = false">关闭</el-button>
        <el-button :loading="modelConfigTesting" @click="testModelConfig">测试连接</el-button>
      </template>
    </el-dialog>
    <el-drawer v-model="citationVisible" title="引用来源" size="min(520px, 92vw)" class="citation-drawer">
      <div v-loading="citationLoading" class="citation-detail">
        <el-alert v-if="citationError" :title="citationError" type="warning" :closable="false" show-icon />
        <template v-else-if="selectedCitation">
          <div class="citation-detail__meta">
            <strong>{{ selectedCitation.title }}</strong>
            <span>{{ selectedCitation.source_type }} · {{ selectedCitation.section }} · v{{ selectedCitation.document_version }}</span>
          </div>
          <pre>{{ selectedCitation.content }}</pre>
        </template>
      </div>
    </el-drawer>
  </main>
</template>

<style scoped lang="scss">
.ai-workbench {
  --console-cyan: var(--accent);
  --console-cyan-soft: color-mix(in srgb, var(--accent) 10%, transparent);
  --console-amber: var(--status-warning);
  --console-green: var(--status-success);
  // Keep the workbench inside the viewport. The chat body below owns the
  // scroll, so a growing conversation must not push the composer downward.
  display: flex;
  flex-direction: column;
  height: calc(100vh - 108px);
  min-height: 0;
  color: var(--text-primary);
}

.ai-workbench__hero {
  flex: 0 0 auto;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 20px;
}

.ai-workbench__nav { flex:0 0 auto; display:flex; align-items:center; gap:5px; width:max-content; max-width:100%; margin:0 0 12px; padding:4px; overflow:auto; background:var(--bg-sunken); border:1px solid var(--border-subtle); border-radius:999px; }
.ai-workbench__nav button { display:inline-flex; align-items:center; gap:7px; min-height:32px; padding:0 13px; color:var(--text-tertiary); background:transparent; border:0; border-radius:999px; cursor:pointer; font:inherit; font-size:11px; white-space:nowrap; transition:background var(--motion-fast),color var(--motion-fast); }
.ai-workbench__nav button svg { width:13px; }.ai-workbench__nav button:hover { color:var(--text-primary); }.ai-workbench__nav button.is-active { color:var(--text-primary); background:var(--bg-elevated); box-shadow:var(--shadow-soft); }
.ai-workbench > :deep(.knowledge-panel),.ai-workbench > :deep(.usage-panel) { flex:1 1 auto; min-height:0; overflow:auto; }
.conversation-entry { display:flex; align-items:center; gap:2px; }
.conversation-entry .conversation-item { flex:1; min-width:0; }
.conversation-delete { flex:none; opacity:0; color:var(--text-tertiary); }
.conversation-entry:hover .conversation-delete,.conversation-entry:focus-within .conversation-delete { opacity:1; }
.model-config__tabs { margin-top:8px; }.model-config__state { display:flex; align-items:center; gap:7px; margin:0 0 14px; color:var(--text-tertiary); font-size:10px; }.model-config__state > span { width:7px; height:7px; background:var(--status-warning); border-radius:50%; }.model-config__state > span.is-configured { background:var(--status-success); }.model-config__state small { margin-left:auto; }
.model-config__details { display:grid; grid-template-columns:1fr 1fr; gap:9px; margin-bottom:15px; }
.model-config__details > div { display:grid; gap:5px; min-width:0; padding:10px 12px; border:1px solid var(--border-subtle); border-radius:9px; background:var(--bg-sunken); }
.model-config__details span { color:var(--text-tertiary); font-size:10px; }
.model-config__details strong { overflow-wrap:anywhere; color:var(--text-primary); font-size:12px; font-weight:550; }
.embedding-rebuild { margin: 4px 0 16px; padding: 16px; border: 1px solid var(--border-subtle); border-radius: 12px; background: color-mix(in srgb, var(--accent) 4%, var(--bg-elevated)); }
.embedding-rebuild__heading,.embedding-rebuild__job-head { display:flex; align-items:center; justify-content:space-between; gap:14px; }
.embedding-rebuild__heading strong { color:var(--text-primary); font-size:13px; }
.embedding-rebuild__heading p,.embedding-rebuild__empty { margin:5px 0 0; color:var(--text-tertiary); font-size:11px; line-height:1.6; }
.embedding-rebuild__job { display:grid; gap:9px; margin-top:14px; padding-top:13px; border-top:1px solid var(--border-subtle); }
.embedding-rebuild__job-head { color:var(--text-secondary); font-size:11px; }
.embedding-rebuild__job small { color:var(--text-tertiary); font-size:10px; }
.embedding-rebuild__error { color:var(--status-danger) !important; }

.ai-workbench__eyebrow,
.section-kicker {
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.ai-workbench__eyebrow {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--console-cyan);
}

.ai-workbench__signal,
.ai-chat__head-status span,
.run-status__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--console-green);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--console-green) 16%, transparent), 0 0 12px color-mix(in srgb, var(--console-green) 55%, transparent);
}

.ai-workbench__hero h1 {
  margin: 8px 0 4px;
  font-family: var(--font-display);
  font-size: clamp(28px, 3vw, 42px);
  letter-spacing: -0.03em;
}

.ai-workbench__hero p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 14px;
}

.ai-workbench__hero-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  padding-bottom: 4px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: 11px;
}

.ai-workbench__mode {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--console-green);
}
.ai-workbench__mode.is-unavailable { color: var(--status-warning); }

.ai-workbench__mode svg { width: 14px; }
.model-config-button { --el-button-text-color: var(--console-cyan); --el-button-border-color: var(--border-accent); --el-button-bg-color: var(--accent-soft); }
.model-config-button:hover { --el-button-hover-text-color: var(--text-on-accent); --el-button-hover-bg-color: var(--console-cyan); --el-button-hover-border-color: var(--console-cyan); }

.panel-surface {
  background: color-mix(in srgb, var(--bg-surface) 92%, transparent);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-soft-light);
}

.ai-workbench__grid {
  flex: 1 1 auto;
  display: grid;
  grid-template-columns: 220px minmax(440px, 1fr) 270px;
  gap: 12px;
  // min-height: 0 is required for a grid item containing a flex scroller;
  // otherwise the grid row expands to the full message history height.
  min-height: 0;
  height: 100%;
}

.ai-history,
.ai-chat,
.ai-context { min-height: 0; }

.ai-history { display: flex; flex-direction: column; padding: 18px 12px 12px; }
.ai-history__head,
.ai-chat__head,
.context-block__title { display: flex; align-items: center; justify-content: space-between; }
.ai-history__head h2,
.ai-chat__head h2 { margin: 5px 0 0; font-size: 15px; font-weight: 600; }
.icon-button { color: var(--text-secondary); }
.icon-button:hover { color: var(--console-cyan); }
.new-chat {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  margin: 20px 0 12px;
  padding: 10px 11px;
  color: var(--console-cyan);
  text-align: left;
  background: var(--console-cyan-soft);
  border: 1px solid var(--border-accent);
  border-radius: var(--radius-control);
  cursor: pointer;
  font-size: 12px;
}
.new-chat:hover { background: color-mix(in srgb, var(--accent) 15%, transparent); }
.new-chat svg { width: 14px; }
.new-chat kbd { margin-left: auto; color: var(--text-tertiary); font-family: var(--font-mono); font-size: 9px; }
.ai-history__list { flex: 1; overflow: auto; }
.conversation-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 8px;
  color: var(--text-secondary);
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-control);
  cursor: pointer;
}
.conversation-item:hover,
.conversation-item.is-active { color: var(--text-primary); background: var(--bg-elevated); border-color: var(--border-subtle); }
.conversation-item.is-active .conversation-item__dot { background: var(--console-cyan); box-shadow: 0 0 8px var(--console-cyan); }
.conversation-item__dot { width: 6px; height: 6px; flex: none; border-radius: 50%; background: var(--text-tertiary); }
.conversation-item__copy { display: grid; gap: 3px; min-width: 0; }
.conversation-item__copy strong { overflow: hidden; font-size: 12px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.conversation-item__copy small { color: var(--text-tertiary); font-family: var(--font-mono); font-size: 9px; }
.conversation-item__chevron { width: 11px; margin-left: auto; color: var(--text-tertiary); transform: rotate(-90deg); }
.history-empty { display: grid; place-items: center; gap: 8px; padding: 60px 0; color: var(--text-tertiary); font-size: 11px; }
.history-empty svg { width: 24px; color: var(--console-cyan); opacity: .6; }
.ai-history__foot { display: flex; gap: 7px; padding-top: 12px; color: var(--text-tertiary); border-top: 1px solid var(--border-subtle); font-size: 10px; line-height: 1.4; }
.ai-history__foot svg { flex: none; width: 14px; color: var(--console-green); }

.ai-chat { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.ai-chat__head { flex: 0 0 auto; padding: 16px 20px; border-bottom: 1px solid var(--border-subtle); }
.ai-chat__identity { display: flex; align-items: center; gap: 10px; }
.agent-avatar,
.message-avatar { display: grid; place-items: center; color: var(--console-cyan); background: var(--console-cyan-soft); border: 1px solid var(--border-accent); }
.agent-avatar { width: 34px; height: 34px; border-radius: 10px; }
.agent-avatar svg { width: 17px; }
.ai-chat__head-status { display: flex; align-items: center; gap: 8px; color: var(--console-green); font-family: var(--font-mono); font-size: 10px; }
.ai-chat__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  padding: 18px clamp(18px, 4vw, 48px);
}
.ai-chat__head-status.is-unavailable { color: var(--status-warning); }
.ai-chat__head-status.is-unavailable span { background: var(--status-warning); box-shadow: 0 0 8px color-mix(in srgb, var(--status-warning) 45%, transparent); }
.ai-config-required { display:flex; align-items:center; gap:12px; margin:0 auto 22px; max-width:720px; padding:14px 16px; border:1px solid color-mix(in srgb,var(--status-warning) 28%,var(--border-subtle)); border-radius:12px; background:color-mix(in srgb,var(--status-warning) 7%,var(--bg-elevated)); }
.ai-config-required__mark { display:grid; place-items:center; flex:none; width:34px; height:34px; color:var(--status-warning); border:1px solid color-mix(in srgb,var(--status-warning) 24%,transparent); border-radius:10px; }
.ai-config-required__mark svg { width:16px; }
.ai-config-required > div:nth-child(2) { flex:1; min-width:0; }
.ai-config-required strong { color:var(--text-primary); font-size:12px; }
.ai-config-required p,.ai-config-required > span { margin:4px 0 0; color:var(--text-tertiary); font-size:10px; line-height:1.5; }
.chat-empty { display: flex; flex-direction: column; align-items: center; max-width: 560px; margin: 20px auto 0; text-align: center; }
.chat-empty__mark { display: grid; place-items: center; width: 60px; height: 60px; margin-bottom: 12px; color: var(--console-cyan); background: radial-gradient(circle, color-mix(in srgb, var(--accent) 18%, transparent), transparent 70%); border: 1px solid var(--border-accent); border-radius: 18px; }
.chat-empty__mark svg { width: 28px; }
.chat-empty h3 { margin: 10px 0 8px; font-family: var(--font-display); font-size: 22px; }
.chat-empty p { max-width: 440px; margin: 0 0 14px; color: var(--text-secondary); font-size: 13px; line-height: 1.65; }
.prompt-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; width: 100%; }
.prompt-grid button { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 9px 12px; color: var(--text-secondary); text-align: left; background: var(--bg-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-control); cursor: pointer; font-size: 11px; }
.prompt-grid button:hover { color: var(--console-cyan); border-color: var(--border-accent); }
.prompt-grid svg { width: 13px; color: var(--text-tertiary); }
.workbench-alert { display: flex; justify-content: space-between; margin-bottom: 16px; padding: 10px 12px; color: var(--status-danger); background: color-mix(in srgb, var(--status-danger) 8%, transparent); border: 1px solid color-mix(in srgb, var(--status-danger) 25%, transparent); border-radius: var(--radius-control); font-size: 12px; }
.chat-message { display: flex; gap: 10px; margin: 0 auto 22px; max-width: 720px; }
.chat-message--user { justify-content: flex-end; }
.chat-message--user .chat-message__content { align-items: flex-end; }
.chat-message__content { display: flex; flex-direction: column; gap: 5px; max-width: 82%; }
.chat-message__meta { color: var(--text-tertiary); font-family: var(--font-mono); font-size: 9px; letter-spacing: .08em; text-transform: uppercase; }
.chat-message__bubble { padding: 11px 14px; color: var(--text-primary); background: var(--bg-elevated); border: 1px solid var(--border-subtle); border-radius: 4px 12px 12px 12px; font-size: 13px; line-height: 1.65; white-space: pre-wrap; }
.message-citations { display:flex; flex-wrap:wrap; gap:7px; margin-top:8px; }
.message-citation { display:inline-flex; align-items:center; gap:6px; padding:5px 9px; color:var(--text-secondary); background:var(--bg-sunken); border:1px solid var(--border-subtle); border-radius:999px; cursor:pointer; font:inherit; font-size:10px; }
.message-citation:hover { color:var(--console-cyan); border-color:var(--console-cyan); }
.message-citation svg { width:12px; color:var(--console-cyan); }
.message-citation span { color:var(--text-tertiary); }
.chat-message--user .chat-message__bubble { color: var(--text-on-accent); background: var(--console-cyan); border-color: transparent; border-radius: 12px 4px 12px 12px; }
.message-avatar { flex: none; width: 25px; height: 25px; margin-top: 16px; border-radius: 7px; }
.message-avatar svg { width: 13px; }
.typing-indicator { display: inline-flex; gap: 4px; }
.typing-indicator i { width: 5px; height: 5px; border-radius: 50%; background: var(--console-cyan); animation: typing 1s ease-in-out infinite; }
.typing-indicator i:nth-child(2) { animation-delay: .12s; }.typing-indicator i:nth-child(3) { animation-delay: .24s; }
@keyframes typing { 0%, 100% { opacity: .3; transform: translateY(0); } 50% { opacity: 1; transform: translateY(-3px); } }

.confirmation-card { max-width: 720px; margin: 6px auto 22px; padding: 16px; background: color-mix(in srgb, var(--console-amber) 6%, transparent); border: 1px solid color-mix(in srgb, var(--console-amber) 35%, transparent); border-radius: var(--radius-card); }
.confirmation-card__head { display: flex; gap: 10px; align-items: center; }.confirmation-card__icon { display: grid; place-items: center; width: 30px; height: 30px; color: var(--console-amber); background: color-mix(in srgb, var(--console-amber) 12%, transparent); border-radius: 8px; }.confirmation-card__icon svg { width: 16px; }
.section-kicker--amber { color: var(--console-amber); }.confirmation-card h3 { margin: 4px 0 0; font-size: 14px; }.confirmation-card > p { margin: 14px 0; color: var(--text-secondary); font-size: 12px; }
.confirmation-card__facts { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }.confirmation-card__facts div { display: grid; gap: 4px; padding: 9px; background: color-mix(in srgb, var(--bg-sunken) 70%, transparent); border-radius: 7px; }.confirmation-card__facts span { color: var(--text-tertiary); font-size: 10px; }.confirmation-card__facts strong { color: var(--text-primary); font-size: 11px; font-weight: 500; line-height: 1.4; }
.confirmation-card pre { max-height: 150px; overflow: auto; margin: 10px 0; padding: 10px; color: var(--text-secondary); background: var(--bg-sunken); border: 1px solid var(--border-subtle); border-radius: 7px; font-family: var(--font-mono); font-size: 10px; line-height: 1.5; }.confirmation-card__actions { display: flex; justify-content: flex-end; gap: 8px; }

.ai-composer { flex: 0 0 auto; position: relative; z-index: 1; padding: 12px 20px 16px; border-top: 1px solid var(--border-subtle); background: color-mix(in srgb, var(--bg-sunken) 92%, transparent); box-shadow: 0 -8px 20px color-mix(in srgb, var(--text-primary) 12%, transparent); }.ai-composer textarea { display: block; width: 100%; box-sizing: border-box; padding: 11px 12px; resize: none; color: var(--text-primary); background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: var(--radius-control); outline: none; font: inherit; font-size: 12px; }.ai-composer textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 8%, transparent); }.ai-composer textarea:disabled { opacity: .65; }.ai-composer__bottom { display: flex; align-items: center; justify-content: space-between; padding-top: 8px; color: var(--text-tertiary); font-size: 10px; }.ai-composer__bottom > span { display: inline-flex; align-items: center; gap: 5px; }.ai-composer__bottom svg { width: 13px; color: var(--console-cyan); }

.ai-context { display: flex; flex-direction: column; overflow: auto; }.context-block { padding: 18px 16px; border-bottom: 1px solid var(--border-subtle); }.context-block__title svg { width: 14px; color: var(--text-tertiary); }.run-status { display: flex; align-items: center; gap: 9px; margin: 17px 0 12px; font-size: 13px; }.run-status__dot { background: var(--console-cyan); box-shadow: 0 0 0 4px color-mix(in srgb, var(--console-cyan) 12%, transparent), 0 0 12px color-mix(in srgb, var(--console-cyan) 55%, transparent); }.run-stats { display: flex; gap: 16px; color: var(--text-tertiary); font-family: var(--font-mono); font-size: 10px; }.run-stats b { color: var(--text-primary); font-size: 14px; font-weight: 500; }.context-block--trace { flex: none; min-height: 170px; }.trace-line { flex: 1; height: 1px; margin-left: 10px; background: linear-gradient(90deg, var(--border-strong), transparent); }.context-muted { margin-top: 18px; color: var(--text-tertiary); font-size: 11px; line-height: 1.6; }.trace-step { display: flex; align-items: center; gap: 9px; margin-top: 13px; }.trace-step__index { color: var(--text-tertiary); font-family: var(--font-mono); font-size: 9px; }.trace-step__copy { display: grid; gap: 2px; min-width: 0; }.trace-step__copy strong { overflow: hidden; color: var(--text-secondary); font-family: var(--font-mono); font-size: 10px; font-weight: 500; text-overflow: ellipsis; }.trace-step__copy small { color: var(--text-tertiary); font-size: 10px; }.trace-step__ok { width: 13px; margin-left: auto; color: var(--console-green); }.context-block--sources { flex: 1; }.citation { margin-top: 12px; border-bottom: 1px solid var(--border-subtle); }.citation summary { display: flex; align-items: center; gap: 7px; padding-bottom: 10px; color: var(--text-secondary); cursor: pointer; list-style: none; font-size: 11px; }.citation summary::-webkit-details-marker { display: none; }.citation summary svg { width: 13px; color: var(--console-cyan); }.citation summary span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.citation summary small { margin-left: auto; color: var(--text-tertiary); font-family: var(--font-mono); }.citation p { margin: 0 0 12px; color: var(--text-tertiary); font-size: 10px; line-height: 1.6; }.context-security { display: flex; gap: 8px; margin: 14px; padding: 10px; color: var(--text-tertiary); background: color-mix(in srgb, var(--console-green) 6%, transparent); border: 1px solid color-mix(in srgb, var(--console-green) 16%, transparent); border-radius: 7px; font-size: 10px; line-height: 1.5; }.context-security svg { flex: none; width: 14px; color: var(--console-green); }
.ai-workbench__footer { flex: 0 0 auto; display: flex; justify-content: space-between; padding: 12px 2px; color: var(--text-tertiary); font-family: var(--font-mono); font-size: 9px; letter-spacing: .08em; }.ai-workbench__footer a { color: var(--text-tertiary); text-decoration: none; }.ai-workbench__footer a:hover { color: var(--console-cyan); }

.model-config__notice { display: flex; gap: 10px; margin-bottom: 16px; padding: 12px; color: var(--text-secondary); background: color-mix(in srgb, var(--accent) 7%, transparent); border: 1px solid color-mix(in srgb, var(--accent) 18%, transparent); border-radius: 8px; }
.model-config__notice > svg { flex: none; width: 18px; margin-top: 2px; color: var(--console-cyan); }
.model-config__notice strong { color: var(--text-primary); font-size: 13px; }
.model-config__notice p { margin: 5px 0 0; color: var(--text-tertiary); font-size: 11px; line-height: 1.5; }
.model-config__hint { margin: -2px 0 0; color: var(--text-tertiary); font-size: 11px; }
.model-config-dialog :deep(.el-dialog) { display:flex; flex-direction:column; max-height:calc(100vh - 48px); overflow:hidden; background:var(--bg-surface); border:1px solid var(--border-default); }
.model-config-dialog :deep(.el-dialog__header),.model-config-dialog :deep(.el-dialog__footer) { flex:0 0 auto; }
.model-config-dialog :deep(.el-dialog__title), .model-config-dialog :deep(.el-form-item__label) { color: var(--text-primary); }
.model-config-dialog :deep(.el-dialog__body) { flex:1 1 auto; min-height:0; overflow-y:auto; color:var(--text-secondary); }

@media (max-width: 1180px) { .ai-workbench__grid { grid-template-columns: 190px minmax(400px, 1fr); }.ai-context { display: none; } }
@media (max-width: 760px) { .ai-workbench { height: auto; min-height: calc(100vh - 108px); }.ai-workbench__hero { align-items: flex-start; flex-direction: column; }.ai-workbench__hero-meta { padding: 0; }.ai-workbench__grid { grid-template-columns: 1fr; height: auto; flex: 0 0 auto; min-height: 0; }.ai-history { min-height: 220px; }.ai-history__list { max-height: 120px; }.ai-chat { height: 620px; min-height: 620px; }.prompt-grid { grid-template-columns: 1fr; }.ai-workbench__footer { flex-direction: column; gap: 6px; }.model-config__details { grid-template-columns:1fr; }.conversation-delete { opacity:1; } }
@media (prefers-reduced-motion: reduce) { .typing-indicator i { animation: none; } }

// The chat is the product surface. History and run details stay available as
// focused drawers so they never squeeze the composer or turn the workbench
// into a three-column admin dashboard.
.ai-workbench__grid {
  position: relative;
  grid-template-columns: minmax(0, 1fr);
}

.ai-chat {
  grid-column: 1;
  min-width: 0;
}

.ai-history,
.ai-context {
  display: none;
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: 5;
  width: min(320px, calc(100% - 32px));
  box-shadow: var(--shadow-floating);
}

.ai-history.is-open,
.ai-context.is-open {
  display: flex;
}

.ai-history.is-open { left: 0; }
.ai-context.is-open { right: 0; }

.ai-chat__head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ai-head-tool {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  padding: 0 9px;
  color: var(--text-tertiary);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 999px;
  cursor: pointer;
  font: inherit;
  font-size: 11px;
  transition: color var(--motion-fast), background var(--motion-fast), border-color var(--motion-fast);
}

.ai-head-tool svg { width: 14px; }
.ai-head-tool__icon--history { transform: rotate(90deg); }
.ai-head-tool:hover,
.ai-head-tool.is-active {
  color: var(--accent);
  background: var(--accent-soft);
  border-color: var(--border-accent);
}

.ai-chat__head-status { flex: none; }
.ai-workbench__footer-note { letter-spacing: normal; }

@media (max-width: 760px) {
  .ai-chat__head-actions { gap: 2px; }
  .ai-head-tool span { display: none; }
  .ai-head-tool { padding: 0 7px; }
  .ai-chat__head-status { margin-left: 4px; }
  .ai-history.is-open,
  .ai-context.is-open { width: min(320px, calc(100% - 20px)); }
}

.chat-message__bubble--tool { background: var(--bg-sunken); }
.memory-suggestion { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:8px; padding:12px; background:color-mix(in srgb, var(--console-cyan) 6%, var(--bg-elevated)); border:1px solid color-mix(in srgb, var(--console-cyan) 24%, transparent); border-radius:10px; }
.memory-suggestion > div { flex:1 1 100%; }
.memory-suggestion strong { color:var(--text-primary); font-size:12px; }
.memory-suggestion p { margin:5px 0 0; color:var(--text-secondary); font-size:12px; line-height:1.5; }
.memory-suggestion__status { color:var(--text-tertiary); font-size:11px; }
.chat-message__bubble--tool pre { max-width: min(72vw, 640px); max-height: 220px; overflow: auto; margin: 0; color: var(--text-secondary); font: 11px/1.55 var(--font-mono); white-space: pre-wrap; overflow-wrap: anywhere; }
.dlp-notice { display:flex; align-items:center; gap:8px; max-width:720px; margin:0 auto 14px; padding:8px 11px; color:var(--text-secondary); background:color-mix(in srgb, var(--status-warning) 7%, transparent); border:1px solid color-mix(in srgb, var(--status-warning) 20%, transparent); border-radius:var(--radius-control); font-size:11px; }
.dlp-notice svg { flex:none; width:14px; color:var(--status-warning); }
.citation__button { display:flex; align-items:center; gap:8px; width:100%; padding:9px 0; color:var(--text-secondary); text-align:left; background:transparent; border:0; cursor:pointer; font:inherit; font-size:11px; }
.citation__button:hover { color:var(--console-cyan); }
.citation__button svg { flex:none; width:13px; color:var(--console-cyan); }
.citation__button span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.citation__button small { margin-left:auto; color:var(--text-tertiary); white-space:nowrap; }
.citation-detail__meta { display:grid; gap:7px; margin-bottom:14px; }
.citation-detail__meta strong { color:var(--text-primary); font-size:15px; }
.citation-detail__meta span { color:var(--text-tertiary); font-size:11px; }
.citation-detail pre { max-height:calc(100vh - 190px); overflow:auto; margin:0; padding:16px; color:var(--text-secondary); background:var(--bg-sunken); border:1px solid var(--border-subtle); border-radius:10px; font:12px/1.75 var(--font-mono); white-space:pre-wrap; overflow-wrap:anywhere; }
</style>
