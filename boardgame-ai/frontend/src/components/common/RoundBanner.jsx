import { useEffect, useRef, useState } from 'react'

/**
 * 라운드 시작 안내.
 *
 * 한 판에 12번 뜨므로 화면을 잡아서는 안 된다. 위쪽에 짧게 스쳐 지나가고,
 * 가운데를 쓰는 득점 모달과 자리가 겹치지 않는다.
 *
 * 라운드는 "현재 플레이어가 몇 칸을 채웠는가"로 정해진다. 그 값이 올라가는
 * 순간이 곧 새 라운드의 시작이다.
 */

const VISIBLE_MS = 1700

export default function RoundBanner({ round, total }) {
  const [shown, setShown] = useState(null)
  const previousRef = useRef(null)

  useEffect(() => {
    if (!round) return undefined
    const previous = previousRef.current
    previousRef.current = round
    // 첫 진입(previous === null)에도 알린다 — 1라운드 시작도 라운드 시작이다.
    // 되돌아가는 경우는 알리지 않는다 (되돌리기로 라운드가 줄 수 있다).
    if (previous !== null && round <= previous) return undefined

    setShown(round)
    const timer = setTimeout(() => setShown(null), VISIBLE_MS)
    return () => clearTimeout(timer)
  }, [round])

  if (!shown) return null

  return (
    <div style={styles.wrap} key={shown}>
      <style>{`
        @keyframes rb-in {
          0%   { opacity: 0; transform: translateY(-22px) scale(0.94); }
          16%  { opacity: 1; transform: translateY(0) scale(1); }
          80%  { opacity: 1; transform: translateY(0) scale(1); }
          100% { opacity: 0; transform: translateY(-12px) scale(0.98); }
        }
        @keyframes rb-sweep {
          0%   { transform: translateX(-120%); }
          55%  { transform: translateX(120%); }
          100% { transform: translateX(120%); }
        }
      `}</style>
      <div style={{ ...styles.pill, animation: `rb-in ${VISIBLE_MS}ms ease-out forwards` }}>
        <span style={styles.sweep} />
        <span style={styles.label}>ROUND</span>
        <span style={styles.number}>{shown}</span>
        <span style={styles.total}>/ {total}</span>
      </div>
    </div>
  )
}

const styles = {
  wrap: {
    position: 'fixed',
    top: 'max(14px, env(safe-area-inset-top))',
    left: 0,
    right: 0,
    display: 'flex',
    justifyContent: 'center',
    zIndex: 9997,
    pointerEvents: 'none',
  },
  pill: {
    position: 'relative',
    overflow: 'hidden',
    display: 'flex',
    alignItems: 'baseline',
    gap: 10,
    padding: '9px 22px',
    borderRadius: 999,
    background: 'color-mix(in oklch, var(--bg-deep) 78%, transparent)',
    boxShadow: '0 8px 30px rgba(0,0,0,0.42)',
    backdropFilter: 'blur(8px)',
  },
  // 알약 위를 한 번 훑고 지나가는 빛. 정적인 칩보다 시작하는 느낌이 난다.
  sweep: {
    position: 'absolute',
    inset: 0,
    background:
      'linear-gradient(105deg, transparent 30%, color-mix(in oklch, var(--yacht) 34%,'
      + ' transparent) 50%, transparent 70%)',
    animation: `rb-sweep ${VISIBLE_MS}ms ease-out forwards`,
  },
  label: {
    fontFamily: 'var(--font-mono)',
    fontSize: 12,
    fontWeight: 700,
    letterSpacing: '0.22em',
    color: 'var(--fg-mute)',
  },
  number: {
    fontSize: 26,
    fontWeight: 900,
    lineHeight: 1,
    color: 'var(--yacht)',
  },
  total: { fontSize: 14, fontWeight: 600, color: 'var(--fg-faint)' },
}
