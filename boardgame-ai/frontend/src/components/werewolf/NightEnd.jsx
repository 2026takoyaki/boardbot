import { useEffect, useState } from 'react'
import { audio } from '../../hooks/useAudioPlayer'
import { narrate, useLines } from '../../lines'
import WerewolfScene from './WerewolfScene'
import * as ui from './wwUi'

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
    <div className="ww-root" onClick={onComplete} style={{ ...ui.page, cursor: 'pointer' }}>
      <WerewolfScene mood="dawn" />
      <style>{CSS}</style>

      {/* 해 — 지평선 뒤에서 떠올라 마을 위로 걸린다. 광선은 아주 천천히 돈다. */}
      <div className="ww-sun-stage">
        <div className="ww-sun-rays" />
        <div className="ww-sun-disc" />
      </div>

      {/* 아침 빛이 화면 전체를 한 번 씻고 지나간다 */}
      <div className="ww-daybreak" />

      <div style={{ ...ui.stage, gap: 12, marginBottom: 40 }}>
        <h1 style={{ ...ui.title, letterSpacing: '0.04em' }} className="ww-anim-title">
          {line('werewolf.morning')}
        </h1>
        {!isPracticeMode && (
          <div style={styles.subtitle} className="ww-anim-in">
            {line('werewolf.morning_open_eyes')}
          </div>
        )}
        {showDiscussion && (
          <div style={styles.discussion} className="ww-panel ww-anim-in">
            {isPracticeMode ? (
              <>
                <div style={styles.discussionHead}>
                  밤 동안의 행동을 추론하며 누가 늑대인간인지 찾아내세요.
                </div>
                <ul className="ww-rules" style={styles.rules}>
                  <li>늑대인간이 없다면 아무도 처단하지 마세요</li>
                  <li>늑대인간이 없어도 하수인이 있다면 하수인을 처단해야 마을주민팀이 승리합니다</li>
                  <li>늑대인간과 하수인이 모두 있다면 하수인이 아닌 늑대인간을 처단해야 마을주민팀이 승리합니다</li>
                  <li>무두장이가 처단되면 무두장이 혼자 승리합니다</li>
                </ul>
              </>
            ) : (
              <div style={styles.discussionHead}>{line('werewolf.discussion_start')}</div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

const styles = {
  subtitle: {
    fontSize: 17,
    fontWeight: 550,
    color: 'var(--w-ink-soft)',
    animationDelay: '0.7s',
  },

  discussion: {
    marginTop: 22,
    padding: '20px 30px',
    maxWidth: 'min(860px, 90vw)',
    fontSize: 19,
    fontWeight: 600,
    color: 'var(--w-ink)',
    lineHeight: 1.6,
    textAlign: 'center',
    wordBreak: 'keep-all',
  },

  discussionHead: { letterSpacing: '-0.01em' },

  rules: {
    margin: '14px 0 0',
    padding: 0,
    listStyle: 'none',
    display: 'flex',
    flexDirection: 'column',
    gap: 7,
    fontSize: 15,
    fontWeight: 500,
    color: 'var(--w-ink-soft)',
    textAlign: 'left',
  },
}

const CSS = `
  .ww-rules li { display: flex; gap: 9px; }
  .ww-rules li::before { content: "·"; color: var(--w-gold); font-weight: 900; }

  .ww-sun-stage {
    position: absolute;
    z-index: 1;
    top: 26%;
    left: 50%;
    width: 168px; height: 168px;
    transform: translateX(-50%);
    animation: ww-sun-rise 2.4s cubic-bezier(0.16,0.8,0.24,1) both;
  }
  @keyframes ww-sun-rise {
    0%   { opacity: 0; transform: translate(-50%, 210px) scale(0.62); }
    62%  { opacity: 1; }
    100% { opacity: 1; transform: translate(-50%, 0) scale(1); }
  }
  .ww-sun-disc {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: radial-gradient(circle at 40% 36%, #fffef0 0%, #ffeda0 30%, #ffc63c 62%, #f4820f 92%);
    box-shadow: 0 0 70px 26px rgba(255,206,80,0.45), 0 0 160px 70px rgba(255,140,30,0.24);
    animation: ww-sun-glow 4.2s ease-in-out 2.2s infinite;
  }
  @keyframes ww-sun-glow {
    0%, 100% { box-shadow: 0 0 70px 26px rgba(255,206,80,0.45), 0 0 160px 70px rgba(255,140,30,0.22); }
    50%      { box-shadow: 0 0 104px 40px rgba(255,228,110,0.62), 0 0 220px 96px rgba(255,160,40,0.32); }
  }
  /* 광선. 아주 느리게 돌아 눈에 띄지 않게 화면이 살아 있게 한다. */
  .ww-sun-rays {
    position: absolute;
    inset: -220%;
    background: repeating-conic-gradient(from 0deg,
      rgba(255,222,140,0.16) 0deg 3deg, transparent 3deg 17deg);
    -webkit-mask-image: radial-gradient(circle, #000 12%, transparent 58%);
    mask-image: radial-gradient(circle, #000 12%, transparent 58%);
    animation: ww-rays-spin 90s linear infinite, ww-in 2s ease-out 1.4s both;
  }
  @keyframes ww-rays-spin { to { transform: rotate(360deg); } }

  /* 화면을 한 번 씻고 지나가는 아침 빛 */
  .ww-daybreak {
    position: absolute;
    inset: 0;
    background: linear-gradient(180deg, transparent 30%, rgba(255,206,120,0.34) 78%, rgba(255,232,170,0.5) 100%);
    pointer-events: none;
    animation: ww-daybreak 2.6s ease-out both;
  }
  @keyframes ww-daybreak {
    0%   { opacity: 0; }
    40%  { opacity: 1; }
    100% { opacity: 0.35; }
  }
`
