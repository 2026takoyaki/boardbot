/**
 * 튜토리얼 코치 — 지금 나온 눈을 보고 무엇을 할 수 있는지 말해준다.
 *
 * 인트로 네 장으로 규칙은 설명했지만, 규칙을 안다고 첫 판을 굴릴 수 있는 건
 * 아니다. 처음 하는 사람이 막히는 지점은 "룰을 모르겠다"가 아니라 눈 다섯 개를
 * 앞에 두고 **이걸로 뭘 할 수 있는지 모르겠다** 쪽이다. 그래서 굴릴 때마다
 * 그 눈에 대해서만 이야기한다.
 *
 * 매번 문장이 달라지므로 반복으로 느껴지지 않는다 — 예전 튜토리얼이 지루했던
 * 이유는 안내가 많아서가 아니라 **같은 안내였기 때문**이다.
 *
 * LLM을 부르지 않는다. 규칙 기반이라 TTS·네트워크가 죽어도 돌고, 무엇보다
 * 틀린 조언을 하지 않는다.
 */

import { CATEGORY_LABELS, DISPLAY_CATEGORIES } from './yachtCategories'
import { faceGroups, longestRun, previewScore } from './yachtScoring'

const LABEL = Object.fromEntries(CATEGORY_LABELS)
const UPPER_KEY = ['ones', 'twos', 'threes', 'fours', 'fives', 'sixes']

// 희귀한 것부터. 한 굴림이 여러 조합을 만족할 수 있어(요트는 포카드이기도
// 하다) 더 말할 값어치가 있는 쪽을 먼저 본다.
const HAND_ORDER = ['yacht', 'large_straight', 'four_of_a_kind', 'full_house', 'small_straight']

// 숫자를 읽었을 때 받침이 있는지. 일·삼·육은 있고 이·사·오는 없다.
// "5이 세 개"는 눈에 거슬리고, TTS로 읽히면 더 티가 난다.
const HAS_FINAL_CONSONANT = { 1: true, 2: false, 3: true, 4: false, 5: false, 6: true }

function withJosa(text, afterConsonant, afterVowel) {
  const last = Number(String(text).slice(-1))
  return `${text}${HAS_FINAL_CONSONANT[last] ? afterConsonant : afterVowel}`
}

export function adviseRoll(state) {
  const dice = state?.dice_values
  if (!Array.isArray(dice) || dice.length !== 5) return null
  if (dice.some(value => value == null)) return null

  const open = DISPLAY_CATEGORIES.filter(key => state.available_categories?.includes(key))
  if (!open.length) return null

  const values = dice.map(Number)
  const rollsLeft = Math.max(0, 3 - Number(state.roll_count || 0))
  const ranked = open
    .map(key => [key, Number(previewScore(key, values)) || 0])
    .sort((a, b) => b[1] - a[1])
  const [bestKey, bestScore] = ranked[0]

  const completed = HAND_ORDER.find(
    key => open.includes(key) && Number(previewScore(key, values)) > 0,
  )
  if (completed) return handAdvice(completed, values, open, rollsLeft)
  if (rollsLeft === 0) return lastCallAdvice(bestKey, bestScore)
  return keepAdvice(values, open, bestKey, bestScore)
}

function handAdvice(key, values, open, rollsLeft) {
  const groups = faceGroups(values)
  const run = longestRun(values)
  const score = Number(previewScore(key, values))

  if (key === 'yacht') {
    return `요트입니다. 주사위 다섯 개가 모두 ${values[0]}입니다. `
      + '이 게임에서 가장 어려운 조합이니 더 굴리지 말고 Yacht 칸에 50점을 넣으세요.'
  }
  if (key === 'large_straight') {
    return `${withJosa(run.join('-'), '으로', '로')} 다섯 개가 이어졌습니다. `
      + '라지 스트레이트 30점이에요. 더 굴리면 깨지니 지금 L. Straight 칸에 넣으세요.'
  }
  if (key === 'four_of_a_kind') {
    const chase = rollsLeft > 0 && open.includes('yacht')
      ? ` 아니면 남은 한 개만 다시 굴려서 ${groups[0][0]} 다섯 개, 요트를 노려볼 수도 있어요.`
      : ''
    return `${withJosa(groups[0][0], '이', '가')} 네 개 모였습니다. `
      + `4 of a Kind 칸에 ${score}점을 넣을 수 있어요.${chase}`
  }
  if (key === 'full_house') {
    return `${withJosa(groups[0][0], '이', '가')} 세 개, `
      + `${withJosa(groups[1][0], '이', '가')} 두 개라서 풀 하우스입니다. `
      + `Full House 칸에 ${score}점을 넣을 수 있어요.`
  }
  // small_straight
  const chase = rollsLeft > 0 && open.includes('large_straight')
    ? ' 남은 한 개를 다시 굴려서 다섯 개를 잇는 라지 스트레이트 30점을 노려볼 수도 있어요.'
    : ''
  return `${withJosa(run.join('-'), '이', '가')} 이어져서 스몰 스트레이트 15점을 `
    + `확보했습니다.${chase}`
}

function lastCallAdvice(bestKey, bestScore) {
  if (bestScore > 0) {
    return '세 번을 다 굴렸으니 이제 칸을 골라야 합니다. '
      + `지금 눈으로는 ${LABEL[bestKey]} 칸이 ${bestScore}점으로 가장 큽니다.`
  }
  return '세 번을 다 굴렸는데 점수가 되는 칸이 없네요. '
    + '이럴 때는 나중에 채우기 어려운 칸 하나를 0점으로 비워두는 편이 손해가 적습니다.'
}

function keepAdvice(values, open, bestKey, bestScore) {
  const groups = faceGroups(values)
  const [topFace, topCount] = groups[0]
  const run = longestRun(values)
  const fallback = bestScore > 0
    ? `지금 멈춘다면 ${LABEL[bestKey]} 칸이 ${bestScore}점으로 가장 큽니다.`
    : '지금은 점수가 되는 칸이 없으니 한 번 더 굴려보는 게 좋겠어요.'

  if (topCount === 3) {
    const upperKey = UPPER_KEY[topFace - 1]
    const bonusNote = open.includes(upperKey)
      ? ` 그대로 ${LABEL[upperKey]} 칸에 넣어 상단 보너스를 쌓아도 좋고요.`
      : ''
    return `${withJosa(topFace, '이', '가')} 세 개 있습니다. `
      + `이 셋을 남기고 나머지 두 개만 다시 굴리면 4 of a Kind나 요트까지 `
      + `노려볼 수 있어요.${bonusNote}`
  }
  if (run.length === 3) {
    return `${withJosa(run.join('-'), '이', '가')} 이어져 있습니다. `
      + `이 셋을 남기고 나머지를 다시 굴리면 스트레이트를 노려볼 수 있어요. ${fallback}`
  }
  if (topCount === 2) {
    return `${withJosa(topFace, '이', '가')} 두 개 있습니다. `
      + `이 둘을 남기고 다시 굴려 개수를 늘려볼 수 있어요. ${fallback}`
  }
  return `아직 뚜렷한 조합이 없습니다. 큰 눈 한두 개만 남기고 나머지를 다시 굴려보세요. `
    + fallback
}
