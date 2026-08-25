import { useRef, useEffect } from 'react'
import WerewolfScene from './WerewolfScene'
import * as ui from './wwUi'

const RADIUS = 128
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

// timeLeft는 백엔드 timer_remaining을 그대로 전달받아 사용한다.
// 로컬 setInterval 없이 백엔드 state_update(1초마다)로 동기화된다.
export default function DayDiscussion({ timeLeft = 300, onVote, onAddTime }) {
  const maxTimeRef = useRef(timeLeft)

  useEffect(() => {
    if (timeLeft > maxTimeRef.current) {
      maxTimeRef.current = timeLeft
    }
  }, [timeLeft])

  const formatTime = (s) => {
    const m = Math.floor(s / 60)
    const sec = s % 60
    return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
  }

  const progress = Math.max(0, timeLeft / maxTimeRef.current)
  const strokeDashoffset = CIRCUMFERENCE * (1 - progress)
  const isUrgent = timeLeft <= 30
  // 마지막 10초는 링이 아니라 화면 전체가 반응한다. 숫자를 보고 있지 않아도
  // 시간이 끝나간다는 것을 알아야 하는 구간이다.
  const isFinal = timeLeft <= 10

  return (
    <div className="ww-root" style={ui.page}>
      <WerewolfScene mood="day" />
      <style>{CSS}</style>

      {isUrgent && <div className={isFinal ? 'ww-alarm ww-alarm-final' : 'ww-alarm'} />}

      <div style={{ ...ui.stage, gap: 30 }}>
        <span style={ui.eyebrow} className="ww-anim-down">
          <span style={ui.eyebrowDot} />
          토론 시간
        </span>

        <div
          className={isFinal ? 'ww-timer ww-timer-final' : 'ww-timer'}
          style={styles.timerWrap}
        >
          <svg width={300} height={300} style={{ display: 'block', overflow: 'visible' }}>
            <defs>
              <filter id="ww-ring-glow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="6" result="b" />
                <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <linearGradient id="ww-ring" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor={isUrgent ? '#ff9a5c' : '#ffe9a8'} />
                <stop offset="100%" stopColor={isUrgent ? '#c02a08' : '#d99a1e'} />
              </linearGradient>
            </defs>

            {/* 눈금. 남은 시간을 각도만으로 읽기는 어렵다 — 60등분한 눈금이
                있으면 링이 계기판처럼 읽힌다. */}
            <g opacity="0.28">
              {Array.from({ length: 60 }).map((_, i) => {
                const major = i % 5 === 0
                const angle = (i / 60) * Math.PI * 2 - Math.PI / 2
                const outer = RADIUS + 20
                const inner = outer - (major ? 9 : 5)
                return (
                  <line
                    key={i}
                    x1={150 + Math.cos(angle) * inner}
                    y1={150 + Math.sin(angle) * inner}
                    x2={150 + Math.cos(angle) * outer}
                    y2={150 + Math.sin(angle) * outer}
                    stroke="rgba(255,238,200,0.9)"
                    strokeWidth={major ? 2 : 1}
                    strokeLinecap="round"
                  />
                )
              })}
            </g>

            <circle
              cx={150} cy={150} r={RADIUS}
              fill="rgba(20,8,2,0.34)"
              stroke="rgba(255,255,255,0.10)"
              strokeWidth={12}
            />
            <circle
              cx={150} cy={150} r={RADIUS}
              fill="none"
              stroke="url(#ww-ring)"
              strokeWidth={12}
              strokeLinecap="round"
              strokeDasharray={CIRCUMFERENCE}
              strokeDashoffset={strokeDashoffset}
              transform="rotate(-90 150 150)"
              filter="url(#ww-ring-glow)"
              style={{ transition: 'stroke-dashoffset 1s linear, stroke 300ms ease' }}
            />
          </svg>

          {/* 숫자는 SVG text가 아니라 DOM으로 둔다 — tabular-nums가 걸려야
              1이 나올 때마다 폭이 줄어 숫자가 좌우로 흔들리지 않는다. */}
          <div
            style={{
              ...styles.clock,
              color: isUrgent ? '#ffb08a' : 'var(--w-ink)',
            }}
          >
            {formatTime(timeLeft)}
          </div>
        </div>

        <div style={styles.buttonRow} className="ww-anim-in">
          <button onClick={onAddTime} className="ww-press" style={styles.addBtn}>
            + 30초
          </button>
          <button onClick={onVote} className="ww-press" style={{ ...ui.primaryButton, flex: 1.4 }}>
            즉시 투표 →
          </button>
        </div>
      </div>
    </div>
  )
}

const styles = {
  timerWrap: {
    position: 'relative',
    display: 'grid',
    placeItems: 'center',
    animation: 'ww-pop 720ms cubic-bezier(.2,.9,.25,1.25) both',
  },

  clock: {
    position: 'absolute',
    fontSize: 62,
    fontWeight: 800,
    letterSpacing: '0.01em',
    fontVariantNumeric: 'tabular-nums',
    textShadow: '0 4px 22px rgba(0,0,0,0.55)',
    transition: 'color 300ms ease',
  },

  buttonRow: {
    display: 'flex',
    gap: 14,
    width: 'min(460px, 84vw)',
    animationDelay: '0.25s',
  },

  addBtn: {
    ...ui.ghostButton,
    flex: 1,
    borderColor: 'var(--w-line-strong)',
    color: 'var(--w-gold)',
  },
}

const CSS = `
  /* 급할 때 화면 가장자리가 붉게 숨을 쉰다 */
  .ww-alarm {
    position: absolute;
    inset: 0;
    z-index: 1;
    pointer-events: none;
    background: radial-gradient(ellipse 82% 76% at 50% 50%, transparent 46%, rgba(190,30,10,0.42) 100%);
    animation: ww-alarm 1.6s ease-in-out infinite;
  }
  .ww-alarm-final { animation-duration: 0.75s; }
  @keyframes ww-alarm {
    0%, 100% { opacity: 0.25; }
    50%      { opacity: 0.9; }
  }

  /* 마지막 10초는 링이 박동한다 */
  .ww-timer-final { animation: ww-timer-beat 1s ease-in-out infinite !important; }
  @keyframes ww-timer-beat {
    0%, 100% { transform: scale(1); }
    12%      { transform: scale(1.035); }
    26%      { transform: scale(0.995); }
  }
`
