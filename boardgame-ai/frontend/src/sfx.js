/**
 * 효과음 재생 — 화면이 직접 트리거하는 것들.
 *
 * 백엔드를 거치는 소리(`sfx_play` 메시지)와는 경로가 다르다. 이쪽은 버튼을
 * 누른 그 순간처럼 **왕복을 기다릴 수 없는** 반응에 쓴다. 서버까지 갔다 오면
 * 눌렀는데 늦게 나는 것으로 느껴진다.
 *
 * 파일은 백엔드 StaticFiles가 /sfx/<name>.mp3로 서빙한다(audio/assets/sfx/).
 * 개발 서버에서는 vite 프록시가 넘긴다.
 */

import { sfxVolume } from './hooks/useAudioPlayer'

// 브라우저가 자동재생을 막으면 play()가 reject된다. 소리가 없다고 게임이
// 멈추지는 않으므로 조용히 삼킨다.
//
// 음량은 상단바의 효과음 슬라이더를 따른다. 이쪽은 매번 새 Audio를 만들어
// 쓰기 때문에(겹쳐 울려야 하므로) 재생 직전에 값을 물어본다.
export function playSfx(name) {
  if (!name) return
  const volume = sfxVolume()
  if (volume <= 0) return
  const audio = new Audio(`/sfx/${name}.mp3`)
  audio.volume = volume
  audio.play().catch(() => {})
}

/**
 * 요트 굴림 축하의 등급 → 효과음.
 *
 * 백엔드는 다섯 등급을 보내는데(games/yacht/fsm.py의 _HAND_TIERS) 소리는
 * 셋이다. 위 둘만 따로 두고 나머지는 하나로 묶는다 — 포카드·풀하우스·스몰은
 * 한 판에 여러 번 나오므로 매번 크게 축하하면 야찌가 묻힌다.
 */
export const HAND_TIER_SFX = {
  legendary: 'hand_legendary',  // 야찌
  epic: 'hand_epic',            // 라지 스트레이트
  great: 'hand_good',           // 포카드
  good: 'hand_good',            // 풀하우스
  nice: 'hand_good',            // 스몰 스트레이트
}

/** 득점 연출 종류 → 효과음. 없는 종류는 일반 득점으로 떨어진다. */
export const SCORE_VARIANT_SFX = {
  zero: 'score_zero',
  lead_change: 'lead_change',
  // highlight(야찌·라지)는 주사위가 멈춘 순간에 이미 크게 축하했다.
  // 여기서 또 터뜨리면 한 번의 사건에 두 번 환호하는 꼴이 된다.
  highlight: 'score_normal',
  normal: 'score_normal',
}
