/**
 * 주사위 눈을 숫자가 아니라 실제 눈 모양(pip)으로 그린다.
 *
 * 숫자로 쓰면 화면을 "읽어야" 하지만 눈 모양은 트레이에 놓인 실물과 같은
 * 그림이라 곧바로 대조된다 — 카메라가 잘못 읽었을 때 알아채는 속도가 다르다.
 * 점수판의 족보 힌트와 규칙 화면도 같은 그림을 써서, 설명과 실물이 같은
 * 언어를 쓰게 한다.
 */

// 100×100 좌표계 위의 눈 자리. 세 열/세 행이 27·50·73에 놓인다.
const L = 27
const M = 50
const R = 73

const PIPS = {
  1: [[M, M]],
  2: [[L, L], [R, R]],
  3: [[L, L], [M, M], [R, R]],
  4: [[L, L], [R, L], [L, R], [R, R]],
  5: [[L, L], [R, L], [M, M], [L, R], [R, R]],
  6: [[L, L], [R, L], [L, M], [R, M], [L, R], [R, R]],
}

export default function DiceFace({
  value,
  size = 64,
  face = 'var(--y-die-face)',
  pip = 'var(--y-die-pip)',
  border = 'var(--y-die-edge)',
  shadow,
  radius,
  style,
}) {
  const pips = PIPS[Number(value)]
  // 눈을 모르는 자리(굴리기 전·인식 실패)는 자리만 비워둔다. 0이나 물음표를
  // 그리면 그것도 하나의 눈처럼 읽히고, 흰 면으로 채우면 "빈 눈이 나왔다"로
  // 보인다. 점선 윤곽이라야 아직 아무것도 없다는 뜻이 된다.
  const known = Boolean(pips)

  return (
    <div
      aria-label={known ? `주사위 ${value}` : '주사위 미확정'}
      style={{
        width: size,
        height: size,
        flexShrink: 0,
        borderRadius: radius ?? Math.max(4, Math.round(size * 0.22)),
        background: known ? face : 'transparent',
        border: known
          ? `1px solid ${border}`
          : '2px dashed color-mix(in oklch, var(--y-die-face) 28%, transparent)',
        boxShadow: known ? shadow : undefined,
        display: 'block',
        ...style,
      }}
    >
      {known && (
        <svg viewBox="0 0 100 100" width="100%" height="100%" aria-hidden>
          {pips.map(([x, y]) => (
            <circle key={`${x}-${y}`} cx={x} cy={y} r={9.4} fill={pip} />
          ))}
        </svg>
      )}
    </div>
  )
}

/** 족보 예시처럼 여러 눈을 나란히 보여줄 때. */
export function DiceRow({ values = [], size = 20, gap, ...rest }) {
  return (
    <span style={{ display: 'inline-flex', gap: gap ?? Math.round(size * 0.18) }}>
      {values.map((value, index) => (
        <DiceFace key={`${value}-${index}`} value={value} size={size} {...rest} />
      ))}
    </span>
  )
}
