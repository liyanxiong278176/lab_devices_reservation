/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 实时通知使用同源 SSE，由 /api/v2 反向代理转发至 FastAPI。 */
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
