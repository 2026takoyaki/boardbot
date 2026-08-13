import { useEffect, useMemo, useState } from 'react'
import WerewolfScene from './WerewolfScene'
import * as ui from './wwUi'

const AUTO_ADVANCE_SEC = 10

export default function VoteResult({ players = [], votes = {}, onComplete, editable = false, send, onConfirm }) {
  const [countdown, setCountdown] = useState(AUTO_ADVANCE_SEC)
  const [selectedVoter, setSelectedVoter] = useState(null)
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

  // editable 모드: 2-탭 투표 보정
  const handleCorrectionClick = (playerId) => {
    if (!editable || !send) return
    if (!selectedVoter) {
      setSelectedVoter(playerId)
    } else if (selectedVoter === playerId) {
      setSelectedVoter(null)
    } else {
      send('werewolf_vote_player', { target_id: playerId }, selectedVoter)
      setSelectedVoter(null)
    }
  }

  const handleConfirm = () => {
    if (!send) return
    send('werewolf_vote_result_confirm', {})
    onConfirm?.()
  }

  return (
    <div
      className="ww-root"
      onClick={editable ? undefined : onComplete}
      style={{ ...ui.page, cursor: editable ? 'default' : 'pointer' }}
    >
      <WerewolfScene mood="blood" />
      <style>{CSS}</style>

      {/* 심판이 확정되는 화면이라 처음 한 번 붉게 번쩍인다 */}
      {!editable && <div className="ww-verdict-flash" />}

      <div style={{ ...ui.stage, gap: 16, ...styles.content, marginBottom: editable ? 12 : 60 }}>
        <div style={styles.title} className="ww-anim-title">
          {editable ? '투표 결과 맞나요?' : '투표 결과'}
        </div>

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

        {editable && (
          <div style={styles.correctionPanel} className="ww-panel ww-anim-in">
            <div style={styles.correctionHeader}>
              {selectedVoter
                ? <span>보정할 대상을 선택하세요 — 투표자 <b style={styles.hot}>{players.find(p => p.player_id === selectedVoter)?.playername}</b></span>
                : '오인식 수정: 투표자 이름을 누르세요'}
            </div>
            <div style={styles.correctionGrid}>
              {players.map(p => {
                const targetId = votes[p.player_id]
                const targetName = targetId ? players.find(pp => pp.player_id === targetId)?.playername : '기권'
                const isSelected = selectedVoter === p.player_id
                return (
                  <div
                    key={p.player_id}
                    onClick={() => handleCorrectionClick(p.player_id)}
                    style={{
                      ...styles.correctionRow,
                      ...(isSelected ? styles.correctionRowSelected : null),
                    }}
                  >
                    <span style={styles.correctionVoter}>{p.playername}</span>
                    <span style={styles.correctionArrow}>→</span>
                    <span style={styles.correctionTarget}>{targetName}</span>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {editable ? (
          <button onClick={handleConfirm} className="ww-press" style={{ ...ui.dangerButton, marginTop: 4, padding: '15px 52px', letterSpacing: '0.06em' }}>
            투표 확정
          </button>
        ) : (
          <div style={styles.tapHint}>
            화면을 터치하면 계속합니다
            {countdown > 0 && <span style={{ marginLeft: 7, opacity: 0.55 }}>({countdown})</span>}
          </div>
        )}
      </div>
    </div>
  )
}

const styles = {
  content: {
    width: '100%',
    maxWidth: 520,
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

  correctionPanel: {
    width: '100%',
    padding: '14px 16px',
    borderRadius: 16,
    borderColor: 'rgba(255,120,80,0.2)',
    animationDelay: '0.3s',
  },

  correctionHeader: {
    fontSize: 13,
    color: 'rgba(255,214,200,0.6)',
    marginBottom: 10,
    textAlign: 'center',
  },

  hot: { color: '#ff9068', fontWeight: 800 },

  correctionGrid: { display: 'flex', flexDirection: 'column', gap: 6 },

  correctionRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '9px 13px',
    borderRadius: 10,
    background: 'rgba(0,0,0,0.24)',
    border: '1px solid rgba(255,120,80,0.10)',
    cursor: 'pointer',
    transition: 'background 180ms ease, border-color 180ms ease',
  },

  correctionRowSelected: {
    background: 'rgba(255,150,70,0.2)',
    border: '1px solid rgba(255,190,110,0.7)',
  },

  correctionVoter: { fontSize: 14, fontWeight: 750, color: '#ffe6dc', width: 62, flexShrink: 0 },
  correctionArrow: { fontSize: 13, color: 'rgba(255,214,200,0.35)' },
  correctionTarget: { fontSize: 13, color: '#ff9068', flex: 1 },

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
