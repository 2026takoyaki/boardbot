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

/** 상단 보너스 기준. 백엔드 scoring.py 의 UPPER_BONUS_* 와 같은 값. */
export const BONUS_THRESHOLD = 63
export const BONUS_SCORE = 35

/**
 * 점수판 각 칸 옆에 붙는 족보 그림.
 *
 * 족보 설명을 따로 띄우게 하면 아무도 안 본다 — 게임을 멈추고 창을 열어야
 * 하기 때문이다. 그래서 설명을 칸 옆에 그림으로 상주시킨다. 글로 쓰면 줄이
 * 길어져 점수판이 무너지므로 주사위 눈만 놓는다.
 */
export const CATEGORY_HINTS = {
  ones: { dice: [1] },
  twos: { dice: [2] },
  threes: { dice: [3] },
  fours: { dice: [4] },
  fives: { dice: [5] },
  sixes: { dice: [6] },
  full_house: { dice: [2, 2, 5, 5, 5], split: 2 },
  four_of_a_kind: { dice: [3, 3, 3, 3] },
  small_straight: { dice: [3, 4, 5, 6] },
  large_straight: { dice: [2, 3, 4, 5, 6] },
  yacht: { dice: [4, 4, 4, 4, 4] },
  // 조건이 없다는 것이 곧 설명이라 그림으로 그릴 것이 없다.
  choice: { dice: [], text: '조건 없음' },
}

/**
 * 규칙 화면의 족보 점수표.
 *
 * 상단 여섯 칸은 규칙이 하나라 한 줄로 묶는다. 점수판에서는 여섯 칸이지만
 * 외워야 할 것은 "고른 눈만 더한다" 하나뿐이다.
 */
export const HAND_RULES = [
  {
    name: 'Aces ~ Sixes',
    desc: '고른 숫자와 같은 눈만 모두 더합니다',
    dice: [1, 1, 3, 4, 6],
    mark: [0, 1],
    score: '해당 눈의 합',
    detail: 'Aces면 1 + 1 = 2점',
  },
  {
    name: '상단 보너스',
    desc: `Aces~Sixes 합계가 ${BONUS_THRESHOLD}점 이상이면 자동으로 받습니다`,
    dice: [],
    mark: [],
    score: `+${BONUS_SCORE}점`,
    detail: '각 칸에 눈 3개씩만 채워도 달성',
  },
  {
    name: 'Full House',
    desc: '같은 눈 3개 + 다른 같은 눈 2개',
    dice: [2, 2, 5, 5, 5],
    mark: [2, 3, 4],
    mark2: [0, 1],
    score: '주사위 5개 합',
    detail: '2+2+5+5+5 = 19점',
  },
  {
    name: '4 of a Kind',
    desc: '같은 눈 4개 이상',
    dice: [3, 3, 3, 3, 6],
    mark: [0, 1, 2, 3],
    score: '주사위 5개 합',
    detail: '3+3+3+3+6 = 18점',
  },
  {
    name: 'S. Straight',
    desc: '연속된 눈 4개',
    dice: [1, 3, 4, 5, 6],
    mark: [1, 2, 3, 4],
    score: '15점 고정',
    detail: '3-4-5-6 연속',
  },
  {
    name: 'L. Straight',
    desc: '연속된 눈 5개',
    dice: [2, 3, 4, 5, 6],
    mark: [0, 1, 2, 3, 4],
    score: '30점 고정',
    detail: '1-2-3-4-5 또는 2-3-4-5-6',
  },
  {
    name: 'Yacht',
    desc: '주사위 5개가 모두 같은 눈',
    dice: [4, 4, 4, 4, 4],
    mark: [0, 1, 2, 3, 4],
    score: '50점 고정',
    detail: '이 게임의 최고 족보',
  },
  {
    name: 'Choice',
    desc: '조건 없이 아무 조합이나',
    dice: [1, 3, 4, 5, 6],
    mark: [],
    score: '주사위 5개 합',
    detail: '애매한 조합을 버릴 때',
  },
]
