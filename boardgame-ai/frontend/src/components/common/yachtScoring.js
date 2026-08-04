/**
 * 화면에 예상 점수를 미리 띄우기 위한 계산.
 *
 * 백엔드 games/yacht/scoring.py 와 같은 규칙이다. 확정 점수는 언제나 백엔드가
 * 계산한 값을 쓰고, 여기 있는 것은 "이 칸을 고르면 몇 점인지" 미리 보여주기
 * 위한 것이다 — 칸을 고르기 전에는 서버에 물어볼 것이 없기 때문이다.
 */

import { UPPER } from './yachtCategories'

const UPPER_FACE = { ones: 1, twos: 2, threes: 3, fours: 4, fives: 5, sixes: 6 }

export function previewScore(category, dice) {
  const values = dice.map(Number)
  const sum = values.reduce((acc, value) => acc + value, 0)
  const unique = new Set(values)
  const counts = faceGroups(values)
  const maxCount = counts[0]?.[1] ?? 0

  const face = UPPER_FACE[category]
  if (face) return values.filter(value => value === face).length * face
  if (category === 'choice') return sum
  if (category === 'four_of_a_kind') return maxCount >= 4 ? sum : 0
  if (category === 'full_house') {
    return counts.length === 2 && maxCount === 3 ? sum : 0
  }
  if (category === 'small_straight') return longestRun(values).length >= 4 ? 15 : 0
  if (category === 'large_straight') {
    return unique.size === 5 && (!unique.has(1) || !unique.has(6)) ? 30 : 0
  }
  if (category === 'yacht') return maxCount === 5 ? 50 : 0
  return '—'
}

export function upperSubtotal(scores) {
  return UPPER.reduce((sum, key) => sum + Number(scores?.[key] || 0), 0)
}

/**
 * [눈, 개수] 목록. 개수 많은 순, 같으면 큰 눈 먼저.
 *
 * 개수가 같을 때 큰 눈을 앞에 두는 것은 조언 때문이다 — 2가 둘, 5가 둘이면
 * 남길 값어치가 있는 쪽은 5다.
 */
export function faceGroups(dice) {
  const counts = new Map()
  for (const value of dice) {
    const face = Number(value)
    counts.set(face, (counts.get(face) || 0) + 1)
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || b[0] - a[0])
}

/** 가장 길게 이어진 눈들. [3,4,5] 처럼 실제 값을 돌려준다. */
export function longestRun(dice) {
  const sorted = [...new Set(dice.map(Number))].sort((a, b) => a - b)
  let best = []
  let current = []
  for (const value of sorted) {
    current = current.length && value === current[current.length - 1] + 1
      ? [...current, value]
      : [value]
    if (current.length > best.length) best = current
  }
  return best
}
