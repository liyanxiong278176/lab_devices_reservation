import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// https://vite.dev/config/  (vitest/config extends UserConfig with the `test` key)
export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    port: 5173,
    proxy: {
      // v2 FastAPI 单体服务；SSE 和原生 WebSocket 共用 /api 代理。
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
