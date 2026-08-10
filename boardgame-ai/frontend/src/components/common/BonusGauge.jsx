import { useEffect, useRef, useState } from 'react'

/**
 * 상단 보너스 진행 막대.
 *
 * 숫자만 있을 때는 "24 / 63"이 얼마나 온 것인지 매번 계산해야 했다. 막대는
 * 그 계산을 눈이 대신 해준다. 상단 칸에 점수를 넣을 때마다 그만큼 차오르므로,
 * 무심코 고른 칸이 보너스에 얼마나 보탬이 됐는지가 바로 보인다.
 *
 * 색은 금색이 아니라 청록을 쓴다. 점수판에서 금색은 "지금 누를 만한 칸" 하나에만
 * 쓰기로 했고, 여기까지 금색이면 요약 정보와 선택지가 같은 색이 되어 프레임과
 * 점수 영역이 갈리지 않는다. 다만 **다 채운 순간에는 금색으로 넘어간다** —
 * 그때는 정보가 아니라 사건이기 때문이다.
 */

export default function BonusGauge({ subtotal, threshold, height = 7 }) {
  const ratio = Math.max(0, Math.min(1, subtotal / threshold))
  const earned = subtotal >= threshold

  // 달성으로 넘어가는 순간에만 한 번 번쩍인다. 이미 달성된 상태로 다시 그려질
  // 때(리렌더·리더보드 열기)는 조용해야 한다.
  const [justEarned, setJustEarned] = useState(false)
  const wasEarnedRef = useRef(earned)
  useEffect(() => {
    const was = wasEarnedRef.current
    wasEarnedRef.current = earned
    if (was || !earned) return undefined
    setJustEarned(true)
    const timer = setTimeout(() => setJustEarned(false), 1200)
    return () => clearTimeout(timer)
  }, [earned])

  return (
    <div
      style={{ ...styles.track, height }}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={threshold}
      aria-valuenow={Math.min(subtotal, threshold)}
      aria-label="상단 보너스 진행도"
    >
      <style>{`
        @keyframes bg-earned {
          0%   { box-shadow: 0 0 0 0 color-mix(in oklch, var(--y-gold) 60%, transparent); }
          40%  { box-shadow: 0 0 14px 3px color-mix(in oklch, var(--y-gold) 55%, transparent); }
          100% { box-shadow: 0 0 0 0 transparent; }
        }
        /* 다 찬 막대 위를 빛이 한 번 훑는다. 채워지는 것과 다 찬 것은 다른 사건이다. */
        @keyframes bg-sweep {
          0%   { transform: translateX(-110%); }
          100% { transform: translateX(210%); }
        }
      `}</style>

      <div
        className={justEarned ? 'bonus-gauge-earned' : undefined}
        style={{
          ...styles.fill,
          width: `${ratio * 100}%`,
          background: earned
            ? 'linear-gradient(90deg, var(--y-gold-deep), var(--y-gold))'
            : 'linear-gradient(90deg, color-mix(in oklch, var(--y-pick) 70%, transparent),'
              + ' var(--y-pick))',
          animation: justEarned ? 'bg-earned 1100ms ease-out' : undefined,
        }}
      >
        {justEarned && <span style={styles.sweep} />}
      </div>
    </div>
  )
}

const styles = {
  track: {
    position: 'relative',
    width: '100%',
    borderRadius: 999,
    background: 'oklch(0.20 0.008 78)',
    overflow: 'hidden',
    boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.4)',
  },
  fill: {
    position: 'relative',
    height: '100%',
    borderRadius: 999,
    overflow: 'hidden',
    // 점수가 들어간 만큼 차오르는 데 걸리는 시간. 득점 연출(1.6초 안팎)보다
    // 짧아야 모달이 닫히기 전에 막대가 멈춰 있는다.
    transition: 'width 720ms cubic-bezier(.2,.8,.25,1), background 420ms ease',
  },
  sweep: {
    position: 'absolute',
    inset: 0,
    background:
      'linear-gradient(100deg, transparent 20%, rgba(255,255,255,0.55) 50%, transparent 80%)',
    animation: 'bg-sweep 900ms ease-out',
  },
}
