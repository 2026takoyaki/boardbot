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
      // 진행자 목록. 좌석 등록 화면의 선택 UI가 접속 시 한 번 읽는다.
      '/personas': { target: 'http://localhost:8000', changeOrigin: true },
      // 개발 모드 (BOARDBOT_DEV=1). 꺼져 있으면 /dev/config가 dev_mode=false를
      // 주고, 상태를 바꾸는 나머지 /dev/* 는 404가 된다.
      '/dev': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
