import { useEffect, useRef, useState } from 'react'

/**
 * 라운드 시작 안내.
 *
 * 화면 가운데를 가로지르는 **띠**로 알린다. 득점·조합 연출과 같은 자리를 쓰지만
 * 생김새가 전혀 달라야 한다 — 셋 다 "어둡게 깔고 가운데에 금색 글자"였을 때는
 * 무슨 일이 일어난 건지 구별되지 않았다. 여기서 갈라놓는 축은 셋이다.
 *
 *   기하 — 저쪽은 가운데서 퍼지는 빛, 이쪽은 가로로 열리는 띠
 *   색   — 저쪽은 금색(축하), 이쪽은 무채색(구분자). 라운드는 축하가 아니다
 *   범위 — 저쪽은 화면 전체를 덮고, 이쪽은 띠 안쪽만 가린다
 *
 * 띠가 걷힐 때 글자는 상시 라운드 표시 자리로 작아지며 빨려 들어간다. 연출이
 * 끝나는 곳이 곧 "이 정보는 앞으로 여기 있다"는 안내가 된다.
 *
 * **득점 연출과 같은 순간에 발생한다.** 라운드는 현재 플레이어가 채운 칸 수로
 * 정해지므로, 마지막 사람이 점수를 넣어 다음 사람으로 넘어가는 순간 함께 오른다.
 * 둘이 겹치면 어느 쪽도 읽히지 않으니, 득점 연출이 끝날 때까지 기다렸다 시작한다.
 */

const ENTER_MS = 380
const HOLD_MS = 820
const FLY_MS = 620

export default function RoundBanner({ round, total, anchorRef, paused = false, onActiveChange }) {
  const [shown, setShown] = useState(null)
  // null이면 아직 가운데, 값이 있으면 상시 표시 자리로 날아가는 중.
  const [flight, setFlight] = useState(null)
  const [pending, setPending] = useState(null)
  const previousRef = useRef(null)
  const stageRef = useRef(null)
  // 부모가 매 렌더 새로 만들어도 타이머가 리셋되지 않도록 담아둔다.
  const activeRef = useRef(onActiveChange)
  useEffect(() => { activeRef.current = onActiveChange }, [onActiveChange])
  // 연출 도중에 사라지더라도 자리를 되돌려준다. 안 그러면 상시 라운드 표시가
  // 비워진 채로 남는다 (튜토리얼로 전환될 때처럼 통째로 언마운트되는 경우).
  useEffect(() => () => activeRef.current?.(false), [])

  // 라운드가 오른 순간을 잡아둔다. 지금 띄울 수 있는지는 여기서 따지지 않는다.
  useEffect(() => {
    if (!round) return
    const previous = previousRef.current
    previousRef.current = round
    if (previous === null) {
      setPending(round)
      return
    }
    // 새 판은 1로 돌아온다. 되돌리기로 줄어든 것과 구별해 이때는 다시 알린다.
    if (round === 1 && previous !== 1) {
      setPending(round)
      return
    }
    if (round <= previous) return
    setPending(round)
  }, [round])

  /**
   * 득점 연출이 비워지면 그때 시작한다.
   *
   * 한 박자 두고 시작하는 것이 중요하다. 백엔드는 state_update와 득점 큐를 잇달아
   * 보내는데 프론트에서는 서로 다른 렌더로 도착한다. 라운드가 먼저 올라오는 그
   * 순간에는 대기열이 아직 비어 있어 "겹칠 일 없다"고 판단해버려, 곧바로 시작하면
   * 뒤이어 뜨는 득점 연출과 화면 한가운데에서 정면으로 부딪친다.
   */
  useEffect(() => {
    if (paused || pending === null || shown !== null) return undefined
    const timer = setTimeout(() => {
      setShown(pending)
      setPending(null)
    }, 320)
    return () => clearTimeout(timer)
  }, [paused, pending, shown])

  /**
   * 재생 중에 막히면 그 자리에서 거둔다.
   *
   * paused는 "시작하지 말라"만이 아니라 "지금 화면을 쓰지 말라"는 뜻이다. 이미
   * 떠 있는 띠를 그냥 두면, 연출 도중에 전체 점수판을 연 순간 띠가 그 창을
   * 가로질러 뚫고 나온다 — 띠는 화면 맨 위에 그려지기 때문이다. 다시 부르지는
   * 않는다. 라운드는 상시 표시에 그대로 적혀 있어 놓쳐도 잃는 것이 없다.
   */
  useEffect(() => {
    if (!paused || shown === null) return
    setShown(null)
    setFlight(null)
    activeRef.current?.(false)
  }, [paused, shown])

  useEffect(() => {
    if (shown === null) return undefined
    activeRef.current?.(true)

    const flyTimer = setTimeout(() => {
      const stage = stageRef.current
      const anchor = anchorRef?.current
      if (!stage || !anchor) {
        // 앵커를 못 찾으면 제자리에서 작아지며 사라진다. 자리를 못 잡았다고
        // 연출이 통째로 멈추는 것보다 낫다.
        setFlight({ dx: 0, dy: 0, scale: 0.4 })
        return
      }
      const from = stage.getBoundingClientRect()
      const to = anchor.getBoundingClientRect()
      setFlight({
        dx: to.left + to.width / 2 - (from.left + from.width / 2),
        dy: to.top + to.height / 2 - (from.top + from.height / 2),
        // 한 줄짜리 표시에 맞추는 것이라 높이가 실제 크기 차이를 낸다. 너무
        // 작아지면 도착 전에 사라져 보이므로 하한을 둔다.
        scale: Math.max(0.26, to.height / from.height),
      })
    }, ENTER_MS + HOLD_MS)

    const endTimer = setTimeout(() => {
      setShown(null)
      setFlight(null)
      activeRef.current?.(false)
    }, ENTER_MS + HOLD_MS + FLY_MS)

    return () => {
      clearTimeout(flyTimer)
      clearTimeout(endTimer)
    }
  }, [shown, anchorRef])

  if (shown === null) return null

  return (
    <div style={styles.overlay}>
      <style>{`
        /* 띠는 가로로 열린다. 가운데서 퍼지는 다른 연출과 방향부터 다르다. */
        @keyframes rb-band {
          0%   { transform: scaleY(0.08); opacity: 0; }
          55%  { transform: scaleY(1.04); opacity: 1; }
          100% { transform: scaleY(1); opacity: 1; }
        }
        /* 가운데 맞추기(-50%,-50%)를 키프레임 안에 같이 넣는다. transform은 통째로
           갈아치워지므로, 여기서 빼먹으면 애니메이션이 끝나는 순간 글자가 중심에서
           자기 크기의 절반만큼 밀려나 띠 밖으로 흘러내린다. */
        @keyframes rb-text {
          0%   {
            opacity: 0;
            transform: translate(-50%, -50%) translateX(-26px);
            letter-spacing: 0.3em;
          }
          100% {
            opacity: 1;
            transform: translate(-50%, -50%);
            letter-spacing: normal;
          }
        }
        /* 띠 위를 한 번 훑고 지나가는 빛. 새 장이 열리는 느낌만 준다. */
        @keyframes rb-sweep {
          0%   { transform: translateX(-100%); opacity: 0; }
          25%  { opacity: 1; }
          100% { transform: translateX(100%); opacity: 0; }
        }
      `}</style>

      <div
        style={{
          ...styles.band,
          transform: flight ? 'scaleY(0.06)' : undefined,
          opacity: flight ? 0 : undefined,
          animation: flight ? 'none' : `rb-band ${ENTER_MS}ms cubic-bezier(.2,.9,.25,1.1) both`,
          transition: flight
            ? `transform ${FLY_MS * 0.7}ms ease-in, opacity ${FLY_MS * 0.7}ms ease-in`
            : undefined,
        }}
      >
        {!flight && <span style={styles.sweep} />}
      </div>

      <div
        ref={stageRef}
        style={{
          ...styles.stage,
          transform: flight
            ? `translate(-50%, -50%) translate(${flight.dx}px, ${flight.dy}px)`
              + ` scale(${flight.scale})`
            : 'translate(-50%, -50%)',
          opacity: flight ? 0 : undefined,
          animation: flight
            ? 'none'
            : `rb-text ${ENTER_MS + 120}ms cubic-bezier(.2,.9,.25,1) both`,
          transition: flight
            ? `transform ${FLY_MS}ms cubic-bezier(.45,.02,.25,1),`
              + ` opacity ${FLY_MS}ms cubic-bezier(.7,0,.9,.4)`
            : undefined,
        }}
      >
        <span style={styles.label}>ROUND</span>
        <span style={styles.number}>{shown}</span>
        <span style={styles.total}>/ {total}</span>
      </div>
    </div>
  )
}

const styles = {
  overlay: {
    position: 'fixed',
    inset: 0,
    // 득점 연출(9998)보다 아래. 순서 제어로 겹치지 않게 하지만, 만에 하나
    // 겹치더라도 더 중요한 쪽이 위에 오는 편이 낫다.
    zIndex: 9997,
    pointerEvents: 'none',
    overflow: 'hidden',
  },
  /**
   * 화면 전체를 덮지 않는다. 득점·조합 연출은 화면을 통째로 눌러 "지금은 이것만
   * 보라"고 하지만, 라운드는 한 판에 12번 오는 구분자라 그만한 무게가 없다.
   * 띠 안쪽만 가려 글자가 읽히게 하고 나머지는 그대로 둔다.
   */
  band: {
    position: 'absolute',
    left: 0,
    right: 0,
    top: '50%',
    height: 128,
    marginTop: -64,
    transformOrigin: 'center center',
    overflow: 'hidden',
    background:
      'linear-gradient(90deg, rgba(0,0,0,0) 0%, rgba(0,0,0,0.86) 14%,'
      + ' rgba(0,0,0,0.86) 86%, rgba(0,0,0,0) 100%)',
    boxShadow:
      'inset 0 1px 0 rgba(255,255,255,0.10), inset 0 -1px 0 rgba(255,255,255,0.10)',
    backdropFilter: 'blur(3px)',
    WebkitBackdropFilter: 'blur(3px)',
  },
  sweep: {
    position: 'absolute',
    inset: 0,
    background:
      'linear-gradient(100deg, transparent 35%, rgba(255,255,255,0.14) 50%, transparent 65%)',
    animation: `rb-sweep ${ENTER_MS + HOLD_MS}ms ease-out both`,
  },
  // 띠 안이라 가로로 놓는다. 세로로 쌓으면 띠를 벗어난다.
  stage: {
    position: 'absolute',
    left: '50%',
    top: '50%',
    display: 'flex',
    alignItems: 'baseline',
    gap: 16,
    whiteSpace: 'nowrap',
    transformOrigin: 'center center',
    willChange: 'transform, opacity',
  },
  label: {
    fontFamily: 'var(--font-mono)',
    fontSize: 'clamp(13px, 1.7vw, 18px)',
    fontWeight: 700,
    letterSpacing: '0.3em',
    color: 'var(--y-text-mute, var(--fg-mute))',
  },
  /**
   * 금색을 쓰지 않는다. 점수판에서 금색은 "지금 노릴 칸"이고 축하 연출도 금색이라,
   * 라운드까지 금색이면 무엇이 좋은 일이고 무엇이 그냥 안내인지 구별되지 않는다.
   */
  number: {
    fontSize: 'clamp(46px, 6.4vw, 82px)',
    fontWeight: 900,
    lineHeight: 1,
    color: 'var(--y-text, var(--fg))',
    textShadow: '0 2px 18px rgba(0,0,0,0.7)',
  },
  total: {
    fontSize: 'clamp(17px, 2.3vw, 26px)',
    fontWeight: 700,
    color: 'var(--y-text-mute, var(--fg-mute))',
  },
}
