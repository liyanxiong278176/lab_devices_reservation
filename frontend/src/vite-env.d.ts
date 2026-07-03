/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** WebSocket 基址：dev=http://localhost:8080，prod 留空→同源（由 nginx 反代） */
  readonly VITE_WS_BASE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
