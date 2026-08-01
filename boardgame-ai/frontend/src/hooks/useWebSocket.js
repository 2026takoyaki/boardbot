import { useState, useEffect, useRef, useCallback } from 'react'

const RECONNECT_DELAY_MS = 2000

const AUDIO_MSG_TYPES = new Set([
  'tts_play',
  'tts_interrupt',
  'sfx_play',
  'bgm_play',
  'bgm_duck',
])

/**
 * useWebSocket(path, options?)
 * options:
 *   onAudioMessage(msg) — audio 관련 메시지 수신 시 호출. 기본은 no-op.
 *                         보통 useAudioPlayer(send).enqueue를 넘김.
 *   onCue(payload)      — 연출 큐 수신 시 호출. 기본은 no-op.
 *
 * state_update가 "지금 어떤 상태인가"라면 cue는 "방금 무슨 일이 일어났는가"다.
 * 상태가 아니라 사건이므로 state에 담지 않고 콜백으로 흘린다 — 리렌더로
 * 되살아나면 안 되고, 놓친 큐를 나중에 재생해서도 안 된다.
 */
export function useWebSocket(path, options = {}) {
  const { onAudioMessage, onCue, onLightState } = options
  const [state, setState] = useState(null)
  const [connected, setConnected] = useState(false)
  const [messages, setMessages] = useState([])
  const ws = useRef(null)
  const onAudioRef = useRef(onAudioMessage)
  const onCueRef = useRef(onCue)
  const onLightStateRef = useRef(onLightState)
  const benchSeq = useRef(0)
  useEffect(() => { onAudioRef.current = onAudioMessage }, [onAudioMessage])
  useEffect(() => { onCueRef.current = onCue }, [onCue])
  useEffect(() => { onLightStateRef.current = onLightState }, [onLightState])

  useEffect(() => {
    let destroyed = false
    let reconnectTimer = null

    function connect() {
      if (destroyed) return
      const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const url = `${scheme}//${location.host}${path}`
      const socket = new WebSocket(url)
      ws.current = socket

      socket.onopen = () => {
        // 새 연결마다 메시지 버퍼 초기화 — 이전 연결의 hello 잔재가 다음 세션을
        // 잘못 트리거하는 것을 막는다 (재연결 시 START_YACHT 재발사 보장).
        setMessages([])
        setConnected(true)
        // Benchmark hook (window._bench가 true일 때만 의미).
        if (window._bench) {
          try { window._bench.log('ws_event', 'open', path, performance.now()) } catch (_) {}
        }
      }

      socket.onclose = () => {
        setConnected(false)
        if (window._bench) {
          try { window._bench.log('ws_event', 'close', path, performance.now()) } catch (_) {}
        }
        if (!destroyed) {
          reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS)
        }
      }

      socket.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          setMessages(prev => [msg, ...prev].slice(0, 20))
          if (msg.msg_type === 'state_update') {
            const receivedAt = performance.now()
            const state_version = (msg.state ?? msg.payload)?.state_version ?? -1
            const seq = ++benchSeq.current
            setState(msg.state ?? msg.payload)
            // Benchmark hook: UI paint 완료 시각 (state_version별).
            if (window._bench) {
              requestAnimationFrame(() => {
                const paintedAt = performance.now()
                try {
                  window._bench.log(
                    'ui_update_latency',
                    state_version,
                    seq,
                    receivedAt,
                    paintedAt,
                    paintedAt - receivedAt,
                  )
                  window._bench.log('ui_painted', state_version, paintedAt)
                } catch (_) {}
              })
            }
          }
          if (AUDIO_MSG_TYPES.has(msg.msg_type) && onAudioRef.current) {
            try { onAudioRef.current(msg) } catch (_) {}
          }
          if (msg.msg_type === 'cue' && onCueRef.current) {
            try { onCueRef.current(msg.payload) } catch (_) {}
          }
          if (msg.msg_type === 'light_state' && onLightStateRef.current) {
            try { onLightStateRef.current(msg.payload) } catch (_) {}
          }
        } catch (_) {}
      }
    }

    connect()

    return () => {
      destroyed = true
      clearTimeout(reconnectTimer)
      ws.current?.close()
    }
  }, [path])

  // send(input_type, data?, player_id?)
  const send = useCallback((input_type, data = {}, player_id = undefined) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      const msg = { msg_type: 'input', input_type, data }
      if (player_id !== undefined) msg.player_id = player_id
      ws.current.send(JSON.stringify(msg))
    }
  }, [])

  return { state, connected, messages, send }
}
