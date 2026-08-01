/**
 * 조명 상태 표시.
 *
 * 전구가 없어도(또는 켜기 전에도) 어떤 색을 어떤 밝기로 요청했는지 확인할 수
 * 있어야 연출을 조율할 수 있다. 로그를 뒤져서는 "밤이 충분히 어두운가" 같은
 * 판단을 할 수 없다.
 *
 * 화면을 물들이지는 않는다. 게임 화면의 색감이 그대로 보여야 UI를 판단할 수
 * 있는데, 조명색이 덧씌워지면 무엇이 UI 색이고 무엇이 조명인지 구분되지 않는다.
 * 값만 정확히 읽히면 충분하다.
 *
 * 백엔드 FrontendDriver가 보내는 light_state를 그대로 그린다. 실제 전구와 같은
 * (color, brightness, duration)을 받으므로 둘이 자동으로 동기화된다.
 */
export default function LightStrip({ light }) {
  if (!light) return null

  const [r, g, b] = light.color ?? [255, 255, 255]
  const brightness = Number(light.brightness ?? 0)
  const duration = Number(light.duration_ms ?? 800)
  const strength = Math.max(0, Math.min(100, brightness)) / 100
  const rgb = `${r}, ${g}, ${b}`

  return (
    <div style={styles.chip}>
      <span
        style={{
          ...styles.dot,
          background: `rgb(${rgb})`,
          // 소등은 점을 거의 지워 어둠을 그대로 보여준다.
          opacity: strength === 0 ? 0.15 : 0.4 + strength * 0.6,
          boxShadow: `0 0 ${4 + strength * 14}px rgba(${rgb}, ${strength})`,
          transition: `all ${duration}ms ease`,
        }}
      />
      <span style={styles.value}>{brightness === 0 ? '소등' : `${brightness}%`}</span>
      <span style={styles.rgb}>{r},{g},{b}</span>
    </div>
  )
}

const styles = {
  chip: {
    position: 'fixed',
    left: 12,
    bottom: 12,
    zIndex: 9996,
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '6px 12px',
    borderRadius: 999,
    background: 'color-mix(in oklch, var(--bg-deep) 82%, transparent)',
    fontFamily: 'var(--font-mono)',
    fontSize: 11,
    pointerEvents: 'none',
  },
  dot: { width: 12, height: 12, borderRadius: '50%', flexShrink: 0 },
  value: { color: 'var(--fg-soft)', fontWeight: 700, minWidth: 34 },
  rgb: { color: 'var(--fg-faint)' },
}
