import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev, the backend runs separately (uvicorn on :8001) and Vite proxies
// /api to it, so the browser still sees one origin -- same as production,
// where the backend serves this app's build itself.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://localhost:8001' },
  },
})
