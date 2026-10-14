import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// In development the frontend calls relative `/api/...` URLs and Vite forwards
// them to FastAPI, so the browser never needs CORS and never talks to the
// database directly.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react(), tailwindcss()],
    build: {
      // Never inline fonts as data: URIs - the production Content-Security-Policy
      // (font-src 'self', see vercel.json) would block them.
      assetsInlineLimit: (filePath: string) => (/\.(woff2?|ttf|otf)$/.test(filePath) ? false : undefined),
    },
    server: {
      port: 5173,
      proxy: {
        '/api': { target: env.VITE_API_PROXY_TARGET || 'http://localhost:8000', changeOrigin: true },
      },
    },
  }
})
