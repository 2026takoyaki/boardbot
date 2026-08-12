import { useState, useEffect } from 'react'
import { audio } from '../../hooks/useAudioPlayer'
import { narrate } from '../../lines'

export default function VoteCountdown({ players = [], votes = {}, send, onExit, countdownRemaining }) {
  // votes: { player_id: target_player_id } — 현재 지목 상태 (카운트다운 중 가변)
  const [selectedVoter, setSelectedVoter] = useState(null)

  const doneCount = Object.keys(votes).length
  const total = players.length

  useEffect(() => {
    // 안내 TTS를 먼저 재생하고, 그 발화가 끝난 뒤에야 카운트다운(5→0)을 시작하도록
    // 백엔드에 신호(werewolf_vote_countdown_start)를 보낸다. 페이지 전환 직후 곧바로
    // 숫자가 줄어 지목 타이밍을 놓치는 문제를 막는다. 준비 구간에도 미리 지목은 가능.
    narrate(send, 'werewolf.vote_intro')

    let started = false
    let unsubscribeEnd = null
    const startCountdown = () => {
      if (started) return
      started = true
      send?.('werewolf_vote_countdown_start', {})
    }

    // 안전장치: 안내 TTS가 전혀 시작되지 않으면(합성 실패 등) 4초 후 폴백으로 시작.
    const startWatchdog = setTimeout(startCountdown, 4000)

    // TTS가 "시작"된 뒤 그 "종료"를 기다린다. (직전 발화 잔여로 조기 시작되는 것 방지)
    const unsubscribeStart = audio.onNextTtsStarted(() => {
      clearTimeout(startWatchdog)
      unsubscribeEnd = audio.onNextTtsEnded(startCountdown)
    })

    return () => {
      clearTimeout(startWatchdog)
      unsubscribeStart()
      if (unsubscribeEnd) unsubscribeEnd()
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 카운트다운 숫자가 바뀔 때마다 읽어준다: 5→오, 4→사, ... 0→지목.
  // 숫자를 그대로 넘기면 TTS가 어색하게 읽어서 호령 문구를 카탈로그가 갖는다.
  useEffect(() => {
    if (countdownRemaining == null) return
    if (countdownRemaining < 0 || countdownRemaining > 5) return
    narrate(send, `werewolf.vote_count_${countdownRemaining}`)
  }, [countdownRemaining]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleCardClick = (playerId) => {
    if (!send) return
    if (!selectedVoter) {
      if (votes[playerId] !== undefined) return
      setSelectedVoter(playerId)
    } else if (selectedVoter === playerId) {
      setSelectedVoter(null)
    } else {
      send('werewolf_vote_player', { target_id: playerId }, selectedVoter)
      setSelectedVoter(null)
    }
  }

  // countdownRemaining: null=카운트다운 없음, 0="지목!", 1/2/3=숫자
  const showCountdown = countdownRemaining != null
  const countdownLabel = countdownRemaining === 0 ? '지목!' : String(countdownRemaining)

  return (
    <>
      <style>{`
        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(14px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes flicker {
          0%, 100% { opacity: 1; }
          45%      { opacity: 0.85; }
          50%      { opacity: 0.55; }
          55%      { opacity: 0.9; }
        }
        @keyframes checkPop {
          0%   { transform: scale(0.5); opacity: 0; }
          70%  { transform: scale(1.2); }
          100% { transform: scale(1);   opacity: 1; }
        }
        @keyframes countPop {
          0%   { transform: scale(1.4); opacity: 0; }
          40%  { transform: scale(0.95); opacity: 1; }
          100% { transform: scale(1); opacity: 1; }
        }
        @keyframes shoutPop {
          0%   { transform: scale(0.8); opacity: 0; }
          50%  { transform: scale(1.15); }
          100% { transform: scale(1); opacity: 1; }
        }
      `}</style>

      <div style={styles.page}>
        <button onClick={onExit} style={exitBtn}>나가기</button>

        {/* 배경 */}
        <div style={styles.sky} />
        <div style={styles.overlay} />

        {/* 마을 실루엣 */}
        <svg viewBox="0 0 800 160" preserveAspectRatio="xMidYMax slice" style={styles.silhouette}>
          <polygon points="40,160 62,95 84,160"    fill="#110500" />
          <polygon points="58,160 84,72 110,160"   fill="#110500" />
          <polygon points="95,160 118,100 141,160" fill="#110500" />
          <rect x="155" y="118" width="58" height="42" fill="#110500" />
          <polygon points="150,120 184,92 218,120"  fill="#110500" />
          <rect x="162" y="130" width="13" height="30" fill="#0a0300" />
          <rect x="245" y="86" width="32" height="74" fill="#110500" />
          <polygon points="240,88 261,62 282,88"   fill="#110500" />
          <rect x="300" y="112" width="52" height="48" fill="#110500" />
          <polygon points="295,114 326,86 357,114" fill="#110500" />
          <polygon points="372,160 394,90 416,160" fill="#110500" />
          <polygon points="390,160 416,70 442,160" fill="#110500" />
          <rect x="455" y="120" width="46" height="40" fill="#110500" />
          <polygon points="450,122 478,98 506,122" fill="#110500" />
          <rect x="524" y="96" width="72" height="64" fill="#110500" />
          <polygon points="519,98 560,68 601,98"   fill="#110500" />
          <rect x="552" y="74" width="16" height="26" fill="#110500" />
          <polygon points="618,160 638,102 658,160" fill="#110500" />
          <polygon points="646,160 670,84 694,160" fill="#110500" />
          <rect x="710" y="118" width="54" height="42" fill="#110500" />
          <polygon points="705,120 737,94 769,120" fill="#110500" />
        </svg>

        {/* 타이틀 */}
        <div style={{ ...styles.title, animation: 'flicker 4s ease-in-out infinite' }}>
          투표
        </div>

        {/* 카운트다운 숫자 */}
        {showCountdown && (
          <div
            key={countdownRemaining}
            style={{
              ...styles.countdownNum,
              animation: countdownRemaining === 0 ? 'shoutPop 0.4s ease-out both' : 'countPop 0.35s ease-out both',
              color: countdownRemaining === 0 ? '#ff6030' : '#f5c6c6',
            }}
          >
            {countdownLabel}
          </div>
        )}

        {/* 안내 텍스트 (카운트다운 중에도 표시) */}
        <div style={styles.guideBox}>
          {selectedVoter ? (
            <>
              <div style={styles.guideLine}>
                지목할 상대를 선택하세요.
              </div>
              <div style={styles.guideLineSub}>
                투표자: <span style={{ color: '#ff9980', fontWeight: 700 }}>
                  {players.find(p => p.player_id === selectedVoter)?.playername}
                </span>　|　카드를 다시 누르면 취소
              </div>
            </>
          ) : (
            <>
              <div style={styles.guideLine}>지목할 플레이어를 손가락으로 가리키세요.</div>
              <div style={styles.guideLineSub}>직접 선택: 투표자 카드를 먼저 누르세요. 자기 자신 지목은 기권입니다.</div>
            </>
          )}
        </div>

        {/* 진행 현황 */}
        <div style={styles.progressLabel}>
          {doneCount} / {total} 지목 완료
        </div>

        {/* 플레이어 카드 그리드 */}
        <div style={styles.grid}>
          {players.map((p, i) => {
            const targetId = votes[p.player_id]
            const targetPlayer = targetId ? players.find(pp => pp.player_id === targetId) : null
            const done = targetId !== undefined
            const isSelected = selectedVoter === p.player_id
            const clickable = send && (!done || !!selectedVoter)
            const cardStyle = {
              ...styles.card,
              ...(isSelected ? styles.cardSelected : done ? styles.cardDone : styles.cardPending),
              cursor: clickable ? 'pointer' : 'default',
            }
            return (
              <div
                key={p.player_id}
                style={cardStyle}
                onClick={() => handleCardClick(p.player_id)}
              >
                {/* 번호 */}
                <div style={{ ...styles.cardNum, color: isSelected ? '#ffe0b2' : done ? '#ff9980' : 'rgba(245,200,190,0.4)' }}>
                  {String(i + 1).padStart(2, '0')}
                </div>

                {/* 이름 */}
                <div style={{ ...styles.cardName, color: isSelected ? '#fff' : done ? '#fff' : 'rgba(245,200,190,0.6)' }}>
                  {p.playername}
                </div>

                {/* 상태 뱃지 */}
                {isSelected ? (
                  <div style={styles.badgeSelected}>선택됨</div>
                ) : done ? (
                  <div style={styles.badgeDone}>
                    <span style={{ animation: 'checkPop 0.3s ease-out both' }}>→</span>{' '}
                    {targetPlayer?.playername ?? '?'}
                  </div>
                ) : (
                  <div style={styles.badgePending}>대기 중</div>
                )}
              </div>
            )
          })}
        </div>


      </div>
    </>
  )
}

const styles = {
  page: {
    height: '100vh',
    overflow: 'hidden',
    position: 'relative',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 20,
    fontFamily: "'Segoe UI', 'Apple SD Gothic Neo', sans-serif",
    color: '#F8F1DD',
    userSelect: 'none',
  },

  sky: {
    position: 'absolute',
    inset: 0,
    background: 'linear-gradient(180deg, #0a0000 0%, #1a0200 20%, #3d0a05 42%, #7a1a08 62%, #b03010 78%, #c84010 100%)',
  },

  overlay: {
    position: 'absolute',
    inset: 0,
    background: 'radial-gradient(ellipse at 50% 40%, rgba(180,30,10,0.15), transparent 65%)',
    pointerEvents: 'none',
  },

  silhouette: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    width: '100%',
    height: 160,
    pointerEvents: 'none',
  },

  title: {
    position: 'relative',
    zIndex: 1,
    fontSize: 52,
    fontWeight: 800,
    letterSpacing: 8,
    color: '#f5c6c6',
    textShadow: '0 0 30px rgba(200,60,30,0.7), 0 2px 8px rgba(0,0,0,0.6)',
  },

  countdownNum: {
    position: 'relative',
    zIndex: 1,
    fontSize: 96,
    fontWeight: 900,
    letterSpacing: 4,
    textShadow: '0 0 40px rgba(255,80,30,0.8), 0 4px 16px rgba(0,0,0,0.7)',
    lineHeight: 1,
  },

  guideBox: {
    position: 'relative',
    zIndex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 8,
    background: 'rgba(0,0,0,0.35)',
    backdropFilter: 'blur(8px)',
    border: '1px solid rgba(200,80,50,0.25)',
    borderRadius: 16,
    padding: '18px 40px',
    animation: 'fadeUp 0.7s ease-out both',
  },

  guideLine: {
    fontSize: 20,
    fontWeight: 600,
    color: '#f5d8d0',
    textAlign: 'center',
  },

  guideLineSub: {
    fontSize: 15,
    color: 'rgba(245,200,190,0.6)',
    textAlign: 'center',
  },

  progressLabel: {
    position: 'relative',
    zIndex: 1,
    fontSize: 16,
    fontWeight: 700,
    letterSpacing: 2,
    color: 'rgba(245,200,190,0.5)',
    textTransform: 'uppercase',
  },

  grid: {
    position: 'relative',
    zIndex: 1,
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gap: 12,
    width: '100%',
    maxWidth: 680,
    padding: '0 24px',
    animation: 'fadeUp 0.7s ease-out 0.15s both',
  },

  card: {
    borderRadius: 14,
    padding: '18px 12px',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 8,
    transition: 'background 0.3s, border-color 0.3s',
  },

  cardPending: {
    background: 'rgba(0,0,0,0.3)',
    border: '1px solid rgba(200,80,50,0.18)',
  },

  cardDone: {
    background: 'rgba(180,40,20,0.25)',
    border: '1px solid rgba(255,120,80,0.45)',
    boxShadow: '0 0 14px rgba(200,60,30,0.2)',
  },

  cardSelected: {
    background: 'rgba(255,140,60,0.22)',
    border: '2px solid rgba(255,180,80,0.8)',
    boxShadow: '0 0 20px rgba(255,140,60,0.35)',
  },

  cardNum: {
    fontSize: 12,
    fontWeight: 700,
    letterSpacing: 1,
  },

  cardName: {
    fontSize: 18,
    fontWeight: 700,
    textAlign: 'center',
  },

  badgeDone: {
    fontSize: 13,
    fontWeight: 700,
    color: '#ff9980',
    background: 'rgba(200,60,30,0.3)',
    borderRadius: 20,
    padding: '4px 14px',
    maxWidth: '100%',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },

  badgePending: {
    fontSize: 13,
    color: 'rgba(245,200,190,0.4)',
    background: 'rgba(0,0,0,0.2)',
    borderRadius: 20,
    padding: '4px 14px',
  },

  badgeSelected: {
    fontSize: 13,
    fontWeight: 700,
    color: '#ffe0b2',
    background: 'rgba(255,140,60,0.35)',
    borderRadius: 20,
    padding: '4px 14px',
  },
}

const exitBtn = {
  position: 'absolute', top: 20, right: 20, zIndex: 10,
  padding: '8px 18px',
  border: '1px solid rgba(248,241,221,0.2)',
  borderRadius: 8,
  background: 'rgba(255,255,255,0.08)',
  color: 'rgba(248,241,221,0.7)',
  fontSize: 14, fontWeight: 600, cursor: 'pointer',
  backdropFilter: 'blur(8px)',
}
