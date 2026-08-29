/**
 * useAudioPlayer — 태블릿 브라우저 오디오 재생 싱글톤.
 *
 * 모델: backend AudioManager가 ack-driven 푸시. 따라서 frontend는
 * 한 번에 한 메시지만 받고 즉시 재생. 큐는 운영하지 않음 (backend가 큐).
 *
 * 동작:
 * - tts_play / sfx_play: audio_url 즉시 재생. ended 시 audio_ack 전송.
 * - tts_interrupt: 현재 재생을 150ms fade-out 후 정지, audio_ack(status=interrupted).
 * - bgm_play / bgm_duck: 별도 BGM Audio 인스턴스, TTS와 독립적 재생.
 * - iPad Safari autoplay 차단 우회: 첫 user interaction에 무음 unlock.
 */

import { useEffect, useRef } from 'react'

const FADE_OUT_MS = 150 // 인터럽트 시 음량 감쇠 시간. 너무 길면 다음 발화 지연됨.

/**
 * 채널별 음량.
 *
 * 세 채널을 따로 두는 이유는 시연장에서 줄이고 싶은 것이 매번 다르기 때문이다.
 * 사람이 많아 시끄러우면 **말**만 키워야 하고, 촬영 중이면 배경음만 내려야
 * 하고, 주사위를 자주 굴리는 구간에서는 효과음만 거슬린다. 하나로 묶으면
 * 그때마다 전부 같이 움직여서 결국 통째로 꺼버리게 된다.
 *
 * localStorage에 남기는 것은 태블릿이 화면을 옮길 때마다 App이 다시 마운트
 * 되기 때문이다 — 매번 기본값으로 돌아가면 조절한 의미가 없다.
 */
const VOL_KEYS = { tts: 'boardbot.vol.tts', sfx: 'boardbot.vol.sfx', bgm: 'boardbot.vol.bgm' }

function readVolume(channel) {
  try {
    if (typeof localStorage === 'undefined') return 1
    const stored = localStorage.getItem(VOL_KEYS[channel])
    // 저장된 적이 없으면 null이고, Number(null)은 0이다. 그대로 두면 처음
    // 켠 태블릿이 소리가 통째로 꺼진 채로 시작한다 — 실제로 그랬다.
    if (stored === null || stored === '') return 1
    const raw = Number(stored)
    return Number.isFinite(raw) && raw >= 0 && raw <= 1 ? raw : 1
  } catch {
    // 사파리 프라이빗 등에서 막힌다. 기억을 못 할 뿐 조절은 된다.
    return 1
  }
}

function storeVolume(channel, value) {
  try {
    if (typeof localStorage === 'undefined') return
    localStorage.setItem(VOL_KEYS[channel], String(value))
  } catch {
    // 이번 세션 동안은 유지된다.
  }
}

const player = {
  current: null,       // {playback_id, type, t0, playStartAt, fadeTimer}
  audio: null,         // 단일 재사용 Audio 인스턴스 (TTS/SFX 공용)
  unlocked: false,
  ttsEnabled: true,
  ackSenders: new Set(),
  bgmAudio: null,
  bgmGainDb: 0,
  duckGainDb: 0,
  // 0.0~1.0. 위 세 채널을 각각 곱한다.
  ttsVolume: readVolume('tts'),
  sfxVolume: readVolume('sfx'),
  bgmVolume: readVolume('bgm'),
  // 음량이 바뀔 때 화면에 알린다(슬라이더가 여럿일 수 있어 구독형).
  volumeListeners: new Set(),
  // backend가 다음을 푸시하기 전 우리에게 새 메시지가 빨리 오는 race 케이스용 슬롯
  pendingNext: null,
  // TTS 재생 종료 시 1회 호출되는 콜백 집합
  ttsEndCallbacks: new Set(),
  // TTS 재생 시작 시 1회 호출되는 콜백 집합
  ttsStartCallbacks: new Set(),
}

function dbToGain(db) {
  return Math.pow(10, db / 20)
}

function ensureAudioElement() {
  if (!player.audio) {
    player.audio = new Audio()
    player.audio.preload = 'auto'
  }
  return player.audio
}

function ensureBgmElement() {
  if (!player.bgmAudio) {
    player.bgmAudio = new Audio()
    player.bgmAudio.loop = true
  }
  return player.bgmAudio
}

function applyBgmGain() {
  if (player.bgmAudio) {
    const gain = dbToGain(player.bgmGainDb + player.duckGainDb) * player.bgmVolume
    player.bgmAudio.volume = Math.max(0, Math.min(1, gain))
  }
}

/** 지금 재생 중인 것에 바뀐 음량을 즉시 반영한다. 다음 발화까지 기다리면
 *  슬라이더를 움직여도 아무 일이 없어 고장 난 것으로 보인다. */
function applyCurrentVolume() {
  if (!player.audio || !player.current) return
  // fade-out 중이면 건드리지 않는다 — 감쇠 곡선이 도로 튀어오른다.
  if (player.current.fadeTimer) return
  player.audio.volume = volumeFor(player.current.type)
}

function volumeFor(msgType) {
  return msgType === 'sfx_play' ? player.sfxVolume : player.ttsVolume
}

function notifyVolume() {
  for (const cb of player.volumeListeners) {
    try { cb(volumes()) } catch (_) {}
  }
}

function volumes() {
  return { tts: player.ttsVolume, sfx: player.sfxVolume, bgm: player.bgmVolume }
}

/** 채널 음량 설정. channel: 'tts' | 'sfx' | 'bgm', value: 0.0~1.0 */
function setVolume(channel, value) {
  const v = Math.max(0, Math.min(1, Number(value)))
  if (!Number.isFinite(v) || !(channel in VOL_KEYS)) return
  if (channel === 'tts') player.ttsVolume = v
  else if (channel === 'sfx') player.sfxVolume = v
  else player.bgmVolume = v
  storeVolume(channel, v)
  if (channel === 'bgm') applyBgmGain()
  else applyCurrentVolume()
  notifyVolume()
}

/** 음량 변화를 구독한다. 해제 함수를 반환. */
function onVolumeChange(callback) {
  player.volumeListeners.add(callback)
  return () => player.volumeListeners.delete(callback)
}

function sendAck(playback_id, status, t0) {
  const now = Date.now() / 1000
  const data = { playback_id, status, started_at: t0, ended_at: now }
  for (const send of player.ackSenders) {
    try {
      send('audio_ack', data)
    } catch (_) {}
  }
}

async function playMessage(msg) {
  const payload = msg.payload || {}
  const audio_url = payload.audio_url
  const playback_id = payload.playback_id || `pb_${Math.random().toString(36).slice(2, 10)}`
  const receivedAt = payload.__bench_received_at ?? performance.now()
  const receiveToStartMs = performance.now() - receivedAt

  if (msg.msg_type === 'tts_play' && !player.ttsEnabled) {
    if (window._bench) {
      try { window._bench.log('audio_play_skipped', msg.msg_type, playback_id, performance.now()) } catch (_) {}
    }
    sendAck(playback_id, 'skipped', Date.now() / 1000)
    const cbs = [...player.ttsEndCallbacks]
    player.ttsEndCallbacks.clear()
    cbs.forEach(cb => cb())
    return
  }

  if (!audio_url) {
    // 합성 실패한 text-only — ack만 보내 backend 큐 진행.
    if (window._bench) {
      try { window._bench.log('audio_play_end', msg.msg_type, playback_id, 'error', performance.now(), 0) } catch (_) {}
    }
    sendAck(playback_id, 'error', Date.now() / 1000)
    return
  }

  const el = ensureAudioElement()
  // 같은 Audio 하나로 말과 효과음을 다 내보내므로, 재생 직전에 그 종류의
  // 음량으로 맞춘다. 한 번 정해두면 앞 재생의 음량이 그대로 따라온다.
  el.volume = volumeFor(msg.msg_type)
  el.src = audio_url
  const t0 = Date.now() / 1000
  const playStartAt = performance.now()
  player.current = { playback_id, type: msg.msg_type, t0, playStartAt, fadeTimer: null }
  // Benchmark hook: 첫 음 재생 시작 시각 (사용자 체감 기준점).
  if (window._bench) {
    try {
      window._bench.log(
        'audio_play_start',
        msg.msg_type,
        playback_id,
        playStartAt,
        receiveToStartMs,
      )
    } catch (_) {}
  }

  // TTS가 시작될 때 BGM을 자동으로 낮추지 않는다.
  //
  // 늑대인간 밤은 배경음이 곧 분위기라, 진행자가 말할 때마다 음악이 꺼졌다
  // 켜지면 장면이 매번 끊긴다. 오르내리는 것 자체도 거슬린다. BGM은 애초에
  // 말소리를 덮지 않는 음량으로 깔아두고, 정말 낮춰야 하는 순간에는 백엔드가
  // bgm_duck을 명시적으로 보낸다(handleBgmDuck) — 그건 연출의 선택이지
  // 발화의 부작용이 아니다.

  const onEnded = (status) => {
    // 멱등성: 이미 인터럽트로 정리됐으면 무시
    if (!player.current || player.current.playback_id !== playback_id) return
    if (player.current.fadeTimer) {
      clearInterval(player.current.fadeTimer)
    }
    // 발화가 끝났다고 BGM 음량을 되돌리지 않는다. 이제 더킹의 주인은
    // bgm_duck 하나뿐이라(위 playMessage 주석), 여기서 0으로 되돌리면
    // 백엔드가 일부러 걸어둔 더킹이 다음 발화가 끝날 때 조용히 풀린다.
    if (window._bench) {
      const endedAt = performance.now()
      try { window._bench.log('audio_play_end', msg.msg_type, playback_id, status, endedAt, endedAt - playStartAt) } catch (_) {}
    }
    player.current = null
    sendAck(playback_id, status, t0)
    // TTS 종료 콜백 실행 (1회성)
    if (msg.msg_type === 'tts_play') {
      const cbs = [...player.ttsEndCallbacks]
      player.ttsEndCallbacks.clear()
      cbs.forEach(cb => cb())
    }
    // pending 메시지가 있으면 즉시 처리
    if (player.pendingNext) {
      const next = player.pendingNext
      player.pendingNext = null
      playMessage(next)
    }
  }

  el.onended = () => onEnded('played')
  el.onerror = () => onEnded('error')

  try {
    await el.play()
    // 재생 시작 성공 시 start 콜백 발화
    if (msg.msg_type === 'tts_play') {
      const scbs = [...player.ttsStartCallbacks]
      player.ttsStartCallbacks.clear()
      scbs.forEach(cb => cb())
    }
  } catch (err) {
    // autoplay 차단 등. 일단 ack로 backend 진행시킴 (block 해제는 unlock에서).
    onEnded('error')
  }
}

/**
 * 현재 재생을 150ms fade-out 후 정지. ack(status=interrupted) 발행.
 * 멱등: 이미 정리됐거나 다른 playback_id면 no-op.
 */
function fadeOutInterrupt(playback_id) {
  if (!player.current) return
  if (playback_id && player.current.playback_id !== playback_id) return

  const cur = player.current
  const el = player.audio
  if (!el) {
    // 안전망
    if (window._bench) {
      const endedAt = performance.now()
      try { window._bench.log('audio_play_end', cur.type, cur.playback_id, 'interrupted', endedAt, endedAt - (cur.playStartAt ?? endedAt)) } catch (_) {}
    }
    player.current = null
    sendAck(cur.playback_id, 'interrupted', cur.t0)
    return
  }

  // 이미 fade 중이면 그대로 둠
  if (cur.fadeTimer) return

  const startVolume = el.volume
  const startTime = performance.now()
  cur.fadeTimer = setInterval(() => {
    if (!player.current || player.current.playback_id !== cur.playback_id) {
      clearInterval(cur.fadeTimer)
      return
    }
    const elapsed = performance.now() - startTime
    const ratio = Math.min(1, elapsed / FADE_OUT_MS)
    el.volume = Math.max(0, startVolume * (1 - ratio))
    if (ratio >= 1) {
      clearInterval(cur.fadeTimer)
      try { el.pause() } catch (_) {}
      try { el.currentTime = 0 } catch (_) {}
      // 다음 재생이 playMessage에서 다시 맞추지만, 그 사이에 0으로 남아
      // 있으면 unlock 무음 재생 등이 소리 없이 지나간다.
      el.volume = player.ttsVolume
      // 인터럽트로 끊긴 경우도 마찬가지 — 더킹은 bgm_duck만 건드린다.
      if (window._bench) {
        const endedAt = performance.now()
        try { window._bench.log('audio_play_end', cur.type, cur.playback_id, 'interrupted', endedAt, endedAt - (cur.playStartAt ?? startTime)) } catch (_) {}
      }
      player.current = null
      sendAck(cur.playback_id, 'interrupted', cur.t0)
      if (cur.type === 'tts_play') {
        const cbs = [...player.ttsEndCallbacks]
        player.ttsEndCallbacks.clear()
        cbs.forEach(cb => cb())
      }
      if (player.pendingNext) {
        const next = player.pendingNext
        player.pendingNext = null
        playMessage(next)
      }
    }
  }, 16) // ~60fps ramp
}

function enqueue(msg) {
  if (!msg || typeof msg !== 'object') return
  const t = msg.msg_type
  if (t === 'bgm_play') {
    handleBgmPlay(msg.payload || {})
    return
  }
  if (t === 'bgm_duck') {
    handleBgmDuck(msg.payload || {})
    return
  }
  if (t === 'tts_interrupt') {
    const pbid = (msg.payload || {}).playback_id
    fadeOutInterrupt(pbid)
    return
  }
  if (t !== 'tts_play' && t !== 'sfx_play') return
  const payload = msg.payload || {}
  if (window._bench) {
    const playback_id = payload.playback_id || '-'
    try { window._bench.log('audio_msg_received', t, playback_id, performance.now()) } catch (_) {}
  }
  msg.payload = { ...payload, __bench_received_at: performance.now() }
  if (t === 'tts_play' && !player.ttsEnabled) {
    const playback_id = payload.playback_id || `pb_${Math.random().toString(36).slice(2, 10)}`
    if (window._bench) {
      try { window._bench.log('audio_play_skipped', t, playback_id, performance.now()) } catch (_) {}
    }
    sendAck(playback_id, 'skipped', Date.now() / 1000)
    return
  }
  if (!player.unlocked) {
    player.pendingNext = msg
    return
  }
  if (player.current) {
    // backend가 ack-driven이라 보통 안 오지만, CRITICAL 인터럽트 직후엔
    // 진행 중인 fade-out과 새 메시지가 겹침. 슬롯에 저장하고 fade 끝나면 처리.
    player.pendingNext = msg
    return
  }
  playMessage(msg)
}

function handleBgmPlay({ audio_url, loop = true, gain_db = -6, preserve_position = false }) {
  // 빈 audio_url은 정지/일시정지 신호.
  if (!audio_url) {
    if (player.bgmAudio) {
      try { player.bgmAudio.pause() } catch (_) {}
      if (!preserve_position) {
        try { player.bgmAudio.currentTime = 0 } catch (_) {}
        player.bgmAudio.src = ''
      }
    }
    return
  }
  const el = ensureBgmElement()
  if (el.src !== new URL(audio_url, window.location.href).href) {
    el.src = audio_url
  }
  el.loop = !!loop
  player.bgmGainDb = gain_db
  applyBgmGain()
  if (player.unlocked) {
    el.play().catch(() => {})
  }
}

function handleBgmDuck({ on, attenuation_db = -12 }) {
  player.duckGainDb = on ? attenuation_db : 0
  applyBgmGain()
}

/**
 * BGM을 즉시 정지하고 위치를 0으로 리셋. 페이지 전환 등 backend round-trip을
 * 기다릴 수 없는 상황에서 frontend가 직접 호출.
 */
function stopBgm() {
  handleBgmPlay({ audio_url: '' })
}

/**
 * BGM을 즉시 재생. backend를 거치지 않고 frontend가 직접 트리거할 때 사용
 * (로비 진입 시 등). url은 정적 자산 경로(예: '/bgm/lobby_loop.mp3').
 */
function playBgm(url, { loop = true, gain_db = -12 } = {}) {
  handleBgmPlay({ audio_url: url, loop, gain_db })
}

function unlock() {
  if (player.unlocked) return
  player.unlocked = true
  const el = ensureAudioElement()
  const prev = el.src
  el.src = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA='
  el.play().then(() => {
    el.pause()
    el.src = prev || ''
  }).catch(() => {})
  // unlock 직전에 도착한 메시지 처리
  if (player.pendingNext && !player.current) {
    const next = player.pendingNext
    player.pendingNext = null
    playMessage(next)
  }
  // unlock 이전에 BGM이 enqueue됐다면(예: seat 페이지 첫 진입 로비 BGM)
  // src는 세팅됐지만 play()가 막혔던 상태. 여기서 재생을 트리거한다.
  if (player.bgmAudio && player.bgmAudio.src && player.bgmAudio.paused) {
    player.bgmAudio.play().catch(() => {})
  }
}

function setTtsEnabled(enabled) {
  player.ttsEnabled = !!enabled
  if (!player.ttsEnabled) {
    if (player.current?.type === 'tts_play') {
      fadeOutInterrupt(player.current.playback_id)
    }
    if (player.pendingNext?.msg_type === 'tts_play') {
      const payload = player.pendingNext.payload || {}
      const playback_id = payload.playback_id || `pb_${Math.random().toString(36).slice(2, 10)}`
      player.pendingNext = null
      sendAck(playback_id, 'skipped', Date.now() / 1000)
    }
  }
}

/**
 * App에 한 번만 마운트. send 함수(useWebSocket의 send)를 받아 audio_ack를 backend로.
 */
export function useAudioPlayer(send) {
  const registered = useRef(false)
  useEffect(() => {
    if (send && !registered.current) {
      player.ackSenders.add(send)
      registered.current = true
    }
    const onFirstInteraction = () => {
      unlock()
      window.removeEventListener('pointerdown', onFirstInteraction)
      window.removeEventListener('keydown', onFirstInteraction)
    }
    if (!player.unlocked) {
      window.addEventListener('pointerdown', onFirstInteraction)
      window.addEventListener('keydown', onFirstInteraction)
    }
    return () => {
      if (send) {
        player.ackSenders.delete(send)
        registered.current = false
      }
      window.removeEventListener('pointerdown', onFirstInteraction)
      window.removeEventListener('keydown', onFirstInteraction)
    }
  }, [send])

  return { enqueue, interrupt: fadeOutInterrupt, unlock }
}

/** TTS 재생이 끝나면(완료 또는 인터럽트) 1회 호출할 콜백 등록. 등록 해제 함수 반환. */
function onNextTtsEnded(callback) {
  player.ttsEndCallbacks.add(callback)
  return () => player.ttsEndCallbacks.delete(callback)
}

/** TTS 재생이 시작되면 1회 호출할 콜백 등록. 등록 해제 함수 반환. */
function onNextTtsStarted(callback) {
  player.ttsStartCallbacks.add(callback)
  return () => player.ttsStartCallbacks.delete(callback)
}

export const audio = {
  enqueue,
  interrupt: fadeOutInterrupt,
  unlock,
  setTtsEnabled,
  stopBgm,
  playBgm,
  onNextTtsEnded,
  onNextTtsStarted,
  volumes,
  setVolume,
  onVolumeChange,
}

/**
 * 프론트가 직접 트리거하는 효과음(sfx.js)이 읽는 값.
 *
 * 그쪽은 `new Audio()`를 따로 만들어 쓰므로 이 모듈의 Audio 인스턴스를
 * 공유하지 않는다. 그래도 음량은 같은 슬라이더를 따라야 하므로 값만 넘긴다.
 */
export function sfxVolume() {
  return player.sfxVolume
}
