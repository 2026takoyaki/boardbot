/**
 * 늑대인간 화면이 공유하는 부품.
 *
 * 나가기 버튼 하나가 여섯 파일에 각각 복사돼 있었고, 그래서 화면마다 모서리
 * 둥글기와 글자색이 조금씩 달랐다. 눈에 띄는 차이는 아니지만 그런 어긋남이
 * 쌓이면 "만들다 만 화면"으로 보인다. 여기 한 벌만 둔다.
 *
 * 그 나가기 버튼은 이제 여기에도 없다 — 두 게임이 함께 쓰는 상단바
 * (components/common/GameTopBar.jsx)로 옮겼다. 같은 기기에서 도는 두 게임인데
 * 요트에만 소리·전략 조작이 있는 것이 더 큰 어긋남이었다.
 */

export const page = {
  position: 'absolute',
  inset: 0,
  overflow: 'hidden',
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  userSelect: 'none',
}

/** 배경 위에 얹히는 콘텐츠는 전부 이 층에 올린다. */
export const stage = {
  position: 'relative',
  zIndex: 1,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
}

export const ghostButton = {
  padding: '13px 26px',
  border: '1px solid var(--w-line)',
  borderRadius: 14,
  background: 'rgba(10,8,16,0.5)',
  color: 'var(--w-ink-soft)',
  fontFamily: 'inherit',
  fontSize: 16,
  fontWeight: 650,
  letterSpacing: '-0.01em',
  cursor: 'pointer',
  WebkitBackdropFilter: 'blur(10px)',
  backdropFilter: 'blur(10px)',
}

/**
 * 주 버튼.
 *
 * 예전에는 `box-shadow: 0 6px 0 #68420E`로 두께를 준 '입체 버튼'이었다. 그
 * 표현은 2010년대 모바일 게임의 것이고, 지금 화면의 나머지(유리판·안개)와
 * 재질이 맞지 않는다. 두께 대신 **빛**으로 존재감을 준다.
 */
export const primaryButton = {
  padding: '15px 30px',
  border: '1px solid rgba(255,240,192,0.55)',
  borderRadius: 14,
  background: 'linear-gradient(180deg, var(--w-gold-hi), var(--w-gold) 42%, var(--w-gold-deep))',
  color: '#2a1a04',
  fontFamily: 'inherit',
  fontSize: 17,
  fontWeight: 800,
  letterSpacing: '-0.01em',
  cursor: 'pointer',
  boxShadow: '0 1px 0 rgba(255,255,255,0.5) inset, 0 10px 30px rgba(224,178,70,0.28)',
}

export const dangerButton = {
  ...primaryButton,
  border: '1px solid rgba(255,150,110,0.5)',
  background: 'linear-gradient(180deg, #ff8552, var(--w-blood) 46%, var(--w-blood-deep))',
  color: '#fff4ec',
  boxShadow: '0 1px 0 rgba(255,255,255,0.3) inset, 0 10px 34px rgba(220,70,30,0.36)',
}

/** 화면 상단의 작은 상태 뱃지 — "TTS 재생 중", "튜토리얼 모드" 같은 것. */
export const eyebrow = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 9,
  padding: '7px 15px 7px 12px',
  borderRadius: 999,
  border: '1px solid var(--w-line)',
  background: 'rgba(10,8,16,0.45)',
  color: 'var(--w-ink-mute)',
  fontSize: 12,
  fontWeight: 750,
  letterSpacing: '0.16em',
  WebkitBackdropFilter: 'blur(10px)',
  backdropFilter: 'blur(10px)',
}

export const eyebrowDot = {
  width: 7,
  height: 7,
  borderRadius: '50%',
  background: 'var(--w-gold)',
  boxShadow: '0 0 0 4px rgba(240,207,122,0.18)',
  animation: 'ww-beat 1.8s ease-in-out infinite',
}

/** 화면 어디서나 쓰는 큰 제목. */
export const title = {
  margin: 0,
  fontSize: 'clamp(36px, 6vw, 58px)',
  fontWeight: 850,
  lineHeight: 1.1,
  color: 'var(--w-ink)',
  textShadow: '0 0 60px rgba(240,207,122,0.30), 0 4px 18px rgba(0,0,0,0.7)',
  textAlign: 'center',
}

/** eyebrowDot이 쓰는 박동. 무대 CSS와 함께 한 번만 주입한다. */
export const WW_UI_CSS = `
  @keyframes ww-beat {
    0%, 100% { opacity: 1;   box-shadow: 0 0 0 4px rgba(240,207,122,0.18); }
    50%      { opacity: 0.5; box-shadow: 0 0 0 7px rgba(240,207,122,0.05); }
  }
  .ww-hover:hover { background: rgba(255,255,255,0.10); color: var(--w-ink); }
  .ww-press:active { transform: translateY(1px); }
`
