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
  // define 覆盖源码与 prod 构建，optimizeDeps.esbuildOptions.define 覆盖 dev 预打包依赖，双通道确保生效。
  define: {
    global: 'globalThis',
  },
  optimizeDeps: {
    esbuildOptions: {
      define: { global: 'globalThis' },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8080', changeOrigin: true },
      '/ws': { target: 'http://localhost:8080', ws: true, changeOrigin: true },
    },
  },
  test: { environment: 'jsdom', globals: true },
})
