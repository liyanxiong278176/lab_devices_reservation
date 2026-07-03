import { Client } from '@stomp/stompjs'
import SockJS from 'sockjs-client'
import { useUserStore } from '@/stores/user'
import { useNotificationStore } from '@/stores/notification'

let client: Client | null = null

/**
 * S3 实时推送：建立 STOMP/SockJS 长连接。
 *
 * 鉴权：在 STOMP CONNECT 帧头携带 `Authorization: Bearer <jwt>`，
 * 后端 WebSocketAuthInterceptor 读取该头并设置 Principal，再 convertAndSendToUser。
 *
 * 直连后端绝对 URL（dev；prod 改为配置）。
 * 注意：/api 代理规则未带 ws:true，故不走 vite 代理。
 */
export function connectWs() {
  const u = useUserStore()
  if (!u.accessToken || client) return
  client = new Client({
    webSocketFactory: () => new SockJS('http://localhost:8080/api/ws'),
    connectHeaders: { Authorization: `Bearer ${u.accessToken}` },
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
