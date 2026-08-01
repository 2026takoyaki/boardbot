import { useState } from 'react'
import ScoreMoment from '../components/common/ScoreMoment'

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
  highlight: {
    cue: 'yacht_turn_transition',
    variant: 'highlight',
    scorer_name: '성민',
    category: 'yacht',
    category_label: '요트',
    score: 50,
    is_highlight: true,
    took_lead: true,
    rank_before: 2,
    rank_after: 1,
    previous_leader: '형승',
  },
  lead_change: {
    cue: 'yacht_turn_transition',
    variant: 'lead_change',
    scorer_name: '승경',
    category: 'four_of_a_kind',
    category_label: '포카드',
    score: 24,
    is_highlight: false,
    took_lead: true,
    rank_before: 3,
    rank_after: 1,
    previous_leader: '성민',
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
    previous_leader: '성민',
  },
}

// FSM의 games/yacht/fsm.py _CUE_DURATION_MS 와 같은 값.
const DEFAULT_DURATIONS = { highlight: 3000, lead_change: 2600, zero: 1400 }

export default function MomentPreview() {
  const [moment, setMoment] = useState(null)
  const [durations, setDurations] = useState(DEFAULT_DURATIONS)

  const play = (variant) => {
    // 이미 떠 있으면 한 번 내렸다가 다시 올려야 애니메이션이 처음부터 돈다.
    setMoment(null)
    setTimeout(
      () => setMoment({ ...SAMPLES[variant], duration_ms: durations[variant] }),
      20,
    )
  }

  return (
    <div style={styles.page}>
      <ScoreMoment moment={moment} onDone={() => setMoment(null)} />

      <h1 style={styles.title}>득점 순간 연출</h1>
      <p style={styles.lede}>
        일반 득점(normal)은 모달 없이 점수판 안에서 처리된다. 여기 있는 셋만 화면을 잡는다.
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
