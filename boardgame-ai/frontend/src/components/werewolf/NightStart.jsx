import { useEffect } from 'react'
import { audio } from '../../hooks/useAudioPlayer'

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
    <>
      <style>{`
        @keyframes moonGlowPulse {
          0%,100% { box-shadow: 0 0 48px 18px rgba(220,185,80,0.22); }
          50%      { box-shadow: 0 0 72px 28px rgba(220,185,80,0.38); }
        }
        @keyframes fogDrift {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-8%); }
        }
        @keyframes starFlicker { 0%,100%{opacity:.6} 50%{opacity:.2} }
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(12px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes ttsFlicker {
          0%,100% { opacity: 0.5; }
          50%     { opacity: 1; }
        }
      `}</style>

      <div onClick={onComplete} style={styles.page}>
        <button onClick={(e) => { e.stopPropagation(); onExit?.() }} style={exitBtn}>나가기</button>

        {/* 배경 */}
        <div style={styles.sky} />

        {/* 달 */}
        <div style={styles.moon} />

        {/* 별 */}
        {[
          {t:'7%', l:'10%', s:2.2}, {t:'13%', l:'32%', s:1.4},
          {t:'5%', l:'55%', s:1.8}, {t:'19%', l:'75%', s:1.2},
          {t:'25%', l:'18%', s:1.0}, {t:'9%',  l:'44%', s:1.5},
          {t:'28%', l:'90%', s:2.0}, {t:'4%',  l:'82%', s:1.4},
          {t:'35%', l:'60%', s:1.2}, {t:'40%', l:'5%',  s:1.8},
        ].map((st, i) => (
          <div key={i} style={{
            position: 'absolute', top: st.t, left: st.l,
            width: st.s, height: st.s, borderRadius: '50%',
            background: '#fff', opacity: 0.6,
            animation: `starFlicker ${2.2 + i * 0.35}s ease-in-out infinite`,
          }} />
        ))}

        {/* 마을 실루엣 */}
        <svg viewBox="0 0 800 160" preserveAspectRatio="xMidYMax slice" style={styles.silhouette}>
          <polygon points="40,160 62,95 84,160"    fill="#06030f" />
          <polygon points="58,160 84,72 110,160"   fill="#06030f" />
          <polygon points="95,160 118,100 141,160" fill="#06030f" />
          <rect x="155" y="118" width="58" height="42" fill="#06030f" />
          <polygon points="150,120 184,92 218,120"  fill="#06030f" />
          <rect x="162" y="130" width="13" height="30" fill="#030108" />
          <rect x="245" y="86" width="32" height="74" fill="#06030f" />
          <polygon points="240,88 261,62 282,88"   fill="#06030f" />
          <rect x="300" y="112" width="52" height="48" fill="#06030f" />
          <polygon points="295,114 326,86 357,114" fill="#06030f" />
          <polygon points="372,160 394,90 416,160" fill="#06030f" />
          <polygon points="390,160 416,70 442,160" fill="#06030f" />
          <rect x="455" y="120" width="46" height="40" fill="#06030f" />
          <polygon points="450,122 478,98 506,122" fill="#06030f" />
          <rect x="524" y="96" width="72" height="64" fill="#06030f" />
          <polygon points="519,98 560,68 601,98"   fill="#06030f" />
          <rect x="552" y="74" width="16" height="26" fill="#06030f" />
          <polygon points="618,160 638,102 658,160" fill="#06030f" />
          <polygon points="646,160 670,84 694,160" fill="#06030f" />
          <rect x="710" y="118" width="54" height="42" fill="#06030f" />
          <polygon points="705,120 737,94 769,120" fill="#06030f" />
        </svg>

        {/* 안개 */}
        <div style={{
          position: 'absolute', bottom: 0, left: '-8%',
          width: '116%', height: '30%',
          background: 'linear-gradient(to top, rgba(60,30,90,0.5) 0%, rgba(40,20,70,0.22) 55%, transparent 100%)',
          animation: 'fogDrift 18s linear infinite alternate',
          filter: 'blur(14px)',
          pointerEvents: 'none',
        }} />

        {/* 중앙 텍스트 */}
        <div style={styles.inner}>
          <div style={{ ...styles.ttsLabel, animation: 'ttsFlicker 1.6s ease-in-out infinite' }}>
            {isPracticeMode ? '튜토리얼 모드' : 'TTS 재생 중'}
          </div>
          <div style={{ ...styles.title, animation: 'fadeIn 0.8s ease-out both' }}>
            밤이 되었습니다
          </div>
          {isPracticeMode && (
            <div style={{ ...styles.subtitle, animation: 'fadeIn 0.8s ease-out 0.2s both' }}>
              튜토리얼 모드에서는 눈을 감지 않고 진행합니다
            </div>
          )}
          {isPracticeMode && (
            <div style={{ ...styles.subtitle, fontSize: 14, marginTop: 4, animation: 'fadeIn 0.8s ease-out 0.4s both' }}>
              차례가 되면 해당 역할 플레이어가 행동을 수행하면 됩니다
            </div>
          )}
        </div>

      </div>
    </>
  )
}

const styles = {
  page: {
    height: '100vh',
    overflow: 'hidden',
    position: 'relative',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontFamily: "'Segoe UI', 'Apple SD Gothic Neo', sans-serif",
    cursor: 'pointer',
    userSelect: 'none',
  },

  sky: {
    position: 'absolute',
    inset: 0,
    background: 'radial-gradient(ellipse at 72% 8%, rgba(180,140,40,0.18) 0%, transparent 38%), radial-gradient(ellipse at 15% 85%, rgba(90,20,140,0.32) 0%, transparent 48%), linear-gradient(160deg, #160d38 0%, #0c1628 35%, #180c28 65%, #081420 100%)',
  },

  moon: {
    position: 'absolute',
    top: 48,
    right: 90,
    width: 90,
    height: 90,
    borderRadius: '50%',
    background: 'radial-gradient(circle at 38% 36%, #fffde7, #f5e070 40%, #c8a820 80%)',
    animation: 'moonGlowPulse 3.5s ease-in-out infinite',
  },

  silhouette: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    width: '100%',
    height: 160,
    pointerEvents: 'none',
  },

  inner: {
    position: 'relative',
    zIndex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 14,
    marginBottom: 80,
  },

  ttsLabel: {
    fontSize: 13,
    fontWeight: 600,
    letterSpacing: 2,
    color: 'rgba(220,185,120,0.6)',
    textTransform: 'uppercase',
  },

  title: {
    fontSize: 46,
    fontWeight: 800,
    color: '#F8F1DD',
    letterSpacing: 2,
    textShadow: '0 0 40px rgba(220,185,120,0.35), 0 2px 12px rgba(0,0,0,0.7)',
  },

  subtitle: {
    fontSize: 18,
    fontWeight: 400,
    color: 'rgba(248,241,221,0.55)',
    letterSpacing: 1,
  },
}

const exitBtn = {
  position: 'absolute', top: 20, right: 20, zIndex: 10,
  padding: '8px 18px',
  border: '1px solid rgba(248,241,221,0.2)',
  borderRadius: 8,
  background: 'rgba(255,255,255,0.08)',
  color: 'rgba(248,241,221,0.7)',
  fontSize: 14, fontWeight: 600, cursor: 'pointer',
  backdropFilter: 'blur(8px)',
}
