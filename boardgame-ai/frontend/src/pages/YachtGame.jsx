import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'
import { audio as audioApi, useAudioPlayer } from '../hooks/useAudioPlayer'
import {
  IconBook,
  IconExpand,
  IconMusic,
  IconRefresh,
  IconVolume,
} from '../components/common/Icons'
import BonusGauge from '../components/common/BonusGauge'
import DevPanel from '../components/common/DevPanel'
import DiceFace from '../components/common/DiceFace'
import RoundBanner from '../components/common/RoundBanner'
import ScoreMoment from '../components/common/ScoreMoment'
import YachtRules from '../components/common/YachtRules'
import YachtTutorial from '../components/common/YachtTutorial'
import { adviseRoll } from '../components/common/yachtCoach'
import { previewScore, upperSubtotal } from '../components/common/yachtScoring'
import {
  BONUS_SCORE,
  BONUS_THRESHOLD,
  CATEGORY_HINTS,
  CATEGORY_LABELS,
  DISPLAY_CATEGORIES,
  TOTAL_ROUNDS,
} from '../components/common/yachtCategories'

// 백엔드 YachtPhase.GAME_END 와 같은 값. 요트 페이즈는 대문자 규약이다.
const GAME_END_PHASE = 'GAME_END'
const SHOW_MANUAL_ROLL = import.meta.env.VITE_SHOW_MANUAL_ROLL === 'true'
const SHOW_DICE_MANUAL_INPUT = import.meta.env.VITE_SHOW_DICE_MANUAL_INPUT !== 'false'

/**
 * 튜토리얼 코치가 하는 말.
 *
 * "어떻게 조작하는가"는 한 판에 한 번이면 족하다 — 예전에는 플레이어가 바뀔
 * 때마다 같은 안내를 다시 읽혀서, 세 명이면 같은 말을 세 번 들었다.
 *
 * 대신 **굴릴 때마다 그 눈에 대해** 이야기한다(yachtCoach). 규칙을 안다고 첫
 * 판을 굴릴 수 있는 건 아니고, 처음 하는 사람이 막히는 곳은 눈 다섯 개를 앞에
 * 두고 이걸로 뭘 할 수 있는지 모르겠는 쪽이기 때문이다.
 */
const FIRST_ROLL_HINT = '주사위 5개를 트레이 안에 굴려주세요. 카메라가 눈을 읽습니다.'
const REROLL_MECHANIC = '남길 주사위는 트레이 한쪽의 킵 존으로 옮겨두고, 나머지만 다시 굴리면 됩니다.'

/**
 * 지금 화면에 띄워야 할 코치 문구의 식별자.
 *
 * 굴릴 때마다 달라져야 하므로 눈까지 넣는다. 같은 사람이 같은 횟수에 같은 눈을
 * 다시 볼 일은 없으니, 이 값이 바뀌었다는 것은 곧 새로 할 말이 생겼다는 뜻이다.
 */
function coachKeyOf(state) {
  if (!state) return null
  if (state.phase === 'AWAITING_ROLL') return 'roll'
  if (!state.dice_values?.length) return null
  return `advice:${state.current_player_id}:${state.roll_count}:${state.dice_values.join('')}`
}

/** 읽을 시간을 글자 수로 잡는다. 짧은 문구가 화면에 오래 남으면 그것도 잡음이다. */
function readingMs(text) {
  return Math.min(9000, Math.max(4200, text.length * 180))
}

const SCORE_CUES = new Set(['yacht_turn_transition', 'yacht_game_finish'])

const s = {
  page: {
    position: 'absolute',
    inset: 0,
    // 테이블 펠트. 회색 위의 회색이던 화면에 색과 깊이를 준다.
    background:
      'radial-gradient(ellipse 120% 100% at 30% 34%, var(--y-felt-hi), var(--y-felt-lo) 72%)',
    color: 'var(--y-text)',
    fontFamily: 'var(--font)',
    padding: '58px 0 0',
    boxSizing: 'border-box',
    overflow: 'hidden',
  },
  shell: {
    width: '100vw',
    height: 'calc(100vh - 58px)',
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 1.02fr) minmax(0, 0.98fr)',
    gap: 18,
    padding: '0 18px 18px',
    boxSizing: 'border-box',
    overflow: 'hidden',
  },
  topbar: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    height: 58,
    padding: '0 22px',
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    zIndex: 5,
  },
  brand: {
    fontSize: 20,
    fontWeight: 850,
    letterSpacing: '-0.02em',
    color: 'var(--y-text)',
  },
  topActions: { marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 9 },
  iconButton: active => ({
    width: 40,
    height: 40,
    border: `1px solid ${active ? 'var(--y-gold)' : 'var(--y-line)'}`,
    borderRadius: 12,
    background: active ? 'color-mix(in oklch, var(--y-gold) 20%, transparent)' : 'transparent',
    color: active ? 'var(--y-gold)' : 'var(--y-text-mute)',
    display: 'grid',
    placeItems: 'center',
    cursor: 'pointer',
    padding: 0,
  }),
  topButton: {
    border: '1px solid var(--y-line)',
    borderRadius: 12,
    background: 'transparent',
    color: 'var(--y-text-soft)',
    padding: '10px 15px',
    fontSize: 15,
    fontWeight: 700,
    cursor: 'pointer',
  },
  disabled: { opacity: 0.4, cursor: 'not-allowed' },

  main: {
    minWidth: 0,
    padding: '18px 8px 10px 24px',
    display: 'flex',
    flexDirection: 'column',
    gap: 18,
    overflow: 'hidden',
  },
  turnRow: { display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' },
  /**
   * 누구 차례인지.
   *
   * 원색 금색으로 채우고 같은 색 드롭섀도까지 두니 화면에서 여기만 형광펜을
   * 그은 것처럼 튀었다 — 글로우를 가진 요소가 이것 하나뿐이라 더 그랬다.
   * 게다가 점수판에서 금색은 "지금 누를 만한 칸"에 쓰기로 했으므로, 채움까지
   * 금색이면 왼쪽의 안내와 오른쪽의 선택지가 같은 무게로 보인다.
   *
   * 존재감은 채도가 아니라 크기와 굵기로 가져간다. 색은 점 하나만 남긴다.
   */
  turnBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 11,
    background: 'color-mix(in oklch, var(--y-gold) 10%, oklch(0.26 0.028 168))',
    border: '1px solid color-mix(in oklch, var(--y-gold) 30%, transparent)',
    color: 'var(--y-text)',
    borderRadius: 999,
    padding: '10px 21px',
    fontSize: 25,
    fontWeight: 850,
  },
  turnDot: {
    width: 10,
    height: 10,
    borderRadius: '50%',
    background: 'var(--y-gold)',
    flexShrink: 0,
  },
  roundText: {
    fontSize: 20,
    fontWeight: 750,
    color: 'var(--y-text-soft)',
    // 라운드 배너가 이 자리로 날아와 앉는다. 날아오는 동안은 비워둬야 같은
    // 것이 두 개로 보이지 않는다.
    transition: 'opacity 260ms ease',
  },

  rollRow: { display: 'flex', alignItems: 'center', gap: 11 },
  rollLabel: { fontSize: 16, fontWeight: 750, color: 'var(--y-text-mute)' },
  clip: active => ({
    width: 17,
    height: 17,
    borderRadius: '50%',
    background: active ? 'var(--y-gold)' : 'transparent',
    border: `2px solid ${active ? 'var(--y-gold)' : 'var(--y-line)'}`,
    boxShadow: active ? '0 0 0 4px color-mix(in oklch, var(--y-gold) 18%, transparent)' : 'none',
  }),

  tray: {
    width: 'min(560px, 100%)',
    padding: '22px 20px',
    background: 'oklch(0.235 0.035 168)',
    border: '1px solid var(--y-line-soft)',
    borderRadius: 22,
    boxShadow: 'inset 0 2px 14px rgba(0,0,0,0.35)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 14,
  },
  editDie: {
    padding: 0,
    border: 0,
    background: 'transparent',
    cursor: 'pointer',
    borderRadius: 16,
    lineHeight: 0,
  },
  // 버튼은 폭을 아낄 이유가 없다. 태블릿을 서서 누르는 화면이라 넓고 큰 쪽이 낫다.
  actionRow: {
    width: 'min(560px, 100%)',
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 12,
  },
  bigButton: enabled => ({
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    padding: '17px 18px',
    fontSize: 18,
    fontWeight: 800,
    color: enabled ? 'var(--y-text)' : 'var(--y-text-mute)',
    background: enabled ? 'var(--y-panel-head)' : 'transparent',
    border: `1px solid ${enabled ? 'var(--y-line)' : 'var(--y-line-soft)'}`,
    borderRadius: 16,
    cursor: enabled ? 'pointer' : 'not-allowed',
    opacity: enabled ? 1 : 0.5,
  }),
  primaryButton: {
    background: 'linear-gradient(180deg, var(--y-gold), var(--y-gold-deep))',
    borderColor: 'transparent',
    color: 'oklch(0.20 0.03 55)',
  },

  messageSlot: { marginTop: 'auto', paddingTop: 12 },
  statusMessage: {
    width: 'min(620px, 100%)',
    padding: '15px 18px',
    borderRadius: 14,
    background: 'oklch(0.24 0.03 168 / 0.8)',
    border: '1px solid var(--y-line-soft)',
    color: 'var(--y-text-soft)',
    fontSize: 18,
    fontWeight: 650,
    lineHeight: 1.5,
  },
  coach: {
    width: 'min(620px, 100%)',
    display: 'flex',
    alignItems: 'flex-start',
    gap: 14,
    padding: '18px 20px',
    borderRadius: 16,
    background: 'color-mix(in oklch, var(--y-gold) 16%, oklch(0.26 0.03 168))',
    border: '1px solid color-mix(in oklch, var(--y-gold) 45%, transparent)',
    boxShadow: '0 10px 30px rgba(0,0,0,0.3)',
    cursor: 'pointer',
  },
  coachDot: {
    flexShrink: 0,
    marginTop: 4,
    width: 10,
    height: 10,
    borderRadius: '50%',
    background: 'var(--y-gold)',
  },
  // 글자가 작아 눈에 안 들어온다는 지적이 있었다. 본문보다 확실히 크게 둔다.
  coachText: { fontSize: 21, fontWeight: 750, lineHeight: 1.5, color: 'var(--y-text)' },
  editHint: {
    width: 'min(560px, 100%)',
    padding: '14px 16px',
    borderRadius: 14,
    border: '1px solid color-mix(in oklch, var(--y-gold) 40%, transparent)',
    background: 'color-mix(in oklch, var(--y-gold) 12%, transparent)',
    color: 'var(--y-text-soft)',
    fontSize: 16,
    fontWeight: 650,
    lineHeight: 1.45,
  },

  // ── 점수판 ──────────────────────────────────────────────────────────────
  // 배경과 같은 색이라 구분이 안 된다는 지적. 색상(따뜻한 톤)과 밝기를 함께
  // 띄우고 테두리·그림자로 판을 하나 올려놓은 것처럼 만든다.
  aside: {
    minWidth: 0,
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    background: 'var(--y-panel)',
    border: '1px solid var(--y-line)',
    borderRadius: 20,
    boxShadow: '0 18px 44px rgba(0,0,0,0.38)',
    overflow: 'hidden',
  },
  asideHead: {
    flexShrink: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    padding: '14px 16px',
    background: 'var(--y-panel-head)',
    borderBottom: '1px solid var(--y-line)',
  },
  asideTitle: { fontSize: 19, fontWeight: 850, color: 'var(--y-text)' },
  // 금색은 점수판 안에서 "지금 노릴 칸"과 보너스가 쓰는 색이다. 버튼까지
  // 금색이면 셋이 서로 경쟁한다. 여기는 판을 여는 손잡이일 뿐이라 물러선다.
  headButton: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 8,
    padding: '10px 15px',
    fontSize: 15,
    fontWeight: 750,
    color: 'var(--y-text-soft)',
    background: 'transparent',
    border: '1px solid var(--y-line)',
    borderRadius: 12,
    cursor: 'pointer',
  },
  sheetWrap: { flex: 1, minHeight: 0, overflowY: 'auto' },
  // height 100%면 표가 남는 높이를 행에 고르게 나눠 가진다. 예전에는 컨테이너를
  // 재어 padding을 계산했는데, 재는 시점을 맞추기 어려워 판 아래가 비곤 했다.
  // 넘칠 때는 표가 내용 높이를 지키므로 감싼 쪽이 스크롤한다.
  table: { width: '100%', height: '100%', borderCollapse: 'collapse', fontSize: 18 },
  /**
   * 행의 상태는 배경으로 갈린다.
   *
   * 숫자 색만 다르면 열세 줄을 훑을 때 티가 안 난다. 이미 채운 칸은 판에 눌러
   * 박은 것처럼 어둡게, 지금 제일 큰 칸은 행 전체를 금색으로, 0점밖에 안 되는
   * 칸은 통째로 흐리게 — 색이 아니라 밝기가 다르면 곁눈질로도 갈린다.
   */
  row: ({ alt, filled, suggested, zero, clickable }) => {
    if (suggested) {
      return {
        // 아래에만 금색 선을 그으면 줄이 밑줄 그어진 것처럼 보여, 강조가 아니라
        // 표의 구분선이 하나 더 생긴 꼴이 된다. 구분선은 다른 줄과 똑같이 두고
        // 대신 면 자체를 안에서 빛나게 한다.
        background:
          'linear-gradient(180deg, color-mix(in oklch, var(--y-gold) 30%, var(--y-panel)),'
          + ' color-mix(in oklch, var(--y-gold) 19%, var(--y-panel)))',
        boxShadow:
          'inset 0 0 26px color-mix(in oklch, var(--y-gold) 26%, transparent),'
          + ' inset 0 -1px 0 var(--y-line-soft)',
        cursor: 'pointer',
      }
    }
    if (filled) {
      return {
        background: 'oklch(0.222 0.010 78)',
        boxShadow: 'inset 0 -1px 0 var(--y-line-soft)',
        cursor: 'default',
      }
    }
    return {
      background: alt ? 'var(--y-row-alt)' : 'transparent',
      boxShadow: 'inset 0 -1px 0 var(--y-line-soft)',
      cursor: clickable ? 'pointer' : 'default',
      // 넣어봐야 0점인 칸. 고를 수는 있으니 지우지는 않고 뒤로 물린다.
      opacity: zero ? 0.42 : 1,
    }
  },
  tdName: { padding: '10px 8px 10px 16px' },
  tdScore: {
    padding: '10px 16px 10px 8px',
    textAlign: 'right',
    fontVariantNumeric: 'tabular-nums',
    fontWeight: 750,
    whiteSpace: 'nowrap',
  },
  nameCell: { display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 },
  label: ({ filled, suggested }) => ({
    // 채운 칸은 라벨을 물린다 — 그 줄에서 볼 것은 이제 기록된 숫자뿐이다.
    fontWeight: suggested ? 850 : 750,
    color: filled ? 'var(--y-text-mute)' : suggested ? 'var(--y-text)' : 'var(--y-text-soft)',
    whiteSpace: 'nowrap',
  }),
  hintRow: dim => ({ display: 'inline-flex', gap: 3, opacity: dim ? 0.22 : 0.85 }),
  hintText: dim => ({
    fontSize: 12,
    fontWeight: 700,
    color: 'var(--y-text-mute)',
    opacity: dim ? 0.4 : 1,
  }),
  scoreValue: ({ filled, suggested }) => ({
    color: suggested ? 'var(--y-gold)' : filled ? 'var(--y-text)' : 'var(--y-text-mute)',
    fontWeight: suggested || filled ? 850 : 700,
  }),
  // 채운 칸에만 붙는 표식. "이 줄은 끝났다"를 배경 말고 하나 더 말해준다.
  doneMark: {
    marginRight: 8,
    fontSize: 13,
    color: 'var(--y-text-mute)',
    opacity: 0.75,
  },
  /**
   * 요약 줄(보너스·합계)은 프레임이지 선택지가 아니다.
   *
   * 예전에는 보너스가 금색 틴트라 추천 칸과 같은 색이었다. 하나는 "정보"고
   * 하나는 "눌러라"인데 같은 색을 쓰니, 눌러야 하는 영역과 판의 테두리가
   * 갈리지 않았다. 요약 줄은 색을 빼고 중립 밴드로 내리되, 위쪽에 굵은 선을
   * 그어 목록이 여기서 한 번 끊긴다는 것을 구조로 말한다.
   */
  frameRow: {
    background: 'var(--y-panel-head)',
    borderTop: '2px solid var(--y-line)',
  },
  frameCell: { padding: '9px 16px' },
  frameLabel: {
    fontSize: 13,
    fontWeight: 800,
    letterSpacing: '0.06em',
    color: 'var(--y-text-mute)',
    whiteSpace: 'nowrap',
  },
  bonusTop: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 10,
    marginBottom: 7,
  },
  bonusNums: {
    marginLeft: 'auto',
    fontFamily: 'var(--font-mono)',
    fontSize: 15,
    fontWeight: 750,
    color: 'var(--y-text-soft)',
    fontVariantNumeric: 'tabular-nums',
  },
  bonusNow: { fontSize: 18, fontWeight: 850, color: 'var(--y-text)' },
  bonusBadge: earned => ({
    display: 'inline-flex',
    alignItems: 'center',
    height: 22,
    padding: '0 9px',
    borderRadius: 999,
    background: earned ? 'var(--y-gold)' : 'transparent',
    border: `1px solid ${earned ? 'transparent' : 'var(--y-line)'}`,
    color: earned ? 'oklch(0.20 0.03 55)' : 'var(--y-text-mute)',
    fontSize: 12,
    fontWeight: 850,
    whiteSpace: 'nowrap',
  }),
  // 합계는 판의 바닥이다. 굵은 선 위에 올려 목록의 일부가 아님을 분명히 한다.
  totalRow: {
    background: 'var(--y-panel-head)',
    borderTop: '2px solid var(--y-line)',
  },
  totalLabel: {
    fontSize: 13,
    fontWeight: 800,
    letterSpacing: '0.06em',
    color: 'var(--y-text-mute)',
  },
  totalValue: {
    fontSize: 26,
    fontWeight: 900,
    color: 'var(--y-text)',
    fontVariantNumeric: 'tabular-nums',
  },

  // ── 오버레이 ────────────────────────────────────────────────────────────
  shade: {
    position: 'fixed',
    inset: 0,
    zIndex: 55,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 16,
    background: 'oklch(0.14 0.02 168 / 0.78)',
    backdropFilter: 'blur(3px)',
    WebkitBackdropFilter: 'blur(3px)',
  },
  leaderboard: {
    width: '100%',
    maxHeight: '100%',
    display: 'flex',
    flexDirection: 'column',
    background: 'var(--y-panel)',
    border: '1px solid var(--y-line)',
    borderRadius: 22,
    overflow: 'hidden',
    boxShadow: '0 30px 80px rgba(0,0,0,0.55)',
  },
  leaderboardHead: {
    flexShrink: 0,
    height: 64,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0 20px',
    background: 'var(--y-panel-head)',
    borderBottom: '1px solid var(--y-line)',
    fontSize: 21,
    fontWeight: 850,
  },
  close: {
    width: 40,
    height: 40,
    borderRadius: 12,
    border: '1px solid var(--y-line)',
    background: 'transparent',
    color: 'var(--y-text-soft)',
    fontSize: 17,
    cursor: 'pointer',
  },
  /**
   * 열은 판으로 세우지 않는다.
   *
   * 배경·테두리·둥근 모서리·그림자를 겹겹이 얹으니 창 안에 창이 셋 더 생긴 꼴이
   * 되어 오히려 복잡해졌다. 구분에 필요한 건 층이 아니라 **뚜렷한 세로선** 하나다
   * — 가로줄이 세 사람을 관통하는 것만 끊어주면 된다.
   */
  boardGrid: { flex: 1, minHeight: 0, overflowY: 'auto', display: 'grid' },
  boardColumn: divided => ({
    minWidth: 0,
    // 원래 1px 흐린 선이라 가로줄에 묻혔다. 굵기와 밝기를 함께 올린다.
    // 마지막 열은 오른쪽이 곧 창 테두리라 선을 하나 더 그을 이유가 없다.
    borderRight: divided ? '3px solid var(--y-line)' : undefined,
  }),
  boardName: {
    display: 'flex',
    alignItems: 'center',
    gap: 9,
    padding: '12px 16px',
    fontSize: 18,
    fontWeight: 850,
    color: 'var(--y-text)',
    background: 'var(--y-panel-head)',
    borderBottom: '1px solid var(--y-line)',
  },
  boardRank: leading => ({
    display: 'inline-flex',
    alignItems: 'center',
    height: 22,
    padding: '0 9px',
    borderRadius: 999,
    background: leading ? 'var(--y-gold)' : 'transparent',
    border: `1px solid ${leading ? 'transparent' : 'var(--y-line)'}`,
    color: leading ? 'oklch(0.20 0.03 55)' : 'var(--y-text-mute)',
    fontSize: 12,
    fontWeight: 850,
    fontVariantNumeric: 'tabular-nums',
    flexShrink: 0,
  }),

  // ── 결과 화면 ───────────────────────────────────────────────────────────
  endShell: {
    width: '100vw',
    height: 'calc(100vh - 58px)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  endPanel: { width: 'min(470px, calc(100vw - 40px))' },
  winner: { fontSize: 38, fontWeight: 850, textAlign: 'center', marginBottom: 36 },
  finalTitle: {
    fontSize: 15,
    fontWeight: 800,
    letterSpacing: '0.1em',
    color: 'var(--y-gold)',
    marginBottom: 16,
  },
  rankRow: place => ({
    display: 'flex',
    alignItems: 'center',
    gap: 14,
    background: place === 1 ? 'color-mix(in oklch, var(--y-gold) 18%, var(--y-panel))' : 'var(--y-panel)',
    border: `1px solid ${place === 1 ? 'var(--y-gold)' : 'var(--y-line)'}`,
    borderRadius: 14,
    padding: '15px 20px',
    marginBottom: 11,
    fontSize: 21,
    fontWeight: 750,
  }),
  rankPlace: { width: 26, color: 'var(--y-text-mute)', fontFamily: 'var(--font-mono)' },
  rankTotal: { marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontWeight: 850 },
  endActions: { display: 'flex', gap: 12, justifyContent: 'center', marginTop: 26, flexWrap: 'wrap' },
  endButton: {
    padding: '14px 22px',
    fontSize: 16,
    fontWeight: 750,
    color: 'var(--y-text)',
    background: 'var(--y-panel-head)',
    border: '1px solid var(--y-line)',
    borderRadius: 14,
    cursor: 'pointer',
  },
  endText: {
    textAlign: 'center',
    color: 'var(--y-text-soft)',
    fontSize: 18,
    lineHeight: 1.6,
    marginBottom: 28,
  },
}

export default function YachtGame({ players, tutorialMode = false, onExit, onChangePlayers }) {
  const [leaderboardOpen, setLeaderboardOpen] = useState(false)
  const [rulesOpen, setRulesOpen] = useState(false)
  const [introOpen, setIntroOpen] = useState(tutorialMode)
  const [coach, setCoach] = useState(null)
  const [diceEditMode, setDiceEditMode] = useState(false)
  const [editDiceValues, setEditDiceValues] = useState([1, 1, 1, 1, 1])
  const [ttsEnabled, setTtsEnabled] = useState(true)
  const [bgmEnabled, setBgmEnabled] = useState(true)
  const [turnPulseKey, setTurnPulseKey] = useState(0)
  // 라운드 배너가 상시 표시 자리로 날아오는 동안은 그 자리를 비워둔다.
  const [roundBannerActive, setRoundBannerActive] = useState(false)
  const roundAnchorRef = useRef(null)
  const [recentScore, setRecentScore] = useState(null)
  // 연출 대기열. 득점과 보너스처럼 한 번에 두 사건이 겹칠 수 있어 순서대로 튼다.
  // 밀리면 오래된 것부터 버린다 — 지나간 턴의 연출을 뒤늦게 보여줄 이유가 없다.
  const [momentQueue, setMomentQueue] = useState([])
  const startedRef = useRef(false)
  const previousRollRef = useRef(null)
  const momentSeqRef = useRef(0)
  // 한 판 동안 이미 보여준 조작 안내. 플레이어가 바뀌어도 다시 뜨지 않는다.
  const seenCoachRef = useRef(new Set())
  const lastCoachKeyRef = useRef(null)

  // 득점 순간을 diff로 추론하지 않고 백엔드가 보낸 cue를 그대로 받는다.
  // 같은 payload의 duration_ms로 조명·TTS가 함께 움직이므로 세 채널이 어긋나지 않는다.
  const enqueueMoment = useCallback((payload) => {
    // 같은 종류가 연달아 와도 애니메이션이 다시 돌도록 매번 다른 키를 붙인다.
    const keyed = { ...payload, momentKey: `${payload.cue}-${momentSeqRef.current++}` }
    setMomentQueue(queue => [...queue, keyed].slice(-2))
  }, [])

  const dismissMoment = useCallback(() => setMomentQueue(queue => queue.slice(1)), [])

  const handleCue = useCallback((payload) => {
    if (!payload) return

    // 주사위가 멈춘 순간의 축하. 아직 점수를 고르기 전이라 점수판은 건드리지
    // 않는다. 조명도 이 큐에는 반응하지 않는다 — 굴림 구간은 인식이 걸린 곳이다.
    if (payload.cue === 'yacht_hand_achieved') {
      enqueueMoment(payload)
      playLocalSfx('score_select')
      return
    }

    // 상단 보너스. 득점 연출 바로 뒤에 이어진다.
    if (payload.cue === 'yacht_bonus_achieved') {
      enqueueMoment(payload)
      return
    }

    if (!SCORE_CUES.has(payload.cue)) return
    const variant = payload.variant || 'normal'
    const isFinish = payload.cue === 'yacht_game_finish'

    setTurnPulseKey(key => key + 1)
    setRecentScore({
      seq: momentSeqRef.current++,
      playerId: payload.scorer_id,
      category: payload.category,
      score: payload.score,
      variant,
      // 인라인 하이라이트는 연출 전체 길이를 넘기지 않는다.
      holdMs: Math.min(1100, payload.duration_ms || 1100),
    })
    playLocalSfx(isFinish ? 'game_end' : 'score_select')

    // 상단 숫자든 족보든 "+n점"은 똑같이 뜬다. 어떤 칸이냐에 따라 반응이
    // 달라지면 플레이어는 규칙을 하나 더 외워야 한다.
    // 게임 종료만 예외 — 전용 결과 화면이 따로 있어 겹치지 않는다.
    if (!isFinish) enqueueMoment(payload)
  }, [enqueueMoment])

  const { state, connected, messages, send } = useWebSocket('/ws/yacht', {
    onAudioMessage: audioApi.enqueue,
    onCue: handleCue,
  })
  // /ws/yacht 채널로도 audio_ack가 흐르도록 등록 (FSM 멘트는 이 채널로 옴).
  useAudioPlayer(send)

  useEffect(() => {
    audioApi.setTtsEnabled(true)
  }, [])

  // 재연결 시 START_YACHT를 다시 보낼 수 있도록 ref를 리셋.
  useEffect(() => {
    if (!connected) startedRef.current = false
  }, [connected])

  // 백엔드가 보낸 hello 수신을 확인한 뒤에 START_YACHT 송신.
  const helloSeen = useMemo(
    () => messages.some(m => m.msg_type === 'hello'),
    [messages],
  )

  useEffect(() => {
    if (!connected || !helloSeen) return
    if (startedRef.current) return
    startedRef.current = true
    send('START_YACHT', { players: normalizePlayers(players), tutorial_mode: tutorialMode })
  }, [connected, helloSeen, players, send, tutorialMode])

  // 굴림 효과음만 state diff로 남는다. 굴림에는 cue가 없고, 같은 턴 안에서
  // roll_count 증가만 보므로 재연결로 되살아나지 않는다.
  useEffect(() => {
    if (!state?.players?.length) return
    const previous = previousRollRef.current
    const current = {
      playerId: state.current_player_id,
      rollCount: Number(state.roll_count || 0),
    }
    if (previous && previous.playerId === current.playerId
      && current.rollCount > previous.rollCount) {
      playLocalSfx('dice_roll')
    }
    previousRollRef.current = current
  }, [state])

  useEffect(() => {
    if (!recentScore) return undefined
    const timeout = window.setTimeout(() => setRecentScore(null), recentScore.holdMs)
    return () => window.clearTimeout(timeout)
  }, [recentScore])

  // 판이 끝나면 남은 연출을 버린다.
  //
  // 튜토리얼 완료 화면도 포함해야 한다. 그 화면은 ScoreMoment를 렌더하지 않아
  // 대기열이 그대로 얼어붙는데, 거기서 "게임 시작하기"를 누르면 본게임 첫
  // 화면에 방금 판의 "요트"가 뒤늦게 터진다. (재현 확인함)
  useEffect(() => {
    if (state?.phase !== GAME_END_PHASE && !state?.tutorial_complete) return
    setMomentQueue([])
    setRecentScore(null)
  }, [state?.phase, state?.tutorial_complete])

  const isTutorial = Boolean(state?.tutorial_mode)

  // 튜토리얼을 끝내고 정식 게임으로 넘어가면 인트로는 더 볼 것이 없다.
  useEffect(() => {
    if (state && state.tutorial_mode === false) setIntroOpen(false)
  }, [state?.tutorial_mode, state])

  useEffect(() => {
    if (!isTutorial || introOpen) return
    const key = coachKeyOf(state)
    if (key === lastCoachKeyRef.current) return
    lastCoachKeyRef.current = key

    // 굴리기 전 안내는 조작법이라 처음 한 번이면 된다. 두 번째 사람부터는
    // 여기서 비워야 앞사람 굴림에 대한 조언이 남아 있지 않는다.
    if (key === 'roll' || !key) {
      const first = key === 'roll' && !seenCoachRef.current.has('roll')
      if (first) seenCoachRef.current.add('roll')
      setCoach(first ? { key, text: FIRST_ROLL_HINT, transient: true } : null)
      return
    }

    const advice = adviseRoll(state)
    if (!advice) { setCoach(null); return }
    // 처음 굴린 사람에게만 "어떻게 다시 굴리는가"를 앞에 붙인다. 조언 자체는
    // 매번 다르므로 반복으로 느껴지지 않지만, 조작법은 한 번이면 족하다.
    const needsMechanic = !seenCoachRef.current.has('reroll')
    seenCoachRef.current.add('reroll')
    setCoach({
      key,
      text: needsMechanic ? `${REROLL_MECHANIC} ${advice}` : advice,
      // 조언은 지금 테이블에 놓인 눈에 대한 말이라, 눈이 그대로인 동안은
      // 남아 있어야 한다. 시간이 지나 사라지면 읽던 사람만 손해다.
      transient: false,
    })
  }, [isTutorial, introOpen, state])

  useEffect(() => {
    if (!coach) return undefined
    if (connected) send('TTS_REQUEST', { text: coach.text, interrupt_existing: true })
    if (!coach.transient) return undefined
    const timer = window.setTimeout(() => setCoach(null), readingMs(coach.text))
    return () => window.clearTimeout(timer)
  }, [coach, connected, send])

  const currentPlayer = useMemo(
    () => state?.players?.find(p => p.player_id === state.current_player_id),
    [state],
  )
  // 점수판을 다 채우면 filled+1이 13이 되어 "13 / 12"로 넘어간다. 마지막에서 멈춘다.
  const round = Math.min(
    TOTAL_ROUNDS,
    (currentPlayer?.scores ? Object.keys(currentPlayer.scores).length : 0) + 1,
  )
  const ranked = useMemo(
    () => [...(state?.players || [])].sort((a, b) => b.total - a.total),
    [state],
  )
  // 동점은 같은 순위를 나눠 갖는다. 백엔드 _ranking과 같은 규칙이라 역전 연출이
  // 보여주는 순위와 전체 점수판의 순위가 어긋나지 않는다.
  const ranks = useMemo(() => {
    const players = state?.players || []
    const totals = [...new Set(players.map(p => p.total))].sort((a, b) => b - a)
    const rankOfTotal = new Map(totals.map((total, index) => [total, index + 1]))
    return new Map(players.map(p => [p.player_id, rankOfTotal.get(p.total)]))
  }, [state])
  const statusMessage = useMemo(() => {
    const latestError = messages.find(m => m.msg_type === 'error')
    return latestError?.payload?.message || state?.last_message
  }, [messages, state?.last_message])
  const canUndo = state?.can_undo ?? true
  const canManualRoll =
    SHOW_MANUAL_ROLL &&
    ['AWAITING_ROLL', 'AWAITING_KEEP'].includes(state?.phase) &&
    Number(state?.remaining_rolls || 0) > 0
  const canManualDiceInput =
    SHOW_DICE_MANUAL_INPUT &&
    (
      (state?.phase === 'AWAITING_ROLL' && Number(state?.remaining_rolls || 0) > 0) ||
      ['AWAITING_KEEP', 'AWAITING_SCORE'].includes(state?.phase)
    )

  // 수동 수정이 불가능한 상태로 바뀌면(턴 종료·새 굴림 등) 편집 모드를 자동 종료.
  useEffect(() => {
    if (diceEditMode && !canManualDiceInput) setDiceEditMode(false)
  }, [diceEditMode, canManualDiceInput])

  // 인트로 낭독. 문장이 아니라 line_id를 보낸다 — 문장의 소유자는 백엔드
  // (agents/lines.py)라 페르소나를 바꾸면 여기를 건드리지 않아도 말투가 바뀐다.
  const narrateLine = useCallback((lineId) => {
    if (!connected || !lineId) return
    send('NARRATION_REQUEST', { line_id: lineId, interrupt_existing: true })
  }, [connected, send])

  // 새 판으로 넘어갈 때는 앞 판의 흔적을 남기지 않는다. 대기열에 남은 연출은
  // 새 판 첫 화면에서 뒤늦게 터지고, 코치는 이미 설명한 것을 또 설명한다.
  const resetForNewGame = () => {
    setMomentQueue([])
    setRecentScore(null)
    setCoach(null)
    lastCoachKeyRef.current = null
  }

  const startFullGame = () => {
    resetForNewGame()
    send('START_YACHT', { players: normalizePlayers(players), tutorial_mode: false })
  }

  const restartTutorial = () => {
    resetForNewGame()
    seenCoachRef.current.clear()
    setIntroOpen(true)
    send('RESTART')
  }

  const toggleBgm = () => {
    const next = !bgmEnabled
    setBgmEnabled(next)
    send('BGM_SET', { enabled: next })
  }

  const toggleTts = () => {
    const next = !ttsEnabled
    setTtsEnabled(next)
    audioApi.setTtsEnabled(next)
  }

  const startDiceEdit = () => {
    setEditDiceValues(
      state?.dice_values?.length === 5
        ? state.dice_values.map(value => Number(value) || 1)
        : [1, 1, 1, 1, 1],
    )
    setDiceEditMode(true)
  }

  // 주사위를 누를 때마다 눈을 1씩 증가 (6 다음 1로 순환).
  const cycleEditDie = index => {
    setEditDiceValues(prev => prev.map((value, i) => (i === index ? (value % 6) + 1 : value)))
  }

  const applyDiceEdit = () => {
    send('MANUAL_DICE_INPUT', { dice_values: editDiceValues.map(Number) })
    setDiceEditMode(false)
  }

  const exitGame = () => {
    audioApi.setTtsEnabled(true)
    send('BGM_STOP')
    onExit?.()
  }

  const palette = <style>{PALETTE_CSS}</style>

  if (!state) {
    return (
      <div style={s.page} className="yacht-root">
        {palette}
        <div style={s.topbar}><span style={s.brand}>요트다이스</span></div>
        <div style={s.endShell}>
          <div style={s.endText}>{connected ? '게임 준비 중…' : '서버 연결 중…'}</div>
        </div>
      </div>
    )
  }

  if (state.phase === GAME_END_PHASE) {
    const winner = ranked[0]
    return (
      <div style={s.page} className="yacht-root">
        {palette}
        <div style={s.endShell}>
          <div style={s.endPanel}>
            <div style={s.winner}>{winner?.playername || '플레이어'} 님 승리!</div>
            <div style={s.finalTitle}>최종 점수</div>
            {ranked.map((player, index) => (
              <div key={player.player_id} style={s.rankRow(index + 1)}>
                <span style={s.rankPlace}>{index + 1}</span>
                <strong>{player.playername}</strong>
                <span style={s.rankTotal}>{player.total}</span>
              </div>
            ))}
            <div style={s.endActions}>
              <button style={s.endButton} onClick={onChangePlayers}>플레이어 변경</button>
              <button style={s.endButton} onClick={exitGame}>게임 변경</button>
              <button style={s.endButton} onClick={() => send('RESTART')}>게임 재시작</button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (state.tutorial_complete) {
    return (
      <div style={s.page} className="yacht-root">
        {palette}
        <div style={s.endShell}>
          <div style={s.endPanel}>
            <div style={s.winner}>튜토리얼 완료</div>
            <div style={s.endText}>
              모든 플레이어가 한 번씩 굴리고 점수를 기록했습니다.
              이제 정식 게임을 시작해볼까요?
            </div>
            <div style={s.endActions}>
              <button style={s.endButton} onClick={exitGame}>게임 선택화면</button>
              <button style={s.endButton} onClick={restartTutorial}>튜토리얼 한 번 더</button>
              <button
                style={{ ...s.endButton, ...s.primaryButton }}
                onClick={startFullGame}
              >
                게임 시작하기
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  const diceValues = state.dice_values?.length ? state.dice_values : [null, null, null, null, null]

  return (
    <div style={s.page} className="yacht-root">
      {palette}
      <ScoreMoment moment={momentQueue[0] ?? null} onDone={dismissMoment} />
      {/* 튜토리얼에서는 띄우지 않는다. 각자 한 턴씩만 굴리고 끝나는 자리라
          라운드가 넘어간다는 개념 자체가 아직 없고, 배우는 중에 화면을 가로막는
          연출이 하나 더 끼어들 이유도 없다.

          득점 연출이 남아 있는 동안은 기다린다. 마지막 사람이 점수를 넣는
          순간 라운드도 함께 오르므로, 그대로 두면 둘이 화면 가운데에서 겹친다. */}
      {!isTutorial && (
        <RoundBanner
          round={round}
          total={TOTAL_ROUNDS}
          anchorRef={roundAnchorRef}
          // 창을 열어둔 동안에도 기다린다. 띠는 화면 맨 위에 그려지므로 그냥
          // 두면 펼쳐놓은 전체 점수판을 가로질러 뚫고 나온다. 라운드 안내는
          // 급할 것이 없으니 창을 닫은 뒤에 알려도 된다.
          paused={momentQueue.length > 0 || leaderboardOpen || rulesOpen}
          onActiveChange={setRoundBannerActive}
        />
      )}
      <DevPanel
        title="요트"
        actions={[
          { label: '랜덤 굴림', run: () => send('ROLL_DICE') },
          {
            label: '야찌 (5 5 5 5 5)',
            hint: '요트 칸을 고르면 highlight 연출',
            run: () => send('ROLL_DICE', { dice_values: [5, 5, 5, 5, 5] }),
          },
          {
            label: '라지스트레이트 (1~5)',
            hint: '라지 스트레이트 칸을 고르면 highlight 연출',
            run: () => send('ROLL_DICE', { dice_values: [1, 2, 3, 4, 5] }),
          },
          {
            label: '0점 유도 (2~6)',
            hint: '에이스 칸을 고르면 zero 연출',
            run: () => send('ROLL_DICE', { dice_values: [2, 3, 4, 5, 6] }),
          },
          {
            label: '후반 상황 만들기',
            hint: '7칸을 채워 역전(lead_change) 연출을 볼 수 있게 한다',
            run: () => send('DEV_SETUP_LATE_GAME'),
          },
        ]}
      />

      <div style={s.topbar}>
        <span style={s.brand}>요트다이스</span>
        <span style={s.topActions}>
          <button
            type="button"
            style={s.iconButton(ttsEnabled)}
            onClick={toggleTts}
            title={ttsEnabled ? 'TTS 끄기' : 'TTS 켜기'}
            aria-label={ttsEnabled ? 'TTS 끄기' : 'TTS 켜기'}
          >
            <IconVolume size={19} />
          </button>
          <button
            type="button"
            style={s.iconButton(bgmEnabled)}
            onClick={toggleBgm}
            title={bgmEnabled ? '배경음 끄기' : '배경음 켜기'}
            aria-label={bgmEnabled ? '배경음 끄기' : '배경음 켜기'}
          >
            <IconMusic size={19} />
          </button>
          <button
            style={{ ...s.topButton, ...(canUndo ? {} : s.disabled) }}
            onClick={() => send('UNDO_ROUND')}
            disabled={!canUndo}
          >
            되돌리기
          </button>
          <button style={s.topButton} onClick={exitGame}>나가기</button>
        </span>
      </div>

      <div style={s.shell}>
        <main style={s.main}>
          <div style={s.turnRow}>
            <div
              key={turnPulseKey}
              className={turnPulseKey ? 'yacht-turn-pulse' : undefined}
              style={s.turnBadge}
            >
              <span style={s.turnDot} />
              {currentPlayer?.playername || '-'} 님 차례
            </div>
            <div
              ref={roundAnchorRef}
              style={{ ...s.roundText, opacity: roundBannerActive ? 0 : 1 }}
            >
              라운드 {round} / {TOTAL_ROUNDS}
            </div>
          </div>

          <div style={s.rollRow}>
            <span style={s.rollLabel}>굴림</span>
            {[0, 1, 2].map(i => <span key={i} style={s.clip(i < state.roll_count)} />)}
          </div>

          <div style={s.tray}>
            {diceEditMode
              ? editDiceValues.map((value, index) => (
                  <button
                    key={index}
                    type="button"
                    style={s.editDie}
                    onClick={() => cycleEditDie(index)}
                    title="눌러서 눈 변경"
                  >
                    <DiceFace
                      value={value}
                      size={80}
                      border="var(--y-gold)"
                      shadow="0 0 0 3px color-mix(in oklch, var(--y-gold) 32%, transparent)"
                    />
                  </button>
                ))
              : diceValues.map((value, index) => (
                  <DiceFace
                    key={index}
                    value={value}
                    size={80}
                    shadow="0 6px 14px rgba(0,0,0,0.35)"
                  />
                ))}
          </div>

          {diceEditMode ? (
            <>
              <div style={s.editHint}>
                실제로 나온 눈과 다르면 주사위를 눌러 맞춰주세요. 누를 때마다 눈이 1씩
                커지고 6 다음은 1로 돌아갑니다.
              </div>
              <div style={s.actionRow}>
                <button
                  type="button"
                  style={s.bigButton(true)}
                  onClick={() => setDiceEditMode(false)}
                >
                  취소
                </button>
                <button
                  type="button"
                  style={{ ...s.bigButton(true), ...s.primaryButton }}
                  onClick={applyDiceEdit}
                >
                  수정 완료
                </button>
              </div>
            </>
          ) : (
            <div style={s.actionRow}>
              <button
                type="button"
                style={s.bigButton(canManualDiceInput)}
                onClick={canManualDiceInput ? startDiceEdit : undefined}
                disabled={!canManualDiceInput}
              >
                <IconRefresh size={21} />
                주사위 눈 수정
              </button>
              <button type="button" style={s.bigButton(true)} onClick={() => setRulesOpen(true)}>
                <IconBook size={21} />
                게임 규칙
              </button>
            </div>
          )}

          {canManualRoll && !diceEditMode && (
            <div style={s.actionRow}>
              <button
                type="button"
                style={{ ...s.bigButton(true), ...s.primaryButton }}
                onClick={() => send('ROLL_DICE')}
              >
                굴리기
              </button>
            </div>
          )}

          {/* 안내는 열 아래쪽에 붙여둔다. 흐름 바로 밑에 두면 문구가 나타났다
              사라질 때마다 주사위와 버튼이 통째로 위아래로 튄다. */}
          <div style={s.messageSlot}>
            {coach ? (
              <div style={s.coach} onClick={() => setCoach(null)} role="note">
                <span style={s.coachDot} />
                <span style={s.coachText}>{coach.text}</span>
              </div>
            ) : (
              statusMessage && <div style={s.statusMessage}>{statusMessage}</div>
            )}
          </div>
        </main>

        <aside style={s.aside}>
          <div style={s.asideHead}>
            <span style={s.asideTitle}>
              점수판 · {currentPlayer?.playername || '-'}
            </span>
            <button type="button" style={s.headButton} onClick={() => setLeaderboardOpen(true)}>
              <IconExpand size={17} />
              전체 점수판
            </button>
          </div>
          <div style={s.sheetWrap} className="scroll">
            <ScoreTable
              state={state}
              player={currentPlayer}
              recentScore={recentScore}
              onScore={(category) => scoreCategory(category, state, send)}
            />
          </div>
        </aside>
      </div>

      {leaderboardOpen && (
        <div style={s.shade} onClick={() => setLeaderboardOpen(false)}>
          <div style={s.leaderboard} onClick={event => event.stopPropagation()}>
            <div style={s.leaderboardHead}>
              전체 점수판
              <button
                type="button"
                style={s.close}
                onClick={() => setLeaderboardOpen(false)}
                aria-label="닫기"
              >
                ✕
              </button>
            </div>
            <div
              style={{
                ...s.boardGrid,
                gridTemplateColumns: `repeat(${state.players.length}, minmax(0, 1fr))`,
              }}
              className="scroll"
            >
              {state.players.map((player, index) => (
                <div
                  key={player.player_id}
                  style={s.boardColumn(index < state.players.length - 1)}
                >
                  {/* 합계는 각 열 맨 아래에 이미 있다. 이름 옆에 또 쓰는 대신
                      혼자서는 알 수 없는 것 — 몇 등인지 — 을 보여준다. */}
                  <div style={s.boardName}>
                    <span style={s.boardRank(ranks.get(player.player_id) === 1)}>
                      {ranks.get(player.player_id)}위
                    </span>
                    {player.playername}
                  </div>
                  <ScoreTable state={state} player={player} compact recentScore={recentScore} />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {rulesOpen && <YachtRules onClose={() => setRulesOpen(false)} />}
      {introOpen && (
        <YachtTutorial onDone={() => setIntroOpen(false)} onNarrateLine={narrateLine} />
      )}
    </div>
  )
}

function ScoreTable({ state, player, compact = false, recentScore, onScore }) {
  const isCurrent = player?.player_id === state.current_player_id
  const tdName = s.tdName
  const tdScore = s.tdScore
  // 리더보드는 세 판을 나란히 놓느라 높이가 정해져 있지 않다. 늘리려 들면
  // 열마다 행 높이가 달라져 가로로 줄이 안 맞는다.
  const tableStyle = compact ? { ...s.table, height: 'auto' } : s.table

  // 지금 눈으로 가장 크게 넣을 수 있는 칸 셋. 점수판을 처음 보는 사람이
  // 13칸을 전부 계산해보지 않아도 되게 한다.
  const suggested = new Set(
    !compact && isCurrent && state.phase !== 'AWAITING_ROLL' && state.dice_values?.length
      ? DISPLAY_CATEGORIES
        .filter(key => state.available_categories?.includes(key))
        .map(key => [key, Number(previewScore(key, state.dice_values))])
        .filter(([, value]) => value > 0)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([key]) => key)
      : [],
  )

  return (
    <table style={tableStyle}>
      <tbody>
        {CATEGORY_LABELS.map(([key, label], rowIndex) => {
          if (key === 'bonus') {
            const subtotal = upperSubtotal(player?.scores || {})
            const earned = subtotal >= BONUS_THRESHOLD
            return (
              <tr key={key} style={s.frameRow}>
                {/* 막대가 줄 전체를 가로질러야 얼마나 왔는지 읽힌다. 점수 열
                    안에 가두면 폭이 좁아 눈금 구실을 못 한다. */}
                <td colSpan={2} style={s.frameCell}>
                  <div style={s.bonusTop}>
                    <span style={s.frameLabel}>{label}</span>
                    <span style={s.bonusNums}>
                      <span style={s.bonusNow}>{subtotal}</span> / {BONUS_THRESHOLD}
                    </span>
                    <span style={s.bonusBadge(earned)}>
                      {earned
                        ? `+${BONUS_SCORE}`
                        : `${Math.max(0, BONUS_THRESHOLD - subtotal)}점 남음`}
                    </span>
                  </div>
                  <BonusGauge
                    subtotal={subtotal}
                    threshold={BONUS_THRESHOLD}
                    height={compact ? 5 : 7}
                  />
                </td>
              </tr>
            )
          }

          const score = player?.scores?.[key]
          const hasScore = score != null
          const open = compact ? false : state.available_categories?.includes(key)
          const canScore = !compact && isCurrent && open && Boolean(state.dice_values?.length)
          const displayScore = hasScore
            ? score
            : (compact ? '—' : predictedScore(key, state))
          const highlight = recentScore?.playerId === player?.player_id
            && recentScore?.category === key
          const isZero = highlight && recentScore?.variant === 'zero'
          // 채운 칸도, 이미 지나간 칸도 아닌 "아직 쓸 수 있는" 칸만 힌트를 밝게 둔다.
          const dimHint = hasScore || !open

          const isSuggested = suggested.has(key)
          // 아직 안 채웠는데 지금 눈으로는 0점인 칸. 고를 수는 있으니 지우지 않고
          // 뒤로 물린다. 굴리기 전('—')은 아직 알 수 없는 것이라 해당 없다.
          const isDud = !hasScore && open && displayScore === 0
          const valueStyle = s.scoreValue({ filled: hasScore, suggested: isSuggested })

          return (
            <tr
              key={key}
              className={highlight ? (isZero ? 'yacht-flash-zero' : 'yacht-flash') : undefined}
              style={s.row({
                alt: rowIndex % 2 === 1,
                filled: hasScore,
                suggested: isSuggested,
                zero: isDud,
                clickable: canScore,
              })}
              onClick={canScore ? () => onScore(key) : undefined}
            >
              <td style={tdName}>
                <span style={s.nameCell}>
                  <span style={s.label({ filled: hasScore, suggested: isSuggested })}>
                    {label}
                  </span>
                  {!compact && <CategoryHint category={key} dim={dimHint} />}
                </span>
              </td>
              <td style={tdScore}>
                {hasScore && <span style={s.doneMark}>✓</span>}
                {highlight ? (
                  // 득점마다 올라가는 seq를 key에 섞는다. key가 그대로면 React가
                  // 같은 노드를 재사용해 애니메이션이 다시 돌지 않는다.
                  <span
                    key={`${key}-${recentScore.seq}`}
                    className={isZero ? 'yacht-pop-zero' : 'yacht-pop'}
                    style={valueStyle}
                  >
                    {displayScore}
                  </span>
                ) : <span style={valueStyle}>{displayScore}</span>}
              </td>
            </tr>
          )
        })}
        <tr style={s.totalRow}>
          <td style={tdName}><span style={s.totalLabel}>합계</span></td>
          <td style={tdScore}>
            <span style={s.totalValue}><CountUpTotal value={player?.total ?? 0} /></span>
          </td>
        </tr>
      </tbody>
    </table>
  )
}

/**
 * 점수판 칸 옆의 족보 그림.
 *
 * 족보 설명을 별도 화면에만 두면 아무도 안 본다 — 게임을 멈추고 창을 열어야
 * 하기 때문이다. 그래서 설명을 칸 옆에 그림으로 상주시킨다. 이미 채운 칸과
 * 못 쓰는 칸은 흐리게 둬서, 지금 노릴 수 있는 칸만 눈에 남는다.
 */
function CategoryHint({ category, dim }) {
  const hint = CATEGORY_HINTS[category]
  if (!hint) return null
  if (hint.text) return <span style={s.hintText(dim)}>{hint.text}</span>
  return (
    <span style={s.hintRow(dim)}>
      {hint.dice.map((value, index) => (
        <DiceFace
          key={index}
          value={value}
          size={19}
          radius={5}
          // 풀하우스는 3개와 2개가 다른 눈이라는 것이 규칙이라 두 묶음을 갈라 보여준다.
          face={hint.split != null && index < hint.split
            ? 'oklch(0.78 0.03 85)'
            : 'var(--y-die-face)'}
        />
      ))}
    </span>
  )
}

/** 합계가 뛰지 않고 굴러 올라간다. 점수가 쌓이는 감각이 여기서 나온다. */
function CountUpTotal({ value }) {
  const [shown, setShown] = useState(value)
  const fromRef = useRef(value)
  const frameRef = useRef(0)

  useEffect(() => {
    const from = fromRef.current
    fromRef.current = value
    if (from === value) return undefined
    // 오르는 폭에 비례해 길어지되 상한을 둔다 — 매 턴 오는 연출이라 길면 답답하다.
    const duration = Math.min(700, 220 + Math.abs(value - from) * 8)
    const start = performance.now()
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration)
      setShown(Math.round(from + (value - from) * (1 - (1 - t) ** 3)))
      if (t < 1) frameRef.current = requestAnimationFrame(tick)
    }
    frameRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frameRef.current)
  }, [value])

  return shown
}

function normalizePlayers(players) {
  if (!players?.length) {
    return [
      { player_id: 'p1', playername: '형승' },
      { player_id: 'p2', playername: '병진' },
      { player_id: 'p3', playername: '성민' },
    ]
  }
  return players.map((player, index) => ({
    player_id: String(player.player_id || player.id || `p${index + 1}`),
    playername: String(player.playername || player.name || `플레이어 ${index + 1}`),
  }))
}

function scoreCategory(category, state, send) {
  if (!DISPLAY_CATEGORIES.includes(category)) return
  send('SCORE_CATEGORY_SELECTED', { category }, state.current_player_id)
}

function playLocalSfx(name) {
  const audio = new Audio(`/sfx/${name}.mp3`)
  audio.play().catch(() => {})
}

function predictedScore(category, state) {
  if (!state.available_categories?.includes(category)) return '—'
  if (!state.dice_values?.length) return '—'
  return previewScore(category, state.dice_values)
}

/**
 * 요트 화면 전용 팔레트.
 *
 * 공용 테마는 회색 계열 하나로만 되어 있어서, 점수판을 올려놔도 배경과 같은
 * 색이라 판이 판으로 보이지 않았다. 여기서는 놀이판 쪽을 펠트 초록으로,
 * 점수판을 따뜻한 밝은 톤으로 갈라 색상 자체가 두 영역을 나누게 한다.
 * 늑대인간은 같은 공용 테마를 쓰므로 이 변수들은 요트 화면 안에만 둔다.
 */
const PALETTE_CSS = `
  .yacht-root {
    --y-felt-hi: oklch(0.335 0.046 168);
    --y-felt-lo: oklch(0.185 0.028 170);

    --y-panel:      oklch(0.295 0.014 78);
    --y-panel-head: oklch(0.375 0.026 74);
    --y-row-alt:    oklch(0.325 0.013 78);
    --y-line:       oklch(0.46 0.021 76);
    --y-line-soft:  oklch(0.365 0.015 76);

    --y-gold:      oklch(0.80 0.145 78);
    --y-gold-deep: oklch(0.66 0.150 62);
    --y-pick:      oklch(0.74 0.115 205);

    --y-die-face: oklch(0.96 0.012 85);
    --y-die-pip:  oklch(0.24 0.025 45);
    --y-die-edge: oklch(0.80 0.020 85);

    --y-text:      oklch(0.97 0.008 85);
    --y-text-soft: oklch(0.86 0.014 80);
    --y-text-mute: oklch(0.69 0.016 80);
  }

  @keyframes yachtTurnPulse {
    0%   { transform: scale(0.94); }
    40%  { transform: scale(1.07); }
    70%  { transform: scale(0.99); }
    100% { transform: scale(1); }
  }
  .yacht-turn-pulse { animation: yachtTurnPulse 420ms ease-out; }

  @keyframes yachtFlash {
    0%   { background: color-mix(in oklch, var(--y-gold) 46%, var(--y-panel)); }
    55%  { background: color-mix(in oklch, var(--y-gold) 22%, var(--y-panel)); }
    100% { background: transparent; }
  }
  /* 0점은 같은 자리에 다른 표정으로 — 색이 빠지고 아래로 처진다. */
  @keyframes yachtFlashZero {
    0%   { background: color-mix(in oklch, var(--y-text-mute) 34%, var(--y-panel)); }
    55%  { background: color-mix(in oklch, var(--y-text-mute) 16%, var(--y-panel)); }
    100% { background: transparent; }
  }
  .yacht-flash      { animation: yachtFlash 900ms ease-out; }
  .yacht-flash-zero { animation: yachtFlashZero 900ms ease-out; }

  /* 점수 숫자가 칸에 "착지"한다. 매 턴 오는 연출이라 짧고 경쾌하게. */
  @keyframes yachtPop {
    0%   { transform: scale(2.1) translateY(-14px); opacity: 0; }
    35%  { transform: scale(1.18) translateY(0); opacity: 1; }
    60%  { transform: scale(0.94); }
    100% { transform: scale(1); }
  }
  @keyframes yachtPopZero {
    0%   { transform: scale(1.5) translateY(-8px); opacity: 0; }
    40%  { transform: scale(1) translateY(3px); opacity: 1; }
    100% { transform: scale(1); }
  }
  .yacht-pop      { animation: yachtPop 620ms cubic-bezier(.2,.9,.25,1.3); display: inline-block; }
  .yacht-pop-zero { animation: yachtPopZero 520ms ease-out; display: inline-block; }
`
