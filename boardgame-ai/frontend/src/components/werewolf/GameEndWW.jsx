import { useEffect, useMemo } from 'react'
import { narrate } from '../../lines'

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

// 시스템은 역할을 모르므로 승리팀 색이 없다. 투표 결과를 담담하게 비추는 새벽 톤 하나로 간다.
const SKY = 'linear-gradient(180deg, #0f0800 0%, #2d1400 25%, #6e3510 50%, #b86018 70%, #d4920a 85%, #e8b830 100%)'
const GLOW = 'rgba(230,180,40,0.18)'
const ACCENT = '#F6D568'

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
    <>
      <style>{`
        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(14px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes headlinePop {
          0%   { opacity: 0; transform: scale(0.88); }
          70%  { transform: scale(1.03); }
          100% { opacity: 1; transform: scale(1); }
        }
        @keyframes flicker {
          0%, 100% { opacity: 1; }
          45% { opacity: 0.85; }
          50% { opacity: 0.55; }
          55% { opacity: 0.9; }
        }
      `}</style>

      <div style={{ ...styles.page, background: SKY }}>

        {/* 배경 오버레이 */}
        <div style={{ ...styles.overlay, background: `radial-gradient(ellipse at 50% 35%, ${GLOW}, transparent 60%)` }} />

        {/* 마을 실루엣 */}
        <svg viewBox="0 0 800 160" preserveAspectRatio="xMidYMax slice" style={styles.silhouette}>
          <polygon points="40,160 62,95 84,160"    fill="#0a0400" />
          <polygon points="58,160 84,72 110,160"   fill="#0a0400" />
          <polygon points="95,160 118,100 141,160" fill="#0a0400" />
          <rect x="155" y="118" width="58" height="42" fill="#0a0400" />
          <polygon points="150,120 184,92 218,120"  fill="#0a0400" />
          <rect x="162" y="130" width="13" height="30" fill="#050200" />
          <rect x="245" y="86" width="32" height="74" fill="#0a0400" />
          <polygon points="240,88 261,62 282,88"   fill="#0a0400" />
          <rect x="300" y="112" width="52" height="48" fill="#0a0400" />
          <polygon points="295,114 326,86 357,114" fill="#0a0400" />
          <polygon points="372,160 394,90 416,160" fill="#0a0400" />
          <polygon points="390,160 416,70 442,160" fill="#0a0400" />
          <rect x="455" y="120" width="46" height="40" fill="#0a0400" />
          <polygon points="450,122 478,98 506,122" fill="#0a0400" />
          <rect x="524" y="96" width="72" height="64" fill="#0a0400" />
          <polygon points="519,98 560,68 601,98"   fill="#0a0400" />
          <rect x="552" y="74" width="16" height="26" fill="#0a0400" />
          <polygon points="618,160 638,102 658,160" fill="#0a0400" />
          <polygon points="646,160 670,84 694,160" fill="#0a0400" />
          <rect x="710" y="118" width="54" height="42" fill="#0a0400" />
          <polygon points="705,120 737,94 769,120" fill="#0a0400" />
        </svg>

        {/* 컨텐츠 */}
        <div style={styles.content}>

          <div style={{ ...styles.teamLabel, color: ACCENT, animation: 'flicker 4s ease-in-out infinite' }}>
            투표 결과
          </div>

          <div style={{ ...styles.headline, animation: 'headlinePop 0.7s cubic-bezier(0.22,0.61,0.36,1) 0.1s both' }}>
            {headline}
          </div>

          {/* 득표 집계 */}
          <div style={{ ...styles.sectionLabel, animation: 'fadeUp 0.5s ease-out 0.3s both' }}>
            득표 집계
          </div>

          <div style={{ ...styles.roleList, animation: 'fadeUp 0.5s ease-out 0.4s both' }}>
            {tally.map((row, i) => (
              <div key={row.player_id} style={{
                ...styles.roleRow,
                ...(row.isExecuted ? styles.roleRowExecuted : {}),
                animation: `fadeUp 0.4s ease-out ${0.4 + i * 0.07}s both`,
              }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  <span style={styles.playerName}>{row.playername}</span>
                  {row.voters.length > 0 && (
                    <span style={styles.voterList}>
                      {row.voters.map(v => nameOf[v] ?? v).join(', ')} 지목
                    </span>
                  )}
                </div>
                <span style={{
                  ...styles.voteCount,
                  color: row.isExecuted ? '#ff9980' : 'rgba(248,241,221,0.85)',
                }}>
                  {row.count}표
                </span>
              </div>
            ))}
          </div>

          {/* 카드 공개 안내 — 승패 판정은 플레이어 몫 */}
          <div style={{ ...styles.revealNotice, animation: 'fadeUp 0.5s ease-out 0.55s both' }}>
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

          {/* 하단 버튼 */}
          <div style={{ ...styles.btnRow, animation: 'fadeUp 0.5s ease-out 0.7s both' }}>
            <button onClick={onChangePlayers} style={styles.btnSecondary}>
              플레이어 변경
            </button>
            <button onClick={onChangeGame} style={styles.btnSecondary}>
              게임 변경
            </button>
            <button onClick={onRestart} style={{ ...styles.btnPrimary, background: `linear-gradient(135deg, ${ACCENT}, #8a5010)` }}>
              게임 재시작
            </button>
          </div>

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
    fontFamily: "'Segoe UI', 'Apple SD Gothic Neo', sans-serif",
    color: '#F8F1DD',
    userSelect: 'none',
  },

  overlay: {
    position: 'absolute',
    inset: 0,
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

  content: {
    position: 'relative',
    zIndex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 18,
    width: '100%',
    maxWidth: 560,
    padding: '0 36px',
    marginBottom: 80,
  },

  teamLabel: {
    fontSize: 18,
    fontWeight: 700,
    letterSpacing: 4,
    textTransform: 'uppercase',
    textShadow: '0 0 20px rgba(255,200,80,0.4)',
  },

  headline: {
    fontSize: 34,
    fontWeight: 800,
    letterSpacing: -0.5,
    textAlign: 'center',
    color: '#fff8e1',
    textShadow: '0 2px 16px rgba(0,0,0,0.5)',
  },

  sectionLabel: {
    fontSize: 15,
    fontWeight: 700,
    letterSpacing: 2,
    color: 'rgba(248,241,221,0.4)',
    textTransform: 'uppercase',
    marginTop: 4,
  },

  roleList: {
    width: '100%',
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },

  roleRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    background: 'rgba(0,0,0,0.3)',
    border: '1px solid rgba(255,255,255,0.07)',
    borderRadius: 12,
    padding: '14px 24px',
    backdropFilter: 'blur(6px)',
  },

  roleRowExecuted: {
    border: '1px solid rgba(255,153,128,0.45)',
    background: 'rgba(60,0,0,0.35)',
  },

  playerName: {
    fontSize: 19,
    fontWeight: 600,
    color: '#F8F1DD',
  },

  voterList: {
    fontSize: 13,
    color: 'rgba(248,241,221,0.38)',
    fontWeight: 400,
  },

  voteCount: {
    fontSize: 18,
    fontWeight: 700,
  },

  revealNotice: {
    width: '100%',
    textAlign: 'center',
    fontSize: 15,
    fontWeight: 600,
    color: 'rgba(248,241,221,0.7)',
    lineHeight: 1.6,
  },

  deckLine: {
    marginTop: 6,
    fontSize: 13,
    fontWeight: 400,
    color: 'rgba(248,241,221,0.35)',
  },

  btnRow: {
    display: 'flex',
    gap: 14,
    width: '100%',
    marginTop: 4,
  },

  btnSecondary: {
    flex: 1,
    padding: '18px 0',
    border: '1.5px solid rgba(248,241,221,0.2)',
    borderRadius: 16,
    background: 'rgba(0,0,0,0.4)',
    backdropFilter: 'blur(8px)',
    color: 'rgba(248,241,221,0.75)',
    fontSize: 18,
    fontWeight: 600,
    cursor: 'pointer',
    letterSpacing: 0.5,
  },

  btnPrimary: {
    flex: 2,
    padding: '18px 0',
    border: 'none',
    borderRadius: 16,
    color: '#1A0A00',
    fontSize: 18,
    fontWeight: 700,
    cursor: 'pointer',
    letterSpacing: 0.5,
    boxShadow: '0 6px 0 rgba(0,0,0,0.3), 0 8px 20px rgba(0,0,0,0.4)',
  },
}
