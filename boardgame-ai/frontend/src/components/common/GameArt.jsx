// Decorative game art (SVG/CSS only). No copyrighted assets.

export function YachtDiceArt() {
  const PIP = {
    1: [[50, 50]],
    2: [[28, 28], [72, 72]],
    3: [[26, 26], [50, 50], [74, 74]],
    4: [[28, 28], [72, 28], [28, 72], [72, 72]],
    5: [[26, 26], [74, 26], [50, 50], [26, 74], [74, 74]],
  }

  const DICE = [
    { x:  18, y:  64, s: 70, r: -14, n: 1 },
    { x:  88, y:  30, s: 78, r:   6, n: 2 },
    { x: 168, y:  76, s: 84, r:  -3, n: 3 },
    { x: 250, y:  22, s: 80, r:  12, n: 4 },
    { x: 312, y:  72, s: 90, r:  -6, n: 5 },
  ]

  return (
    <div className="game-art game-art-yacht">
      <div className="ya-sky" />
      <div className="ya-grain" />
      <div className="ya-felt" />
      <svg className="ya-dice" viewBox="0 0 400 220" preserveAspectRatio="xMidYMid meet" aria-hidden>
        <defs>
          <linearGradient id="dieFaceA" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#fff4dd" />
            <stop offset="1" stopColor="#e6b888" />
          </linearGradient>
          <linearGradient id="dieFaceB" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#fbeed4" />
            <stop offset="1" stopColor="#d9a978" />
          </linearGradient>
          <filter id="dieShadow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="3" />
          </filter>
        </defs>

        {DICE.map((d, i) => {
          const fill = i % 2 ? 'url(#dieFaceA)' : 'url(#dieFaceB)'
          const s = d.s
          const pips = PIP[d.n]
          const useCenter = pips.find(([x, y]) => x === 50 && y === 50)
          return (
            <g key={i} transform={`translate(${d.x} ${d.y}) rotate(${d.r} ${s/2} ${s/2})`}>
              <rect x={3} y={6} width={s} height={s} rx={s * 0.18}
                    fill="rgba(0,0,0,0.45)" filter="url(#dieShadow)" />
              <rect width={s} height={s} rx={s * 0.18}
                    fill={fill} stroke="rgba(0,0,0,0.35)" strokeWidth="1.2" />
              <path d={`M ${s*0.12} ${s*0.06} Q ${s*0.06} ${s*0.10} ${s*0.06} ${s*0.40} L ${s*0.10} ${s*0.36} Q ${s*0.10} ${s*0.16} ${s*0.18} ${s*0.10} Z`}
                    fill="rgba(255,255,255,0.45)" />
              {pips.map(([px, py], k) => {
                const cx = px / 100 * s
                const cy = py / 100 * s
                const isCenter = useCenter && px === 50 && py === 50
                const isAccent = i === DICE.length - 1 && isCenter
                return (
                  <circle key={k} cx={cx} cy={cy} r={s * 0.082}
                    fill={isAccent ? 'oklch(0.65 0.20 30)' : '#2a1a0c'} />
                )
              })}
            </g>
          )
        })}
      </svg>
      <style>{`
        .game-art-yacht {
          position: relative; width: 100%; height: 100%;
          overflow: hidden;
          background:
            radial-gradient(ellipse at 70% 20%, oklch(0.78 0.13 65) 0%, transparent 55%),
            radial-gradient(ellipse at 20% 80%, oklch(0.42 0.09 35) 0%, transparent 60%),
            linear-gradient(140deg, oklch(0.40 0.09 40), oklch(0.26 0.06 30));
        }
        .game-art-yacht .ya-sky {
          position: absolute; inset: 0;
          background: radial-gradient(ellipse at 75% 0%, rgba(255,220,170,0.35), transparent 55%);
        }
        .game-art-yacht .ya-felt {
          position: absolute; inset: auto 0 0 0; height: 30%;
          background: linear-gradient(180deg, transparent, rgba(40,20,10,0.55));
        }
        .game-art-yacht .ya-grain {
          position: absolute; inset: 0; opacity: 0.16;
          background-image:
            radial-gradient(circle at 30% 30%, rgba(255,255,255,0.4) 0.5px, transparent 1px),
            radial-gradient(circle at 70% 65%, rgba(255,255,255,0.3) 0.5px, transparent 1px);
          background-size: 3px 3px, 4px 4px;
        }
        .game-art-yacht .ya-dice {
          position: absolute; inset: 0;
          width: 100%; height: 100%;
          filter: drop-shadow(0 10px 22px rgba(0,0,0,0.4));
        }
      `}</style>
    </div>
  )
}

export function WerewolfArt() {
  return (
    <div className="game-art game-art-wolf">
      <div className="wa-sky" />
      <div className="wa-stars" />
      <div className="wa-moon" />
      <svg className="wa-back" viewBox="0 0 400 220" preserveAspectRatio="none" aria-hidden>
        <path d="M0 220 L0 150 Q 30 130 60 140 T 120 130 T 200 145 T 280 125 T 360 138 T 400 130 L 400 220 Z"
              fill="#0c0f1e" />
      </svg>
      <svg className="wa-mid" viewBox="0 0 400 220" preserveAspectRatio="none" aria-hidden>
        <path d="M0 220 L0 175 Q 25 165 50 170 L 90 158 L 130 175 L 170 165 L 210 178 L 250 168 L 290 180 L 330 170 L 370 182 L 400 175 L 400 220 Z"
              fill="#080a14" />
      </svg>
      <svg className="wa-front" viewBox="0 0 400 220" preserveAspectRatio="xMidYMax meet" aria-hidden>
        <defs>
          <linearGradient id="ridgeGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#040506" />
            <stop offset="1" stopColor="#020203" />
          </linearGradient>
        </defs>
        <path d="M 0 220 L 0 198 Q 100 195 200 198 Q 290 200 400 196 L 400 220 Z"
              fill="url(#ridgeGrad)" />
        <g transform="translate(260 128)" fill="#020203">
          <path d="M 5 70 L 3 50 Q 4 45 8 45 L 11 45 L 12 70 Z" />
          <path d="M 16 70 L 15 50 Q 16 46 20 46 L 23 46 L 23 70 Z" />
          <path d="M 4 48 Q -4 42 -6 30 Q -7 18 0 12 Q 4 8 8 8 Q 6 14 4 22 Q 2 32 6 42 Q 7 46 8 48 Z" />
          <path d="M 2 50 Q 0 38 6 32 Q 10 28 16 28 L 28 28 Q 38 28 46 32 L 52 36 Q 56 38 56 44 L 56 50 Q 40 54 22 54 Q 8 54 2 50 Z" />
          <path d="M 46 70 L 45 50 L 50 50 L 51 70 Z" />
          <path d="M 54 70 L 53 50 L 58 50 L 58 70 Z" />
          <path d="M 48 36 L 54 28 Q 58 22 60 18 L 62 18 L 62 36 Q 58 38 52 38 Z" />
          <path d="M 58 22 Q 62 10 68 4 L 76 0 L 80 4 L 76 8 L 70 12 Q 66 18 64 22 Z" />
          <path d="M 62 8 L 60 0 L 66 4 Z" />
        </g>
      </svg>
      <div className="wa-fog" />
      <style>{`
        .game-art-wolf {
          position: relative; width: 100%; height: 100%;
          overflow: hidden;
          background:
            radial-gradient(ellipse at 70% 22%, oklch(0.46 0.08 260) 0%, transparent 55%),
            linear-gradient(180deg, oklch(0.20 0.04 270) 0%, oklch(0.11 0.03 265) 65%, oklch(0.06 0.02 260) 100%);
        }
        .game-art-wolf .wa-sky {
          position: absolute; inset: 0;
          background: radial-gradient(ellipse at 22% 25%, oklch(0.62 0.10 255 / 0.30), transparent 50%);
        }
        .game-art-wolf .wa-stars {
          position: absolute; inset: 0 0 50% 0;
          background-image:
            radial-gradient(circle at 8% 18%, white 0.6px, transparent 1.2px),
            radial-gradient(circle at 18% 8%, white 0.7px, transparent 1.4px),
            radial-gradient(circle at 32% 14%, white 0.5px, transparent 1px),
            radial-gradient(circle at 48% 22%, white 0.6px, transparent 1.2px),
            radial-gradient(circle at 62% 12%, white 0.5px, transparent 1px),
            radial-gradient(circle at 28% 30%, white 0.4px, transparent 0.8px),
            radial-gradient(circle at 82% 32%, white 0.4px, transparent 0.8px),
            radial-gradient(circle at 12% 38%, white 0.3px, transparent 0.7px),
            radial-gradient(circle at 56% 36%, white 0.4px, transparent 0.8px);
          opacity: 0.85;
        }
        .game-art-wolf .wa-moon {
          position: absolute; top: 14%; left: 18%;
          width: 30%; aspect-ratio: 1;
          border-radius: 50%;
          background: radial-gradient(circle at 35% 35%, oklch(0.95 0.04 90) 0%, oklch(0.86 0.06 80) 50%, oklch(0.72 0.10 70) 95%);
          box-shadow:
            0 0 50px oklch(0.85 0.10 80 / 0.45),
            0 0 110px oklch(0.75 0.12 75 / 0.35);
        }
        .game-art-wolf .wa-moon::after {
          content: "";
          position: absolute;
          width: 18%; height: 18%;
          background: oklch(0.74 0.07 75);
          border-radius: 50%;
          top: 28%; left: 32%;
          opacity: 0.35;
          filter: blur(2px);
        }
        .game-art-wolf .wa-fog {
          position: absolute; inset: auto 0 0 0; height: 28%;
          background: linear-gradient(180deg, transparent, oklch(0.08 0.02 260 / 0.7));
          pointer-events: none;
        }
        .game-art-wolf .wa-back,
        .game-art-wolf .wa-mid,
        .game-art-wolf .wa-front {
          position: absolute; left: 0; right: 0; bottom: 0;
          width: 100%; height: 100%;
        }
        .game-art-wolf .wa-front { filter: drop-shadow(0 -4px 10px rgba(0,0,0,0.6)); }
      `}</style>
    </div>
  )
}


/**
 * 컨트롤 카드 아트.
 *
 * 게임 둘은 그 게임의 물건(주사위·달)을 그린다. 컨트롤에는 물건이 없고 다루는
 * 대상이 빛 자체라, **색이 번지는 빛무리**를 그린다. CSS 그라디언트만 쓰므로
 * 무게가 거의 없다.
 */
export function ControlArt() {
  const ORBS = [
    { x: 22, y: 46, s: 132, c: '#ff5a7a' },
    { x: 44, y: 30, s: 116, c: '#ffb43c' },
    { x: 62, y: 58, s: 148, c: '#3ec8ff' },
    { x: 80, y: 36, s: 120, c: '#a97cff' },
  ]
  return (
    <div className="game-art game-art-control">
      {ORBS.map((o, i) => (
        <span
          key={i}
          className="ca-orb"
          style={{
            left: `${o.x}%`,
            top: `${o.y}%`,
            width: o.s,
            height: o.s,
            background: `radial-gradient(circle, ${o.c} 0%, transparent 68%)`,
            animationDelay: `${i * 900}ms`,
          }}
        />
      ))}
      <div className="ca-veil" />
      <style>{`
        .game-art-control {
          position: absolute; inset: 0;
          background: #0d1016;
          overflow: hidden;
        }
        .ca-orb {
          position: absolute;
          transform: translate(-50%, -50%);
          border-radius: 50%;
          filter: blur(6px);
          opacity: 0.75;
          animation: ca-breathe 5200ms ease-in-out infinite;
        }
        @keyframes ca-breathe {
          0%, 100% { transform: translate(-50%, -50%) scale(0.92); opacity: 0.55; }
          50%      { transform: translate(-50%, -50%) scale(1.1);  opacity: 0.85; }
        }
        /* 색이 너무 날것이면 카드 글자가 안 읽힌다. 아주 옅은 검정을 덮는다. */
        .ca-veil {
          position: absolute; inset: 0;
          background: linear-gradient(180deg, rgba(8,10,14,0.16), rgba(8,10,14,0.52));
        }
        @media (prefers-reduced-motion: reduce) {
          .ca-orb { animation: none; }
        }
      `}</style>
    </div>
  )
}
