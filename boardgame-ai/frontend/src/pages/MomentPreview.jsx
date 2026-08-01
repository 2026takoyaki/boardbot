import { useRef, useState } from 'react'
import RoundBanner from '../components/common/RoundBanner'
import ScoreMoment from '../components/common/ScoreMoment'
import { TOTAL_ROUNDS } from '../components/common/yachtCategories'

/**
 * 득점 순간 연출 미리보기. 백엔드·카메라 없이 모달만 띄워본다.
 *
 *     npm run dev   →   http://localhost:3000/?preview=moments
 *
 * 지속시간은 아직 실물 플레이로 확정해야 하는 값이라(설계문서 §7.2-12),
 * 여기서 슬라이더로 바꿔가며 감을 잡고 FSM의 _CUE_DURATION_MS에 반영한다.
 * 조명 Cue 길이도 같은 값을 예산으로 쓰므로 늘릴 때는 bulb/scenes.py의
 * 해당 Cue가 그 안에 들어오는지 함께 확인해야 한다.
 */

const SAMPLES = {
  // 주사위가 멈춘 순간 (조명 관여 안 함)
  hand: {
    cue: 'yacht_hand_achieved',
    scorer_name: '성민',
    category: 'yacht',
    category_label: '요트',
    score: 50,
  },
  highlight: {
    cue: 'yacht_turn_transition',
    variant: 'highlight',
    scorer_name: '성민',
    category: 'yacht',
    category_label: '요트',
    score: 50,
    is_highlight: true,
    took_lead: false,
    rank_before: 1,
    rank_after: 1,
  },
  lead_change: {
    cue: 'yacht_turn_transition',
    variant: 'lead_change',
    scorer_id: 'p3',
    scorer_name: '승경',
    category: 'four_of_a_kind',
    category_label: '포카드',
    score: 24,
    is_highlight: false,
    took_lead: true,
    rank_before: 3,
    rank_after: 1,
    previous_leader: '성민',
    standings: [
      { player_id: 'p1', playername: '성민', total: 118, rank_before: 1, rank_after: 2 },
      { player_id: 'p2', playername: '형승', total: 104, rank_before: 2, rank_after: 3 },
      { player_id: 'p3', playername: '승경', total: 126, rank_before: 3, rank_after: 1 },
    ],
  },
  zero: {
    cue: 'yacht_turn_transition',
    variant: 'zero',
    scorer_name: '형승',
    category: 'large_straight',
    category_label: '라지 스트레이트',
    score: 0,
    is_highlight: false,
    took_lead: false,
    rank_before: 2,
    rank_after: 2,
  },
}

// FSM의 games/yacht/fsm.py _CUE_DURATION_MS · _HAND_CUE_DURATION_MS 와 같은 값.
const DEFAULT_DURATIONS = { hand: 2600, highlight: 1800, lead_change: 2600, zero: 1400 }

export default function MomentPreview() {
  const [moment, setMoment] = useState(null)
  const [durations, setDurations] = useState(DEFAULT_DURATIONS)
  const [round, setRound] = useState(0)
  const seqRef = useRef(0)

  const play = (variant) => {
    // 실제 게임과 같은 방식으로 다시 튼다 — momentKey가 바뀌면 ScoreMoment가
    // 새 인스턴스로 갈아끼워져 애니메이션이 처음부터 돈다. setTimeout으로
    // 지웠다 켜면 연타할 때 이전 클릭이 뒤늦게 뜨거나 언마운트 후 setState가 난다.
    setMoment({
      ...SAMPLES[variant],
      duration_ms: durations[variant],
      momentKey: `${variant}-${seqRef.current++}`,
    })
  }

  return (
    <div style={styles.page}>
      <ScoreMoment moment={moment} onDone={() => setMoment(null)} />
      <RoundBanner round={round} total={TOTAL_ROUNDS} />

      <h1 style={styles.title}>요트 연출</h1>
      <p style={styles.lede}>
        <strong>hand</strong>는 주사위가 멈춘 순간에 뜬다 — 조명이 관여하지 않으므로
        가장 화려해도 된다. 나머지 셋은 칸을 고른 뒤에 뜨고 조명과 같은 duration을 쓴다.
        일반 득점(normal)은 모달 없이 점수판 안에서 처리된다.
      </p>

      {Object.keys(SAMPLES).map(variant => (
        <div key={variant} style={styles.row}>
          <button type="button" style={styles.button} onClick={() => play(variant)}>
            {variant}
          </button>
          <input
            type="range"
            min={800}
            max={5000}
            step={100}
            value={durations[variant]}
            onChange={e =>
              setDurations(d => ({ ...d, [variant]: Number(e.target.value) }))
            }
            style={styles.slider}
          />
          <span style={styles.duration}>{durations[variant]}ms</span>
        </div>
      ))}

      <div style={{ ...styles.row, marginTop: 26 }}>
        <button
          type="button"
          style={styles.button}
          onClick={() => setRound(r => (r >= 13 ? 1 : r + 1))}
        >
          라운드 안내
        </button>
        <span style={styles.duration}>다음: {round >= 13 ? 1 : round + 1}</span>
      </div>

      <p style={styles.note}>
        지속시간을 바꿨다면 <code>games/yacht/fsm.py</code>의 <code>_CUE_DURATION_MS</code>에
        반영하고, <code>bulb/scenes.py</code>의 해당 Cue가 그 예산 안에 들어오는지 확인한다.
        조명이 늦게 복귀하면 다음 굴림 인식이 깨진다.
      </p>
    </div>
  )
}

const styles = {
  page: {
    minHeight: '100vh',
    padding: '48px 32px',
    background: 'var(--bg-app)',
    color: 'var(--fg)',
    fontFamily: 'var(--font)',
  },
  title: { fontSize: 28, fontWeight: 800, marginBottom: 8 },
  lede: { color: 'var(--fg-mute)', marginBottom: 32, maxWidth: 560, lineHeight: 1.6 },
  row: { display: 'flex', alignItems: 'center', gap: 16, marginBottom: 14 },
  button: {
    minWidth: 150,
    padding: '12px 20px',
    fontSize: 16,
    fontWeight: 700,
    fontFamily: 'var(--font-mono)',
    color: 'var(--fg)',
    background: 'var(--bg-elev)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    cursor: 'pointer',
  },
  slider: { width: 260 },
  duration: {
    minWidth: 72,
    fontFamily: 'var(--font-mono)',
    fontSize: 14,
    color: 'var(--fg-soft)',
  },
  note: {
    marginTop: 36,
    maxWidth: 560,
    fontSize: 14,
    lineHeight: 1.7,
    color: 'var(--fg-mute)',
  },
}
