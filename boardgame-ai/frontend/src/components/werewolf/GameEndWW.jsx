import { useEffect, useMemo } from 'react'
import { narrate } from '../../lines'
import WerewolfScene from './WerewolfScene'
import * as ui from './wwUi'

const ROLE_NAMES = {
  doppelganger: '도플갱어',
  werewolf: '늑대인간',
  minion: '하수인',
  seer: '예언자',
  robber: '강도',
  troublemaker: '말썽쟁이',
  drunk: '주정뱅이',
  insomniac: '불면증환자',
  tanner: '무두장이',
  hunter: '사냥꾼',
  mason: '프리메이슨',
  villager: '마을주민',
}

const normalizeRoleId = (id) => (id ?? '').replace(/_\d+$/, '')

// 시스템은 역할을 모르므로 승리팀 색이 없다. 투표 결과를 담담하게 비추는
// 새벽 톤(WerewolfScene의 dawn) 하나로 간다.

/**
 * 투표 결과 발표 화면.
 *
 * 시스템은 각 플레이어의 역할을 알지 못한다. 따라서 승패를 판정하지 않고
 * 득표 집계와 처형자까지만 발표한 뒤, 카드 공개와 승패 판단은 플레이어에게 넘긴다.
 *
 * @param players    [{ player_id, playername }]
 * @param votes      { voter_player_id: target_player_id }
 * @param executed   최다 득표자 player_id 배열. 빈 배열이면 처형 없음(전원 분산)
 * @param deckRoles  이번 판에 사용한 역할 카드 문자열 배열
 */
export default function GameEndWW({
  players = [],
  votes = {},
  executed = [],
  deckRoles = [],
  onChangePlayers,
  onChangeGame,
  onRestart,
  send,
}) {
  const nameOf = useMemo(() => {
    const map = {}
    players.forEach(p => { map[p.player_id] = p.playername ?? p.player_id })
    return map
  }, [players])

  // 득표 집계 + 나를 찍은 사람 목록
  const tally = useMemo(() => {
    const counts = {}
    const votersByTarget = {}
    Object.entries(votes).forEach(([voter, target]) => {
      if (!target) return
      counts[target] = (counts[target] ?? 0) + 1
      ;(votersByTarget[target] ??= []).push(voter)
    })
    return players
      .map(p => ({
        player_id: p.player_id,
        playername: p.playername ?? p.player_id,
        count: counts[p.player_id] ?? 0,
        voters: votersByTarget[p.player_id] ?? [],
        isExecuted: executed.includes(p.player_id),
      }))
      .sort((a, b) => b.count - a.count)
  }, [players, votes, executed])

  const headline = useMemo(() => {
    if (executed.length === 0) return '아무도 처형되지 않았습니다'
    if (executed.length === 1) return `${nameOf[executed[0]] ?? executed[0]} 님이 처형되었습니다`
    return `${executed.map(id => nameOf[id] ?? id).join(', ')} 님이 동률로 처형되었습니다`
  }, [executed, nameOf])

  const uniqueDeck = useMemo(() => {
    const counts = {}
    deckRoles.map(normalizeRoleId).filter(Boolean).forEach(r => {
      counts[r] = (counts[r] ?? 0) + 1
    })
    return Object.entries(counts)
  }, [deckRoles])

  useEffect(() => {
    narrate(send, 'werewolf.game_end', { headline })
  }, [])

  return (
    <div className="ww-root" style={ui.page}>
      <WerewolfScene mood="dawn" />
      <style>{CSS}</style>

      {/* 판이 끝난 화면. 한 번 크게 빛나고 가라앉는다. */}
      <div className="ww-finale" />

      <div style={{ ...ui.stage, ...styles.content }}>
        <span style={ui.eyebrow} className="ww-anim-down">
          <span style={ui.eyebrowDot} />
          투표 결과
        </span>

        <div style={styles.headline} className="ww-anim-title">{headline}</div>

        <div className="ww-rule" style={styles.rule}><i /></div>

        <div style={styles.sectionLabel} className="ww-anim-in">득표 집계</div>

        <div style={styles.tallyList}>
          {tally.map((row, i) => (
            <div
              key={row.player_id}
              className="ww-anim-in"
              style={{
                ...styles.tallyRow,
                ...(row.isExecuted ? styles.tallyRowExecuted : null),
                animationDelay: `${0.4 + i * 0.07}s`,
              }}
            >
              <div style={styles.tallyWho}>
                <span style={styles.playerName}>{row.playername}</span>
                {row.voters.length > 0 && (
                  <span style={styles.voterList}>
                    {row.voters.map(v => nameOf[v] ?? v).join(', ')} 지목
                  </span>
                )}
              </div>
              <span
                style={{
                  ...styles.voteCount,
                  color: row.isExecuted ? '#ff9068' : 'var(--w-ink)',
                }}
              >
                {row.count}<span style={styles.voteUnit}>표</span>
              </span>
            </div>
          ))}
        </div>

        {/* 카드 공개 안내 — 승패 판정은 플레이어 몫 */}
        <div style={styles.revealNotice} className="ww-anim-in">
          이제 각자 카드를 공개하세요. 승패는 직접 확인해 주세요.
          {uniqueDeck.length > 0 && (
            <div style={styles.deckLine}>
              이번 판 구성 ·{' '}
              {uniqueDeck.map(([role, n]) =>
                `${ROLE_NAMES[role] ?? role}${n > 1 ? ` ×${n}` : ''}`
              ).join(', ')}
            </div>
          )}
        </div>

        <div style={styles.btnRow} className="ww-anim-in">
          <button onClick={onChangePlayers} className="ww-hover ww-press" style={{ ...ui.ghostButton, flex: 1 }}>
            플레이어 변경
          </button>
          <button onClick={onChangeGame} className="ww-hover ww-press" style={{ ...ui.ghostButton, flex: 1 }}>
            게임 변경
          </button>
          <button onClick={onRestart} className="ww-press" style={{ ...ui.primaryButton, flex: 1.6 }}>
            게임 재시작
          </button>
        </div>
      </div>
    </div>
  )
}

const styles = {
  content: {
    gap: 15,
    width: '100%',
    maxWidth: 580,
    padding: '0 36px',
    marginBottom: 56,
  },

  headline: {
    fontSize: 'clamp(26px, 4.2vw, 36px)',
    fontWeight: 850,
    letterSpacing: '0.02em',
    textAlign: 'center',
    color: 'var(--w-ink)',
    textShadow: '0 0 50px rgba(255,200,90,0.35), 0 3px 16px rgba(0,0,0,0.6)',
    wordBreak: 'keep-all',
  },

  rule: { width: '100%', animation: 'ww-in 700ms ease-out 0.4s both' },

  sectionLabel: {
    fontSize: 12,
    fontWeight: 800,
    letterSpacing: '0.2em',
    color: 'var(--w-ink-faint)',
    animationDelay: '0.35s',
  },

  tallyList: {
    width: '100%',
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },

  tallyRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 14,
    background: 'rgba(10,6,4,0.42)',
    border: '1px solid rgba(255,255,255,0.07)',
    borderRadius: 14,
    padding: '13px 20px',
    WebkitBackdropFilter: 'blur(10px)',
    backdropFilter: 'blur(10px)',
  },

  tallyRowExecuted: {
    border: '1px solid rgba(255,140,100,0.45)',
    background: 'linear-gradient(90deg, rgba(120,20,8,0.42), rgba(40,8,4,0.42))',
    boxShadow: '0 0 26px rgba(200,60,30,0.18)',
  },

  tallyWho: { display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 },

  playerName: {
    fontSize: 18,
    fontWeight: 700,
    letterSpacing: '-0.01em',
    color: 'var(--w-ink)',
  },

  voterList: {
    fontSize: 12.5,
    color: 'var(--w-ink-faint)',
    fontWeight: 500,
  },

  voteCount: {
    fontSize: 20,
    fontWeight: 800,
    fontVariantNumeric: 'tabular-nums',
    flexShrink: 0,
  },

  voteUnit: { fontSize: 13, fontWeight: 650, marginLeft: 2, opacity: 0.65 },

  revealNotice: {
    width: '100%',
    textAlign: 'center',
    fontSize: 15,
    fontWeight: 600,
    color: 'var(--w-ink-soft)',
    lineHeight: 1.6,
    animationDelay: '0.6s',
  },

  deckLine: {
    marginTop: 6,
    fontSize: 12.5,
    fontWeight: 500,
    color: 'var(--w-ink-faint)',
  },

  btnRow: {
    display: 'flex',
    gap: 12,
    width: '100%',
    marginTop: 6,
    animationDelay: '0.75s',
  },
}

const CSS = `
  .ww-finale {
    position: absolute;
    inset: 0;
    z-index: 1;
    pointer-events: none;
    background: radial-gradient(ellipse 70% 60% at 50% 40%, rgba(255,214,120,0.4), transparent 70%);
    animation: ww-finale 1600ms ease-out both;
  }
  @keyframes ww-finale {
    0%   { opacity: 0; }
    18%  { opacity: 1; }
    100% { opacity: 0.14; }
  }
`
