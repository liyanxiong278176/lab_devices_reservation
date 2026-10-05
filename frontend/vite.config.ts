import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

const rootEnvDirectory = path.resolve(__dirname, '..')
const rootViteEnv = loadEnv('development', rootEnvDirectory, 'VITE_')

// https://vite.dev/config/  (vitest/config extends UserConfig with the `test` key)
export default defineConfig({
  // Keep frontend build-time settings in the repository root .env.
  envDir: rootEnvDirectory,
  plugins: [vue()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    port: 5173,
    // FastAPI 本地开发端口默认是 8000；可用 VITE_API_PROXY_TARGET 覆盖。
    proxy: {
      '/api': {
        target:
          rootViteEnv.VITE_API_PROXY_TARGET ||
          process.env.VITE_API_PROXY_TARGET ||
          'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    exclude: ['e2e/**', '**/node_modules/**', '**/dist/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['src/**/*.{ts,tsx,vue}'],
      exclude: [
        'src/**/__tests__/**',
        'src/**/ai/**',
        'src/api/aiV2.ts',
        'src/stores/aiWorkbench.ts',
        'src/types/aiWorkbench.ts',
      ],
      thresholds: {
        lines: 100,
        functions: 100,
        branches: 100,
        statements: 100,
        'src/api/request.ts': { lines: 85, branches: 65, functions: 100 },
        'src/composables/useEventStream.ts': { lines: 90, branches: 70, functions: 75 },
        'src/stores/notification.ts': { lines: 90, branches: 80, functions: 90 },
        'src/utils/fetch-all-pages.ts': { lines: 100, branches: 50, functions: 100 },
      },
    },
  },
})
