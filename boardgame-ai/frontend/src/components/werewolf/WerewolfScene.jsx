import { useMemo } from 'react'
import { WW_UI_CSS } from './wwUi'

/**
 * 늑대인간 화면의 배경 무대.
 *
 * 예전에는 하늘·달·별·마을 실루엣·안개가 여섯 개 화면에 통째로 복사돼 있었다.
 * 같은 그림이 여섯 벌이니 한 곳을 고쳐도 나머지가 따라오지 않았고, 페이즈가
 * 넘어갈 때 배경이 **다시 그려져** 화면이 툭툭 끊겼다. 여기로 모아 한 벌만 두고,
 * 페이즈는 mood만 바꾼다 — 하늘색과 공기만 갈리고 마을은 같은 자리에 남는다.
 *
 * 깊이는 층으로 만든다. 뒤에서부터
 *   하늘 → 성운/노을 → 별 → 달(또는 해) → 구름 → 마을 → 안개 3겹 → 입자 → 비네팅 → 그레인
 * 순으로 쌓고, 각 층이 서로 다른 속도로 흐르게 해 시차(parallax)를 만든다.
 * 요트의 펠트 테이블처럼 "화면이 하나의 장소"로 보이게 하는 것이 목적이다.
 *
 * 쓰는 쪽은 페이지 루트에 className="ww-root"를 달고 이 컴포넌트를 맨 위에 둔다.
 * 팔레트 변수(--w-*)가 ww-root에 걸리므로 콘텐츠도 같은 색을 쓸 수 있다.
 */

// 정지 그레인. feTurbulence를 한 번만 래스터화해 쓰므로 애니메이션 비용이 없다.
// 매끈한 그라디언트에 아주 옅은 노이즈를 얹으면 색 띠(banding)가 사라지고
// 화면이 '인쇄물'처럼 보인다 — 올드한 느낌의 절반은 이 띠에서 온다.
const NOISE_URL =
  "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'>"
  + "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='3' stitchTiles='stitch'/>"
  + "<feColorMatrix type='saturate' values='0'/></filter>"
  + "<rect width='180' height='180' filter='url(%23n)' opacity='0.55'/></svg>\")"

/** 무드별 공기. 하늘 그라디언트와 그 위에 얹는 빛만 다르다. */
const MOODS = {
  // 밤 — 깊은 남보라. 달빛이 오른쪽 위에서 들어온다.
  night: {
    sky: 'linear-gradient(172deg, #0b0a24 0%, #0d1030 26%, #10122c 52%, #0a0f1e 78%, #05080f 100%)',
    aura: [
      'radial-gradient(ellipse 46% 38% at 74% 6%, rgba(196,166,88,0.20), transparent 70%)',
      'radial-gradient(ellipse 60% 46% at 14% 84%, rgba(88,38,140,0.30), transparent 72%)',
      'radial-gradient(ellipse 90% 40% at 50% 100%, rgba(24,44,74,0.55), transparent 76%)',
    ].join(', '),
    stars: 0.95,
    moon: 'moon',
    village: { body: '#05030d', roof: '#070512', window: 'rgba(255,196,92,0.85)' },
    fog: ['rgba(74,44,116,0.40)', 'rgba(44,30,80,0.30)', 'rgba(26,22,52,0.34)'],
    vignette: 'rgba(2,2,8,0.72)',
    particles: null,
  },
  // 준비 화면 — 밤보다 한 톤 밝고 푸르다. 카드 그림이 묻히면 안 되는 자리다.
  dusk: {
    sky: 'linear-gradient(168deg, #16223a 0%, #101a2e 34%, #0b1220 66%, #070b12 100%)',
    aura: [
      'radial-gradient(ellipse 44% 40% at 80% 4%, rgba(214,178,92,0.18), transparent 70%)',
      'radial-gradient(ellipse 70% 50% at 8% 92%, rgba(52,74,120,0.34), transparent 74%)',
    ].join(', '),
    stars: 0.6,
    moon: 'moon',
    village: { body: '#060a12', roof: '#080d17', window: 'rgba(255,196,92,0.7)' },
    fog: ['rgba(60,84,128,0.26)', 'rgba(34,52,84,0.24)', 'rgba(18,28,46,0.30)'],
    vignette: 'rgba(3,5,10,0.66)',
    particles: null,
  },
  // 여명 — 밤이 아래에서부터 타오른다.
  dawn: {
    sky: 'linear-gradient(180deg, #0b0a24 0%, #1c0f3a 20%, #4a1a34 44%, #93401c 66%, #d4761c 84%, #f2ad3c 100%)',
    aura: [
      'radial-gradient(ellipse 80% 46% at 50% 104%, rgba(255,176,60,0.55), transparent 72%)',
      'radial-gradient(ellipse 46% 30% at 50% 82%, rgba(255,224,150,0.30), transparent 70%)',
    ].join(', '),
    stars: 0.28,
    moon: null,
    village: { body: '#100616', roof: '#12081a', window: 'rgba(255,214,140,0.55)' },
    fog: ['rgba(255,168,80,0.20)', 'rgba(180,90,50,0.22)', 'rgba(60,24,30,0.34)'],
    vignette: 'rgba(20,6,4,0.60)',
    particles: 'mote',
  },
  // 낮(토론) — 늦은 오후의 마른 빛. 먼지가 떠다닌다.
  day: {
    sky: 'linear-gradient(180deg, #241205 0%, #4a2109 22%, #8c4413 46%, #c4741a 68%, #e0a324 86%, #f0c246 100%)',
    aura: [
      'radial-gradient(ellipse 62% 44% at 50% 8%, rgba(255,206,110,0.22), transparent 70%)',
      'radial-gradient(ellipse 96% 40% at 50% 100%, rgba(255,168,50,0.30), transparent 74%)',
    ].join(', '),
    stars: 0,
    moon: null,
    village: { body: '#1d0a02', roof: '#210d03', window: 'rgba(255,226,150,0.42)' },
    fog: ['rgba(255,190,100,0.18)', 'rgba(220,130,50,0.18)', 'rgba(90,36,10,0.28)'],
    vignette: 'rgba(28,10,2,0.55)',
    particles: 'mote',
  },
  // 투표·심판 — 피의 하늘. 불티가 올라오고 화면이 낮게 맥동한다.
  blood: {
    sky: 'linear-gradient(180deg, #080002 0%, #1a0304 22%, #3d0a08 44%, #78180b 64%, #ab2c10 82%, #c43c12 100%)',
    aura: [
      'radial-gradient(ellipse 70% 50% at 50% 96%, rgba(255,96,32,0.34), transparent 72%)',
      'radial-gradient(ellipse 54% 40% at 50% 30%, rgba(160,20,10,0.28), transparent 72%)',
    ].join(', '),
    stars: 0,
    moon: null,
    village: { body: '#0d0301', roof: '#100401', window: 'rgba(255,140,70,0.5)' },
    fog: ['rgba(180,50,20,0.24)', 'rgba(120,26,12,0.26)', 'rgba(46,8,4,0.36)'],
    vignette: 'rgba(14,0,0,0.74)',
    particles: 'ember',
  },
}

/** 시드 고정 난수. 리렌더마다 별이 자리를 옮기면 배경이 아니라 잡음이 된다. */
function mulberry32(seed) {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function useStars(count) {
  return useMemo(() => {
    const rand = mulberry32(20260813)
    return Array.from({ length: count }, () => {
      const size = 0.8 + rand() * 1.9
      return {
        top: (rand() * 62).toFixed(2) + '%',
        left: (rand() * 100).toFixed(2) + '%',
        size,
        // 큰 별일수록 느리게 깜빡인다. 전부 같은 주기면 화면이 함께 뛴다.
        dur: (2.4 + rand() * 4.5).toFixed(2),
        delay: (rand() * 6).toFixed(2),
        // 위쪽 별이 더 밝다 — 아래는 마을 불빛에 씻긴다.
        base: 0.35 + rand() * 0.55,
      }
    })
  }, [count])
}

function useParticles(kind) {
  return useMemo(() => {
    if (!kind) return []
    const rand = mulberry32(kind === 'ember' ? 77321 : 44119)
    const count = kind === 'ember' ? 18 : 14
    return Array.from({ length: count }, () => ({
      left: (rand() * 100).toFixed(2) + '%',
      size: kind === 'ember' ? 1.6 + rand() * 2.6 : 1.4 + rand() * 2.2,
      dur: (kind === 'ember' ? 7 + rand() * 7 : 14 + rand() * 12).toFixed(2),
      delay: (rand() * 12).toFixed(2),
      drift: (rand() * 80 - 40).toFixed(0) + 'px',
    }))
  }, [kind])
}

export default function WerewolfScene({ mood = 'night' }) {
  const m = MOODS[mood] ?? MOODS.night
  const stars = useStars(m.stars > 0 ? 76 : 0)
  const particles = useParticles(m.particles)

  return (
    <div className="ww-scene" aria-hidden="true">
      {/* 팔레트·부품·무대를 한 번에 주입한다. 화면은 한 번에 하나만 떠 있으므로
          여기 한 곳에서 내보내면 각 화면이 style 태그를 따로 들 이유가 없다. */}
      <style>{WW_CSS + WW_UI_CSS + SCENE_CSS}</style>

      <div className="ww-sky" style={{ background: m.sky }} />
      <div className="ww-aura" style={{ background: m.aura }} />

      {m.stars > 0 && (
        <div className="ww-stars" style={{ opacity: m.stars }}>
          {stars.map((s, i) => (
            <span
              key={i}
              style={{
                top: s.top,
                left: s.left,
                width: s.size,
                height: s.size,
                '--base': s.base,
                animationDuration: `${s.dur}s`,
                animationDelay: `${s.delay}s`,
              }}
            />
          ))}
          {/* 유성. 아주 가끔 지나가야 '가끔'으로 읽힌다. */}
          <i className="ww-shoot" />
          <i className="ww-shoot ww-shoot-2" />
        </div>
      )}

      {m.moon === 'moon' && <Moon />}

      {/* 구름 띠 — 달 앞을 천천히 가로지르며 하늘에 움직임을 준다. */}
      <div className="ww-cloud ww-cloud-a" />
      <div className="ww-cloud ww-cloud-b" />

      <Village palette={m.village} />

      <div className="ww-fog ww-fog-a" style={{ '--tint': m.fog[0] }} />
      <div className="ww-fog ww-fog-b" style={{ '--tint': m.fog[1] }} />
      <div className="ww-fog ww-fog-c" style={{ '--tint': m.fog[2] }} />

      {particles.length > 0 && (
        <div className={`ww-particles ww-particles-${m.particles}`}>
          {particles.map((p, i) => (
            <span
              key={i}
              style={{
                left: p.left,
                width: p.size,
                height: p.size,
                '--drift': p.drift,
                animationDuration: `${p.dur}s`,
                animationDelay: `${p.delay}s`,
              }}
            />
          ))}
        </div>
      )}

      {mood === 'blood' && <div className="ww-pulse" />}

      <div
        className="ww-vignette"
        style={{ background: `radial-gradient(ellipse 78% 72% at 50% 44%, transparent 42%, ${m.vignette} 100%)` }}
      />
      <div className="ww-grain" />
    </div>
  )
}

/**
 * 달.
 *
 * 예전 달은 그냥 노란 원이었다. 원 하나는 아무리 빛나도 스티커로 보인다 —
 * 분화구(살짝 어두운 점 몇 개)와 바깥으로 번지는 두 겹 후광, 그리고 앞을
 * 지나가는 옅은 구름까지 있어야 하늘에 떠 있는 것으로 읽힌다.
 */
function Moon() {
  return (
    <div className="ww-moon">
      <div className="ww-moon-halo" />
      <div className="ww-moon-disc">
        <i style={{ top: '26%', left: '30%', width: 17, height: 17 }} />
        <i style={{ top: '52%', left: '20%', width: 11, height: 11 }} />
        <i style={{ top: '58%', left: '58%', width: 14, height: 14 }} />
        <i style={{ top: '20%', left: '62%', width: 8, height: 8 }} />
        <i style={{ top: '40%', left: '46%', width: 6, height: 6 }} />
      </div>
      <div className="ww-moon-veil" />
    </div>
  )
}

/**
 * 마을 실루엣.
 *
 * 여섯 화면이 같은 마을을 본다. 색만 무드에 맞춰 갈리고 형태는 고정이라,
 * 페이즈가 넘어가도 "같은 마을의 다른 시각"으로 이어진다.
 * 창문 몇 개에 불이 켜져 있고 저마다 다른 박자로 흔들린다 — 사람이 산다는 표시다.
 */
function Village({ palette }) {
  const { body, roof, window: win } = palette
  return (
    <svg
      className="ww-village"
      viewBox="0 0 800 190"
      preserveAspectRatio="xMidYMax slice"
    >
      {/* 뒷줄 — 한 톤 흐리게 깔아 원근을 만든다 */}
      <g opacity="0.55">
        <polygon points="90,190 116,104 142,190" fill={roof} />
        <polygon points="330,190 356,96 382,190" fill={roof} />
        <rect x="600" y="112" width="64" height="78" fill={roof} />
        <polygon points="594,114 632,84 670,114" fill={roof} />
        <polygon points="690,190 714,110 738,190" fill={roof} />
      </g>

      {/* 앞줄 */}
      <polygon points="40,190 62,118 84,190" fill={body} />
      <polygon points="58,190 84,92 110,190" fill={body} />
      <polygon points="95,190 118,124 141,190" fill={body} />

      <rect x="155" y="140" width="58" height="50" fill={body} />
      <polygon points="148,142 184,112 220,142" fill={body} />
      <rect x="166" y="152" width="12" height="14" fill={win} className="ww-win" style={{ animationDelay: '0s' }} />
      <rect x="190" y="152" width="12" height="14" fill={win} className="ww-win" style={{ animationDelay: '2.6s' }} />

      <rect x="245" y="104" width="32" height="86" fill={body} />
      <polygon points="238,106 261,76 284,106" fill={body} />
      <rect x="254" y="124" width="10" height="13" fill={win} className="ww-win" style={{ animationDelay: '1.4s' }} />

      <rect x="300" y="132" width="52" height="58" fill={body} />
      <polygon points="293,134 326,104 359,134" fill={body} />
      <rect x="312" y="146" width="13" height="15" fill={win} className="ww-win" style={{ animationDelay: '3.4s' }} />

      <polygon points="372,190 394,110 416,190" fill={body} />
      <polygon points="390,190 416,86 442,190" fill={body} />

      <rect x="455" y="142" width="46" height="48" fill={body} />
      <polygon points="448,144 478,118 508,144" fill={body} />
      <rect x="466" y="154" width="11" height="13" fill={win} className="ww-win" style={{ animationDelay: '0.8s' }} />

      {/* 마을 회관 — 종탑이 있는 큰 건물. 화면의 무게중심이다. */}
      <rect x="524" y="112" width="72" height="78" fill={body} />
      <polygon points="517,114 560,80 603,114" fill={body} />
      <rect x="552" y="86" width="16" height="28" fill={body} />
      <rect x="538" y="130" width="14" height="17" fill={win} className="ww-win" style={{ animationDelay: '1.9s' }} />
      <rect x="568" y="130" width="14" height="17" fill={win} className="ww-win" style={{ animationDelay: '4.2s' }} />

      <polygon points="618,190 638,120 658,190" fill={body} />
      <polygon points="646,190 670,100 694,190" fill={body} />

      <rect x="710" y="140" width="54" height="50" fill={body} />
      <polygon points="703,142 737,114 771,142" fill={body} />
      <rect x="722" y="152" width="12" height="15" fill={win} className="ww-win" style={{ animationDelay: '2.2s' }} />

      {/* 땅. 실루엣 아래를 완전히 눌러 화면 바닥을 닫는다. */}
      <rect x="0" y="186" width="800" height="6" fill={body} />
    </svg>
  )
}

/**
 * 늑대인간 화면 전용 팔레트 + 무대 스타일.
 *
 * 공용 테마(theme.css)는 회색 한 계열이라 밤도 낮도 같은 색이 된다. 요트가
 * .yacht-root 안에서 펠트 초록을 따로 쓰듯, 여기도 .ww-root 안에서만 쓴다.
 */
export const WW_CSS = `
  .ww-root {
    --w-ink:       #f5efe3;
    --w-ink-soft:  rgba(245,239,227,0.74);
    --w-ink-mute:  rgba(245,239,227,0.45);
    --w-ink-faint: rgba(245,239,227,0.26);

    --w-gold:      #f0cf7a;
    --w-gold-hi:   #fff0c0;
    --w-gold-deep: #a8761c;
    --w-blood:     #ff6a3c;
    --w-blood-deep:#a32209;

    --w-glass:      rgba(10,8,16,0.42);
    --w-glass-hi:   rgba(22,18,30,0.58);
    --w-line:       rgba(240,207,122,0.20);
    --w-line-strong:rgba(240,207,122,0.46);

    font-family: var(--font);
    color: var(--w-ink);
  }

  /* 제목 아래를 가로지르는 얇은 금선. 그 위를 빛이 한 번씩 훑고 지나간다 —
     정적인 구분선 하나만 있으면 화면이 멈춰 보인다. */
  .ww-rule {
    position: relative;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--w-line-strong), transparent);
    overflow: hidden;
  }
  .ww-rule > i {
    position: absolute;
    top: 0; left: 0;
    width: 34%; height: 100%;
    background: linear-gradient(90deg, transparent, var(--w-gold), transparent);
    animation: ww-sweep 4.2s ease-in-out infinite;
  }
  @keyframes ww-sweep {
    0%       { transform: translateX(-140%); opacity: 0; }
    18%, 60% { opacity: 1; }
    100%     { transform: translateX(420%); opacity: 0; }
  }

  /* 유리판. 밤 배경 위에 얹는 모든 상자가 이 한 겹을 공유한다 —
     상자마다 다른 투명도를 쓰면 층이 몇 겹인지 눈이 세기 시작한다. */
  .ww-panel {
    background: var(--w-glass);
    border: 1px solid var(--w-line);
    border-radius: 20px;
    -webkit-backdrop-filter: blur(14px) saturate(1.1);
    backdrop-filter: blur(14px) saturate(1.1);
    box-shadow:
      0 1px 0 rgba(255,255,255,0.06) inset,
      0 24px 60px rgba(0,0,0,0.45);
  }
`

const SCENE_CSS = `
  .ww-scene {
    position: absolute;
    inset: 0;
    overflow: hidden;
    pointer-events: none;
    z-index: 0;
  }
  .ww-scene > * { position: absolute; }

  .ww-sky   { inset: 0; }
  .ww-aura  { inset: 0; }

  /* ── 별 ─────────────────────────────────────────────────────────────── */
  .ww-stars { inset: 0; }
  .ww-stars > span {
    position: absolute;
    border-radius: 50%;
    background: #fff;
    opacity: var(--base);
    box-shadow: 0 0 4px rgba(255,255,255,0.8);
    animation-name: ww-twinkle;
    animation-timing-function: ease-in-out;
    animation-iteration-count: infinite;
  }
  @keyframes ww-twinkle {
    0%, 100% { opacity: calc(var(--base) * 0.28); transform: scale(0.85); }
    50%      { opacity: var(--base);              transform: scale(1); }
  }

  .ww-shoot {
    position: absolute;
    top: 12%; left: 78%;
    width: 130px; height: 1.5px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.95));
    filter: blur(0.4px);
    opacity: 0;
    transform: rotate(18deg);
    animation: ww-shoot 17s linear infinite;
  }
  .ww-shoot-2 { top: 26%; left: 46%; animation-duration: 23s; animation-delay: 9s; }
  @keyframes ww-shoot {
    0%, 92%  { opacity: 0; transform: translate(0,0) rotate(18deg) scaleX(0.2); }
    94%      { opacity: 0.9; }
    99%      { opacity: 0; transform: translate(-320px, 110px) rotate(18deg) scaleX(1); }
    100%     { opacity: 0; }
  }

  /* ── 달 ─────────────────────────────────────────────────────────────── */
  .ww-moon {
    top: 42px; right: 84px;
    width: 132px; height: 132px;
    animation: ww-moon-float 22s ease-in-out infinite;
  }
  @keyframes ww-moon-float {
    0%, 100% { transform: translateY(0); }
    50%      { transform: translateY(-10px); }
  }
  .ww-moon-halo {
    position: absolute;
    inset: -78px;
    border-radius: 50%;
    background:
      radial-gradient(circle, rgba(255,236,168,0.30) 0%, rgba(255,214,110,0.14) 34%, transparent 68%);
    animation: ww-halo 6.5s ease-in-out infinite;
  }
  @keyframes ww-halo {
    0%, 100% { opacity: 0.72; transform: scale(0.97); }
    50%      { opacity: 1;    transform: scale(1.06); }
  }
  .ww-moon-disc {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: radial-gradient(circle at 36% 32%, #fffdf0 0%, #f7e9ae 34%, #e2c46a 62%, #b8912f 92%);
    box-shadow:
      inset -14px -12px 30px rgba(96,66,10,0.42),
      0 0 44px 8px rgba(255,222,130,0.28);
    overflow: hidden;
  }
  .ww-moon-disc > i {
    position: absolute;
    border-radius: 50%;
    background: rgba(150,116,38,0.28);
    box-shadow: inset 1px 1px 2px rgba(90,68,16,0.35);
  }
  /* 달 앞을 지나는 옅은 구름. 원 하나를 하늘에 붙여놓은 느낌을 지운다. */
  .ww-moon-veil {
    position: absolute;
    inset: -30% -140% -30% -140%;
    background: linear-gradient(90deg, transparent 0%, rgba(24,22,44,0.62) 42%, rgba(24,22,44,0.5) 58%, transparent 100%);
    filter: blur(12px);
    animation: ww-veil 34s linear infinite;
  }
  @keyframes ww-veil {
    0%   { transform: translateX(-42%); opacity: 0; }
    18%  { opacity: 0.85; }
    52%  { opacity: 0.85; }
    72%  { opacity: 0; }
    100% { transform: translateX(42%); opacity: 0; }
  }

  /* ── 구름 띠 ────────────────────────────────────────────────────────── */
  .ww-cloud {
    border-radius: 50%;
    filter: blur(30px);
    opacity: 0.5;
  }
  .ww-cloud-a {
    top: 8%; left: -30%;
    width: 60%; height: 130px;
    background: radial-gradient(ellipse at center, rgba(40,36,74,0.85), transparent 70%);
    animation: ww-drift-r 96s linear infinite;
  }
  .ww-cloud-b {
    top: 24%; left: -40%;
    width: 46%; height: 96px;
    background: radial-gradient(ellipse at center, rgba(26,26,56,0.75), transparent 70%);
    animation: ww-drift-r 148s linear infinite;
    animation-delay: -40s;
  }
  @keyframes ww-drift-r {
    from { transform: translateX(0); }
    to   { transform: translateX(230%); }
  }

  /* ── 마을 ───────────────────────────────────────────────────────────── */
  .ww-village {
    bottom: 0; left: 0;
    width: 100%; height: 200px;
    filter: drop-shadow(0 -12px 26px rgba(0,0,0,0.5));
  }
  .ww-win {
    animation: ww-window 5.5s ease-in-out infinite;
  }
  @keyframes ww-window {
    0%, 100% { opacity: 0.9; }
    42%      { opacity: 0.35; }
    46%      { opacity: 0.85; }
    64%      { opacity: 0.5; }
  }

  /* ── 안개 ───────────────────────────────────────────────────────────── */
  /* 세 겹이 서로 다른 속도로 흐른다. 한 겹만 있으면 '흐르는 배경 이미지'로
     보이지만, 속도가 다른 겹이 겹치면 공기에 두께가 생긴다. */
  .ww-fog {
    left: -60%; width: 220%;
    background: radial-gradient(ellipse 30% 100% at 20% 100%, var(--tint), transparent 72%),
                radial-gradient(ellipse 26% 100% at 52% 100%, var(--tint), transparent 70%),
                radial-gradient(ellipse 34% 100% at 82% 100%, var(--tint), transparent 74%);
  }
  .ww-fog-a { bottom: -4%;  height: 34%; filter: blur(26px); animation: ww-fog-move 64s ease-in-out infinite alternate; }
  .ww-fog-b { bottom: -2%;  height: 24%; filter: blur(18px); animation: ww-fog-move 44s ease-in-out infinite alternate-reverse; opacity: 0.85; }
  .ww-fog-c { bottom: -6%;  height: 16%; filter: blur(12px); animation: ww-fog-move 30s ease-in-out infinite alternate; opacity: 0.9; }
  @keyframes ww-fog-move {
    from { transform: translateX(-6%) translateY(0); }
    to   { transform: translateX(6%)  translateY(-8px); }
  }

  /* ── 입자 ───────────────────────────────────────────────────────────── */
  .ww-particles { inset: 0; }
  .ww-particles > span {
    position: absolute;
    bottom: -4%;
    border-radius: 50%;
    animation-name: ww-rise;
    animation-timing-function: linear;
    animation-iteration-count: infinite;
  }
  .ww-particles-ember > span {
    background: #ffb057;
    box-shadow: 0 0 8px 2px rgba(255,120,40,0.65);
  }
  .ww-particles-mote > span {
    background: rgba(255,232,180,0.9);
    box-shadow: 0 0 6px 1px rgba(255,220,150,0.5);
  }
  @keyframes ww-rise {
    0%   { opacity: 0;    transform: translate(0, 0) scale(0.6); }
    12%  { opacity: 0.9; }
    70%  { opacity: 0.7; }
    100% { opacity: 0;    transform: translate(var(--drift), -86vh) scale(1); }
  }

  /* 심판의 하늘만 낮게 맥동한다. 소리 없이 심박을 보여주는 층. */
  .ww-pulse {
    inset: 0;
    background: radial-gradient(ellipse 70% 60% at 50% 55%, rgba(255,60,20,0.16), transparent 68%);
    animation: ww-heart 2.6s ease-in-out infinite;
  }
  @keyframes ww-heart {
    0%, 100% { opacity: 0.35; }
    14%      { opacity: 0.9; }
    28%      { opacity: 0.45; }
    42%      { opacity: 0.75; }
  }

  .ww-vignette { inset: 0; }
  .ww-grain {
    inset: 0;
    background-image: ${NOISE_URL};
    opacity: 0.045;
    mix-blend-mode: overlay;
  }

  /* ── 콘텐츠 등장 ────────────────────────────────────────────────────── */
  /* 화면마다 제각각이던 fadeIn/fadeUp을 한 벌로 모은다. 같은 곡선을 쓰면
     페이즈가 달라도 '같은 게임의 화면'으로 읽힌다. */
  @keyframes ww-in {
    from { opacity: 0; transform: translateY(16px); }
    to   { opacity: 1; transform: none; }
  }
  @keyframes ww-in-down {
    from { opacity: 0; transform: translateY(-14px); }
    to   { opacity: 1; transform: none; }
  }
  @keyframes ww-pop {
    0%   { opacity: 0; transform: scale(0.9); }
    62%  { opacity: 1; transform: scale(1.03); }
    100% { opacity: 1; transform: scale(1); }
  }
  /* 큰 제목은 흐릿하게 벌어져 있다가 초점이 맞으며 조여든다. */
  @keyframes ww-title {
    0%   { opacity: 0; letter-spacing: 0.42em; filter: blur(14px); transform: scale(1.06); }
    60%  { opacity: 1; filter: blur(0); }
    100% { opacity: 1; letter-spacing: 0.08em; filter: blur(0); transform: scale(1); }
  }
  .ww-anim-in    { animation: ww-in 640ms cubic-bezier(.2,.7,.2,1) both; }
  .ww-anim-down  { animation: ww-in-down 560ms cubic-bezier(.2,.7,.2,1) both; }
  .ww-anim-pop   { animation: ww-pop 620ms cubic-bezier(.2,.9,.25,1.25) both; }
  .ww-anim-title { animation: ww-title 1150ms cubic-bezier(.16,.8,.24,1) both; }

  @media (prefers-reduced-motion: reduce) {
    .ww-scene *, .ww-anim-in, .ww-anim-down, .ww-anim-pop, .ww-anim-title {
      animation-duration: 1ms !important;
      animation-iteration-count: 1 !important;
    }
  }
`
