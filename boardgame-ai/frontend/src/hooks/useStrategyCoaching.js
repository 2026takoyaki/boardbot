import { useCallback, useEffect, useState } from 'react'

/**
 * 전략 조언 on/off.
 *
 * 백엔드 StrategyAgent는 기본이 꺼짐이고(agents/strategy_agent.py), 게임
 * 세션이 새로 만들어질 때마다 그 기본값으로 돌아간다. 그래서 화면이 값을
 * 기억하고 **붙을 때마다 다시 알려준다** — 안 그러면 켜둔 채로 나갔다 들어온
 * 사람에게 조언이 조용히 사라진다.
 *
 * 켜고 끄는 것을 기억해두는 이유: 훈수를 원하는 사람은 계속 원하고, 싫은
 * 사람은 계속 싫다. 판마다 다시 켜게 하면 결국 아무도 안 쓴다.
 *
 * 요트 튜토리얼은 이 토글과 무관하게 코치가 항상 켜진다(처음 하는 사람에게
 * "조언 켜기"를 먼저 찾게 하는 것은 순서가 뒤집힌 요구다). 그 화면에서는
 * 버튼을 아예 감춘다 — 눌러도 아무 일이 없는 버튼이 제일 나쁘다.
 */
const KEY = 'boardbot.strategyCoaching'

function readStored() {
  try {
    if (typeof localStorage === 'undefined') return false
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function useStrategyCoaching(send, connected) {
  const [enabled, setEnabled] = useState(readStored)

  // connected를 의존성에 넣는 이유: send는 소켓이 OPEN이 아니면 조용히
  // 버린다. 마운트 직후엔 아직 연결 전이라 그냥 보내면 사라지고, 재연결
  // 뒤에도 백엔드는 꺼진 상태로 시작한다.
  useEffect(() => {
    if (!send || !connected) return
    send('SET_STRATEGY_COACHING', { enabled })
  }, [send, connected, enabled])

  const toggle = useCallback(() => {
    setEnabled(prev => {
      const next = !prev
      try {
        if (typeof localStorage !== 'undefined') {
          localStorage.setItem(KEY, next ? '1' : '0')
        }
      } catch {
        // 기억하지 못할 뿐, 이번 판 동안은 유지된다.
      }
      return next
    })
  }, [])

  return [enabled, toggle]
}
