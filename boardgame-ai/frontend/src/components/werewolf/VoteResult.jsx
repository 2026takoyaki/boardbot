import { useEffect, useMemo, useState } from 'react'
import WerewolfScene from './WerewolfScene'
import * as ui from './wwUi'

const AUTO_ADVANCE_SEC = 10

/**
 * 투표 결과.
 *
 * 한 컴포넌트가 성격이 다른 두 화면을 그린다.
 *
 *   editable=false  발표. 막대가 자라고 붉게 번쩍인다. 아무 데나 눌러 넘긴다.
 *   editable=true   확인·보정. 카메라가 잘못 읽은 지목을 사람이 고치는 자리.
 *
 * **보정 화면의 조작을 갈아엎었다.** 전에는 집계 막대가 화면을 차지하고
 * 보정은 아래 작은 칸에 있었는데, 정작 이 화면에 온 이유는 고치기 위해서다.
 * 게다가 조작이 "투표자 줄을 누르고 → 다른 줄을 누르면 그 줄의 주인이
 * 대상이 된다"였다. 같은 줄이 누를 때마다 다른 뜻이 되고("나는 투표자다" /
 * "나는 대상이다"), 화면에는 그 차이를 알려주는 것이 없었다. 'A → B'라고
 * 적힌 줄을 눌렀는데 B가 아니라 A가 골라지는 식이다.
 *
 * 지금은 누를 때마다 뜻이 하나다.
 *   대상 칸을 누른다        → "이 사람 지목을 고치겠다"
 *   아래 뜬 이름을 누른다   → "이 사람을 지목했다"
 * 고를 이름은 그 줄 **안에서** 펼쳐지므로 누구의 지목을 고르는 중인지
 * 헷갈릴 자리가 없다.
 */
export default function VoteResult({ players = [], votes = {}, onComplete, editable = false, send, onConfirm }) {
  const [countdown, setCountdown] = useState(AUTO_ADVANCE_SEC)
  // 지금 대상을 고르는 중인 투표자. null이면 아무 줄도 펼쳐져 있지 않다.
  const [editingVoter, setEditingVoter] = useState(null)
  // 막대는 0에서 자란다. 첫 렌더에 이미 제 길이면 transition이 돌 자리가 없어
  // '집계된 결과'가 아니라 처음부터 그려진 그림으로 보인다.
  const [grown, setGrown] = useState(false)

  useEffect(() => {
    const frame = requestAnimationFrame(() => setGrown(true))
    return () => cancelAnimationFrame(frame)
  }, [])

  // 비편집 모드: 자동 진행 타이머
  useEffect(() => {
    if (editable) return
    let remaining = AUTO_ADVANCE_SEC
    const interval = setInterval(() => {
      remaining -= 1
      setCountdown(remaining)
      if (remaining <= 0) {
        clearInterval(interval)
        onComplete?.()
      }
    }, 1000)
    return () => clearInterval(interval)
  }, [editable]) // eslint-disable-line react-hooks/exhaustive-deps

  // votes: { voter_player_id: target_player_id }
  const { tally, condemned } = useMemo(() => {
    const count = {}
    players.forEach(p => { count[p.player_id] = 0 })
    Object.values(votes).forEach(targetId => {
      if (count[targetId] !== undefined) count[targetId]++
    })

    const maxVotes = Math.max(...Object.values(count), 0)
    const cond = players.filter(p => count[p.player_id] === maxVotes && maxVotes > 0)

    const t = [...players]
      .sort((a, b) => count[b.player_id] - count[a.player_id])
      .map(p => ({ ...p, voteCount: count[p.player_id] }))

    return { tally: t, condemned: cond }
  }, [players, votes])

  const maxVotes = tally[0]?.voteCount ?? 0
  const condemnedNames = condemned.map(p => p.playername).join(', ')

  const nameOf = (id) => players.find(p => p.player_id === id)?.playername

  /** 한 번의 누름 = 한 가지 뜻. "이 투표자는 이 사람을 지목했다." */
  const setVote = (voterId, targetId) => {
    send?.('werewolf_vote_player', { target_id: targetId }, voterId)
    setEditingVoter(null)
  }

  if (editable) {
    return (
      <div className="ww-root" style={ui.page}>
        <WerewolfScene mood="blood" />
        <style>{CSS}</style>

        <div style={{ ...ui.stage, gap: 14, ...styles.content }}>
          <div style={styles.title} className="ww-anim-title">투표 결과 확인</div>
          <div style={styles.lead}>
            카메라가 읽은 지목입니다. 틀린 것이 있으면 <b style={styles.hot}>눌러서</b> 고치세요.
          </div>

          <div style={styles.editList}>
            {players.map((p, i) => {
              const targetId = votes[p.player_id]
              const isAbstain = targetId === p.player_id
              const isOpen = editingVoter === p.player_id
              const unread = targetId === undefined
              return (
                <div
                  key={p.player_id}
                  style={{ ...styles.editRow, ...(isOpen ? styles.editRowOpen : null), animationDelay: `${0.1 + i * 0.05}s` }}
                  className="ww-anim-in"
                >
                  <div style={styles.editHead}>
                    <span style={styles.editVoter}>{p.playername}</span>
                    <span style={styles.editArrow}>지목 →</span>
                    {/* 이 칸 하나가 "고치기"의 입구다. 알약 모양으로 두어
                        옆의 이름(글자)과 눌리는 것이 구별된다. */}
                    <button
                      type="button"
                      className="ww-press"
                      style={{
                        ...styles.targetPill,
                        ...(unread ? styles.targetPillEmpty : null),
                        ...(isOpen ? styles.targetPillOpen : null),
                      }}
                      onClick={() => setEditingVoter(isOpen ? null : p.player_id)}
                      aria-expanded={isOpen}
                    >
                      {unread ? '인식 안 됨' : isAbstain ? '기권' : nameOf(targetId) ?? '?'}
                      <span style={{ ...styles.pillCaret, transform: isOpen ? 'rotate(180deg)' : 'none' }}>▾</span>
                    </button>
                  </div>

                  {isOpen && (
                    <div style={styles.picker}>
                      <div style={styles.pickerHint}>
                        <b style={styles.hot}>{p.playername}</b> 님이 누구를 지목했나요?
                      </div>
                      <div style={styles.chips}>
                        {players
                          .filter(t => t.player_id !== p.player_id)
                          .map(t => (
                            <button
                              key={t.player_id}
                              type="button"
                              className="ww-press"
                              style={{
                                ...styles.chip,
                                ...(t.player_id === targetId ? styles.chipOn : null),
                              }}
                              onClick={() => setVote(p.player_id, t.player_id)}
                            >
                              {t.playername}
                            </button>
                          ))}
                        {/* 자기 자신 지목이 곧 기권이다. 규칙을 알아야만 누를 수
                            있는 조작은 조작이 아니라 퀴즈다 — 그래서 이름 대신
                            '기권'이라고 적어 따로 낸다. */}
                        <button
                          type="button"
                          className="ww-press"
                          style={{ ...styles.chip, ...styles.chipAbstain, ...(isAbstain ? styles.chipOn : null) }}
                          onClick={() => setVote(p.player_id, p.player_id)}
                        >
                          기권
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* 집계는 여기서 거들 뿐이다. 이 화면의 일은 고치는 것이고, 결과
              발표는 다음 화면이 크게 한다. */}
          <div style={styles.summary}>
            {maxVotes > 0 ? (
              <>
                최다 득표 <b style={styles.hot}>{condemnedNames}</b>
                <span style={styles.sep}>·</span>{maxVotes}표
                {condemned.length > 1 && <span style={styles.sep}>·</span>}
                {condemned.length > 1 && '동률'}
              </>
            ) : (
              '아직 지목이 없습니다'
            )}
          </div>

          <button
            onClick={() => { send?.('werewolf_vote_result_confirm', {}); onConfirm?.() }}
            className="ww-press"
            style={{ ...ui.dangerButton, marginTop: 2, padding: '15px 52px', letterSpacing: '0.06em' }}
          >
            이대로 확정
          </button>
        </div>
      </div>
    )
  }

  // ── 발표 ────────────────────────────────────────────────────────────────
  return (
    <div className="ww-root" onClick={onComplete} style={{ ...ui.page, cursor: 'pointer' }}>
      <WerewolfScene mood="blood" />
      <style>{CSS}</style>

      {/* 심판이 확정되는 화면이라 처음 한 번 붉게 번쩍인다 */}
      <div className="ww-verdict-flash" />

      <div style={{ ...ui.stage, gap: 16, ...styles.content, marginBottom: 60 }}>
        <div style={styles.title} className="ww-anim-title">투표 결과</div>

        <div style={styles.condemnedCard} className="ww-panel ww-anim-pop">
          <div style={styles.avatarRing}>
            <div style={styles.avatar}>
              <svg viewBox="0 0 48 48" width="40" height="40" fill="none">
                <circle cx="24" cy="18" r="9" fill="rgba(255,190,170,0.65)" />
                <path
                  d="M8 42c0-8.837 7.163-16 16-16s16 7.163 16 16"
                  stroke="rgba(255,190,170,0.65)"
                  strokeWidth="2.6"
                  strokeLinecap="round"
                />
              </svg>
            </div>
          </div>
          <div style={styles.condemnedLabel}>
            <span style={styles.condemnedName}>{condemnedNames || '—'}</span>
            <span style={styles.condemnedSuffix}> 님 심판</span>
          </div>
        </div>

        <div style={styles.tallyList}>
          {tally.map((p, i) => {
            const top = p.voteCount === maxVotes && maxVotes > 0
            return (
              <div
                key={p.player_id}
                style={{
                  ...styles.tallyRow,
                  ...(top ? styles.tallyRowTop : null),
                  animationDelay: `${0.25 + i * 0.07}s`,
                }}
                className="ww-anim-in"
              >
                <span style={styles.tallyName}>{p.playername}</span>
                <div style={styles.barTrack}>
                  <div
                    style={{
                      ...styles.barFill,
                      width: grown && maxVotes > 0 ? `${(p.voteCount / maxVotes) * 100}%` : '0%',
                      background: top
                        ? 'linear-gradient(90deg, var(--w-blood-deep), var(--w-blood))'
                        : 'rgba(255,214,200,0.22)',
                      boxShadow: top ? '0 0 16px rgba(255,106,60,0.55)' : 'none',
                      // 막대가 자기 자리까지 자라는 것을 보여준다. 처음부터 다 차
                      // 있으면 '집계 결과'가 아니라 '고정된 그림'으로 보인다.
                      transitionDelay: `${0.3 + i * 0.07}s`,
                    }}
                  />
                </div>
                <span style={{ ...styles.tallyCount, color: top ? '#ff9068' : 'rgba(255,214,200,0.45)' }}>
                  {p.voteCount}
                </span>
              </div>
            )
          })}
        </div>

        <div style={styles.tapHint}>
          화면을 터치하면 계속합니다
          {countdown > 0 && <span style={{ marginLeft: 7, opacity: 0.55 }}>({countdown})</span>}
        </div>
      </div>
    </div>
  )
}

const styles = {
  content: {
    width: '100%',
    maxWidth: 560,
    padding: '0 24px',
    overflowY: 'auto',
    maxHeight: '92vh',
  },

  title: {
    fontSize: 'clamp(26px, 3.6vw, 34px)',
    fontWeight: 850,
    letterSpacing: '0.16em',
    paddingLeft: '0.16em',
    color: '#ffd9cc',
    textShadow: '0 0 40px rgba(220,70,30,0.7), 0 3px 10px rgba(0,0,0,0.7)',
    textAlign: 'center',
  },

  lead: {
    fontSize: 14.5,
    color: 'rgba(255,214,200,0.62)',
    textAlign: 'center',
    marginTop: -4,
  },

  // ── 보정 목록 ──────────────────────────────────────────────────────────
  editList: {
    width: '100%',
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },

  editRow: {
    borderRadius: 14,
    padding: '11px 14px',
    background: 'rgba(10,3,2,0.46)',
    border: '1px solid rgba(255,120,80,0.14)',
    transition: 'background 180ms ease, border-color 180ms ease',
  },

  editRowOpen: {
    background: 'linear-gradient(180deg, rgba(120,32,10,0.34), rgba(30,8,4,0.46))',
    border: '1px solid rgba(255,170,110,0.55)',
  },

  editHead: { display: 'flex', alignItems: 'center', gap: 10 },

  editVoter: {
    fontSize: 16,
    fontWeight: 800,
    color: '#ffe6dc',
    minWidth: 72,
  },

  editArrow: {
    fontSize: 12.5,
    fontWeight: 650,
    color: 'rgba(255,214,200,0.42)',
    letterSpacing: '0.02em',
  },

  /** 눌러서 고치는 자리. 44px 높이는 손가락으로 빗나가지 않는 최소치다. */
  targetPill: {
    marginLeft: 'auto',
    minWidth: 128,
    height: 44,
    padding: '0 16px',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
    borderRadius: 999,
    border: '1px solid rgba(255,150,100,0.5)',
    background: 'rgba(200,60,30,0.26)',
    color: '#ffcbb8',
    fontFamily: 'inherit',
    fontSize: 15.5,
    fontWeight: 750,
    cursor: 'pointer',
  },

  // 카메라가 못 읽은 자리는 색이 아니라 **비어 보이는 것**으로 알린다.
  // 붉게 칠해두면 지목이 있는 것처럼 보여 그냥 넘어가게 된다.
  targetPillEmpty: {
    border: '1px dashed rgba(255,214,200,0.34)',
    background: 'transparent',
    color: 'rgba(255,214,200,0.5)',
  },

  targetPillOpen: {
    border: '1px solid rgba(255,200,140,0.9)',
    background: 'rgba(255,150,70,0.3)',
    color: '#fff0e4',
  },

  pillCaret: { fontSize: 11, opacity: 0.7, transition: 'transform 160ms ease' },

  picker: {
    marginTop: 11,
    paddingTop: 11,
    borderTop: '1px solid rgba(255,150,100,0.22)',
  },

  pickerHint: {
    fontSize: 13,
    color: 'rgba(255,224,214,0.72)',
    marginBottom: 9,
  },

  chips: { display: 'flex', flexWrap: 'wrap', gap: 7 },

  chip: {
    height: 42,
    padding: '0 17px',
    borderRadius: 999,
    border: '1px solid rgba(255,255,255,0.16)',
    background: 'rgba(0,0,0,0.28)',
    color: '#ffe6dc',
    fontFamily: 'inherit',
    fontSize: 15,
    fontWeight: 700,
    cursor: 'pointer',
    transition: 'background 140ms ease, border-color 140ms ease',
  },

  chipOn: {
    border: '1px solid rgba(255,190,110,0.9)',
    background: 'rgba(255,150,70,0.32)',
    color: '#fff4e8',
  },

  chipAbstain: { color: 'rgba(255,214,200,0.6)', fontWeight: 650 },

  summary: {
    fontSize: 13.5,
    fontWeight: 650,
    color: 'rgba(255,214,200,0.55)',
    letterSpacing: '0.01em',
  },

  hot: { color: '#ff9068', fontWeight: 800 },
  sep: { margin: '0 7px', opacity: 0.4 },

  // ── 발표 ───────────────────────────────────────────────────────────────
  condemnedCard: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 10,
    padding: '16px 34px',
    borderColor: 'rgba(255,130,90,0.42)',
    boxShadow: '0 0 40px rgba(200,60,30,0.28), 0 24px 60px rgba(0,0,0,0.45)',
    animationDelay: '0.12s',
  },

  // 심판당한 사람 주위로 붉은 고리가 천천히 돈다
  avatarRing: {
    position: 'relative',
    padding: 4,
    borderRadius: '50%',
    background: 'conic-gradient(from 0deg, rgba(255,106,60,0.8), transparent 42%, rgba(255,106,60,0.8))',
    animation: 'ww-ring-spin 6s linear infinite',
  },

  avatar: {
    width: 56,
    height: 56,
    borderRadius: '50%',
    background: 'rgba(60,14,6,0.85)',
    display: 'grid',
    placeItems: 'center',
    animation: 'ww-ring-spin 6s linear infinite reverse',
  },

  condemnedLabel: { fontSize: 17, textAlign: 'center' },
  condemnedName: { fontWeight: 850, color: '#ff9068', fontSize: 20 },
  condemnedSuffix: { fontWeight: 500, color: 'rgba(255,224,214,0.8)' },

  tallyList: {
    width: '100%',
    display: 'flex',
    flexDirection: 'column',
    gap: 7,
  },

  tallyRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    background: 'rgba(10,3,2,0.4)',
    border: '1px solid rgba(255,120,80,0.10)',
    borderRadius: 12,
    padding: '10px 15px',
  },

  tallyRowTop: {
    background: 'linear-gradient(90deg, rgba(150,34,14,0.32), rgba(40,8,4,0.34))',
    border: '1px solid rgba(255,120,80,0.4)',
  },

  tallyName: {
    fontSize: 14,
    fontWeight: 700,
    color: '#ffe6dc',
    width: 62,
    flexShrink: 0,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },

  barTrack: {
    flex: 1,
    height: 7,
    borderRadius: 999,
    background: 'rgba(255,255,255,0.08)',
    overflow: 'hidden',
  },

  barFill: {
    height: '100%',
    width: 0,
    borderRadius: 999,
    transition: 'width 760ms cubic-bezier(.2,.8,.25,1)',
  },

  tallyCount: {
    fontSize: 17,
    fontWeight: 800,
    width: 22,
    textAlign: 'right',
    flexShrink: 0,
    fontVariantNumeric: 'tabular-nums',
  },

  tapHint: {
    fontSize: 12,
    color: 'rgba(255,214,200,0.32)',
    letterSpacing: '0.04em',
    marginTop: 6,
  },
}

const CSS = `
  /* 결과가 확정되는 순간의 붉은 섬광. 한 번만 친다. */
  .ww-verdict-flash {
    position: absolute;
    inset: 0;
    z-index: 1;
    pointer-events: none;
    background: radial-gradient(ellipse at center, rgba(255,90,40,0.5), rgba(120,10,0,0.35) 60%, transparent 78%);
    animation: ww-verdict 900ms ease-out both;
  }
  @keyframes ww-verdict {
    0%   { opacity: 0; }
    12%  { opacity: 1; }
    100% { opacity: 0; }
  }

  @keyframes ww-ring-spin { to { transform: rotate(360deg); } }
`
