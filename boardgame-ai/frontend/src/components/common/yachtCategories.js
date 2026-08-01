/**
 * 요트 점수판 칸 정의. 화면과 프리뷰가 같은 값을 봐야 라운드 수가 어긋나지 않는다.
 *
 * 백엔드 games/yacht/scoring.py 의 ALL_CATEGORIES 와 같은 12칸이다.
 * bonus는 상단 합계에서 계산되는 결과라 여기서는 표시용 행일 뿐, 채우는 칸이 아니다.
 */
export const CATEGORY_LABELS = [
  ['ones', 'Aces'],
  ['twos', 'Twos'],
  ['threes', 'Threes'],
  ['fours', 'Fours'],
  ['fives', 'Fives'],
  ['sixes', 'Sixes'],
  ['bonus', '상단 보너스'],
  ['full_house', 'Full House'],
  ['four_of_a_kind', '4 of a Kind'],
  ['small_straight', 'S. Straight'],
  ['large_straight', 'L. Straight'],
  ['yacht', 'Yacht'],
  ['choice', 'Choice'],
]

export const UPPER = ['ones', 'twos', 'threes', 'fours', 'fives', 'sixes']

export const DISPLAY_CATEGORIES = CATEGORY_LABELS
  .filter(([key]) => key !== 'bonus')
  .map(([key]) => key)

/** 한 사람이 채우는 칸 수 = 전체 라운드 수. */
export const TOTAL_ROUNDS = DISPLAY_CATEGORIES.length
