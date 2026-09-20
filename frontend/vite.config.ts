import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// https://vite.dev/config/  (vitest/config extends UserConfig with the `test` key)
export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  // sockjs-client@1.6.1 是 Node 时代老库，顶层引用全局 `global`，浏览器无此全局 →
  // `ReferenceError: global is not defined`（登录后导航到 MainLayout 时连带加载即崩，
  // 导致 router.push('/dashboard') 中断、停在登录页）。用 globalThis polyfill：
  // define 覆盖源码、依赖预构建与 prod 构建，确保 sockjs-client 在浏览器中可用。
  define: {
    global: 'globalThis',
  },
  server: {
    port: 5173,
    proxy: {
      // v2 FastAPI 单体服务；SSE 走普通 HTTP，保留 /ws 代理给通知兼容层。
      '/api': { target: 'http://localhost:8000', changeOrigin: true, ws: true },
      '/ws': { target: 'http://localhost:8000', ws: true, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    exclude: ['e2e/**', '**/node_modules/**', '**/dist/**'],
  },
})
