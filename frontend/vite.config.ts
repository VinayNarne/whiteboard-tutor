import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Where the API runs. Set VITE_BACKEND_PORT=8100 in frontend/.env.local if Windows has reserved port 8001
  // (see README, "Troubleshooting").
  const backend = `http://127.0.0.1:${loadEnv(mode, process.cwd(), '').VITE_BACKEND_PORT || 8001}`
  return {
    plugins: [react()],
    server: {
      host: true,
      proxy: {
        '/api': { target: backend, changeOrigin: true, ws: true },
        '/static': { target: backend, changeOrigin: true },
      },
    },
  }
})
