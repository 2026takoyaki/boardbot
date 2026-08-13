import { useEffect, useMemo, useState } from 'react'
import { narrate } from '../../lines'

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
    <div style={styles.page}>
      <div style={styles.moon} />
      <div style={styles.fog} />

      <aside style={styles.leftPanel}>
        <div style={styles.logoBox}>
          <div style={styles.logoSmall}>ROLE SETTING</div>
          <h1 style={styles.logoTitle}>한밤의 늑대인간</h1>
          <p style={styles.logoDesc}>플레이어 수에 맞게 역할 카드를 선택하세요.</p>
        </div>

        <div style={styles.ruleCard}>
          <div style={styles.ruleLabel}>필요 카드</div>
          <div style={styles.ruleCount}>
            {selected.length}
            <span>/ {needed}</span>
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

        <div style={styles.selectedBox}>
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
                    <img src={role.image} alt={role.name} style={styles.selectedImage} />
                  ) : (
                    <span style={styles.emptySlot}>+</span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </aside>

      <main style={styles.mainPanel}>
        <header style={styles.topBar}>
          <div>
            <h2 style={styles.mainTitle}>역할 선택</h2>
            <p style={styles.mainSub}>카드를 눌러 게임에 사용할 역할을 추가하세요.</p>
          </div>

          <div style={styles.topActions}>
            <button type="button" onClick={onExit} style={styles.exitButton}>
              나가기
            </button>
            <button
              type="button"
              disabled={!done}
              onClick={() => onStart(selected)}
              style={{
                ...styles.startButton,
                ...(!done ? styles.startButtonDisabled : {}),
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
          {filteredRoles.map((role) => {
            const isSelected = selected.includes(role.id)

            return (
              <button
                key={role.id}
                type="button"
                onClick={() => toggle(role.id)}
                style={{
                  ...styles.roleCard,
                  ...(isSelected ? styles.roleCardSelected : {}),
                }}
              >
                <div
                  style={{
                    ...styles.roleGlow,
                    background: role.color,
                  }}
                />

                {isSelected && <div style={styles.checkBadge}>✓</div>}

                <div style={styles.roleImageArea}>
                  <img src={role.image} alt={role.name} style={styles.roleImage} />
                </div>

                <div style={styles.roleInfo}>
                  <strong>{role.name}</strong>
                  <span>{role.team}</span>
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
    height: '100vh',
    position: 'relative',
    overflow: 'hidden',
    display: 'grid',
    gridTemplateColumns: '280px 1fr',
    gap: 14,
    padding: 16,
    boxSizing: 'border-box',
    fontFamily: 'Pretendard, system-ui, sans-serif',
    color: '#F8F1DD',
    background:
      'radial-gradient(circle at 25% 10%, rgba(237,196,92,0.2), transparent 24%), linear-gradient(160deg, #263A46 0%, #14252F 42%, #070D13 100%)',
  },

  moon: {
    position: 'absolute',
    top: 36,
    right: 60,
    width: 100,
    height: 100,
    borderRadius: '50%',
    background: 'radial-gradient(circle, #F3D77B 0%, #D9A93A 48%, transparent 70%)',
    opacity: 0.3,
    filter: 'blur(2px)',
  },

  fog: {
    position: 'absolute',
    inset: 0,
    background:
      'radial-gradient(circle at 50% 100%, rgba(255,255,255,0.08), transparent 38%), linear-gradient(180deg, transparent 0%, rgba(0,0,0,0.28) 100%)',
    pointerEvents: 'none',
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
    padding: 16,
    borderRadius: 20,
    background: 'rgba(5, 10, 15, 0.58)',
    border: '1px solid rgba(245, 203, 92, 0.24)',
    boxShadow: '0 22px 60px rgba(0,0,0,0.35)',
  },

  logoSmall: {
    color: '#EAC45C',
    fontSize: 11,
    fontWeight: 900,
    letterSpacing: 3,
  },

  logoTitle: {
    margin: '5px 0 5px',
    fontSize: 26,
    lineHeight: 1.1,
    color: '#F6D568',
    textShadow: '0 3px 0 rgba(0,0,0,0.55), 0 0 24px rgba(246,213,104,0.28)',
  },

  logoDesc: {
    margin: 0,
    color: 'rgba(255,255,255,0.65)',
    fontSize: 13,
    lineHeight: 1.4,
  },

  ruleCard: {
    padding: 14,
    borderRadius: 18,
    background: 'linear-gradient(180deg, rgba(41,56,65,0.9), rgba(9,17,24,0.9))',
    border: '1px solid rgba(255,255,255,0.1)',
    boxShadow: '0 18px 40px rgba(0,0,0,0.25)',
  },

  ruleLabel: {
    fontSize: 12,
    fontWeight: 800,
    color: 'rgba(255,255,255,0.65)',
  },

  ruleCount: {
    marginTop: 3,
    fontSize: 36,
    fontWeight: 950,
    color: '#FFFFFF',
  },

  progressTrack: {
    height: 8,
    borderRadius: 999,
    overflow: 'hidden',
    background: 'rgba(255,255,255,0.12)',
  },

  progressFill: {
    height: '100%',
    borderRadius: 999,
    background: 'linear-gradient(90deg, #D99D2B, #F8D76A)',
  },

  ruleText: {
    margin: '8px 0 0',
    color: 'rgba(255,255,255,0.58)',
    fontSize: 12,
  },

  selectedBox: {
    flex: 1,
    minHeight: 0,
    padding: 14,
    borderRadius: 20,
    background: 'rgba(5,10,15,0.46)',
    border: '1px solid rgba(255,255,255,0.1)',
    display: 'flex',
    flexDirection: 'column',
  },

  sectionTitle: {
    marginBottom: 10,
    fontSize: 14,
    fontWeight: 900,
    flexShrink: 0,
  },

  selectedGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gap: 7,
  },

  selectedSlot: {
    height: 50,
    borderRadius: 11,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'rgba(255,255,255,0.06)',
    border: '1px dashed rgba(255,255,255,0.2)',
  },

  selectedSlotFilled: {
    background: 'linear-gradient(180deg, rgba(62,78,88,0.9), rgba(16,26,34,0.9))',
    border: '1px solid rgba(246,213,104,0.45)',
    cursor: 'pointer',
  },

  selectedImage: {
    width: '100%',
    height: '100%',
    objectFit: 'contain',
    filter: 'drop-shadow(0 6px 8px rgba(0,0,0,0.65))',
  },

  emptySlot: {
    color: 'rgba(255,255,255,0.25)',
    fontSize: 20,
    fontWeight: 800,
  },

  mainPanel: {
    position: 'relative',
    zIndex: 1,
    minWidth: 0,
    minHeight: 0,
    padding: 16,
    borderRadius: 24,
    background: 'rgba(6, 13, 20, 0.62)',
    border: '1px solid rgba(245,203,92,0.2)',
    boxShadow: '0 28px 80px rgba(0,0,0,0.42)',
    display: 'flex',
    flexDirection: 'column',
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
    fontSize: 28,
    fontWeight: 950,
  },

  mainSub: {
    margin: '4px 0 0',
    color: 'rgba(255,255,255,0.58)',
    fontSize: 13,
  },

  startButton: {
    width: 180,
    height: 50,
    border: 0,
    borderRadius: 16,
    background: 'linear-gradient(180deg, #F6D568, #B8791A)',
    color: '#261400',
    fontSize: 18,
    fontWeight: 950,
    cursor: 'pointer',
    flexShrink: 0,
    boxShadow: '0 6px 0 #68420E, 0 14px 22px rgba(0,0,0,0.35)',
  },

  exitButton: {
    width: 104,
    height: 50,
    border: '1px solid rgba(255,255,255,0.18)',
    borderRadius: 16,
    background: 'rgba(255,255,255,0.08)',
    color: 'rgba(255,255,255,0.82)',
    fontSize: 16,
    fontWeight: 900,
    cursor: 'pointer',
    flexShrink: 0,
  },

  startButtonDisabled: {
    background: 'linear-gradient(180deg, #46545D, #27323A)',
    color: 'rgba(255,255,255,0.35)',
    boxShadow: 'none',
    cursor: 'not-allowed',
  },

  teamTabs: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gap: 8,
    marginBottom: 10,
    flexShrink: 0,
  },

  teamTab: {
    height: 38,
    borderRadius: 12,
    border: '1px solid rgba(255,255,255,0.1)',
    background: 'rgba(255,255,255,0.06)',
    color: 'rgba(255,255,255,0.68)',
    fontSize: 13,
    fontWeight: 900,
    cursor: 'pointer',
  },

  teamTabActive: {
    background: 'linear-gradient(180deg, rgba(82,63,36,0.95), rgba(32,24,17,0.95))',
    color: '#F6D568',
    border: '1px solid rgba(246,213,104,0.42)',
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
    border: '1px solid rgba(255,255,255,0.12)',
    background: 'linear-gradient(180deg, #263B46, #0D1821)',
    cursor: 'pointer',
    boxShadow: '0 10px 20px rgba(0,0,0,0.34), inset 0 1px 0 rgba(255,255,255,0.08)',
    display: 'flex',
    flexDirection: 'column',
  },

  roleCardSelected: {
    border: '2px solid #F6D568',
    boxShadow: '0 0 0 3px rgba(246,213,104,0.14), 0 0 28px rgba(246,213,104,0.28)',
    transform: 'translateY(-2px)',
  },

  roleGlow: {
    position: 'absolute',
    top: -40,
    left: -24,
    width: 120,
    height: 120,
    borderRadius: '50%',
    opacity: 0.22,
    filter: 'blur(16px)',
  },

  checkBadge: {
    position: 'absolute',
    top: 7,
    right: 7,
    zIndex: 3,
    width: 22,
    height: 22,
    borderRadius: '50%',
    background: '#F6D568',
    color: '#211300',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 11,
    fontWeight: 950,
    boxShadow: '0 4px 10px rgba(0,0,0,0.4)',
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
    filter: 'drop-shadow(0 8px 8px rgba(0,0,0,0.65))',
  },

  roleInfo: {
    position: 'relative',
    zIndex: 2,
    height: 34,
    flexShrink: 0,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 10,
    background: 'rgba(0,0,0,0.34)',
    color: '#FFFFFF',
    fontSize: 13,
    fontWeight: 900,
  },
}
