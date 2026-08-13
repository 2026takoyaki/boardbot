import { useEffect } from 'react'
import { audio } from '../../hooks/useAudioPlayer'
import WerewolfScene from './WerewolfScene'
import * as ui from './wwUi'

export default function NightStart({ onComplete, send, onExit, isPracticeMode }) {
  useEffect(() => {
    // night_start TTS는 모드와 무관하게 ProgressAgent가 전담 (중복 발화 방지)

    // 늑대 울음 환경음 — 원본 7초, 최대 5초에서 컷.
    // TTS가 거의 동시에 시작되더라도 최소 3초는 보장한다(밤 분위기 형성).
    // 3초 이후 TTS가 시작되면 페이드아웃해 마스킹 방지.
    // 볼륨 0.35: TTS와 겹쳐도 마스킹 최소화하며 분위기 환경음으로 깔리는 수준.
    const wolfAudio = new Audio('/sfx/wolf_sound.mp3')
    wolfAudio.volume = 0.35
    wolfAudio.play().catch(() => {})
    let wolfFadeInterval = null
    const WOLF_MIN_MS = 3000
    const wolfStartTime = performance.now()
    const stopWolf = () => {
      if (wolfFadeInterval !== null) return
      const startVol = wolfAudio.volume
      const startTime = performance.now()
      const FADE_MS = 300
      wolfFadeInterval = setInterval(() => {
        const ratio = Math.min(1, (performance.now() - startTime) / FADE_MS)
        wolfAudio.volume = Math.max(0, startVol * (1 - ratio))
        if (ratio >= 1) {
          clearInterval(wolfFadeInterval)
          wolfFadeInterval = null
          try { wolfAudio.pause() } catch (_) {}
          try { wolfAudio.currentTime = 0 } catch (_) {}
        }
      }, 16)
    }
    const wolfCutoff = setTimeout(stopWolf, 5000)
    let earlyTtsTimer = null
    let timer = null
    let unsubscribeEnd = null

    // 안전장치: 안내 TTS가 전혀 시작되지 않으면(합성 실패 등) 무한 대기를 방지.
    const startWatchdog = setTimeout(onComplete, 10000)

    // night_start 안내 TTS가 "시작"된 시점을 기준으로 전환 로직을 건다.
    // 마운트 시점에 직전 화면(역할 설명 등)의 TTS가 아직 재생 중이면, 그 종료를
    // night_start TTS 종료로 오인해 조기 전환되는 문제를 막는다 — 이미 재생 중인
    // TTS는 start 콜백이 소비된 상태라, 다음 start = night_start TTS가 잡힌다.
    const unsubscribeStart = audio.onNextTtsStarted(() => {
      clearTimeout(startWatchdog)

      // 늑대 울음 페이드아웃 (최소 3초 보장)
      const elapsed = performance.now() - wolfStartTime
      if (elapsed >= WOLF_MIN_MS) {
        stopWolf()
      } else {
        earlyTtsTimer = setTimeout(stopWolf, WOLF_MIN_MS - elapsed)
      }

      // 이 안내 TTS가 끝난 뒤 일정 시간 후 다음 화면으로 전환.
      // 일반 모드에서 이 화면이 머무는 시간은 여기가 아니라 백엔드가 정한다
      // (fsm.py NIGHT_START_DURATION, 5초). 이 타이머는 그보다 늦게 잡아 둔
      // 폴백일 뿐이므로, 화면 시간을 바꾸려면 NIGHT_START_DURATION을 고쳐야 한다.
      // 튜토리얼 모드는 백엔드 타이머가 없어 이 경로가 실제 전환을 주도한다.
      unsubscribeEnd = audio.onNextTtsEnded(() => {
        timer = setTimeout(onComplete, isPracticeMode ? 5000 : 10000)
      })
    })

    return () => {
      unsubscribeStart()
      if (unsubscribeEnd) unsubscribeEnd()
      if (timer !== null) clearTimeout(timer)
      clearTimeout(startWatchdog)
      clearTimeout(wolfCutoff)
      if (earlyTtsTimer !== null) clearTimeout(earlyTtsTimer)
      if (wolfFadeInterval !== null) clearInterval(wolfFadeInterval)
      try { wolfAudio.pause() } catch (_) {}
    }
  }, [])

  return (
    <div className="ww-root" onClick={onComplete} style={{ ...ui.page, cursor: 'pointer' }}>
      <WerewolfScene mood="night" />

      <button
        className="ww-hover ww-press"
        onClick={(e) => { e.stopPropagation(); onExit?.() }}
        style={ui.exitButton}
      >
        나가기
      </button>

      <div style={{ ...ui.stage, gap: 22, marginBottom: 110 }}>
        <span style={{ ...ui.eyebrow, animationDelay: '0.1s' }} className="ww-anim-down">
          <span style={ui.eyebrowDot} />
          {isPracticeMode ? '튜토리얼 모드' : 'TTS 재생 중'}
        </span>

        {/* 제목이 흐릿하게 벌어져 있다가 초점을 잡으며 조여든다. 밤이 "내려앉는"
            느낌은 페이드인이 아니라 이 조임에서 나온다. */}
        <h1 style={{ ...ui.title, letterSpacing: '0.08em' }} className="ww-anim-title">
          밤이 되었습니다
        </h1>

        <div className="ww-rule" style={styles.rule}><i /></div>

        {isPracticeMode && (
          <div style={styles.notes} className="ww-anim-in">
            <p style={styles.note}>튜토리얼 모드에서는 눈을 감지 않고 진행합니다</p>
            <p style={{ ...styles.note, ...styles.noteSub }}>
              차례가 되면 해당 역할 플레이어가 행동을 수행하면 됩니다
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

const styles = {
  rule: {
    width: 'min(420px, 62vw)',
    animation: 'ww-in 700ms ease-out 0.5s both',
  },

  notes: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 6,
    animationDelay: '0.75s',
  },

  note: {
    margin: 0,
    fontSize: 17,
    fontWeight: 550,
    color: 'var(--w-ink-soft)',
    letterSpacing: '-0.01em',
  },

  noteSub: { fontSize: 14, color: 'var(--w-ink-mute)' },
}
