import { Client } from '@stomp/stompjs'
import SockJS from 'sockjs-client'
import { useUserStore } from '@/stores/user'
import { useNotificationStore } from '@/stores/notification'

let client: Client | null = null

/**
 * S3 实时推送：建立 STOMP/SockJS 长连接。
 *
 * 鉴权：浏览器 WebSocket 无法在握手 HTTP 请求上加自定义头，故 token 经 query 传入握手 URL
 * （浏览器 WS 鉴权的标准做法）。后端 WsAuthHandshakeInterceptor 校验 token 并经 JwtHandshakeHandler
 * 把 userId 设为会话 Principal → 注册到 SimpUserRegistry → convertAndSendToUser(userId,...) 可定位会话。
 *
 * WS URL 走 VITE_WS_BASE 环境变量：
 *  - dev：.env.development 设为 http://localhost:8080，直连后端
 *  - prod：.env.production 留空 → 使用 window.location 同源 /api/ws，由 nginx 反代到 app:8080
 */
export function connectWs() {
  const u = useUserStore()
  if (!u.accessToken || client) return
  client = new Client({
    webSocketFactory: () => {
      const base = import.meta.env.VITE_WS_BASE ?? ''
      const wsBase = base
        ? `${base}/api/ws`
        : `${window.location.protocol === 'https:' ? 'https' : 'http'}://${window.location.host}/api/ws`
      return new SockJS(`${wsBase}?token=${encodeURIComponent(u.accessToken)}`)
    },
    reconnectDelay: 5000,
    onConnect: () => {
      client!.subscribe('/user/queue/notifications', (msg) => {
        try {
          useNotificationStore().onMessage(JSON.parse(msg.body))
        } catch {
          // 解析失败静默忽略，不打扰用户
        }
      })
    },
    onStompError: (frame) => {
      console.warn('STOMP error', frame.headers['message'])
    },
  })
  client.activate()
}

export function disconnectWs() {
  client?.deactivate()
  client = null
}
