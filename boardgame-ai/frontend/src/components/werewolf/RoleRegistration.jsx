import { useEffect, useMemo, useState } from 'react'
import { narrate } from '../../lines'
import WerewolfScene from './WerewolfScene'
import * as ui from './wwUi'

const ROLES = [
  { id: 'doppelganger', name: '도플갱어', image: '/roles/doppelganger.png', team: '마을 팀', color: '#7C3AED' },
  { id: 'werewolf_1', name: '늑대인간', image: '/roles/werewolf.png', team: '늑대 팀', color: '#DC2626' },
  { id: 'werewolf_2', name: '늑대인간', image: '/roles/werewolf.png', team: '늑대 팀', color: '#DC2626' },
  { id: 'minion', name: '하수인', image: '/roles/minion.png', team: '늑대 팀', color: '#9333EA' },
  { id: 'seer', name: '예언자', image: '/roles/seer.png', team: '마을 팀', color: '#2563EB' },
  { id: 'robber', name: '강도', image: '/roles/robber.png', team: '마을 팀', color: '#CA8A04' },
  { id: 'troublemaker', name: '말썽쟁이', image: '/roles/troublemaker.png', team: '마을 팀', color: '#059669' },
  { id: 'drunk', name: '주정뱅이', image: '/roles/drunk.png', team: '마을 팀', color: '#B45309' },
  { id: 'insomniac', name: '불면증환자', image: '/roles/insomniac.png', team: '마을 팀', color: '#4F46E5' },
  { id: 'tanner', name: '무두장이', image: '/roles/tanner.png', team: '중립 팀', color: '#92400E' },
  { id: 'hunter', name: '사냥꾼', image: '/roles/hunter.png', team: '마을 팀', color: '#15803D' },
  { id: 'mason_1', name: '프리메이슨', image: '/roles/mason.png', team: '마을 팀', color: '#0369A1' },
  { id: 'mason_2', name: '프리메이슨', image: '/roles/mason.png', team: '마을 팀', color: '#0369A1' },
  { id: 'villager_1', name: '마을주민', image: '/roles/villager.png', team: '마을 팀', color: '#65A30D' },
  { id: 'villager_2', name: '마을주민', image: '/roles/villager.png', team: '마을 팀', color: '#65A30D' },
  { id: 'villager_3', name: '마을주민', image: '/roles/villager.png', team: '마을 팀', color: '#65A30D' },
]

const TEAMS = ['전체', '마을 팀', '늑대 팀', '중립 팀']

// 팀 이름의 색은 팀마다 하나다. 역할 고유색(role.color)은 카드 뒤 번짐에만 쓴다 —
// 글자까지 역할색을 따라가면 '마을 팀'이 여덟 가지 색으로 적혀 팀이 안 읽힌다.
const TEAM_COLORS = {
  '마을 팀': '#60A5FA',
  '늑대 팀': '#F87171',
  '중립 팀': '#A8A29E',
}

// 프리메이슨은 항상 쌍으로 등장 — 1장만 선택 불가 (0장 또는 2장)
const MASON_IDS = ['mason_1', 'mason_2']

const KOREAN_NUMBERS = [
  '하나', '둘', '셋', '넷', '다섯', '여섯', '일곱', '여덟', '아홉', '열',
  '열하나', '열둘', '열셋', '열넷', '열다섯', '열여섯', '열일곱', '열여덟', '열아홉', '스물',
]
const toKoreanNum = (n) => KOREAN_NUMBERS[n - 1] ?? String(n)

export default function RoleRegistration({ players = [], onStart, onExit, send, connected }) {
  const [selected, setSelected] = useState([])
  const [activeTeam, setActiveTeam] = useState('전체')

  const needed = players.length + 3
  const done = selected.length === needed

  useEffect(() => {
    if (!connected) return
    narrate(send, 'werewolf.role_select_prompt', { count: toKoreanNum(needed) })
  }, [connected])

  const selectedRoles = selected
    .map((id) => ROLES.find((role) => role.id === id))
    .filter(Boolean)

  const filteredRoles = useMemo(() => {
    if (activeTeam === '전체') return ROLES
    return ROLES.filter((role) => role.team === activeTeam)
  }, [activeTeam])

  const toggle = (id) => {
    setSelected((prev) => {
      // 프리메이슨: 쌍으로만 토글 (1장만 선택되는 상태 방지)
      if (MASON_IDS.includes(id)) {
        const hasMason = MASON_IDS.some((m) => prev.includes(m))
        if (hasMason) return prev.filter((x) => !MASON_IDS.includes(x))
        // 두 장이 모두 들어갈 공간이 있을 때만 추가
        if (prev.length + MASON_IDS.length > needed) return prev
        return [...prev, ...MASON_IDS]
      }
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      if (prev.length >= needed) return prev
      return [...prev, id]
    })
  }

  return (
    <div className="ww-root" style={styles.page}>
      <WerewolfScene mood="dusk" />
      <style>{CSS}</style>

      <aside style={styles.leftPanel}>
        <div style={styles.logoBox} className="ww-panel">
          <div style={styles.logoSmall}>ROLE SETTING</div>
          <h1 style={styles.logoTitle}>한밤의 늑대인간</h1>
          <p style={styles.logoDesc}>플레이어 수에 맞게 역할 카드를 선택하세요.</p>
        </div>

        <div style={styles.ruleCard} className="ww-panel">
          <div style={styles.ruleLabel}>필요 카드</div>
          <div style={styles.ruleCount}>
            <span style={{ color: done ? 'var(--w-gold)' : 'var(--w-ink)' }}>{selected.length}</span>
            <span style={styles.ruleCountTotal}>/ {needed}</span>
          </div>
          <div style={styles.progressTrack}>
            <div
              style={{
                ...styles.progressFill,
                width: `${Math.min((selected.length / needed) * 100, 100)}%`,
              }}
            />
          </div>
          <p style={styles.ruleText}>
            플레이어 {players.length || 3}명 + 중앙 카드 3장
          </p>
        </div>

        <div style={styles.selectedBox} className="ww-panel">
          <div style={styles.sectionTitle}>선택된 역할</div>

          <div style={styles.selectedGrid}>
            {Array.from({ length: needed }).map((_, index) => {
              const role = selectedRoles[index]

              return (
                <div
                  key={index}
                  style={{
                    ...styles.selectedSlot,
                    ...(role ? styles.selectedSlotFilled : {}),
                  }}
                  onClick={role ? () => toggle(role.id) : undefined}
                >
                  {role ? (
                    <img
                      key={role.id}
                      src={role.image}
                      alt={role.name}
                      style={styles.selectedImage}
                      className="ww-slot-in"
                    />
                  ) : (
                    <span style={styles.emptySlot}>+</span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </aside>

      <main style={styles.mainPanel} className="ww-panel">
        <header style={styles.topBar}>
          <div>
            <h2 style={styles.mainTitle}>역할 선택</h2>
            <p style={styles.mainSub}>카드를 눌러 게임에 사용할 역할을 추가하세요.</p>
          </div>

          <div style={styles.topActions}>
            <button type="button" onClick={onExit} className="ww-hover ww-press" style={styles.exitButton}>
              나가기
            </button>
            <button
              type="button"
              disabled={!done}
              onClick={() => onStart(selected)}
              className={done ? 'ww-press ww-ready' : undefined}
              style={{
                ...styles.startButton,
                ...(!done ? styles.startButtonDisabled : null),
              }}
            >
              게임 시작
            </button>
          </div>
        </header>

        <nav style={styles.teamTabs}>
          {TEAMS.map((team) => (
            <button
              key={team}
              type="button"
              onClick={() => setActiveTeam(team)}
              style={{
                ...styles.teamTab,
                ...(activeTeam === team ? styles.teamTabActive : {}),
              }}
            >
              {team}
            </button>
          ))}
        </nav>

        <section style={styles.cardBoard}>
          {filteredRoles.map((role, index) => {
            const isSelected = selected.includes(role.id)

            return (
              <button
                key={role.id}
                type="button"
                onClick={() => toggle(role.id)}
                className="ww-role-card"
                style={{
                  ...styles.roleCard,
                  ...(isSelected ? styles.roleCardSelected : null),
                  animationDelay: `${index * 28}ms`,
                }}
              >
                {/* 팀 색은 카드 뒤에서 은은하게 번지게만 둔다. 카드 자체를
                    팀 색으로 칠하면 열여섯 장이 색 조각보가 된다. */}
                <div style={{ ...styles.roleGlow, background: role.color }} />

                {isSelected && <div style={styles.checkBadge} className="ww-check">✓</div>}

                <div style={styles.roleImageArea}>
                  <img src={role.image} alt={role.name} style={styles.roleImage} />
                </div>

                <div style={styles.roleInfo}>
                  <strong style={styles.roleName}>{role.name}</strong>
                  <span style={{ ...styles.roleTeam, color: TEAM_COLORS[role.team] }}>{role.team}</span>
                </div>
              </button>
            )
          })}
        </section>
      </main>
    </div>
  )
}

const styles = {
  page: {
    position: 'absolute',
    inset: 0,
    overflow: 'hidden',
    display: 'grid',
    gridTemplateColumns: '288px 1fr',
    gap: 14,
    padding: 16,
    boxSizing: 'border-box',
  },

  leftPanel: {
    position: 'relative',
    zIndex: 1,
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
    minHeight: 0,
  },

  logoBox: {
    padding: '16px 18px',
    animation: 'ww-in 560ms ease-out both',
  },

  logoSmall: {
    color: 'var(--w-gold)',
    fontSize: 10.5,
    fontWeight: 850,
    letterSpacing: '0.28em',
  },

  logoTitle: {
    margin: '7px 0 6px',
    fontSize: 26,
    fontWeight: 850,
    lineHeight: 1.12,
    letterSpacing: '-0.02em',
    color: 'var(--w-ink)',
    textShadow: '0 0 34px rgba(240,207,122,0.28), 0 2px 10px rgba(0,0,0,0.6)',
  },

  logoDesc: {
    margin: 0,
    color: 'var(--w-ink-mute)',
    fontSize: 13,
    lineHeight: 1.45,
    wordBreak: 'keep-all',
  },

  ruleCard: {
    padding: '14px 18px 16px',
    borderRadius: 18,
    animation: 'ww-in 560ms ease-out 60ms both',
  },

  ruleLabel: {
    fontSize: 10.5,
    fontWeight: 850,
    letterSpacing: '0.2em',
    color: 'var(--w-ink-faint)',
  },

  ruleCount: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 6,
    margin: '4px 0 10px',
    fontSize: 38,
    fontWeight: 900,
    letterSpacing: '-0.03em',
    fontVariantNumeric: 'tabular-nums',
    transition: 'color 200ms ease',
  },

  ruleCountTotal: {
    fontSize: 17,
    fontWeight: 750,
    color: 'var(--w-ink-faint)',
  },

  progressTrack: {
    height: 6,
    borderRadius: 999,
    overflow: 'hidden',
    background: 'rgba(255,255,255,0.10)',
  },

  progressFill: {
    height: '100%',
    borderRadius: 999,
    background: 'linear-gradient(90deg, var(--w-gold-deep), var(--w-gold))',
    boxShadow: '0 0 12px rgba(240,207,122,0.5)',
    // 카드를 누를 때마다 눈금이 미끄러진다. 즉시 점프하면 '반응'이 안 보인다.
    transition: 'width 320ms cubic-bezier(.2,.8,.25,1)',
  },

  ruleText: {
    margin: '9px 0 0',
    color: 'var(--w-ink-faint)',
    fontSize: 12,
  },

  selectedBox: {
    flex: 1,
    minHeight: 0,
    padding: '14px 16px',
    borderRadius: 20,
    display: 'flex',
    flexDirection: 'column',
    animation: 'ww-in 560ms ease-out 120ms both',
  },

  sectionTitle: {
    marginBottom: 11,
    fontSize: 10.5,
    fontWeight: 850,
    letterSpacing: '0.2em',
    color: 'var(--w-ink-faint)',
    flexShrink: 0,
  },

  selectedGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gap: 7,
  },

  selectedSlot: {
    height: 50,
    borderRadius: 12,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'rgba(255,255,255,0.04)',
    border: '1px dashed rgba(255,255,255,0.16)',
    transition: 'background 200ms ease, border-color 200ms ease, box-shadow 200ms ease',
  },

  selectedSlotFilled: {
    background: 'linear-gradient(180deg, rgba(60,52,80,0.9), rgba(14,14,26,0.92))',
    border: '1px solid var(--w-line-strong)',
    boxShadow: '0 0 16px rgba(240,207,122,0.18)',
    cursor: 'pointer',
  },

  selectedImage: {
    width: '100%',
    height: '100%',
    objectFit: 'contain',
    filter: 'drop-shadow(0 6px 8px rgba(0,0,0,0.65))',
  },

  emptySlot: {
    color: 'rgba(255,255,255,0.2)',
    fontSize: 19,
    fontWeight: 800,
  },

  mainPanel: {
    position: 'relative',
    zIndex: 1,
    minWidth: 0,
    minHeight: 0,
    padding: 18,
    borderRadius: 24,
    display: 'flex',
    flexDirection: 'column',
    animation: 'ww-in 560ms ease-out 40ms both',
  },

  topBar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 16,
    marginBottom: 10,
    flexShrink: 0,
  },

  topActions: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    flexShrink: 0,
  },

  mainTitle: {
    margin: 0,
    fontSize: 27,
    fontWeight: 850,
    letterSpacing: '-0.02em',
  },

  mainSub: {
    margin: '5px 0 0',
    color: 'var(--w-ink-mute)',
    fontSize: 13,
  },

  startButton: {
    ...ui.primaryButton,
    width: 176,
    height: 50,
    padding: 0,
    fontSize: 17,
    flexShrink: 0,
  },

  exitButton: {
    ...ui.ghostButton,
    width: 104,
    height: 50,
    padding: 0,
    fontSize: 15,
    flexShrink: 0,
  },

  startButtonDisabled: {
    background: 'rgba(255,255,255,0.06)',
    border: '1px solid rgba(255,255,255,0.10)',
    color: 'rgba(255,255,255,0.3)',
    boxShadow: 'none',
    cursor: 'not-allowed',
  },

  teamTabs: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gap: 8,
    marginBottom: 12,
    flexShrink: 0,
  },

  teamTab: {
    height: 38,
    borderRadius: 12,
    border: '1px solid rgba(255,255,255,0.08)',
    background: 'rgba(255,255,255,0.04)',
    color: 'var(--w-ink-mute)',
    fontFamily: 'inherit',
    fontSize: 13,
    fontWeight: 800,
    letterSpacing: '-0.01em',
    cursor: 'pointer',
    transition: 'background 160ms ease, color 160ms ease, border-color 160ms ease',
  },

  teamTabActive: {
    background: 'linear-gradient(180deg, rgba(240,207,122,0.22), rgba(240,207,122,0.08))',
    color: 'var(--w-gold)',
    border: '1px solid var(--w-line-strong)',
    boxShadow: '0 0 18px rgba(240,207,122,0.14)',
  },

  cardBoard: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gridTemplateRows: 'repeat(4, 1fr)',
    gap: 10,
    flex: 1,
    minHeight: 0,
  },

  roleCard: {
    position: 'relative',
    overflow: 'hidden',
    isolation: 'isolate',
    borderRadius: 16,
    padding: '8px 8px 6px',
    border: '1px solid rgba(255,255,255,0.10)',
    background: 'linear-gradient(180deg, rgba(42,50,72,0.85), rgba(10,14,24,0.9))',
    cursor: 'pointer',
    boxShadow: '0 12px 26px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.07)',
    display: 'flex',
    flexDirection: 'column',
    transition: 'transform 180ms cubic-bezier(.2,.8,.25,1.1), box-shadow 200ms ease, border-color 200ms ease',
    animation: 'ww-deal-in 420ms cubic-bezier(.2,.8,.3,1.05) both',
  },

  roleCardSelected: {
    border: '1px solid var(--w-gold)',
    boxShadow: '0 0 0 3px rgba(240,207,122,0.16), 0 0 30px rgba(240,207,122,0.3), 0 14px 30px rgba(0,0,0,0.45)',
    transform: 'translateY(-4px)',
  },

  roleGlow: {
    position: 'absolute',
    top: -40,
    left: -24,
    width: 130,
    height: 130,
    borderRadius: '50%',
    opacity: 0.26,
    filter: 'blur(18px)',
  },

  checkBadge: {
    position: 'absolute',
    top: 7,
    right: 7,
    zIndex: 3,
    width: 22,
    height: 22,
    borderRadius: '50%',
    background: 'var(--w-gold)',
    color: '#211300',
    display: 'grid',
    placeItems: 'center',
    fontSize: 11,
    fontWeight: 900,
    boxShadow: '0 4px 12px rgba(0,0,0,0.45), 0 0 14px rgba(240,207,122,0.6)',
  },

  roleImageArea: {
    position: 'relative',
    zIndex: 1,
    flex: 1,
    minHeight: 0,
    display: 'flex',
    alignItems: 'flex-end',
    justifyContent: 'center',
  },

  roleImage: {
    maxWidth: '100%',
    maxHeight: '100%',
    objectFit: 'contain',
    filter: 'drop-shadow(0 8px 10px rgba(0,0,0,0.7))',
  },

  roleInfo: {
    position: 'relative',
    zIndex: 2,
    height: 36,
    flexShrink: 0,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 1,
    borderRadius: 11,
    background: 'rgba(0,0,0,0.42)',
  },

  roleName: {
    fontSize: 13,
    fontWeight: 800,
    letterSpacing: '-0.01em',
    color: '#fff',
  },

  // 팀은 글자색으로만 구분한다. 뱃지를 달면 카드 한 장에 요소가 넷이 된다.
  // 색(TEAM_COLORS)은 어두운 카드 위에서 이미 밝게 잡아둔 값이라, 예전처럼
  // brightness로 끌어올리면 세 팀이 모두 흰색 근처로 몰린다.
  roleTeam: {
    fontSize: 10,
    fontWeight: 750,
    letterSpacing: '0.04em',
  },
}

const CSS = `
  @keyframes ww-deal-in {
    from { opacity: 0; transform: translateY(14px) scale(0.96); }
    to   { opacity: 1; transform: none; }
  }
  /* 선택된 카드는 위로 떠 있으므로 등장 애니메이션이 끝난 뒤 그 자리를 지켜야
     한다 — 애니메이션의 to를 덮어쓰지 않도록 hover는 shadow만 건드린다. */
  .ww-role-card:hover { border-color: rgba(255,255,255,0.22); }
  .ww-role-card:active { transform: scale(0.97); }

  /* 선택 표시는 톡 튀어나온다. 체크가 그냥 나타나면 눌렀는지 알기 어렵다. */
  .ww-check { animation: ww-check 320ms cubic-bezier(.2,.9,.25,1.6) both; }
  @keyframes ww-check {
    0%   { opacity: 0; transform: scale(0.2) rotate(-40deg); }
    100% { opacity: 1; transform: scale(1) rotate(0); }
  }

  .ww-slot-in { animation: ww-check 280ms cubic-bezier(.2,.9,.25,1.4) both; }

  /* 필요한 장수를 다 채우면 시작 버튼이 스스로 숨을 쉰다 */
  .ww-ready { animation: ww-ready 2.2s ease-in-out infinite; }
  @keyframes ww-ready {
    0%, 100% { box-shadow: 0 1px 0 rgba(255,255,255,0.5) inset, 0 10px 30px rgba(224,178,70,0.28); }
    50%      { box-shadow: 0 1px 0 rgba(255,255,255,0.5) inset, 0 10px 40px rgba(240,207,122,0.6); }
  }
`
