import { useUserStore } from '@/stores/user'
import { useNotificationStore } from '@/stores/notification'

let source: EventSource | null = null

function parseData(event: MessageEvent<string>): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(event.data)
    return value && typeof value === 'object' ? value as Record<string, unknown> : null
  } catch {
    return null
  }
}

/** Same-origin SSE carries only server-to-browser notification events. */
export function connectEventStream() {
  if (!useUserStore().isAuthenticated || source) return

  const notifications = useNotificationStore()
  notifications.beginEventStream()
  // Native EventSource reconnects with Last-Event-ID and automatically sends
  // the HttpOnly cookie; the application never exposes credentials to JS.
  source = new EventSource('/api/v2/notifications/stream', { withCredentials: true })
  source.addEventListener('notification', ((event: MessageEvent<string>) => {
    const body = parseData(event)
    if (body) notifications.onStreamNotification(body, event.lastEventId)
  }) as EventListener)
  source.addEventListener('batch-start', ((event: MessageEvent<string>) => {
    const body = parseData(event)
    notifications.beginDeliveryBatch(body?.replay === true)
  }) as EventListener)
  source.addEventListener('batch-complete', ((event: MessageEvent<string>) => {
    const body = parseData(event)
    if (body) notifications.completeDeliveryBatch(body, event.lastEventId)
  }) as EventListener)
  source.addEventListener('read-state-changed', () => notifications.onReadStateChanged())
  source.addEventListener('stream-ready', () => { void notifications.loadUnread() })
  source.addEventListener('auth-revoked', () => disconnectEventStream())
  // EventSource owns retry timing and preserves the same Last-Event-ID cursor.
  // The browser emits `error` while retrying, so no timer or new source is needed.
}

export function disconnectEventStream() {
  source?.close()
  source = null
}
