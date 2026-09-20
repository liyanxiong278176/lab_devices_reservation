<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  ArrowDown,
  Reading,
  Check,
  CircleCheck,
  Clock,
  Cpu,
  Coin,
  Document,
  Plus,
  Promotion,
  Refresh,
  Lock,
  VideoPause,
  Setting,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import {
  getAiModelConfig,
  updateAiModelConfig,
} from '@/api/aiV2'
import { useAiWorkbenchStore } from '@/stores/aiWorkbench'
import { useUserStore } from '@/stores/user'
import type { AiModelConfigPayload } from '@/types/aiWorkbench'

const store = useAiWorkbenchStore()
const userStore = useUserStore()
const input = ref('')
const chatRef = ref<HTMLElement | null>(null)
const bootError = ref('')

const isSystemAdmin = computed(() => userStore.hasRole('SYS_ADMIN'))
const modelConfigVisible = ref(false)
const modelConfigLoading = ref(false)
const modelConfigSaving = ref(false)
const modelConfigError = ref('')
const modelFormRef = ref<{ validate: () => Promise<boolean> } | null>(null)
const modelForm = reactive<AiModelConfigPayload>({
  provider: 'openai',
  model: 'gpt-4o-mini',
  api_key: '',
  base_url: '',
  enabled: true,
  daily_quota: 0,
})
const modelOptions = [
  { label: 'OpenAI GPT-4o mini', value: 'gpt-4o-mini' },
  { label: 'OpenAI GPT-4.1 mini', value: 'gpt-4.1-mini' },
  { label: 'Qwen 2.5 72B', value: 'Qwen/Qwen2.5-72B-Instruct' },
  { label: 'DeepSeek V3', value: 'deepseek-ai/DeepSeek-V3' },
]
const baseUrlOptions = [
  { label: 'OpenAI 官方', value: 'https://api.openai.com/v1' },
  { label: 'SiliconFlow', value: 'https://api.siliconflow.cn/v1' },
]
const modelRules = {
  provider: [{ required: true, message: '请选择模型服务商', trigger: 'change' }],
  model: [{ required: true, message: '请选择或填写模型名称', trigger: 'change' }],
}

const hasMessages = computed(() => store.messages.length > 0)
const pending = computed(() => store.pendingConfirmation)

onMounted(async () => {
  try {
    await store.loadConversations()
  } catch (err) {
    bootError.value = (err as Error).message || '无法加载 AI 工作台'
  }
})

onBeforeUnmount(() => store.stop())

async function send() {
  const text = input.value.trim()
  if (!text || store.loading) return
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
    const config = await getAiModelConfig()
    modelForm.provider = config.provider || 'openai'
    modelForm.model = config.model || 'gpt-4o-mini'
    modelForm.base_url = config.base_url || ''
    modelForm.enabled = config.enabled
    modelForm.daily_quota = config.daily_quota || 0
    // Never put the encrypted or plaintext key into the form. An empty value
    // means “keep the existing key” when the backend already has one.
    modelForm.api_key = ''
  } catch (err) {
    modelConfigError.value = (err as Error).message || '无法加载模型配置'
  } finally {
    modelConfigLoading.value = false
  }
}

async function saveModelConfig() {
  if (modelConfigSaving.value) return
  const valid = await modelFormRef.value?.validate()
  if (valid === false) return
  modelConfigSaving.value = true
  modelConfigError.value = ''
  try {
    const updated = await updateAiModelConfig({
      provider: modelForm.provider.trim(),
      model: modelForm.model.trim(),
      api_key: modelForm.api_key?.trim() || undefined,
      base_url: modelForm.base_url?.trim() || undefined,
      enabled: modelForm.enabled,
      daily_quota: Number(modelForm.daily_quota) || 0,
    })
    modelConfigVisible.value = false
    if (updated.enabled && !updated.configured) {
      ElMessage.warning('配置已保存，但 API Key 为空，AI 仍会使用本地降级模式')
    } else {
      ElMessage.success('全局模型配置已更新，新的 AI 请求将使用该配置')
    }
  } catch (err) {
    modelConfigError.value = (err as Error).message || '保存模型配置失败'
  } finally {
    modelConfigSaving.value = false
  }
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
        <span class="ai-workbench__mode"><CircleCheck /> 系统在线</span>
        <span class="ai-workbench__date">自然日预约 · 学院隔离</span>
      </div>
    </header>

    <div class="ai-workbench__grid">
      <aside class="ai-history panel-surface">
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
          <kbd>⌘ K</kbd>
        </button>
        <div v-loading="store.loadingHistory" class="ai-history__list">
          <button
            v-for="conversation in store.conversations"
            :key="conversation.id"
            type="button"
            class="conversation-item"
            :class="{ 'is-active': conversation.id === store.activeConversationId }"
            @click="store.selectConversation(conversation.id)"
          >
            <span class="conversation-item__dot"></span>
            <span class="conversation-item__copy">
              <strong>{{ conversation.title }}</strong>
              <small>{{ formatTime(conversation.updated_at) || '刚刚' }}</small>
            </span>
            <ArrowDown class="conversation-item__chevron" />
          </button>
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
          <div class="ai-chat__head-status"><span></span> READY</div>
        </header>

        <div ref="chatRef" class="ai-chat__body">
          <div v-if="bootError || store.error" class="workbench-alert">
            <span>{{ bootError || store.error }}</span>
            <el-button text :icon="Refresh" @click="store.loadConversations">重试</el-button>
          </div>

          <div v-if="!hasMessages" class="chat-empty">
            <div class="chat-empty__mark"><Cpu /></div>
            <span class="section-kicker">OPERATIONS COPILOT</span>
            <h3>从一个具体问题开始</h3>
            <p>我会先检索知识库，再调用实时业务工具；任何写操作都需要你的确认。</p>
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
            <div v-if="message.role === 'assistant'" class="message-avatar"><Cpu /></div>
            <div class="chat-message__content">
              <div class="chat-message__meta">
                {{ message.role === 'user' ? '你' : 'LabFlow Agent' }}
              </div>
              <div class="chat-message__bubble">
                <span v-if="message.content">{{ message.content }}</span>
                <span v-else class="typing-indicator"><i></i><i></i><i></i></span>
              </div>
            </div>
          </article>

          <section v-if="pending" class="confirmation-card">
            <div class="confirmation-card__head">
              <div class="confirmation-card__icon"><Lock /></div>
              <div>
                <span class="section-kicker section-kicker--amber">CONFIRMATION REQUIRED</span>
                <h3>执行 {{ pending.tool_name }}？</h3>
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
            :disabled="store.loading"
            placeholder="描述你的设备或预约任务… Enter 发送，Shift + Enter 换行"
            @keydown="onKeydown"
          ></textarea>
          <div class="ai-composer__bottom">
            <span><Reading /> 知识库 + 实时工具</span>
            <div>
              <el-button v-if="store.loading" text :icon="VideoPause" @click="store.stop">停止</el-button>
              <el-button type="primary" :icon="Promotion" :disabled="!input.trim() || store.loading" @click="send">发送</el-button>
            </div>
          </div>
        </footer>
      </section>

      <aside class="ai-context panel-surface">
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
          <details v-for="citation in store.citations" :key="citation.point_id || citation.document_id" class="citation">
            <summary><Reading /><span>{{ citation.title }}</span><small>{{ citation.score?.toFixed(2) }}</small></summary>
            <p>{{ citation.content }}</p>
          </details>
        </div>

        <div class="context-security"><Lock /><span>写操作默认预览<br />确认后才会落库</span></div>
      </aside>
    </div>

    <footer class="ai-workbench__footer">
      <span>LABFLOW / SCIENTIFIC OPERATIONS CONSOLE</span>
      <a href="https://deerflow.tech" target="_blank" rel="noreferrer">Created By Deerflow</a>
    </footer>

    <el-dialog
      v-model="modelConfigVisible"
      title="全局模型配置"
      width="560px"
      destroy-on-close
      class="model-config-dialog"
    >
      <div v-loading="modelConfigLoading" class="model-config">
        <div class="model-config__notice">
          <Setting />
          <div>
            <strong>管理员全局配置</strong>
            <p>保存后所有未设置学院专属模型的用户都会使用此配置。</p>
          </div>
        </div>
        <el-alert
          v-if="modelConfigError"
          :title="modelConfigError"
          type="error"
          :closable="false"
          show-icon
        />
        <el-form
          ref="modelFormRef"
          :model="modelForm"
          :rules="modelRules"
          label-position="top"
          class="model-config__form"
        >
          <el-row :gutter="16">
            <el-col :span="10">
              <el-form-item label="服务商" prop="provider">
                <el-select v-model="modelForm.provider" filterable allow-create>
                  <el-option label="OpenAI" value="openai" />
                  <el-option label="SiliconFlow" value="siliconflow" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="14">
              <el-form-item label="模型" prop="model">
                <el-select v-model="modelForm.model" filterable allow-create>
                  <el-option
                    v-for="option in modelOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="API 地址">
            <el-select v-model="modelForm.base_url" filterable allow-create clearable>
              <el-option
                v-for="option in baseUrlOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="modelForm.api_key"
              type="password"
              show-password
              autocomplete="new-password"
              placeholder="首次配置必填；留空则保留当前密钥"
            />
          </el-form-item>
          <div class="model-config__row">
            <el-form-item label="启用 AI">
              <el-switch v-model="modelForm.enabled" active-text="启用" inactive-text="停用" />
            </el-form-item>
            <el-form-item label="每日额度（0 表示不限）">
              <el-input-number v-model="modelForm.daily_quota" :min="0" :max="1000000" :step="100" />
            </el-form-item>
          </div>
          <p class="model-config__hint">密钥仅在服务端加密保存，不会回显到页面。</p>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="modelConfigVisible = false">取消</el-button>
        <el-button type="primary" :loading="modelConfigSaving" @click="saveModelConfig">
          保存并应用
        </el-button>
      </template>
    </el-dialog>
  </main>
</template>

<style scoped lang="scss">
.ai-workbench {
  --console-cyan: #22d3ee;
  --console-cyan-soft: rgba(34, 211, 238, 0.12);
  --console-amber: #fbbf24;
  --console-green: #34d399;
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
  box-shadow: 0 0 0 4px rgba(52, 211, 153, 0.1), 0 0 12px rgba(52, 211, 153, 0.6);
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

.ai-workbench__mode svg { width: 14px; }
.model-config-button { --el-button-text-color: var(--console-cyan); --el-button-border-color: rgba(34,211,238,.35); --el-button-bg-color: rgba(34,211,238,.08); }
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
  border: 1px solid rgba(34, 211, 238, 0.22);
  border-radius: var(--radius-control);
  cursor: pointer;
  font-size: 12px;
}
.new-chat:hover { background: rgba(34, 211, 238, 0.18); }
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
.message-avatar { display: grid; place-items: center; color: var(--console-cyan); background: var(--console-cyan-soft); border: 1px solid rgba(34, 211, 238, 0.22); }
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
  padding: 28px clamp(18px, 4vw, 48px);
}
.chat-empty { display: flex; flex-direction: column; align-items: center; max-width: 560px; margin: 40px auto 0; text-align: center; }
.chat-empty__mark { display: grid; place-items: center; width: 60px; height: 60px; margin-bottom: 18px; color: var(--console-cyan); background: radial-gradient(circle, rgba(34,211,238,.18), transparent 70%); border: 1px solid rgba(34,211,238,.28); border-radius: 18px; }
.chat-empty__mark svg { width: 28px; }
.chat-empty h3 { margin: 10px 0 8px; font-family: var(--font-display); font-size: 22px; }
.chat-empty p { max-width: 440px; margin: 0 0 24px; color: var(--text-secondary); font-size: 13px; line-height: 1.65; }
.prompt-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; width: 100%; }
.prompt-grid button { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 11px 12px; color: var(--text-secondary); text-align: left; background: var(--bg-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-control); cursor: pointer; font-size: 11px; }
.prompt-grid button:hover { color: var(--console-cyan); border-color: rgba(34,211,238,.38); }
.prompt-grid svg { width: 13px; color: var(--text-tertiary); }
.workbench-alert { display: flex; justify-content: space-between; margin-bottom: 16px; padding: 10px 12px; color: var(--status-danger); background: rgba(248,113,113,.08); border: 1px solid rgba(248,113,113,.25); border-radius: var(--radius-control); font-size: 12px; }
.chat-message { display: flex; gap: 10px; margin: 0 auto 22px; max-width: 720px; }
.chat-message--user { justify-content: flex-end; }
.chat-message--user .chat-message__content { align-items: flex-end; }
.chat-message__content { display: flex; flex-direction: column; gap: 5px; max-width: 82%; }
.chat-message__meta { color: var(--text-tertiary); font-family: var(--font-mono); font-size: 9px; letter-spacing: .08em; text-transform: uppercase; }
.chat-message__bubble { padding: 11px 14px; color: var(--text-primary); background: var(--bg-elevated); border: 1px solid var(--border-subtle); border-radius: 4px 12px 12px 12px; font-size: 13px; line-height: 1.65; white-space: pre-wrap; }
.chat-message--user .chat-message__bubble { color: var(--text-on-accent); background: var(--console-cyan); border-color: transparent; border-radius: 12px 4px 12px 12px; }
.message-avatar { flex: none; width: 25px; height: 25px; margin-top: 16px; border-radius: 7px; }
.message-avatar svg { width: 13px; }
.typing-indicator { display: inline-flex; gap: 4px; }
.typing-indicator i { width: 5px; height: 5px; border-radius: 50%; background: var(--console-cyan); animation: typing 1s ease-in-out infinite; }
.typing-indicator i:nth-child(2) { animation-delay: .12s; }.typing-indicator i:nth-child(3) { animation-delay: .24s; }
@keyframes typing { 0%, 100% { opacity: .3; transform: translateY(0); } 50% { opacity: 1; transform: translateY(-3px); } }

.confirmation-card { max-width: 720px; margin: 6px auto 22px; padding: 16px; background: rgba(251,191,36,.06); border: 1px solid rgba(251,191,36,.35); border-radius: var(--radius-card); }
.confirmation-card__head { display: flex; gap: 10px; align-items: center; }.confirmation-card__icon { display: grid; place-items: center; width: 30px; height: 30px; color: var(--console-amber); background: rgba(251,191,36,.12); border-radius: 8px; }.confirmation-card__icon svg { width: 16px; }
.section-kicker--amber { color: var(--console-amber); }.confirmation-card h3 { margin: 4px 0 0; font-size: 14px; }.confirmation-card > p { margin: 14px 0; color: var(--text-secondary); font-size: 12px; }
.confirmation-card__facts { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }.confirmation-card__facts div { display: grid; gap: 4px; padding: 9px; background: rgba(0,0,0,.15); border-radius: 7px; }.confirmation-card__facts span { color: var(--text-tertiary); font-size: 10px; }.confirmation-card__facts strong { color: var(--text-primary); font-size: 11px; font-weight: 500; line-height: 1.4; }
.confirmation-card pre { max-height: 150px; overflow: auto; margin: 10px 0; padding: 10px; color: var(--text-secondary); background: var(--bg-sunken); border: 1px solid var(--border-subtle); border-radius: 7px; font-family: var(--font-mono); font-size: 10px; line-height: 1.5; }.confirmation-card__actions { display: flex; justify-content: flex-end; gap: 8px; }

.ai-composer { flex: 0 0 auto; position: relative; z-index: 1; padding: 12px 20px 16px; border-top: 1px solid var(--border-subtle); background: color-mix(in srgb, var(--bg-sunken) 92%, transparent); box-shadow: 0 -8px 20px rgba(0, 0, 0, .12); }.ai-composer textarea { display: block; width: 100%; box-sizing: border-box; padding: 11px 12px; resize: none; color: var(--text-primary); background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: var(--radius-control); outline: none; font: inherit; font-size: 12px; }.ai-composer textarea:focus { border-color: rgba(34,211,238,.55); box-shadow: 0 0 0 3px rgba(34,211,238,.08); }.ai-composer textarea:disabled { opacity: .65; }.ai-composer__bottom { display: flex; align-items: center; justify-content: space-between; padding-top: 8px; color: var(--text-tertiary); font-size: 10px; }.ai-composer__bottom > span { display: inline-flex; align-items: center; gap: 5px; }.ai-composer__bottom svg { width: 13px; color: var(--console-cyan); }

.ai-context { display: flex; flex-direction: column; overflow: auto; }.context-block { padding: 18px 16px; border-bottom: 1px solid var(--border-subtle); }.context-block__title svg { width: 14px; color: var(--text-tertiary); }.run-status { display: flex; align-items: center; gap: 9px; margin: 17px 0 12px; font-size: 13px; }.run-status__dot { background: var(--console-cyan); box-shadow: 0 0 0 4px rgba(34,211,238,.1), 0 0 12px rgba(34,211,238,.6); }.run-stats { display: flex; gap: 16px; color: var(--text-tertiary); font-family: var(--font-mono); font-size: 10px; }.run-stats b { color: var(--text-primary); font-size: 14px; font-weight: 500; }.context-block--trace { flex: none; min-height: 170px; }.trace-line { flex: 1; height: 1px; margin-left: 10px; background: linear-gradient(90deg, var(--border-strong), transparent); }.context-muted { margin-top: 18px; color: var(--text-tertiary); font-size: 11px; line-height: 1.6; }.trace-step { display: flex; align-items: center; gap: 9px; margin-top: 13px; }.trace-step__index { color: var(--text-tertiary); font-family: var(--font-mono); font-size: 9px; }.trace-step__copy { display: grid; gap: 2px; min-width: 0; }.trace-step__copy strong { overflow: hidden; color: var(--text-secondary); font-family: var(--font-mono); font-size: 10px; font-weight: 500; text-overflow: ellipsis; }.trace-step__copy small { color: var(--text-tertiary); font-size: 10px; }.trace-step__ok { width: 13px; margin-left: auto; color: var(--console-green); }.context-block--sources { flex: 1; }.citation { margin-top: 12px; border-bottom: 1px solid var(--border-subtle); }.citation summary { display: flex; align-items: center; gap: 7px; padding-bottom: 10px; color: var(--text-secondary); cursor: pointer; list-style: none; font-size: 11px; }.citation summary::-webkit-details-marker { display: none; }.citation summary svg { width: 13px; color: var(--console-cyan); }.citation summary span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.citation summary small { margin-left: auto; color: var(--text-tertiary); font-family: var(--font-mono); }.citation p { margin: 0 0 12px; color: var(--text-tertiary); font-size: 10px; line-height: 1.6; }.context-security { display: flex; gap: 8px; margin: 14px; padding: 10px; color: var(--text-tertiary); background: rgba(52,211,153,.06); border: 1px solid rgba(52,211,153,.16); border-radius: 7px; font-size: 10px; line-height: 1.5; }.context-security svg { flex: none; width: 14px; color: var(--console-green); }
.ai-workbench__footer { flex: 0 0 auto; display: flex; justify-content: space-between; padding: 12px 2px; color: var(--text-tertiary); font-family: var(--font-mono); font-size: 9px; letter-spacing: .08em; }.ai-workbench__footer a { color: var(--text-tertiary); text-decoration: none; }.ai-workbench__footer a:hover { color: var(--console-cyan); }

.model-config__notice { display: flex; gap: 10px; margin-bottom: 16px; padding: 12px; color: var(--text-secondary); background: rgba(34,211,238,.07); border: 1px solid rgba(34,211,238,.18); border-radius: 8px; }
.model-config__notice > svg { flex: none; width: 18px; margin-top: 2px; color: var(--console-cyan); }
.model-config__notice strong { color: var(--text-primary); font-size: 13px; }
.model-config__notice p { margin: 5px 0 0; color: var(--text-tertiary); font-size: 11px; line-height: 1.5; }
.model-config__form :deep(.el-select), .model-config__form :deep(.el-input), .model-config__form :deep(.el-input-number) { width: 100%; }
.model-config__row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.model-config__hint { margin: -2px 0 0; color: var(--text-tertiary); font-size: 11px; }
.model-config-dialog :deep(.el-dialog) { background: var(--bg-surface); border: 1px solid var(--border-default); }
.model-config-dialog :deep(.el-dialog__title), .model-config-dialog :deep(.el-form-item__label) { color: var(--text-primary); }
.model-config-dialog :deep(.el-dialog__body) { color: var(--text-secondary); }

@media (max-width: 1180px) { .ai-workbench__grid { grid-template-columns: 190px minmax(400px, 1fr); }.ai-context { display: none; } }
@media (max-width: 760px) { .ai-workbench { height: auto; min-height: calc(100vh - 108px); }.ai-workbench__hero { align-items: flex-start; flex-direction: column; }.ai-workbench__hero-meta { padding: 0; }.ai-workbench__grid { grid-template-columns: 1fr; height: auto; flex: 0 0 auto; min-height: 0; }.ai-history { min-height: 220px; }.ai-history__list { max-height: 120px; }.ai-chat { height: 620px; min-height: 620px; }.prompt-grid { grid-template-columns: 1fr; }.ai-workbench__footer { flex-direction: column; gap: 6px; } }
@media (prefers-reduced-motion: reduce) { .typing-indicator i { animation: none; } }
</style>
