<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from 'vue'

withDefaults(
  defineProps<{
    modelValue: string
    label?: string
    hint?: string
  }>(),
  {
    label: '设备二维码',
    hint: '可手工输入二维码中的设备 token。',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  scan: [value: string]
}>()

type BarcodeResult = { rawValue?: string }
type BarcodeDetectorLike = {
  detect: (source: HTMLVideoElement) => Promise<BarcodeResult[]>
}
type BarcodeDetectorConstructor = new (options?: { formats?: string[] }) => BarcodeDetectorLike
type BarcodeWindow = Window & { BarcodeDetector?: BarcodeDetectorConstructor }

const video = ref<HTMLVideoElement | null>(null)
const scanning = ref(false)
const unsupported = ref(false)
let stream: MediaStream | null = null
let frameTimer: ReturnType<typeof setTimeout> | null = null
let detector: BarcodeDetectorLike | null = null

function updateValue(value: string) {
  emit('update:modelValue', value)
}

async function scanFrame() {
  if (!scanning.value || !detector || !video.value) return
  try {
    const results = await detector.detect(video.value)
    const value = results.find((item) => item.rawValue)?.rawValue?.trim()
    if (value) {
      updateValue(value)
      emit('scan', value)
      stop()
      return
    }
  } catch {
    // 摄像头帧读取失败时继续尝试，手工输入始终可用。
  }
  frameTimer = setTimeout(() => void scanFrame(), 220)
}

async function start() {
  const BarcodeDetector = (window as BarcodeWindow).BarcodeDetector
  if (!BarcodeDetector || !navigator.mediaDevices?.getUserMedia) {
    unsupported.value = true
    return
  }
  try {
    detector = new BarcodeDetector({ formats: ['qr_code'] })
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' } },
      audio: false,
    })
    scanning.value = true
    await nextTick()
    if (video.value) {
      video.value.srcObject = stream
      await video.value.play()
    }
    void scanFrame()
  } catch {
    unsupported.value = true
    stop()
  }
}

function stop() {
  scanning.value = false
  if (frameTimer) {
    clearTimeout(frameTimer)
    frameTimer = null
  }
  stream?.getTracks().forEach((track) => track.stop())
  stream = null
  detector = null
}

function toggle() {
  if (scanning.value) stop()
  else void start()
}

onBeforeUnmount(stop)
</script>

<template>
  <div class="device-scanner">
    <div class="device-scanner__head">
      <span>{{ label }}</span>
      <button type="button" class="device-scanner__toggle" @click="toggle">
        {{ scanning ? '停止扫码' : '打开摄像头' }}
      </button>
    </div>
    <video v-if="scanning" ref="video" class="device-scanner__video" muted playsinline />
    <p class="device-scanner__hint">
      {{ unsupported ? '当前浏览器不支持摄像头二维码识别，请继续使用手工输入。' : hint }}
    </p>
  </div>
</template>

<style scoped lang="scss">
.device-scanner {
  display: grid;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-control);
  background: var(--bg-elevated);
}

.device-scanner__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.device-scanner__toggle {
  padding: 5px 9px;
  border: 1px solid var(--border-default);
  border-radius: 999px;
  color: var(--accent);
  background: transparent;
  cursor: pointer;
  font-size: 11px;
}

.device-scanner__toggle:hover {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}

.device-scanner__video {
  width: 100%;
  max-height: 190px;
  border-radius: 10px;
  object-fit: cover;
  background: #050a10;
}

.device-scanner__hint {
  margin: 0;
  color: var(--text-tertiary);
  font-size: 11px;
  line-height: 1.5;
}
</style>
