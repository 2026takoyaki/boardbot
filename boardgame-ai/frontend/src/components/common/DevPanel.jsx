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
        devModeCache = false
        if (!cancelled) setDevMode(false)
      })
    return () => { cancelled = true }
  }, [])

  return devMode
}

export default function DevPanel({ title, actions = [] }) {
  const devMode = useDevMode()
  const [open, setOpen] = useState(true)

  if (!devMode || actions.length === 0) return null

  return (
    <div style={styles.wrap}>
      <button type="button" style={styles.handle} onClick={() => setOpen(o => !o)}>
        <span style={styles.dot} />
        DEV{title ? ` · ${title}` : ''}
        <span style={styles.chevron}>{open ? '▾' : '▴'}</span>
      </button>

      {open && (
        <div style={styles.body}>
          {actions.map(({ label, run, hint }) => (
            <button
              key={label}
              type="button"
              style={styles.action}
              onClick={run}
              title={hint}
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

const styles = {
  wrap: {
    position: 'fixed',
    right: 12,
    bottom: 12,
    zIndex: 10000,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-end',
    gap: 6,
    fontFamily: 'var(--font-mono)',
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
