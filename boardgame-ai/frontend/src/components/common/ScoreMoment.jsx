import { useEffect, useRef, useState } from 'react'

/**
 * 득점 순간 모달.
 *
 * FSM이 보낸 cue payload의 variant에 따라 연출이 갈린다. 한 판이 36턴이라
 * 일반 득점(normal)은 여기까지 오지 않고 화면 안에서 처리된다 — 이 모달은
 * "사건"에만 뜬다.
 *
 * duration_ms는 payload가 정한다. 같은 값으로 조명 Cue와 TTS가 함께 움직이므로
 * 여기서 임의로 늘이거나 줄이면 세 채널이 어긋난다.
 */

// variant별 성격. 움직임의 방향이 곧 의미다 — 달성은 솟고, 실패는 떨어진다.
const LOOKS = {
  highlight: {
    tint: 'oklch(0.80 0.15 85)',
    glow: 'oklch(0.85 0.18 85)',
    rise: true,
    rays: true,
    countUp: true,
  },
  lead_change: {
    tint: 'oklch(0.78 0.13 230)',
    glow: 'oklch(0.82 0.15 230)',
    rise: true,
    rays: false,
    countUp: true,
  },
  zero: {
    tint: 'oklch(0.62 0.02 250)',
    glow: 'oklch(0.55 0.02 250)',
    rise: false,
    rays: false,
    countUp: false,
  },
}

const HEADLINES = {
  highlight: (m) => (m.category_label || '').toUpperCase(),
  lead_change: () => '역전',
  zero: () => '아쉽네요',
}

export default function ScoreMoment({ moment, onDone }) {
  const look = LOOKS[moment?.variant]

  useEffect(() => {
    if (!moment || !look) return undefined
    // 자동으로 닫힌다. 탭으로 넘기게 만들지 않는다 — 매 턴 손을 요구하면
    // 연출이 아니라 절차가 된다.
    const timer = setTimeout(() => onDone?.(), moment.duration_ms)
    return () => clearTimeout(timer)
  }, [moment, look, onDone])

  if (!moment || !look) return null

  const d = moment.duration_ms
  // 진입 15% · 유지 · 퇴장 20%. 빠르게 들어오고 빠르게 빠져야 경쾌하다.
  const enterMs = Math.round(d * 0.15)
  const exitMs = Math.round(d * 0.2)
  const exitDelay = d - exitMs

  return (
    <div style={{ ...styles.overlay, animation: `sm-veil ${d}ms ease-out forwards` }}>
      <style>{`
        @keyframes sm-veil {
          0%   { opacity: 0; }
          12%  { opacity: 1; }
          80%  { opacity: 1; }
          100% { opacity: 0; }
        }
        @keyframes sm-card-rise {
          0%   { opacity: 0; transform: translateY(28px) scale(0.88); }
          55%  { opacity: 1; transform: translateY(-6px) scale(1.04); }
          75%  { transform: translateY(0) scale(1); }
          100% { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes sm-card-drop {
          0%   { opacity: 0; transform: translateY(-18px) scale(1.03); }
          45%  { opacity: 1; transform: translateY(4px) scale(1); }
          62%  { transform: translateY(0) scale(1); }
          70%  { transform: translateX(-5px); }
          78%  { transform: translateX(5px); }
          86%  { transform: translateX(-3px); }
          100% { opacity: 1; transform: translateX(0); }
        }
        @keyframes sm-exit {
          0%   { opacity: 1; transform: scale(1); }
          100% { opacity: 0; transform: scale(0.94); }
        }
        @keyframes sm-glow {
          0%   { opacity: 0; transform: scale(0.6); }
          40%  { opacity: 0.9; transform: scale(1.1); }
          100% { opacity: 0.35; transform: scale(1); }
        }
        @keyframes sm-rays {
          0%   { opacity: 0; transform: rotate(0deg) scale(0.7); }
          35%  { opacity: 0.55; }
          100% { opacity: 0.2; transform: rotate(26deg) scale(1.15); }
        }
        @keyframes sm-headline {
          0%   { opacity: 0; transform: scale(0.7); letter-spacing: 0.3em; }
          60%  { opacity: 1; transform: scale(1.06); letter-spacing: 0.06em; }
          100% { opacity: 1; transform: scale(1); letter-spacing: 0.08em; }
        }
        @keyframes sm-rank-flip {
          0%   { opacity: 0; transform: translateY(10px); }
          100% { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      {/* 뒤에서 번지는 빛. variant 색이 여기서 화면 전체 인상을 만든다. */}
      <div
        style={{
          ...styles.glow,
          background: `radial-gradient(circle, ${look.glow} 0%, transparent 62%)`,
          animation: `sm-glow ${enterMs * 2}ms cubic-bezier(.2,.9,.3,1) forwards`,
        }}
      />

      {look.rays && (
        <div
          style={{
            ...styles.rays,
            animation: `sm-rays ${d}ms cubic-bezier(.15,.85,.3,1) forwards`,
          }}
        />
      )}

      <div
        style={{
          ...styles.card,
          borderColor: `color-mix(in oklch, ${look.tint} 45%, transparent)`,
          animation: [
            `${look.rise ? 'sm-card-rise' : 'sm-card-drop'} ${enterMs * 2.4}ms `
              + 'cubic-bezier(.2,.9,.25,1.15) both',
            `sm-exit ${exitMs}ms ease-in ${exitDelay}ms forwards`,
          ].join(', '),
        }}
      >
        <div
          style={{
            ...styles.headline,
            color: look.tint,
            textShadow: `0 0 32px color-mix(in oklch, ${look.glow} 55%, transparent)`,
            animation: `sm-headline ${enterMs * 2.6}ms cubic-bezier(.2,.9,.25,1.2) both`,
          }}
        >
          {HEADLINES[moment.variant](moment)}
        </div>

        {moment.variant === 'lead_change' ? (
          <RankFlip moment={moment} tint={look.tint} enterMs={enterMs} />
        ) : (
          <ScoreLine moment={moment} look={look} enterMs={enterMs} />
        )}

        <div style={styles.scorer}>
          {moment.scorer_name}
          {moment.variant !== 'lead_change' && moment.took_lead && (
            <span style={{ ...styles.leadBadge, color: 'oklch(0.78 0.13 230)' }}>
              선두 탈환
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

/** 점수 숫자. 달성 순간에는 숫자가 올라가는 것 자체가 연출이다. */
function ScoreLine({ moment, look, enterMs }) {
  const shown = useCountUp(look.countUp ? moment.score : null, enterMs * 2.2)
  const value = look.countUp ? shown : moment.score

  return (
    <div style={styles.scoreRow}>
      {moment.variant !== 'highlight' && (
        <span style={styles.category}>{moment.category_label}</span>
      )}
      <span style={{ ...styles.score, color: look.tint }}>
        {value}
        <span style={styles.scoreUnit}>점</span>
      </span>
    </div>
  )
}

/** 순위 뒤집힘. 누구를 제쳤는지가 이 순간의 내용이다. */
function RankFlip({ moment, tint, enterMs }) {
  return (
    <div style={styles.rankRow}>
      <span style={{ ...styles.rankFrom, animation: `sm-rank-flip ${enterMs * 2}ms ease-out both` }}>
        {moment.rank_before}위
      </span>
      <span style={styles.rankArrow}>→</span>
      <span
        style={{
          ...styles.rankTo,
          color: tint,
          animation: `sm-rank-flip ${enterMs * 2}ms ease-out ${enterMs * 0.6}ms both`,
        }}
      >
        {moment.rank_after}위
      </span>
      {moment.previous_leader && (
        <span style={styles.displaced}>{moment.previous_leader} 님을 제쳤습니다</span>
      )}
    </div>
  )
}

/** 0 → target 까지 숫자를 굴린다. target이 null이면 카운트업을 쓰지 않는다. */
function useCountUp(target, durationMs) {
  const [value, setValue] = useState(target == null ? null : 0)
  const frameRef = useRef(0)

  useEffect(() => {
    if (target == null) return undefined
    if (target === 0) {
      setValue(0)
      return undefined
    }
    const start = performance.now()
    const tick = (now) => {
      const t = Math.min(1, (now - start) / durationMs)
      // 끝에서 감속 — 마지막 숫자에 안착하는 느낌.
      const eased = 1 - (1 - t) ** 3
      setValue(Math.round(target * eased))
      if (t < 1) frameRef.current = requestAnimationFrame(tick)
    }
    frameRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frameRef.current)
  }, [target, durationMs])

  return value
}

const styles = {
  overlay: {
    position: 'fixed',
    inset: 0,
    zIndex: 9998,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    // 탭을 가로채지 않는다. 자동으로 닫히므로 막을 이유가 없다.
    pointerEvents: 'none',
    background: 'color-mix(in oklch, var(--bg-deep) 62%, transparent)',
    backdropFilter: 'blur(3px)',
  },
  glow: {
    position: 'absolute',
    width: 'min(160vw, 1100px)',
    height: 'min(160vw, 1100px)',
    borderRadius: '50%',
    filter: 'blur(30px)',
  },
  rays: {
    position: 'absolute',
    width: 'min(150vw, 1000px)',
    height: 'min(150vw, 1000px)',
    background:
      'repeating-conic-gradient(from 0deg, oklch(0.9 0.14 85 / 0.5) 0deg 5deg,'
      + ' transparent 5deg 16deg)',
    maskImage: 'radial-gradient(circle, #000 12%, transparent 62%)',
    WebkitMaskImage: 'radial-gradient(circle, #000 12%, transparent 62%)',
  },
  card: {
    position: 'relative',
    minWidth: 'min(86vw, 460px)',
    padding: '40px 52px 34px',
    borderRadius: 'var(--radius-xl)',
    border: '1px solid',
    background: 'color-mix(in oklch, var(--bg-surface) 88%, transparent)',
    boxShadow: 'var(--shadow-lg)',
    textAlign: 'center',
  },
  headline: {
    fontSize: 'clamp(30px, 6vw, 52px)',
    fontWeight: 900,
    lineHeight: 1.05,
    marginBottom: 18,
  },
  scoreRow: {
    display: 'flex',
    alignItems: 'baseline',
    justifyContent: 'center',
    gap: 14,
    marginBottom: 16,
  },
  category: { fontSize: 22, fontWeight: 600, color: 'var(--fg-soft)' },
  score: { fontSize: 'clamp(40px, 8vw, 68px)', fontWeight: 900, lineHeight: 1 },
  scoreUnit: { fontSize: 22, fontWeight: 700, marginLeft: 4, color: 'var(--fg-mute)' },
  rankRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexWrap: 'wrap',
    gap: 12,
    marginBottom: 16,
  },
  rankFrom: {
    fontSize: 30,
    fontWeight: 700,
    color: 'var(--fg-mute)',
    textDecoration: 'line-through',
  },
  rankArrow: { fontSize: 26, color: 'var(--fg-faint)' },
  rankTo: { fontSize: 46, fontWeight: 900, lineHeight: 1 },
  displaced: {
    flexBasis: '100%',
    fontSize: 15,
    color: 'var(--fg-mute)',
    marginTop: 2,
  },
  scorer: { fontSize: 19, fontWeight: 600, color: 'var(--fg-soft)' },
  leadBadge: { marginLeft: 10, fontSize: 14, fontWeight: 800 },
}
