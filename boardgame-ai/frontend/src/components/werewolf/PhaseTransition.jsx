import { useEffect } from 'react'

/**
 * 페이즈 전환 연출.
 *
 * 길이(duration)와 뒷배경 교체 시점(midAt)은 백엔드 타이밍과 맞물려 있다
 * (NightEnd가 dawn 2500ms 이후를 기준으로 발화를 건다). 연출을 손볼 때
 * 숫자는 건드리지 않는다 — 그림만 바꾼다.
 *
 * 전환의 핵심은 "덮었다 걷기"가 아니라 **초점**이다. 화면이 흐려졌다 다시
 * 맞으면 눈이 감겼다 뜬 것처럼 읽히고, 그 사이에 뒷화면이 갈리면 페이즈가
 * 바뀌었다는 것을 글자 없이 알 수 있다. 그래서 각 연출은 색 레이어 위에
 * backdrop-filter로 **뒷화면 자체**를 함께 흐린다.
 */
const CONFIGS = {
  eye_close:    { duration: 1500, midAt: 680 },  // 야간→야간: 눈 감기/뜨기
  dawn:         { duration: 2500, midAt: 300 },  // 야간→낮: 일출
  red_vignette: { duration: 1800, midAt: 740 },  // 낮→투표: 붉은 조임
  flash_fade:   { duration: 3900, midAt: 450 },  // 투표→결과: 처형 낙하
  fade:         { duration: 600,  midAt: 270 },  // 기본 페이드
}

const base = {
  position: 'fixed',
  inset: 0,
  zIndex: 9999,
  pointerEvents: 'none',
}

/**
 * 일출 광선의 살.
 *
 * 예전에는 conic-gradient가 위→오른쪽 90°만 채우고 나머지를 통째로
 * transparent로 두어 **왼쪽에 광선이 아예 없었고**, 700px 정사각 상자 끝에서
 * 오른쪽 광선마저 뚝 잘렸다. 화면 양옆이 끊겨 보인 원인이다.
 * 이제 살 하나를 좌우로 접어 대칭으로 깔고, 상자는 화면보다 크게 잡은 뒤
 * 가장자리는 마스크로 서서히 지운다 — 빛은 끝나는 게 아니라 옅어져야 한다.
 */
const RAY_SPOKES = [
  { at: 4,    w: 1.8, c: 'rgba(255,195,65,0.22)' },
  { at: 11,   w: 1.7, c: 'rgba(255,185,55,0.18)' },
  { at: 18.5, w: 1.8, c: 'rgba(255,205,75,0.20)' },
  { at: 26,   w: 1.7, c: 'rgba(255,190,60,0.15)' },
  { at: 34,   w: 1.9, c: 'rgba(255,200,70,0.20)' },
  { at: 42,   w: 2.0, c: 'rgba(255,185,55,0.16)' },
  { at: 51,   w: 2.1, c: 'rgba(255,200,68,0.18)' },
  { at: 61,   w: 2.2, c: 'rgba(255,190,60,0.12)' },
  { at: 72,   w: 2.6, c: 'rgba(255,195,65,0.15)' },
  { at: 84,   w: 3.2, c: 'rgba(255,185,55,0.10)' },
]

const RAY_GRADIENT = `conic-gradient(from -90deg at 50% 86%, ${
  RAY_SPOKES
    .flatMap(({ at, w, c }) => [{ at, w, c }, { at: 360 - at, w, c }])
    .sort((a, b) => a.at - b.at)
    .flatMap(({ at, w, c }) => [
      `transparent ${(at - w).toFixed(2)}deg`,
      `${c} ${at.toFixed(2)}deg`,
      `transparent ${(at + w).toFixed(2)}deg`,
    ])
    .join(', ')
}, transparent 360deg)`

// 광선 상자 크기와, 그 안에서 태양이 놓이는 지점(가로 50% / 세로 86%).
// 상자 아래에서 origin까지는 (100-86)% = 0.14 * 크기.
const RAY_BOX = 160        // vmax
const RAY_LIFT = RAY_BOX * 0.14
const RAY_MASK =
  'radial-gradient(circle 78vmax at 50% 86%, #000 0%, rgba(0,0,0,0.92) 40%, transparent 100%)'

export default function PhaseTransition({ type = 'fade', onDone, onMidpoint }) {
  const { duration, midAt } = CONFIGS[type] ?? CONFIGS.fade

  useEffect(() => {
    const timers = []
    if (midAt != null && onMidpoint) timers.push(setTimeout(onMidpoint, midAt))
    if (onDone)                       timers.push(setTimeout(onDone, duration))
    return () => timers.forEach(clearTimeout)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (type === 'eye_close')    return <EyeClose duration={duration} />
  if (type === 'dawn')         return <Dawn duration={duration} />
  if (type === 'red_vignette') return <RedVignette duration={duration} />
  if (type === 'flash_fade')   return <FlashFade duration={duration} />
  return <Fade duration={duration} />
}

/**
 * 야간→야간: 눈꺼풀이 닫혔다 열린다.
 *
 * 예전에는 위아래 검은 사각형이 만나는 것이 전부라 '셔터'로 보였다. 눈꺼풀은
 * 직선이 아니다 — 안쪽 모서리를 둥글게 깎고, 닫히는 동안 뒷화면을 흐리며,
 * 만나는 자리에 속눈썹 같은 얇은 그림자를 둔다.
 */
function EyeClose({ duration }) {
  const d = `${duration}ms`
  return (
    <>
      <style>{`
        @keyframes ww-lid-top {
          0%,100% { transform: scaleY(0); }
          43%,57% { transform: scaleY(1); }
        }
        @keyframes ww-lid-bot {
          0%,100% { transform: scaleY(0); }
          43%,57% { transform: scaleY(1); }
        }
        /* 눈이 감기는 동안 세상이 흐려진다. 이 한 겹이 셔터와 눈꺼풀을 가른다. */
        @keyframes ww-eye-blur {
          0%,100% { backdrop-filter: blur(0px); -webkit-backdrop-filter: blur(0px); }
          40%,60% { backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); }
        }
        @keyframes ww-lash {
          0%,100% { opacity: 0; transform: scaleX(0.3); }
          44%,56% { opacity: 1; transform: scaleX(1); }
        }
      `}</style>
      <div style={{ ...base, overflow: 'hidden' }}>
        <div style={{
          position: 'absolute', inset: 0,
          animation: `ww-eye-blur ${d} cubic-bezier(.4,0,.6,1) forwards`,
        }} />
        <div style={{
          position: 'absolute', top: 0, left: '-4%', right: '-4%', height: '52%',
          background: 'linear-gradient(180deg, #000 72%, #05040a 100%)',
          borderRadius: '0 0 50% 50% / 0 0 14% 14%',
          transformOrigin: 'top',
          animation: `ww-lid-top ${d} cubic-bezier(.4,0,.6,1) forwards`,
        }} />
        <div style={{
          position: 'absolute', bottom: 0, left: '-4%', right: '-4%', height: '52%',
          background: 'linear-gradient(0deg, #000 72%, #05040a 100%)',
          borderRadius: '50% 50% 0 0 / 14% 14% 0 0',
          transformOrigin: 'bottom',
          animation: `ww-lid-bot ${d} cubic-bezier(.4,0,.6,1) forwards`,
        }} />
        {/* 눈꺼풀이 맞닿는 선 */}
        <div style={{
          position: 'absolute', top: '50%', left: 0, right: 0, height: 3,
          transform: 'translateY(-50%)',
          background: 'linear-gradient(90deg, transparent, rgba(220,190,140,0.28) 20%, rgba(220,190,140,0.28) 80%, transparent)',
          filter: 'blur(1px)',
          animation: `ww-lash ${d} cubic-bezier(.4,0,.6,1) forwards`,
        }} />
      </div>
    </>
  )
}

// ── 야간→낮: 태양이 지평선에서 떠오르는 일출 ────────────────────────────────
function Dawn({ duration }) {
  const d = `${duration}ms`
  return (
    <>
      <style>{`
        @keyframes ww-night-out {
          0%,18% { opacity: 1; }
          62%    { opacity: 0; }
          100%   { opacity: 0; }
        }
        @keyframes ww-sky-dawn {
          0%,10% { opacity: 0; }
          42%    { opacity: 1; }
          80%    { opacity: 1; }
          100%   { opacity: 0; }
        }
        @keyframes ww-horiz {
          0%    { opacity: 0; transform: scaleX(0.5); }
          20%   { opacity: 0.7; transform: scaleX(0.8); }
          52%   { opacity: 1; transform: scaleX(1.15); }
          80%   { opacity: 0.7; }
          100%  { opacity: 0; }
        }
        @keyframes ww-sun-up {
          0%    { opacity: 0; transform: translateY(0px) scale(0.5); }
          18%   { opacity: 0; transform: translateY(-8px) scale(0.6); }
          44%   { opacity: 1; transform: translateY(-50px) scale(0.9); }
          66%   { opacity: 1; transform: translateY(-80px) scale(1); }
          83%   { opacity: 0.85; transform: translateY(-95px) scale(1.03); }
          100%  { opacity: 0; transform: translateY(-108px) scale(1.06); }
        }
        @keyframes ww-rays-op {
          0%,30% { opacity: 0; }
          55%    { opacity: 0.7; }
          72%    { opacity: 0.75; }
          88%    { opacity: 0.3; }
          100%   { opacity: 0; }
        }
        @keyframes ww-bloom {
          0%,62% { opacity: 0; }
          73%    { opacity: 0.7; }
          82%    { opacity: 0.4; }
          100%   { opacity: 0; }
        }
        /* 빛이 터질 때 뒷화면도 함께 눈부시게 — 초점이 풀렸다 돌아온다 */
        @keyframes ww-dawn-blur {
          0%,40% { backdrop-filter: blur(0px); -webkit-backdrop-filter: blur(0px); }
          70%    { backdrop-filter: blur(9px); -webkit-backdrop-filter: blur(9px); }
          100%   { backdrop-filter: blur(0px); -webkit-backdrop-filter: blur(0px); }
        }
      `}</style>
      <div style={{ ...base, overflow: 'hidden' }}>
        <div style={{
          position: 'absolute', inset: 0,
          animation: `ww-dawn-blur ${d} ease-in-out forwards`,
        }} />
        {/* 밤하늘 */}
        <div style={{
          position: 'absolute', inset: 0,
          background: 'linear-gradient(180deg, #000008 0%, #030114 45%, #090418 100%)',
          animation: `ww-night-out ${d} ease-in-out forwards`,
        }} />
        {/* 새벽 하늘 */}
        <div style={{
          position: 'absolute', inset: 0,
          background: 'linear-gradient(180deg, #060921 0%, #180530 22%, #7a2008 50%, #e25510 74%, #f5a820 100%)',
          animation: `ww-sky-dawn ${d} ease-in-out forwards`,
        }} />
        {/* 수평선 빛 번짐 */}
        <div style={{
          position: 'absolute', bottom: 0,
          left: '-18%', width: '136%', height: '55%',
          transformOrigin: 'bottom center',
          background: 'radial-gradient(ellipse at 50% 100%, rgba(255,165,40,0.95) 0%, rgba(230,78,10,0.82) 25%, rgba(145,32,5,0.52) 55%, transparent 80%)',
          animation: `ww-horiz ${d} ease-in-out forwards`,
        }} />
        {/* 태양 광선 — 화면보다 크게 깔고 가장자리는 마스크로 지운다.
            원래 상자(700px)의 태양 위치(아래에서 98px)는 그대로 유지한다. */}
        <div style={{
          position: 'absolute',
          bottom: `calc(14% + 98px - ${RAY_LIFT}vmax)`,
          left: `calc(50% - ${RAY_BOX / 2}vmax)`,
          width: `${RAY_BOX}vmax`, height: `${RAY_BOX}vmax`,
          background: RAY_GRADIENT,
          WebkitMaskImage: RAY_MASK,
          maskImage: RAY_MASK,
          willChange: 'opacity',
          animation: `ww-rays-op ${d} ease-in-out forwards`,
        }} />
        {/* 태양 후광 + 디스크: 지평선 위치에서 시작해 위로만 이동 */}
        <div style={{
          position: 'absolute',
          bottom: 'calc(14% - 110px)', left: 'calc(50% - 140px)',
          width: 280, height: 280,
          animation: `ww-sun-up ${d} ease-out forwards`,
        }}>
          <div style={{
            position: 'absolute', inset: 0,
            borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(255,248,180,0.95) 0%, rgba(255,195,65,0.88) 15%, rgba(255,135,22,0.65) 42%, rgba(200,58,8,0.28) 68%, transparent 86%)',
          }} />
          <div style={{
            position: 'absolute', top: 85, left: 85,
            width: 110, height: 110,
            borderRadius: '50%',
            background: 'radial-gradient(circle, #fffeee 0%, #fff8b0 28%, #ffdf50 58%, #ffa818 90%)',
            boxShadow: '0 0 45px 22px rgba(255,225,80,0.75), 0 0 95px 48px rgba(255,148,28,0.4)',
          }} />
        </div>
        {/* 절정 빛 번짐 */}
        <div style={{
          position: 'absolute', inset: 0,
          background: 'radial-gradient(ellipse at 50% 80%, rgba(255,225,130,0.42) 0%, rgba(255,165,60,0.22) 28%, transparent 62%)',
          animation: `ww-bloom ${d} ease-in-out forwards`,
        }} />
      </div>
    </>
  )
}

/**
 * 낮→투표: 붉은 빛이 가장자리에서 조여온다.
 *
 * 예전에는 붉은 판이 켜졌다 꺼지는 것이 전부였다. 지금은 두 번 **박동**한다 —
 * 심장이 뛰는 리듬으로 조였다 풀리면, 투표가 시작된다는 압박이 몸으로 온다.
 */
function RedVignette({ duration }) {
  const d = `${duration}ms`
  return (
    <>
      <style>{`
        @keyframes ww-red-vig {
          0%      { opacity: 0; transform: scale(1.25); }
          26%     { opacity: 0.85; transform: scale(1.02); }
          40%     { opacity: 0.6;  transform: scale(1.08); }
          56%     { opacity: 1;    transform: scale(1); }
          72%     { opacity: 0.75; transform: scale(1.04); }
          100%    { opacity: 0;    transform: scale(1.18); }
        }
        @keyframes ww-red-wash {
          0%, 100% { opacity: 0; }
          30%      { opacity: 0.34; }
          58%      { opacity: 0.5; }
          80%      { opacity: 0.18; }
        }
        @keyframes ww-red-blur {
          0%, 100% { backdrop-filter: blur(0px) saturate(1); -webkit-backdrop-filter: blur(0px) saturate(1); }
          50%      { backdrop-filter: blur(7px) saturate(1.6); -webkit-backdrop-filter: blur(7px) saturate(1.6); }
        }
      `}</style>
      <div style={base}>
        <div style={{
          position: 'absolute', inset: 0,
          animation: `ww-red-blur ${d} ease-in-out forwards`,
        }} />
        <div style={{
          position: 'absolute', inset: 0,
          background: 'rgba(150,16,6,0.9)',
          animation: `ww-red-wash ${d} ease-in-out forwards`,
        }} />
        <div style={{
          position: 'absolute', inset: '-14%',
          background: 'radial-gradient(ellipse at center, transparent 8%, rgba(120,10,10,0.82) 56%, rgba(40,0,0,0.99) 100%)',
          animation: `ww-red-vig ${d} cubic-bezier(.36,.07,.25,1) forwards`,
        }} />
      </div>
    </>
  )
}

/**
 * 투표→결과: 처형 낙하.
 *
 * 검은 커튼이 위에서 떨어져 화면을 친다. 떨어지는 것만으로는 무게가 안 실려서
 * 착지 순간에 충격파 한 줄과 흰 섬광을 겹치고, 먼지가 잠깐 튀어오른다.
 */
function FlashFade({ duration }) {
  const d = `${duration}ms`
  const dust = [12, 26, 38, 47, 55, 64, 73, 84, 91]
  return (
    <>
      <style>{`
        @keyframes ww-exec-shadow {
          0%    { opacity: 0; transform: scaleY(0); }
          12%   { opacity: 0.75; transform: scaleY(1); }
          30%   { opacity: 0; }
          100%  { opacity: 0; }
        }
        @keyframes ww-exec-curtain {
          0%    { transform: translateY(-100%) skewX(0deg);
                  animation-timing-function: cubic-bezier(0.4,0,1,0.9); }
          26%   { transform: translateY(3%) skewX(1.5deg);
                  animation-timing-function: ease-out; }
          36%   { transform: translateY(0%) skewX(0deg); }
          66%   { transform: translateY(0%); opacity: 1; }
          88%   { opacity: 0.85; }
          100%  { opacity: 0; }
        }
        @keyframes ww-exec-impact {
          0%,27%  { opacity: 0; }
          30%     { opacity: 0.42; }
          38%     { opacity: 0; }
          100%    { opacity: 0; }
        }
        /* 착지 순간 가로로 퍼지는 충격파 */
        @keyframes ww-exec-shock {
          0%, 26% { opacity: 0; transform: scaleX(0.1) scaleY(1); }
          30%     { opacity: 1; transform: scaleX(1) scaleY(2.4); }
          44%     { opacity: 0; transform: scaleX(1.3) scaleY(0.4); }
          100%    { opacity: 0; }
        }
        /* 튀어오르는 먼지 */
        @keyframes ww-exec-dust {
          0%, 27% { opacity: 0; transform: translateY(0) scale(0.5); }
          32%     { opacity: 0.7; }
          62%     { opacity: 0; transform: translateY(-160px) scale(1.4); }
          100%    { opacity: 0; }
        }
      `}</style>
      <div style={base}>
        {/* 낙하 예고 그림자 */}
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, height: '45%',
          transformOrigin: 'top',
          background: 'linear-gradient(180deg, rgba(0,0,0,0.96) 0%, transparent 100%)',
          animation: `ww-exec-shadow ${d} ease-in forwards`,
        }} />
        {/* 낙하 커튼 */}
        <div style={{
          position: 'absolute', inset: 0,
          background: 'linear-gradient(180deg, #030303 0%, #0a0505 100%)',
          animation: `ww-exec-curtain ${d} linear forwards`,
        }} />
        {/* 충돌 플래시 */}
        <div style={{
          position: 'absolute', inset: 0,
          background: 'radial-gradient(ellipse at 50% 100%, rgba(255,220,210,0.32), rgba(255,240,240,0.14) 50%, transparent 78%)',
          animation: `ww-exec-impact ${d} ease-out forwards`,
        }} />
        {/* 착지 충격파 */}
        <div style={{
          position: 'absolute', bottom: '18%', left: 0, right: 0, height: 3,
          background: 'linear-gradient(90deg, transparent, rgba(255,180,150,0.85) 30%, rgba(255,235,220,0.95) 50%, rgba(255,180,150,0.85) 70%, transparent)',
          filter: 'blur(1px)',
          animation: `ww-exec-shock ${d} cubic-bezier(.2,.9,.3,1) forwards`,
        }} />
        {/* 먼지 */}
        {dust.map((left, i) => (
          <div
            key={i}
            style={{
              position: 'absolute',
              bottom: '18%',
              left: `${left}%`,
              width: 4 + (i % 3) * 2,
              height: 4 + (i % 3) * 2,
              borderRadius: '50%',
              background: 'rgba(200,180,170,0.5)',
              filter: 'blur(1px)',
              animation: `ww-exec-dust ${d} ease-out ${i * 22}ms forwards`,
            }}
          />
        ))}
      </div>
    </>
  )
}

// ── 기본 페이드 ────────────────────────────────────────────────────────────
function Fade({ duration }) {
  const d = `${duration}ms`
  return (
    <>
      <style>{`
        @keyframes ww-fade {
          0%,100% { opacity: 0; }
          43%,57% { opacity: 1; }
        }
        @keyframes ww-fade-blur {
          0%,100% { backdrop-filter: blur(0px); -webkit-backdrop-filter: blur(0px); }
          43%,57% { backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); }
        }
      `}</style>
      <div style={base}>
        <div style={{
          position: 'absolute', inset: 0,
          animation: `ww-fade-blur ${d} ease-in-out forwards`,
        }} />
        <div style={{
          position: 'absolute', inset: 0,
          background: '#000',
          animation: `ww-fade ${d} ease-in-out forwards`,
        }} />
      </div>
    </>
  )
}
