import { useUserStore } from '@/stores/user'
import { useNotificationStore } from '@/stores/notification'

let socket: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let shouldReconnect = false

function websocketUrl(token: string) {
  const configured = String(import.meta.env.VITE_WS_BASE ?? '').trim()
  const base = configured
    ? configured.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:')
    : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
  return `${base}/api/v2/ws?token=${encodeURIComponent(token)}`
}

/**
 * FastAPI 原生 WebSocket 通知通道。
 * 数据库通知仍然是事实源；断线重连后通知页会重新加载历史和未读数，
 * WebSocket 只负责低延迟提示，不承担可靠消息存储。
 */
export function connectWs() {
  const user = useUserStore()
  if (!user.accessToken || socket) return
  shouldReconnect = true
  socket = new WebSocket(websocketUrl(user.accessToken))
  socket.onopen = () => {
    if (socket?.readyState === WebSocket.OPEN) socket.send('ping')
  }
  socket.onmessage = (event) => {
    try {
      useNotificationStore().onMessage(JSON.parse(event.data))
    } catch {
      // Malformed real-time payloads never interrupt the main UI.
    }
  }
  socket.onclose = () => {
    socket = null
    if (shouldReconnect && user.accessToken) {
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null
        connectWs()
      }, 5000)
    }
  }
  socket.onerror = () => socket?.close()
}

export function disconnectWs() {
  shouldReconnect = false
  if (reconnectTimer) clearTimeout(reconnectTimer)
  reconnectTimer = null
  socket?.close()
  socket = null
}
