import { useEffect, useState } from 'react'
import { audio } from '../../hooks/useAudioPlayer'
import { narrate, useLines } from '../../lines'

export default function NightEnd({ onComplete, send, isPracticeMode }) {
  const [showDiscussion, setShowDiscussion] = useState(false)
  // 문장의 소유자는 백엔드다. 화면 문구도 같은 카탈로그에서 읽으므로
  // 페르소나를 바꾸면 자막과 음성이 함께 바뀐다.
  const line = useLines()

  useEffect(() => {
    const cleanups = []

    if (isPracticeMode) {
      // 아침이 TTS 종료 → 규칙 설명 TTS 종료 → onComplete 순으로 진행
      const startRuleExplanation = () => {
        setShowDiscussion(true)
        narrate(send, 'werewolf_practice.day_rules')
        // 규칙 TTS가 시작되지 않을 경우 폴백
        const fallback = setTimeout(onComplete, 25000)
        cleanups.push(() => clearTimeout(fallback))
        const unsubStart = audio.onNextTtsStarted(() => {
          const unsubEnd = audio.onNextTtsEnded(() => {
            clearTimeout(fallback)
            // 토론 단계를 건너뛰고 바로 투표로 가므로, 규칙 설명이 끝난 뒤 한 박자
            // 쉬어 투표 안내 음성과 겹치거나 너무 급하게 넘어가지 않도록 한다.
            setTimeout(onComplete, 3200)
          })
          cleanups.push(unsubEnd)
        })
        cleanups.push(unsubStart)
      }

      // PhaseTransition(dawn) 2500ms 이후 아침이 TTS 시작
      const t1 = setTimeout(() => {
        narrate(send, 'werewolf_practice.morning')
        // 아침이 TTS가 시작되지 않을 경우 폴백
        const fallback1 = setTimeout(startRuleExplanation, 8000)
        cleanups.push(() => clearTimeout(fallback1))
        const unsubStart = audio.onNextTtsStarted(() => {
          clearTimeout(fallback1)
          const unsubEnd = audio.onNextTtsEnded(() => setTimeout(startRuleExplanation, 800))
          cleanups.push(unsubEnd)
        })
        cleanups.push(unsubStart)
      }, 4000)
      cleanups.push(() => clearTimeout(t1))
    } else {
      // 일반 모드: 기존 고정 타이머 유지
      const t1 = setTimeout(() => {
        // 화면이 큰 제목 + 작은 부제로 나눠 보여주는 두 줄. 발화는 이어서 한다
        // (오디오 큐가 순서를 지키므로 한 문장처럼 들린다).
        narrate(send, 'werewolf.morning')
        narrate(send, 'werewolf.morning_open_eyes')
      }, 4000)
      const t2 = setTimeout(() => {
        setShowDiscussion(true)
        narrate(send, 'werewolf.discussion_start')
      }, 8000)
      const t3 = setTimeout(onComplete, 13000)
      cleanups.push(() => clearTimeout(t1), () => clearTimeout(t2), () => clearTimeout(t3))
    }

    return () => cleanups.forEach(fn => fn())
  }, [])

  return (
    <>
      <style>{`
        @keyframes sunRise {
          0%   { transform: translateY(80px) scale(0.7); opacity: 0; }
          60%  { opacity: 1; }
          100% { transform: translateY(0px) scale(1); opacity: 1; }
        }
        @keyframes glowPulse {
          0%, 100% { box-shadow: 0 0 60px 24px rgba(255,210,80,0.45), 0 0 120px 60px rgba(255,140,30,0.2); }
          50%       { box-shadow: 0 0 90px 36px rgba(255,230,100,0.65), 0 0 180px 80px rgba(255,160,40,0.3); }
        }
        @keyframes skyFade {
          0%   { opacity: 0; }
          100% { opacity: 1; }
        }
        @keyframes textRise {
          0%   { opacity: 0; transform: translateY(16px); }
          100% { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      <div onClick={onComplete} style={styles.page}>

        {/* 배경 — 밤에서 여명으로 */}
        <div style={styles.sky} />

        {/* 지평선 글로우 */}
        <div style={styles.horizonGlow} />

        {/* 마을 실루엣 */}
        <svg
          viewBox="0 0 800 160"
          preserveAspectRatio="xMidYMax slice"
          style={styles.silhouette}
        >
          {/* 나무들 */}
          <polygon points="60,160 80,100 100,160" fill="#0a0614" />
          <polygon points="75,160 100,80 125,160" fill="#0a0614" />
          <polygon points="110,160 130,105 150,160" fill="#0a0614" />
          {/* 집들 */}
          <rect x="170" y="120" width="60" height="40" fill="#0a0614" />
          <polygon points="165,120 200,95 235,120" fill="#0a0614" />
          <rect x="175" y="130" width="14" height="30" fill="#1a0a2e" />
          {/* 탑 */}
          <rect x="260" y="90" width="30" height="70" fill="#0a0614" />
          <polygon points="255,92 275,68 295,92" fill="#0a0614" />
          {/* 집 */}
          <rect x="320" y="115" width="50" height="45" fill="#0a0614" />
          <polygon points="315,115 345,88 375,115" fill="#0a0614" />
          {/* 나무 */}
          <polygon points="390,160 410,95 430,160" fill="#0a0614" />
          <polygon points="405,160 430,75 455,160" fill="#0a0614" />
          {/* 집 */}
          <rect x="460" y="125" width="45" height="35" fill="#0a0614" />
          <polygon points="455,125 482,102 510,125" fill="#0a0614" />
          {/* 큰 건물 */}
          <rect x="530" y="100" width="70" height="60" fill="#0a0614" />
          <polygon points="525,102 565,72 605,102" fill="#0a0614" />
          <rect x="558" y="78" width="14" height="24" fill="#0a0614" />
          {/* 나무 */}
          <polygon points="620,160 638,105 656,160" fill="#0a0614" />
          <polygon points="648,160 670,88 692,160" fill="#0a0614" />
          <polygon points="668,160 690,108 712,160" fill="#0a0614" />
          {/* 집 */}
          <rect x="715" y="120" width="55" height="40" fill="#0a0614" />
          <polygon points="710,120 742,96 774,120" fill="#0a0614" />
        </svg>

        {/* 태양 */}
        <div style={styles.sunContainer}>
          <div style={styles.sun} />
        </div>

        {/* 텍스트 */}
        <div style={styles.textBlock}>
          <div style={styles.title}>{line('werewolf.morning')}</div>
          {!isPracticeMode && (
            <div style={styles.subtitle}>{line('werewolf.morning_open_eyes')}</div>
          )}
          {showDiscussion && (
            <div style={styles.discussion}>
              {isPracticeMode ? (
                <>
                  <div>밤 동안의 행동을 추론하며 누가 늑대인간인지 찾아내세요.</div>
                  <div style={{ marginTop: 10, fontSize: 16, opacity: 0.8 }}>
                    · 늑대인간이 없다면 아무도 처단하지 마세요<br />
                    · 늑대인간이 없어도 하수인이 있다면 하수인을 처단해야 마을주민팀이 승리합니다<br />
                    · 늑대인간과 하수인이 모두 있다면 하수인이 아닌 늑대인간을 처단해야 마을주민팀이 승리합니다<br />
                    · 무두장이가 처단되면 무두장이 혼자 승리합니다
                  </div>
                </>
              ) : line('werewolf.discussion_start')}
            </div>
          )}
        </div>

      </div>
    </>
  )
}

const styles = {
  page: {
    minHeight: '100vh',
    position: 'relative',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    fontFamily: "'Segoe UI', 'Apple SD Gothic Neo', sans-serif",
    cursor: 'pointer',
    userSelect: 'none',
  },

  sky: {
    position: 'absolute',
    inset: 0,
    background: 'linear-gradient(180deg, #0d0821 0%, #1e0c3a 22%, #4a1830 45%, #8c3b1e 65%, #d4641c 80%, #f0a030 100%)',
    animation: 'skyFade 1.8s ease-out forwards',
  },

  horizonGlow: {
    position: 'absolute',
    bottom: '20%',
    left: '50%',
    transform: 'translateX(-50%)',
    width: '70%',
    height: 120,
    background: 'radial-gradient(ellipse at center bottom, rgba(255,160,40,0.35), transparent 70%)',
    filter: 'blur(20px)',
    pointerEvents: 'none',
  },

  silhouette: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    width: '100%',
    height: 160,
    pointerEvents: 'none',
  },

  sunContainer: {
    position: 'relative',
    zIndex: 1,
    marginBottom: 60,
    animation: 'sunRise 2s cubic-bezier(0.22, 0.61, 0.36, 1) forwards',
  },

  sun: {
    width: 140,
    height: 140,
    borderRadius: '50%',
    background: 'radial-gradient(circle at 40% 38%, #fffde7, #fdd835 40%, #f57f17 80%)',
    animation: 'glowPulse 2.4s ease-in-out 2s infinite',
    boxShadow: '0 0 60px 24px rgba(255,210,80,0.45), 0 0 120px 60px rgba(255,140,30,0.2)',
  },

  textBlock: {
    position: 'relative',
    zIndex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 10,
    animation: 'textRise 1s ease-out 1.2s both',
  },

  title: {
    fontSize: 38,
    fontWeight: 700,
    color: '#fff8e1',
    letterSpacing: -0.5,
    textShadow: '0 2px 12px rgba(255,160,40,0.5)',
  },

  subtitle: {
    fontSize: 16,
    color: 'rgba(255,240,200,0.85)',
  },

  discussion: {
    marginTop: 18,
    fontSize: 20,
    fontWeight: 500,
    color: 'rgba(255,240,200,0.9)',
    letterSpacing: 0.5,
    animation: 'textRise 0.7s ease-out both',
  },
}
