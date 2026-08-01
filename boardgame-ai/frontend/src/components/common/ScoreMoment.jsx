import { useEffect, useRef, useState } from 'react'

/**
 * 요트 연출 오버레이.
 *
 * 상자를 그리지 않는다. 테두리와 배경이 있으면 "창이 떴다"가 되고, 게임 화면과
 * 분리된 별개의 물건처럼 보인다. 글자와 빛만 화면 위에 얹혀 나타났다 사라지는
 * 편이 자연스럽다.
 *
 * duration_ms는 payload가 정한다. 임의로 바꾸면 조명·TTS와 어긋난다.
 * 단 yacht_hand_achieved(굴림 축하)는 조명이 관여하지 않으므로 화면만 신경 쓰면 된다.
 */

// 굴림 축하는 조합이 희귀할수록 크게 간다. 다 똑같이 터뜨리면 야찌가 스몰
// 스트레이트와 같은 무게가 되어 아무것도 특별하지 않다.
const TIERS = {
  legendary: { rays: true, rayOpacity: 0.62, scale: 1.0, shake: true },
  epic: { rays: true, rayOpacity: 0.42, scale: 0.88, shake: false },
  great: { rays: false, rayOpacity: 0, scale: 0.76, shake: false },
  good: { rays: false, rayOpacity: 0, scale: 0.66, shake: false },
  nice: { rays: false, rayOpacity: 0, scale: 0.58, shake: false },
}

const GOLD = { tint: 'oklch(0.86 0.17 85)', glow: 'oklch(0.88 0.19 85)' }

const LOOKS = {
  hand: GOLD,
  bonus: { tint: 'oklch(0.84 0.16 145)', glow: 'oklch(0.86 0.17 145)' },
  highlight: GOLD,
  lead_change: { tint: 'oklch(0.82 0.15 230)', glow: 'oklch(0.85 0.16 230)' },
  normal: { tint: 'oklch(0.90 0.03 90)', glow: 'oklch(0.80 0.06 90)' },
  zero: { tint: 'oklch(0.68 0.02 250)', glow: 'oklch(0.55 0.02 250)' },
}

function kindOf(moment) {
  if (!moment) return null
  if (moment.cue === 'yacht_hand_achieved') return 'hand'
  if (moment.cue === 'yacht_bonus_achieved') return 'bonus'
  return moment.variant || 'normal'
}

export default function ScoreMoment({ moment, onDone }) {
  const kind = kindOf(moment)
  const look = LOOKS[kind]
  // 연출마다 새 인스턴스로 갈아끼워야 CSS 애니메이션이 처음부터 다시 돈다.
  return <Moment key={moment?.momentKey ?? 'none'} moment={moment} kind={kind} look={look} onDone={onDone} />
}

function Moment({ moment, kind, look, onDone }) {
  // onDone은 매 렌더마다 새로 만들어질 수 있다. ref에 담아두지 않으면 부모가
  // 리렌더될 때마다 타이머가 리셋되어 모달이 닫히지 않고, 다음 판까지 끌려간다.
  const doneRef = useRef(onDone)
  useEffect(() => { doneRef.current = onDone }, [onDone])

  const duration = moment?.duration_ms
  useEffect(() => {
    if (!duration) return undefined
    // 자동으로 닫힌다. 매 턴 손을 요구하면 연출이 아니라 절차가 된다.
    const timer = setTimeout(() => doneRef.current?.(), duration)
    return () => clearTimeout(timer)
  }, [duration])

  if (!moment || !look) return null

  const d = moment.duration_ms
  const enterMs = Math.round(d * 0.16)
  const tier = TIERS[moment.tier] ?? TIERS.great
  const showRays = kind === 'hand' ? tier.rays : false
  const bodyScale = kind === 'hand' ? tier.scale : 1

  return (
    <div style={styles.overlay}>
      <style>{`
        @keyframes ym-veil {
          0%   { opacity: 0; }
          14%  { opacity: 1; }
          78%  { opacity: 1; }
          100% { opacity: 0; }
        }
        @keyframes ym-rise {
          0%   { opacity: 0; transform: translateY(34px) scale(0.86); }
          52%  { opacity: 1; transform: translateY(-8px) scale(1.05); }
          72%  { transform: translateY(0) scale(1); }
          78%  { opacity: 1; transform: scale(1); }
          100% { opacity: 0; transform: scale(1.06); }
        }
        @keyframes ym-drop {
          0%   { opacity: 0; transform: translateY(-20px) scale(1.04); }
          42%  { opacity: 1; transform: translateY(5px) scale(1); }
          58%  { transform: translateY(0); }
          66%  { transform: translateX(-6px); }
          74%  { transform: translateX(6px); }
          82%  { opacity: 1; transform: translateX(0); }
          100% { opacity: 0; transform: scale(0.97); }
        }
        @keyframes ym-glow {
          0%   { opacity: 0; transform: scale(0.55); }
          35%  { opacity: 0.95; transform: scale(1.12); }
          78%  { opacity: 0.5; transform: scale(1); }
          100% { opacity: 0; }
        }
        @keyframes ym-rays {
          0%   { opacity: 0; transform: rotate(-8deg) scale(0.65); }
          30%  { opacity: 0.6; }
          78%  { opacity: 0.28; }
          100% { opacity: 0; transform: rotate(30deg) scale(1.2); }
        }
        @keyframes ym-headline {
          0%   { opacity: 0; transform: scale(0.62); letter-spacing: 0.34em; filter: blur(6px); }
          58%  { opacity: 1; transform: scale(1.07); letter-spacing: 0.05em; filter: blur(0); }
          100% { opacity: 1; transform: scale(1); letter-spacing: 0.07em; }
        }
        @keyframes ym-sub {
          0%   { opacity: 0; transform: translateY(12px); }
          100% { opacity: 1; transform: translateY(0); }
        }
        /* transform은 건드리지 않는다. 여기서 translateY를 쓰면 fill:both가
           자리 이동용 인라인 transform을 덮어써 순위표가 움직이지 않는다. */
        @keyframes ym-row {
          0%   { opacity: 0; }
          100% { opacity: 1; }
        }
      `}</style>

      <div
        style={{
          ...styles.veil,
          animation: `ym-veil ${d}ms ease-out forwards`,
        }}
      />
      <div
        style={{
          ...styles.glow,
          background: `radial-gradient(circle, ${look.glow} 0%, transparent 62%)`,
          animation: `ym-glow ${d}ms cubic-bezier(.2,.9,.3,1) forwards`,
        }}
      />
      {showRays && (
        <div
          style={{
            ...styles.rays,
            opacity: tier.rayOpacity,
            animation: `ym-rays ${d}ms ease-out forwards`,
          }}
        />
      )}

      <div
        style={{
          ...styles.stage,
          '--tier-scale': bodyScale,
          animation: `${kind === 'zero' ? 'ym-drop' : 'ym-rise'} ${d}ms `
            + 'cubic-bezier(.2,.9,.25,1.1) forwards',
        }}
      >
        <Content kind={kind} moment={moment} look={look} enterMs={enterMs} scale={bodyScale} />
      </div>
    </div>
  )
}

function Content({ kind, moment, look, enterMs, scale }) {
  if (kind === 'lead_change') return <LeadChange moment={moment} look={look} enterMs={enterMs} />
  if (kind === 'zero') return <ZeroScore look={look} enterMs={enterMs} />
  if (kind === 'bonus') return <UpperBonus moment={moment} look={look} enterMs={enterMs} />
  if (kind === 'hand') {
    return <HandAchieved moment={moment} look={look} enterMs={enterMs} scale={scale} />
  }
  return <ScoreConfirmed moment={moment} look={look} enterMs={enterMs} />
}

/**
 * 주사위가 멈춘 순간. 조합 이름만 크게 세운다.
 * 누가 몇 점인지는 아직 확정된 것이 아니라 붙이면 오히려 헷갈린다.
 */
function HandAchieved({ moment, look, enterMs, scale }) {
  const size = `clamp(${Math.round(40 * scale)}px, ${(11 * scale).toFixed(1)}vw,`
    + ` ${Math.round(112 * scale)}px)`
  return (
    <div style={{ ...headlineStyle(look, enterMs), fontSize: size }}>
      {moment.category_label}
    </div>
  )
}

/** 상단 보너스. 게임 내내 쌓아온 것이 한 번에 붙는 순간이다. */
function UpperBonus({ moment, look, enterMs }) {
  const shown = useCountUp(moment.score, enterMs * 2.2)
  return (
    <>
      <div
        style={{
          ...styles.sub,
          marginTop: 0,
          marginBottom: 10,
          animation: `ym-sub ${enterMs * 2}ms ease-out both`,
        }}
      >
        상단 합계 {moment.upper_subtotal} · 보너스 달성
      </div>
      <div style={{ ...headlineStyle(look, enterMs), fontSize: 'clamp(46px, 12vw, 108px)' }}>
        +{shown}
        <span style={styles.unit}>점</span>
      </div>
    </>
  )
}

/**
 * 칸을 고른 뒤. 상단 숫자든 족보든 똑같이 "+n점"이다.
 * 칸마다 반응이 다르면 플레이어는 규칙을 하나 더 외워야 한다.
 */
function ScoreConfirmed({ moment, look, enterMs }) {
  const shown = useCountUp(moment.score, enterMs * 2.2)
  return (
    <>
      <div style={{ ...headlineStyle(look, enterMs), fontSize: 'clamp(52px, 13vw, 120px)' }}>
        +{shown}
        <span style={styles.unit}>점</span>
      </div>
      <div
        style={{
          ...styles.sub,
          animation: `ym-sub ${enterMs * 2}ms ease-out ${enterMs}ms both`,
        }}
      >
        {moment.category_label} · {moment.scorer_name} 님
      </div>
    </>
  )
}

/**
 * 0점. 어떤 칸을 버렸는지는 굳이 알리지 않는다 — 이미 본인이 고른 것이고,
 * "풀하우스 0점"은 실패를 두 번 말하는 셈이다.
 */
function ZeroScore({ look, enterMs }) {
  return (
    <>
      <div
        style={{
          ...styles.sub,
          marginBottom: 10,
          animation: `ym-sub ${enterMs * 2}ms ease-out both`,
        }}
      >
        점수를 넣을 칸이 없었어요
      </div>
      <div style={{ ...headlineStyle(look, enterMs), fontSize: 'clamp(44px, 11vw, 96px)' }}>
        +0<span style={styles.unit}>점</span>
      </div>
    </>
  )
}

/**
 * 역전. 순위표가 실제로 자리를 바꾸며 올라가는 것이 이 순간의 내용이다.
 * 3등에서 2등도 역전이므로 1등만 특별 취급하지 않는다.
 */
const ROW_HEIGHT = 46

function LeadChange({ moment, look, enterMs }) {
  const standings = Array.isArray(moment.standings) ? moment.standings : []
  // DOM 순서는 고정하고 자리만 옮긴다. 목록 자체를 다시 정렬하면 React가 노드를
  // 갈아끼워 애니메이션이 끊긴다.
  const rows = [...standings].sort((a, b) => a.rank_before - b.rank_before)
  const [settled, setSettled] = useState(false)

  useEffect(() => {
    // 이전 순위를 한 박자 보여준 뒤 미끄러진다. 곧바로 정렬해버리면 무엇이
    // 바뀌었는지 눈으로 따라갈 수 없다.
    const timer = setTimeout(() => setSettled(true), enterMs * 1.7)
    return () => clearTimeout(timer)
  }, [moment, enterMs])

  const slotOf = (row) => (settled ? row.rank_after : row.rank_before) - 1

  return (
    <>
      <div style={{ ...headlineStyle(look, enterMs), fontSize: 'clamp(38px, 9vw, 78px)' }}>
        역전
      </div>
      <div style={{ ...styles.standings, height: rows.length * ROW_HEIGHT }}>
        {rows.map((row, domIndex) => {
          const moved = row.rank_after !== row.rank_before
          const isScorer = row.player_id === moment.scorer_id
          const climbed = row.rank_after < row.rank_before
          return (
            <div
              key={row.player_id}
              style={{
                ...styles.standingRow,
                top: domIndex * ROW_HEIGHT,
                transform: `translateY(${(slotOf(row) - domIndex) * ROW_HEIGHT}px)`,
                transition: 'transform 620ms cubic-bezier(.3,.9,.25,1.05), color 400ms ease',
                color: isScorer ? look.tint : 'var(--fg-soft)',
                fontWeight: isScorer ? 800 : 600,
                animation: `ym-row ${enterMs * 1.8}ms ease-out ${domIndex * 70}ms both`,
              }}
            >
              <span style={styles.standingRank}>{slotOf(row) + 1}</span>
              <span style={styles.standingName}>{row.playername}</span>
              <span style={styles.standingTotal}>{row.total}</span>
              <span
                style={{
                  ...styles.standingDelta,
                  color: climbed ? 'oklch(0.78 0.14 150)' : 'oklch(0.68 0.14 25)',
                  opacity: moved && settled ? 1 : 0,
                  transition: 'opacity 300ms ease',
                }}
              >
                {climbed ? '▲' : '▼'}
                {Math.abs(row.rank_after - row.rank_before)}
              </span>
            </div>
          )
        })}
      </div>
    </>
  )
}

function headlineStyle(look, enterMs) {
  return {
    ...styles.headline,
    color: look.tint,
    textShadow: `0 0 46px color-mix(in oklch, ${look.glow} 62%, transparent),`
      + ' 0 3px 18px rgba(0,0,0,0.55)',
    animation: `ym-headline ${enterMs * 2.6}ms cubic-bezier(.2,.9,.25,1.2) both`,
  }
}

function useCountUp(target, durationMs) {
  const [value, setValue] = useState(0)
  const frameRef = useRef(0)

  useEffect(() => {
    if (!target) {
      setValue(target ?? 0)
      return undefined
    }
    const start = performance.now()
    const tick = (now) => {
      const t = Math.min(1, (now - start) / durationMs)
      setValue(Math.round(target * (1 - (1 - t) ** 3)))
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
    pointerEvents: 'none',
  },
  // 상자 대신 화면 전체를 살짝 눌러 글자가 읽히게만 한다.
  veil: {
    position: 'absolute',
    inset: 0,
    background:
      'radial-gradient(ellipse at center, rgba(0,0,0,0.62) 0%, rgba(0,0,0,0.34) 55%,'
      + ' rgba(0,0,0,0.12) 100%)',
  },
  glow: {
    position: 'absolute',
    width: 'min(170vw, 1200px)',
    height: 'min(170vw, 1200px)',
    borderRadius: '50%',
    filter: 'blur(40px)',
  },
  rays: {
    position: 'absolute',
    width: 'min(160vw, 1100px)',
    height: 'min(160vw, 1100px)',
    background:
      'repeating-conic-gradient(from 0deg, oklch(0.92 0.16 85 / 0.55) 0deg 4deg,'
      + ' transparent 4deg 15deg)',
    maskImage: 'radial-gradient(circle, transparent 8%, #000 22%, transparent 60%)',
    WebkitMaskImage: 'radial-gradient(circle, transparent 8%, #000 22%, transparent 60%)',
  },
  stage: {
    position: 'relative',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    padding: '0 24px',
    textAlign: 'center',
  },
  headline: { fontWeight: 900, lineHeight: 1, whiteSpace: 'nowrap' },
  unit: { fontSize: '0.36em', fontWeight: 800, marginLeft: 6, opacity: 0.75 },
  sub: {
    marginTop: 14,
    fontSize: 'clamp(16px, 2.6vw, 22px)',
    fontWeight: 600,
    color: 'var(--fg-soft)',
    textShadow: '0 2px 12px rgba(0,0,0,0.6)',
  },
  standings: {
    position: 'relative',
    marginTop: 22,
    width: 'min(82vw, 360px)',
  },
  standingRow: {
    position: 'absolute',
    left: 0,
    right: 0,
    height: ROW_HEIGHT,
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '0 4px',
    fontSize: 'clamp(17px, 3vw, 23px)',
    textShadow: '0 2px 12px rgba(0,0,0,0.6)',
  },
  standingRank: {
    width: 26,
    textAlign: 'right',
    fontFamily: 'var(--font-mono)',
    opacity: 0.7,
  },
  standingName: { flex: 1, textAlign: 'left' },
  standingTotal: { fontFamily: 'var(--font-mono)', fontWeight: 700 },
  standingDelta: {
    width: 34,
    fontSize: '0.72em',
    fontWeight: 800,
    color: 'oklch(0.80 0.14 230)',
  },
}
