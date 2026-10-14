import { defineConfig, mergeConfig } from 'vite'
import baseConfig from '../vite.config'

export default mergeConfig(baseConfig, defineConfig({
  server: {
    host: '127.0.0.1', port: 5175, strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8005', changeOrigin: true } },
  },
}))
