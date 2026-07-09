import { Client, type IMessage } from '@stomp/stompjs'
import SockJS from 'sockjs-client'
import { useUserStore } from '@/stores/user'
import type { WsClientMsg, WsServerFrame } from '@/types/ai'

/**
 * AI 助手 STOMP 客户端 — 复用 /api/ws endpoint (与通知同 endpoint),
 * 但走独立的 STOMP subscription + send path。
 *
 * <p>WS URL pattern 跟 useWebSocket.ts 一致:dev 用 VITE_WS_BASE 直连,
 * prod 用 window.location 同源 /api/ws (nginx 反代)。
 *
 * <p>JWT refresh 后调 reconnect(newToken) 重建连接。
 */

let client: Client | null = null

function buildWsUrl(token: string): string {
  const base = import.meta.env.VITE_WS_BASE ?? ''
  const wsBase = base
    ? `${base}/api/ws`
    : `${window.location.protocol === 'https:' ? 'https' : 'http'}://${window.location.host}/api/ws`
  return `${wsBase}?token=${encodeURIComponent(token)}`
}

let _onFrame: ((frame: WsServerFrame) => void) | null = null

export function connectAiWs(onFrame: (frame: WsServerFrame) => void) {
  const u = useUserStore()
  if (!u.accessToken) return
  if (client) return
  _onFrame = onFrame
  client = new Client({
    webSocketFactory: () => new SockJS(buildWsUrl(u.accessToken)) as unknown as WebSocket,
    reconnectDelay: 5000,
    heartbeatIncoming: 10000,
    heartbeatOutgoing: 10000,
    onConnect: () => {
      client!.subscribe('/user/queue/assistant-stream', (msg: IMessage) => {
        try {
          const frame = JSON.parse(msg.body) as WsServerFrame
          _onFrame?.(frame)
        } catch (e) {
          console.warn('[AI ws] frame parse failed', e)
        }
      })
    },
    onStompError: (frame) => {
      console.warn('[AI ws] STOMP error', frame.headers['message'])
    },
  })
  client.activate()
}

export function disconnectAiWs() {
  client?.deactivate()
  client = null
  _onFrame = null
}

export function reconnectAiWs(newToken?: string) {
  const u = useUserStore()
  if (newToken) u.accessToken = newToken
  disconnectAiWs()
  if (_onFrame) connectAiWs(_onFrame)
}

export function sendAiMsg(msg: WsClientMsg) {
  if (!client?.connected) {
    console.warn('[AI ws] not connected, frame dropped')
    return
  }
  const dest = (() => {
    switch (msg.kind) {
      case 'user_message':
        return '/app/assistant/send'
      case 'confirm_action':
        return '/app/assistant/confirm'
      case 'cancel_action':
        return '/app/assistant/cancel'
      case 'resync':
        return '/app/assistant/resync'
      case 'cancel_session':
        return '/app/assistant/cancel_session'
    }
  })()
  const { kind: _kind, ...body } = msg
  void _kind
  client.publish({ destination: dest, body: JSON.stringify(body) })
}
