import DiceFace from './DiceFace'
import { BONUS_SCORE, BONUS_THRESHOLD, HAND_RULES, TOTAL_ROUNDS } from './yachtCategories'

/**
 * 게임 규칙 화면.
 *
 * 이전에는 족보마다 카드를 하나씩 만들어 두 열로 늘어놓았는데, 칸이 여덟 개면
 * 눈이 어디를 먼저 볼지 정하지 못한다. 여기서는 한 줄에 하나씩 같은 자리에
 * 이름·예시·점수를 놓아 세로로만 훑으면 되게 한다.
 *
 * 족보 그림은 점수판 칸 옆의 힌트와 같은 부품(DiceFace)을 쓴다. 설명에서 본
 * 그림이 점수판에도 그대로 있어야 "그거였구나"가 된다.
 */

const PLAY_STEPS = [
  '주사위 5개를 트레이 안에 굴립니다.',
  '남기고 싶은 눈은 트레이 한쪽의 킵 존으로 옮기고, 나머지만 다시 굴립니다.',
  '한 턴에 최대 세 번까지 굴릴 수 있습니다. 그 전에 멈춰도 됩니다.',
  '점수판에서 칸 하나를 골라 기록하면 턴이 끝납니다. 한 번 채운 칸은 다시 쓸 수 없습니다.',
]

const TABLE_NOTES = [
  '주사위는 카메라가 읽습니다. 태블릿에서는 점수 칸만 고르면 됩니다.',
  '킵은 화면이 아니라 실제 주사위를 킵 존으로 옮겨서 합니다.',
  '눈이 잘못 읽혔다면 주사위 그림 아래 “주사위 눈 수정”으로 바로잡을 수 있습니다.',
]

export default function YachtRules({ onClose }) {
  return (
    <div style={styles.shade} onClick={onClose}>
      <div style={styles.panel} onClick={event => event.stopPropagation()}>
        <div style={styles.head}>
          <span style={styles.headTitle}>게임 규칙</span>
          <button type="button" style={styles.close} onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </div>

        <div style={styles.body} className="scroll">
          <section style={styles.section}>
            <h3 style={styles.sectionTitle}>게임 진행</h3>
            <p style={styles.lede}>
              점수판 {TOTAL_ROUNDS}칸을 모두 채우면 게임이 끝납니다. 총점이 가장 높은
              사람이 승리합니다.
            </p>
            <ol style={styles.steps}>
              {PLAY_STEPS.map((step, index) => (
                <li key={step} style={styles.step}>
                  <span style={styles.stepNum}>{index + 1}</span>
                  <span>{step}</span>
                </li>
              ))}
            </ol>
          </section>

          <section style={styles.section}>
            <h3 style={styles.sectionTitle}>족보와 점수</h3>
            <div style={styles.tableHead}>
              <span>족보</span>
              <span>예시</span>
              <span style={styles.tableHeadScore}>점수</span>
            </div>
            {HAND_RULES.map(rule => (
              <div key={rule.name} style={styles.ruleRow}>
                <div style={styles.ruleName}>
                  <span style={styles.ruleTitle}>{rule.name}</span>
                  <span style={styles.ruleDesc}>{rule.desc}</span>
                </div>
                <div style={styles.ruleDice}>
                  {rule.dice.map((value, index) => (
                    <DiceFace
                      key={`${rule.name}-${index}`}
                      value={value}
                      size={26}
                      face={faceOf(rule, index)}
                      pip={pipOf(rule, index)}
                      border={edgeOf(rule, index)}
                    />
                  ))}
                </div>
                <div style={styles.ruleScoreCell}>
                  <span style={styles.ruleScore}>{rule.score}</span>
                  {rule.detail && <span style={styles.ruleDetail}>{rule.detail}</span>}
                </div>
              </div>
            ))}
          </section>

          <section style={styles.section}>
            <h3 style={styles.sectionTitle}>이 테이블에서는</h3>
            <ul style={styles.notes}>
              {TABLE_NOTES.map(note => (
                <li key={note} style={styles.note}>{note}</li>
              ))}
            </ul>
            <p style={styles.footNote}>
              상단(Aces~Sixes) 합계가 {BONUS_THRESHOLD}점을 넘으면 보너스 {BONUS_SCORE}점이
              자동으로 붙습니다.
            </p>
          </section>
        </div>
      </div>
    </div>
  )
}

// 예시 주사위는 "왜 이 족보인지"를 색으로 가리킨다. 조건을 만족시킨 눈만
// 밝게 두고 나머지는 남는 주사위라는 뜻으로 어둡게 둔다.
const isMarked = (rule, index) => rule.mark?.includes(index)
const isMarked2 = (rule, index) => rule.mark2?.includes(index)

function faceOf(rule, index) {
  if (isMarked(rule, index)) return 'var(--y-gold)'
  if (isMarked2(rule, index)) return 'var(--y-pick)'
  return 'var(--y-die-face)'
}

function pipOf(rule, index) {
  return isMarked(rule, index) || isMarked2(rule, index)
    ? 'oklch(0.20 0.03 60)'
    : 'var(--y-die-pip)'
}

function edgeOf(rule, index) {
  if (isMarked(rule, index)) return 'var(--y-gold)'
  if (isMarked2(rule, index)) return 'var(--y-pick)'
  return 'var(--y-die-edge)'
}

const styles = {
  shade: {
    position: 'fixed',
    inset: 0,
    zIndex: 60,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 18,
    background: 'oklch(0.14 0.02 168 / 0.74)',
    backdropFilter: 'blur(3px)',
    WebkitBackdropFilter: 'blur(3px)',
  },
  panel: {
    width: 'min(1000px, 100%)',
    maxHeight: '100%',
    display: 'flex',
    flexDirection: 'column',
    background: 'var(--y-panel)',
    border: '1px solid var(--y-line)',
    borderRadius: 22,
    overflow: 'hidden',
    boxShadow: '0 30px 80px rgba(0,0,0,0.55)',
  },
  head: {
    flexShrink: 0,
    height: 66,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0 22px',
    background: 'var(--y-panel-head)',
    borderBottom: '1px solid var(--y-line)',
  },
  headTitle: { fontSize: 22, fontWeight: 800, color: 'var(--y-text)' },
  close: {
    width: 40,
    height: 40,
    borderRadius: 12,
    border: '1px solid var(--y-line)',
    background: 'transparent',
    color: 'var(--y-text-soft)',
    fontSize: 17,
    cursor: 'pointer',
  },
  body: { padding: '22px 24px 28px', overflowY: 'auto' },
  section: { marginBottom: 30 },
  sectionTitle: {
    fontSize: 15,
    fontWeight: 800,
    letterSpacing: '0.08em',
    color: 'var(--y-gold)',
    marginBottom: 12,
  },
  lede: {
    margin: '0 0 14px',
    fontSize: 17,
    lineHeight: 1.55,
    color: 'var(--y-text-soft)',
  },
  steps: { margin: 0, padding: 0, listStyle: 'none', display: 'grid', gap: 8 },
  step: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 12,
    fontSize: 17,
    lineHeight: 1.5,
    color: 'var(--y-text)',
  },
  stepNum: {
    flexShrink: 0,
    width: 26,
    height: 26,
    borderRadius: '50%',
    display: 'grid',
    placeItems: 'center',
    background: 'var(--y-gold)',
    color: 'oklch(0.22 0.03 60)',
    fontSize: 14,
    fontWeight: 850,
  },
  // 세 열의 자리를 고정한다. 행마다 폭이 달라지면 "일렬"이 되지 않는다.
  tableHead: {
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 1fr) 190px 168px',
    gap: 14,
    padding: '0 12px 8px',
    fontSize: 13,
    fontWeight: 750,
    letterSpacing: '0.05em',
    color: 'var(--y-text-mute)',
  },
  tableHeadScore: { textAlign: 'right' },
  ruleRow: {
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 1fr) 190px 168px',
    gap: 14,
    alignItems: 'center',
    padding: '11px 12px',
    borderTop: '1px solid var(--y-line-soft)',
  },
  ruleName: { display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 },
  ruleTitle: { fontSize: 18, fontWeight: 800, color: 'var(--y-text)' },
  ruleDesc: { fontSize: 14, color: 'var(--y-text-mute)', lineHeight: 1.4 },
  ruleDice: { display: 'flex', gap: 5 },
  ruleScoreCell: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-end',
    gap: 3,
    textAlign: 'right',
  },
  ruleScore: { fontSize: 16, fontWeight: 800, color: 'var(--y-gold)' },
  ruleDetail: { fontSize: 13, color: 'var(--y-text-mute)' },
  notes: { margin: 0, padding: '0 0 0 20px', display: 'grid', gap: 7 },
  note: { fontSize: 16, lineHeight: 1.5, color: 'var(--y-text-soft)' },
  footNote: {
    margin: '14px 0 0',
    padding: '12px 14px',
    borderRadius: 12,
    background: 'color-mix(in oklch, var(--y-gold) 12%, transparent)',
    border: '1px solid color-mix(in oklch, var(--y-gold) 30%, transparent)',
    fontSize: 15,
    color: 'var(--y-text)',
  },
}
