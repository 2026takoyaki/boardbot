import { useEffect, useState } from 'react'

/**
 * 개발용 컨트롤 패널. 카메라 없이 게임을 손으로 굴리기 위한 버튼 모음.
 *
 * 백엔드가 BOARDBOT_DEV=1로 떠 있을 때만 나타난다. 플래그가 꺼져 있으면
 * /dev/config가 false를 주고 패널은 아예 렌더되지 않으며, 개발 입력도 백엔드에서
 * 무시되므로 시연 중 실수로 눌릴 경로가 없다.
 *
 * 페이지마다 필요한 조작이 다르므로 버튼 목록은 각 페이지가 넘긴다.
 *
 *     <DevPanel title="요트" actions={[{ label: '야찌', run: () => ... }]} />
 */

// 모듈 수준 캐시. 페이지를 옮길 때마다 다시 물어볼 이유가 없다.
// **응답을 받았을 때만** 채운다 — 백엔드가 아직 안 떴거나 네트워크가 잠깐
// 흔들린 것을 "개발 모드 아님"으로 굳혀버리면, 나중에 정상화돼도 새로고침
// 전까지 패널이 돌아오지 않는다.
let devModeCache = null

function useDevMode() {
  const [devMode, setDevMode] = useState(devModeCache)

  useEffect(() => {
    if (devModeCache !== null) return undefined
    let cancelled = false
    fetch('/dev/config')
      .then(r => (r.ok ? r.json() : { dev_mode: false }))
      .then(d => {
        devModeCache = Boolean(d.dev_mode)
        if (!cancelled) setDevMode(devModeCache)
      })
      .catch(() => {
        // 캐시는 건드리지 않는다. 다음 마운트에서 다시 물어본다.
        if (!cancelled) setDevMode(false)
      })
    return () => { cancelled = true }
  }, [])

  return devMode
}

/** localStorage가 막힌 컨텍스트(사파리 프라이빗, 테스트 환경)에서도 렌더는 살아야 한다. */
function readStoredCorner() {
  try {
    if (typeof localStorage === 'undefined') return 0
    const saved = Number(localStorage.getItem(CORNER_STORAGE_KEY))
    return Number.isInteger(saved) && saved >= 0 && saved < CORNERS.length ? saved : 0
  } catch {
    return 0
  }
}

function storeCorner(index) {
  try {
    if (typeof localStorage === 'undefined') return
    localStorage.setItem(CORNER_STORAGE_KEY, String(index))
  } catch {
    // 기억하지 못할 뿐, 이번 세션 동안은 옮긴 자리가 유지된다.
  }
}

// 화면 네 귀퉁이. 게임 UI가 가려지면 눌러서 옮긴다.
const CORNERS = [
  { key: 'br', label: '↘', style: { right: 12, bottom: 12, alignItems: 'flex-end' } },
  { key: 'bl', label: '↙', style: { left: 12, bottom: 12, alignItems: 'flex-start' } },
  { key: 'tl', label: '↖', style: { left: 12, top: 12, alignItems: 'flex-start' } },
  { key: 'tr', label: '↗', style: { right: 12, top: 12, alignItems: 'flex-end' } },
]

const CORNER_STORAGE_KEY = 'devPanelCorner'

export default function DevPanel({ title, actions = [] }) {
  const devMode = useDevMode()
  // 기본은 접힘. 펼친 채로 두면 게임 UI 버튼을 가려서 정작 테스트를 방해한다.
  const [open, setOpen] = useState(false)
  const [cornerIndex, setCornerIndex] = useState(readStoredCorner)

  if (!devMode || actions.length === 0) return null

  const corner = CORNERS[cornerIndex]
  const moveCorner = () => {
    const next = (cornerIndex + 1) % CORNERS.length
    setCornerIndex(next)
    storeCorner(next)
  }
  // 아래쪽 귀퉁이에서는 목록이 위로 자라야 손잡이가 안 밀린다.
  const growsUp = corner.key.startsWith('b')

  return (
    <div style={{ ...styles.wrap, ...corner.style }}>
      {open && growsUp && <Actions actions={actions} />}

      <div style={styles.handleRow}>
        <button type="button" style={styles.handle} onClick={() => setOpen(o => !o)}>
          <span style={styles.dot} />
          DEV{title ? ` · ${title}` : ''}
        </button>
        <button
          type="button"
          style={styles.corner}
          onClick={moveCorner}
          title="패널 위치 옮기기"
        >
          {corner.label}
        </button>
      </div>

      {open && !growsUp && <Actions actions={actions} />}
    </div>
  )
}

function Actions({ actions }) {
  return (
    <div style={styles.body}>
      {actions.map(({ label, run, hint }) => (
        <button key={label} type="button" style={styles.action} onClick={run} title={hint}>
          {label}
        </button>
      ))}
    </div>
  )
}

const styles = {
  wrap: {
    position: 'fixed',
    zIndex: 10000,
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    fontFamily: 'var(--font-mono)',
  },
  handleRow: { display: 'flex', gap: 4 },
  corner: {
    padding: '7px 9px',
    fontSize: 12,
    lineHeight: 1,
    color: 'oklch(0.85 0.14 85)',
    background: 'color-mix(in oklch, var(--bg-deep) 88%, transparent)',
    border: '1px solid oklch(0.85 0.14 85 / 0.4)',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
  },
  handle: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '7px 12px',
    fontSize: 12,
    fontWeight: 700,
    letterSpacing: '0.08em',
    color: 'oklch(0.85 0.14 85)',
    background: 'color-mix(in oklch, var(--bg-deep) 88%, transparent)',
    border: '1px solid oklch(0.85 0.14 85 / 0.4)',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: '50%',
    background: 'oklch(0.85 0.14 85)',
  },
  chevron: { fontSize: 10, opacity: 0.7 },
  body: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    padding: 8,
    minWidth: 190,
    background: 'color-mix(in oklch, var(--bg-deep) 94%, transparent)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    boxShadow: 'var(--shadow-lg)',
  },
  action: {
    padding: '9px 12px',
    fontSize: 13,
    fontWeight: 600,
    textAlign: 'left',
    color: 'var(--fg-soft)',
    background: 'var(--bg-elev)',
    border: '1px solid var(--border-soft)',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
    fontFamily: 'var(--font-mono)',
  },
}
