import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 3000,
    proxy: {
      // 대상은 localhost가 아니라 127.0.0.1로 적는다.
      //
      // uvicorn은 IPv4에만 바인딩하는데(127.0.0.1:8000), Node 17+는 localhost를
      // ::1 → 127.0.0.1 순으로 훑는다. 그래서 백엔드가 잠깐 늦게 뜨거나 하면
      // "AggregateError [ECONNREFUSED] at internalConnectMultiple" 처럼 원인이
      // 안 보이는 에러가 난다 — 주소를 못 찾은 게 아니라 IPv6 쪽을 먼저 두드린
      // 것이다. 숫자로 적으면 해석 단계가 통째로 사라진다.
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
      },
      // 오디오 정적 자원: 백엔드 StaticFiles가 서빙. dev 서버에서 프록시 필수.
      '/cache/tts': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/sfx': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/bgm': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      // 기존 HTTP 라우트
      '/players': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      // 진행자 목록. 좌석 등록 화면의 선택 UI가 접속 시 한 번 읽는다.
      '/personas': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      // 개발 모드 (BOARDBOT_DEV=1). 꺼져 있으면 /dev/config가 dev_mode=false를
      // 주고, 상태를 바꾸는 나머지 /dev/* 는 404가 된다.
      '/dev': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
