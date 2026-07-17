<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Close, Promotion, ChatLineSquare, VideoPause, Setting } from '@element-plus/icons-vue'
import { useAiStore } from '@/stores/ai'
import MessageCard from './MessageCard.vue'
import ConfirmationCard from './ConfirmationCard.vue'
import StepTimelineCard from './StepTimelineCard.vue'
import SuggestionRow from './SuggestionRow.vue'
import AiConfig from './AiConfig.vue'

const store = useAiStore()

const inputText = ref('')
const messagesRef = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLTextAreaElement | null>(null)

const confirmationsOnly = computed(() => store.confirmations.filter((c) => c.status === 'pending'))

// 设置模式(内嵌配置) + AI_NOT_CONFIGURED 兜底
const showSettings = ref(false)
const needsConfig = computed(() => store.lastError?.code === 'AI_NOT_CONFIGURED')

function onConfigSaved() {
  showSettings.value = false
  store.lastError = null // 清掉 AI_NOT_CONFIGURED 错误态
}

function openSettings() {
  showSettings.value = true
}

function open() {
  store.open()
}

function close() {
  store.close()
}

async function send() {
  const text = inputText.value.trim()
  if (!text) return
  inputText.value = ''
  store.send(text)
  await scrollToBottom()
}

function stop() {
  store.cancelSession()
}

function onConfirm(actionId: number) {
  store.confirmAction(actionId)
}

function onCancel(actionId: number) {
  store.cancelAction(actionId)
}

async function scrollToBottom() {
  await nextTick()
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

watch(
  () => store.messages.length,
  () => scrollToBottom(),
)

watch(
  () => store.expanded,
  (v) => {
    if (v) {
      nextTick(() => inputRef.value?.focus())
      // 面板(380×560)比小球大:展开时若已拖动过,把位置 clamp 进面板尺寸,避免超出视口
      if (pos.value) {
        pos.value = {
          right: Math.max(0, Math.min(pos.value.right, window.innerWidth - 380)),
          bottom: Math.max(0, Math.min(pos.value.bottom, window.innerHeight - 560)),
        }
      }
    }
  },
)

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function onSuggestionClick(value: string) {
  inputText.value = value
  send()
}

// ============ 拖动:小球 + 面板 header 可用鼠标自由移动 ============
// 位置用 right/bottom 模型(贴视口右下角锚点);null 时落回 CSS 默认 right/bottom:24px。
// 不持久化:刷新/重登回右下角(用户确认)。
const assistantRef = ref<HTMLElement | null>(null)
const pos = ref<{ right: number; bottom: number } | null>(null)
let isDragging = false
let suppressClick = false
let dragStart = { mx: 0, my: 0, r: 0, b: 0, w: 0, h: 0, moved: false }

const assistantStyle = computed(() =>
  pos.value ? { right: `${pos.value.right}px`, bottom: `${pos.value.bottom}px` } : {},
)

function onDragStart(e: MouseEvent) {
  if (e.button !== 0) return // 只响应左键
  const el = assistantRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  if (!pos.value) {
    // 首次拖动:把当前右下角锚点(right/bottom)固化成数值,之后用数值定位
    pos.value = {
      right: window.innerWidth - rect.right,
      bottom: window.innerHeight - rect.bottom,
    }
  }
  dragStart = {
    mx: e.clientX,
    my: e.clientY,
    r: pos.value.right,
    b: pos.value.bottom,
    w: rect.width,
    h: rect.height,
    moved: false,
  }
  isDragging = true
  e.preventDefault()
  window.addEventListener('mousemove', onDragMove)
  window.addEventListener('mouseup', onDragUp)
}

function onDragMove(e: MouseEvent) {
  if (!isDragging || !pos.value) return
  const dx = e.clientX - dragStart.mx
  const dy = e.clientY - dragStart.my
  if (Math.abs(dx) > 5 || Math.abs(dy) > 5) dragStart.moved = true // 阈值:区分拖动与点击
  // 鼠标右移 → 容器右移 → 离右边距离(right)减小;clamp 在视口内
  const nr = Math.max(0, Math.min(dragStart.r - dx, window.innerWidth - dragStart.w))
  const nb = Math.max(0, Math.min(dragStart.b - dy, window.innerHeight - dragStart.h))
  pos.value = { right: nr, bottom: nb }
}

function onDragUp() {
  if (dragStart.moved) suppressClick = true // 拖动过:吞掉紧随的 click,避免误开面板
  isDragging = false
  window.removeEventListener('mousemove', onDragMove)
  window.removeEventListener('mouseup', onDragUp)
}

// 小球:按住拖动;轻点(未超阈值)才打开面板
function onBallMouseDown(e: MouseEvent) {
  onDragStart(e)
}
function onBallClick() {
  if (suppressClick) {
    suppressClick = false
    return
  }
  open()
}

// 面板 header 拖动;点设置/关闭按钮区域不触发,保留按钮原生点击
function onHeaderMouseDown(e: MouseEvent) {
  if ((e.target as HTMLElement).closest('.ai-header-actions')) return
  onDragStart(e)
}
</script>

<template>
  <div ref="assistantRef" class="ai-assistant" :style="assistantStyle">
    <Transition name="ai-ball">
      <div v-if="!store.expanded" class="ai-ball" @mousedown="onBallMouseDown" @click="onBallClick" title="AI 助手">
        <el-icon><ChatLineSquare /></el-icon>
        <span v-if="store.lastError" class="ai-ball-dot" />
      </div>
    </Transition>

    <Transition name="ai-drawer">
      <div v-if="store.expanded" class="ai-drawer">
        <header class="ai-header" @mousedown="onHeaderMouseDown">
          <div class="ai-title">
            <el-icon><ChatLineSquare /></el-icon>
            <span>AI 助手</span>
          </div>
          <div class="ai-header-actions">
            <el-button text :icon="Setting" circle :class="{ 'is-active': showSettings }" title="AI 配置" @click="showSettings = !showSettings" />
            <el-button text :icon="Close" circle @click="close" />
          </div>
        </header>

        <AiConfig v-if="showSettings" @saved="onConfigSaved" />

        <template v-else>
          <div ref="messagesRef" class="ai-messages">
            <MessageCard
              v-for="m in store.messages"
              :key="m.id"
              :message="m"
            />

            <ConfirmationCard
              v-for="c in confirmationsOnly"
              :key="c.actionId"
              :confirmation="c"
              @confirm="onConfirm"
              @cancel="onCancel"
            />

            <div v-if="store.messages.length === 0 && confirmationsOnly.length === 0" class="ai-empty">
              <p>你好,我是实验室预约 AI 助手。</p>
              <p class="ai-empty-hint">试试问:</p>
              <ul>
                <li>"推荐一台显微镜"</li>
                <li>"我下周的预约有哪些?"</li>
                <li>"怎么开机 FACS Aria III?"</li>
              </ul>
            </div>

            <div v-if="needsConfig" class="ai-notconfig">
              <p>未配置 AI API Key,无法使用 AI 助手。</p>
              <el-button type="primary" size="small" @click="openSettings">去配置</el-button>
            </div>
          </div>

          <div v-if="store.state === 'step_running' || store.state === 'streaming'" class="ai-step-bar">
            <StepTimelineCard :steps="store.currentStepUpdates" />
          </div>

          <SuggestionRow
            v-if="store.currentSuggestions.length > 0"
            :items="store.currentSuggestions"
            @pick="onSuggestionClick"
          />

          <footer class="ai-input-bar">
            <textarea
              ref="inputRef"
              v-model="inputText"
              placeholder="输入消息,Enter 发送,Shift+Enter 换行"
              :disabled="store.state === 'sending' || store.state === 'streaming' || store.state === 'step_running' || store.state === 'executing'"
              rows="2"
              @keydown="onKeydown"
            />
            <el-button
              v-if="store.state === 'sending' || store.state === 'streaming' || store.state === 'step_running' || store.state === 'executing'"
              type="danger"
              plain
              :icon="VideoPause"
              title="停止当前 AI 任务"
              @click="stop"
            >
              停止
            </el-button>
            <el-button
              type="primary"
              :icon="Promotion"
              :disabled="!inputText.trim() || store.state === 'sending' || store.state === 'streaming' || store.state === 'step_running' || store.state === 'executing'"
              @click="send"
            >
              发送
            </el-button>
          </footer>
        </template>
      </div>
    </Transition>
  </div>
</template>

<style scoped lang="scss">
.ai-assistant {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 1000;
}
.ai-ball {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--accent, #6366f1), #ec4899);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.4);
  color: #fff;
  font-size: 22px;
  position: relative;
  transition: transform 0.2s;
  &:hover {
    transform: translateY(-2px);
  }
}
.ai-ball-dot {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--el-color-danger, #ef4444);
  border: 2px solid var(--bg-base, #0b0f1a);
}
.ai-drawer {
  width: 380px;
  height: 560px;
  background: var(--bg-base, #0b0f1a);
  border: 1px solid var(--border-subtle, #1f2937);
  border-radius: 14px;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.6);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.ai-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-subtle, #1f2937);
  cursor: grab;
  user-select: none;
}
.ai-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--fg-primary, #e5e7eb);
}
.ai-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
.ai-header .is-active {
  color: var(--accent, #6366f1);
}
.ai-notconfig {
  margin: 12px 14px;
  padding: 14px;
  background: var(--bg-elev-1, #111827);
  border: 1px solid var(--border-subtle, #1f2937);
  border-radius: 10px;
  text-align: center;
  p {
    color: var(--fg-secondary, #d1d5db);
    font-size: 13px;
    margin-bottom: 10px;
  }
}
.ai-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px 0;
}
.ai-empty {
  padding: 24px;
  color: var(--fg-muted, #9ca3af);
  font-size: 13px;
  line-height: 1.6;
  ul {
    margin-top: 8px;
    padding-left: 20px;
    list-style: disc;
    li {
      cursor: pointer;
      &:hover {
        color: var(--accent, #6366f1);
      }
    }
  }
}
.ai-empty-hint {
  margin-top: 8px;
  color: var(--fg-secondary, #d1d5db);
}
.ai-step-bar {
  padding: 6px 14px;
  font-size: 12px;
  color: var(--fg-muted, #9ca3af);
  border-top: 1px solid var(--border-subtle, #1f2937);
  background: var(--bg-elev-1, #111827);
}
.ai-suggestions {
  padding: 8px 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  border-top: 1px solid var(--border-subtle, #1f2937);
}
.ai-suggestion-chip {
  background: var(--bg-elev-1, #111827);
  border: 1px solid var(--border-subtle, #1f2937);
  color: var(--fg-secondary, #d1d5db);
  border-radius: 12px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  &:hover {
    border-color: var(--accent, #6366f1);
    color: var(--accent, #6366f1);
  }
}
.ai-input-bar {
  padding: 10px 12px;
  border-top: 1px solid var(--border-subtle, #1f2937);
  display: flex;
  gap: 8px;
  align-items: flex-end;
  textarea {
    flex: 1;
    resize: none;
    background: var(--bg-elev-1, #111827);
    border: 1px solid var(--border-subtle, #1f2937);
    border-radius: 8px;
    color: var(--fg-primary, #e5e7eb);
    padding: 8px;
    font-size: 13px;
    font-family: inherit;
    &:focus {
      outline: none;
      border-color: var(--accent, #6366f1);
    }
    &:disabled {
      opacity: 0.6;
    }
  }
}
.ai-ball-enter-active,
.ai-ball-leave-active {
  transition: opacity 0.2s, transform 0.2s;
}
.ai-ball-enter-from,
.ai-ball-leave-to {
  opacity: 0;
  transform: scale(0.8);
}
.ai-drawer-enter-active,
.ai-drawer-leave-active {
  transition: opacity 0.25s, transform 0.25s;
}
.ai-drawer-enter-from,
.ai-drawer-leave-to {
  opacity: 0;
  transform: translateY(12px) scale(0.98);
}
</style>
