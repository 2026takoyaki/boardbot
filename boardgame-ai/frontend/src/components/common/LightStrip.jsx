/**
 * 조명 상태를 화면으로 대신 보여준다.
 *
 * 전구가 없어도(또는 전구를 켜기 전에도) 어떤 색을 어떤 밝기로 요청했는지 눈으로
 * 확인할 수 있어야 연출을 조율할 수 있다. 로그를 뒤져서는 "밤이 충분히 어두운가"
 * 같은 판단을 할 수 없다.
 *
 * 백엔드 FrontendDriver가 보내는 light_state를 그대로 그린다. 실제 전구와 같은
 * (color, brightness, duration)을 받으므로 둘이 자동으로 동기화된다.
 *
 * 화면 가장자리에만 번지게 해서 게임 화면을 가리지 않는다 — 전구가 방을 물들이는
 * 것과 같은 방식이다.
 */
export default function LightStrip({ light }) {
  if (!light) return null

  const [r, g, b] = light.color ?? [255, 255, 255]
  const brightness = Number(light.brightness ?? 0)
  const duration = Number(light.duration_ms ?? 800)
  // 밝기 0은 소등이다. 가장자리를 완전히 비워 어둠을 그대로 보여준다.
  const strength = Math.max(0, Math.min(100, brightness)) / 100
  const rgb = `${r}, ${g}, ${b}`

  return (
    <>
      <div
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 9996,
          pointerEvents: 'none',
          transition: `box-shadow ${duration}ms ease, opacity ${duration}ms ease`,
          opacity: strength === 0 ? 0 : 1,
          boxShadow: `inset 0 0 ${90 + strength * 120}px ${10 + strength * 26}px`
            + ` rgba(${rgb}, ${0.1 + strength * 0.3})`,
        }}
      />
      <div
        style={{
          position: 'fixed',
          left: 12,
          bottom: 12,
          zIndex: 9996,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '6px 10px',
          borderRadius: 999,
          background: 'color-mix(in oklch, var(--bg-deep) 82%, transparent)',
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--fg-mute)',
          pointerEvents: 'none',
        }}
      >
        <span
          style={{
            width: 12,
            height: 12,
            borderRadius: '50%',
            background: `rgb(${rgb})`,
            opacity: strength === 0 ? 0.15 : 0.4 + strength * 0.6,
            boxShadow: `0 0 ${4 + strength * 12}px rgba(${rgb}, ${strength})`,
            transition: `all ${duration}ms ease`,
          }}
        />
        {brightness === 0 ? '소등' : `${brightness}%`}
      </div>
    </>
  )
}
