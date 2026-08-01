import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 3000,
    proxy: {
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
      // 오디오 정적 자원: 백엔드 StaticFiles가 서빙. dev 서버에서 프록시 필수.
      '/cache/tts': { target: 'http://localhost:8000', changeOrigin: true },
      '/sfx': { target: 'http://localhost:8000', changeOrigin: true },
      '/bgm': { target: 'http://localhost:8000', changeOrigin: true },
      // 기존 HTTP 라우트
      '/players': { target: 'http://localhost:8000', changeOrigin: true },
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
      // 개발 모드 (BOARDBOT_DEV=1). 꺼져 있으면 백엔드가 404를 준다.
      '/dev': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
