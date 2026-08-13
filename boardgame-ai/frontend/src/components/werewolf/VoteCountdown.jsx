import { useState, useEffect } from 'react'
import { audio } from '../../hooks/useAudioPlayer'
import { narrate } from '../../lines'
import WerewolfScene from './WerewolfScene'
import * as ui from './wwUi'

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
  const isShout = countdownRemaining === 0
  const countdownLabel = isShout ? '지목!' : String(countdownRemaining)

  return (
    <div className={`ww-root${isShout ? ' ww-shake' : ''}`} style={ui.page}>
      <WerewolfScene mood="blood" />
      <style>{CSS}</style>

      <button className="ww-hover ww-press" onClick={onExit} style={ui.exitButton}>나가기</button>

      <div style={{ ...ui.stage, gap: 18, width: '100%' }}>
        <div style={styles.title} className="ww-anim-title">투표</div>

        {/* 카운트다운. 숫자가 튀어나오면서 충격파 고리가 함께 퍼진다 —
            숫자만 바뀌면 "표시"지만 파문이 함께 가면 "호령"이 된다. */}
        <div style={styles.countStage}>
          {showCountdown ? (
            <div key={countdownRemaining} style={styles.countInner}>
              <span className="ww-shock" />
              {isShout && <span className="ww-shock ww-shock-2" />}
              <span
                className={isShout ? 'ww-count ww-count-shout' : 'ww-count'}
                style={{ color: isShout ? '#ff7038' : '#ffd9cc' }}
              >
                {countdownLabel}
              </span>
            </div>
          ) : (
            <div style={styles.readyLabel}>준비</div>
          )}
        </div>

        <div style={styles.guideBox} className="ww-panel ww-anim-in">
          {selectedVoter ? (
            <>
              <div style={styles.guideLine}>지목할 상대를 선택하세요.</div>
              <div style={styles.guideSub}>
                투표자 <b style={styles.hot}>{players.find(p => p.player_id === selectedVoter)?.playername}</b>
                <span style={styles.sep}>·</span>카드를 다시 누르면 취소
              </div>
            </>
          ) : (
            <>
              <div style={styles.guideLine}>지목할 플레이어를 손가락으로 가리키세요.</div>
              <div style={styles.guideSub}>
                직접 선택하려면 투표자 카드를 먼저 누르세요
                <span style={styles.sep}>·</span>자기 자신 지목은 기권
              </div>
            </>
          )}
        </div>

        {/* 진행 현황은 숫자보다 채워지는 칸으로 먼저 보인다 */}
        <div style={styles.progressRow}>
          <div style={styles.pips}>
            {players.map((p, i) => (
              <span
                key={p.player_id}
                style={{
                  ...styles.pip,
                  ...(votes[p.player_id] !== undefined ? styles.pipDone : null),
                  transitionDelay: `${i * 30}ms`,
                }}
              />
            ))}
          </div>
          <span style={styles.progressText}>{doneCount} / {total} 지목 완료</span>
        </div>

        <div style={styles.grid}>
          {players.map((p, i) => {
            const targetId = votes[p.player_id]
            const targetPlayer = targetId ? players.find(pp => pp.player_id === targetId) : null
            const done = targetId !== undefined
            const isSelected = selectedVoter === p.player_id
            const clickable = send && (!done || !!selectedVoter)
            return (
              <div
                key={p.player_id}
                className="ww-vote-card"
                style={{
                  ...styles.card,
                  ...(isSelected ? styles.cardSelected : done ? styles.cardDone : styles.cardPending),
                  cursor: clickable ? 'pointer' : 'default',
                  animationDelay: `${0.2 + i * 0.05}s`,
                }}
                onClick={() => handleCardClick(p.player_id)}
              >
                <div style={{ ...styles.cardNum, color: isSelected || done ? '#ffb59c' : 'rgba(255,214,200,0.35)' }}>
                  {String(i + 1).padStart(2, '0')}
                </div>
                <div style={{ ...styles.cardName, opacity: isSelected || done ? 1 : 0.62 }}>
                  {p.playername}
                </div>
                {isSelected ? (
                  <div style={{ ...styles.badge, ...styles.badgeSelected }}>선택됨</div>
                ) : done ? (
                  <div style={{ ...styles.badge, ...styles.badgeDone }} key={targetId}>
                    <span className="ww-arrow">→</span>
                    {targetPlayer?.playername ?? '?'}
                  </div>
                ) : (
                  <div style={{ ...styles.badge, ...styles.badgePending }}>대기 중</div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

const styles = {
  title: {
    fontSize: 'clamp(30px, 4.6vw, 46px)',
    fontWeight: 850,
    letterSpacing: '0.34em',
    paddingLeft: '0.34em',
    color: '#ffd9cc',
    textShadow: '0 0 44px rgba(220,70,30,0.7), 0 3px 12px rgba(0,0,0,0.7)',
  },

  countStage: {
    position: 'relative',
    height: 108,
    display: 'grid',
    placeItems: 'center',
  },

  countInner: {
    position: 'relative',
    display: 'grid',
    placeItems: 'center',
  },

  readyLabel: {
    fontSize: 15,
    fontWeight: 750,
    letterSpacing: '0.4em',
    paddingLeft: '0.4em',
    color: 'rgba(255,214,200,0.35)',
  },

  guideBox: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 7,
    padding: '16px 34px',
    borderColor: 'rgba(255,140,90,0.24)',
    animationDelay: '0.15s',
  },

  guideLine: {
    fontSize: 19,
    fontWeight: 700,
    letterSpacing: '-0.01em',
    color: '#ffe6dc',
  },

  guideSub: {
    fontSize: 14,
    color: 'rgba(255,214,200,0.55)',
  },

  hot: { color: '#ff9068', fontWeight: 800 },
  sep: { margin: '0 8px', opacity: 0.4 },

  progressRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    animation: 'ww-in 600ms ease-out 0.3s both',
  },

  pips: { display: 'flex', gap: 5 },

  pip: {
    width: 22,
    height: 4,
    borderRadius: 999,
    background: 'rgba(255,255,255,0.14)',
    transition: 'background 300ms ease, box-shadow 300ms ease',
  },

  pipDone: {
    background: 'var(--w-blood)',
    boxShadow: '0 0 10px rgba(255,106,60,0.7)',
  },

  progressText: {
    fontSize: 13,
    fontWeight: 750,
    letterSpacing: '0.1em',
    color: 'rgba(255,214,200,0.45)',
    fontVariantNumeric: 'tabular-nums',
  },

  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(132px, 1fr))',
    gap: 12,
    width: 'min(760px, 92vw)',
    marginTop: 4,
  },

  card: {
    position: 'relative',
    overflow: 'hidden',
    borderRadius: 16,
    padding: '16px 12px',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 8,
    transition: 'background 260ms ease, border-color 260ms ease, box-shadow 260ms ease, transform 200ms ease',
    animation: 'ww-in 520ms cubic-bezier(.2,.7,.2,1) both',
  },

  cardPending: {
    background: 'rgba(12,4,2,0.42)',
    border: '1px solid rgba(255,120,80,0.14)',
  },

  cardDone: {
    background: 'linear-gradient(180deg, rgba(150,34,14,0.34), rgba(60,10,4,0.42))',
    border: '1px solid rgba(255,120,80,0.45)',
    boxShadow: '0 0 26px rgba(200,60,30,0.22), 0 1px 0 rgba(255,255,255,0.06) inset',
  },

  cardSelected: {
    background: 'linear-gradient(180deg, rgba(255,150,70,0.28), rgba(120,40,8,0.4))',
    border: '1px solid rgba(255,190,110,0.85)',
    boxShadow: '0 0 0 3px rgba(255,170,80,0.16), 0 0 30px rgba(255,150,70,0.4)',
    transform: 'translateY(-3px)',
  },

  cardNum: {
    fontSize: 11,
    fontWeight: 800,
    letterSpacing: '0.14em',
    fontVariantNumeric: 'tabular-nums',
  },

  cardName: {
    fontSize: 18,
    fontWeight: 750,
    letterSpacing: '-0.01em',
    color: '#fff',
    textAlign: 'center',
  },

  badge: {
    maxWidth: '100%',
    padding: '4px 13px',
    borderRadius: 999,
    fontSize: 12.5,
    fontWeight: 700,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },

  badgeDone: { background: 'rgba(220,70,30,0.34)', color: '#ffb59c' },
  badgePending: { background: 'rgba(0,0,0,0.26)', color: 'rgba(255,214,200,0.35)' },
  badgeSelected: { background: 'rgba(255,170,80,0.34)', color: '#ffe4c4' },
}

const CSS = `
  /* "지목!" 순간 화면이 한 번 흔들린다. 게임에서 제일 센 순간이라 화면도
     반응해야 한다 — 다만 아주 짧게. 길면 멀미가 된다. */
  .ww-shake { animation: ww-shake 420ms cubic-bezier(.36,.07,.19,.97) both; }
  @keyframes ww-shake {
    0%, 100% { transform: translate(0, 0); }
    12%      { transform: translate(-7px, 3px); }
    28%      { transform: translate(6px, -3px); }
    46%      { transform: translate(-5px, -2px); }
    64%      { transform: translate(4px, 2px); }
    82%      { transform: translate(-2px, 0); }
  }

  .ww-count {
    display: block;
    font-size: clamp(72px, 11vw, 118px);
    font-weight: 900;
    line-height: 1;
    letter-spacing: 0.02em;
    font-variant-numeric: tabular-nums;
    text-shadow: 0 0 52px rgba(255,90,40,0.75), 0 6px 20px rgba(0,0,0,0.75);
    animation: ww-count-in 400ms cubic-bezier(.2,.9,.25,1.3) both;
  }
  @keyframes ww-count-in {
    0%   { opacity: 0; transform: scale(1.55); filter: blur(9px); }
    46%  { opacity: 1; transform: scale(0.94); filter: blur(0); }
    100% { opacity: 1; transform: scale(1); }
  }
  .ww-count-shout {
    letter-spacing: 0.1em;
    animation: ww-shout-in 520ms cubic-bezier(.2,.9,.25,1.35) both;
  }
  @keyframes ww-shout-in {
    0%   { opacity: 0; transform: scale(0.6); }
    44%  { opacity: 1; transform: scale(1.22); }
    72%  { transform: scale(0.97); }
    100% { transform: scale(1); }
  }

  /* 숫자에서 퍼져나가는 충격파 */
  .ww-shock {
    position: absolute;
    width: 150px; height: 150px;
    border-radius: 50%;
    border: 2px solid rgba(255,120,60,0.7);
    animation: ww-shock 700ms cubic-bezier(.15,.7,.3,1) both;
  }
  .ww-shock-2 { animation-delay: 130ms; border-color: rgba(255,190,120,0.55); }
  @keyframes ww-shock {
    0%   { opacity: 0.9; transform: scale(0.3); }
    100% { opacity: 0;   transform: scale(2.2); }
  }

  .ww-arrow {
    display: inline-block;
    margin-right: 5px;
    animation: ww-pop 320ms cubic-bezier(.2,.9,.25,1.4) both;
  }

  .ww-vote-card:active { transform: scale(0.98); }
`
