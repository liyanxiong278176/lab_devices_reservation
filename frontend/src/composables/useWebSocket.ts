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
 * 直连后端绝对 URL（dev；prod 改为配置）。
 * 注意：/api 代理规则未带 ws:true，故不走 vite 代理。
 */
export function connectWs() {
  const u = useUserStore()
  if (!u.accessToken || client) return
  client = new Client({
    webSocketFactory: () =>
      new SockJS(`http://localhost:8080/api/ws?token=${encodeURIComponent(u.accessToken)}`),
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
