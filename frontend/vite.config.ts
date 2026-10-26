import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // HTTPS-туннель для проверки с телефона (push работает только по HTTPS): cloudflared tunnel --url http://localhost:5173
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      '/api': { target: process.env.API_URL ?? 'http://localhost:8000', changeOrigin: false },
    },
  },
})
