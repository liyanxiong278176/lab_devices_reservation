/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** WebSocket 基址：可留空走同源 /api/v2/ws，或填写 http(s) 后端地址。 */
  readonly VITE_WS_BASE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
