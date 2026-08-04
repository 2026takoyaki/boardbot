import { useEffect, useRef, useState } from 'react'
import DiceFace, { DiceRow } from './DiceFace'
import { BONUS_SCORE, BONUS_THRESHOLD, TOTAL_ROUNDS } from './yachtCategories'

/**
 * 요트다이스 튜토리얼 인트로.
 *
 * 이전 튜토리얼은 플레이어가 바뀔 때마다 같은 설명을 처음부터 다시 읽었다.
 * 세 명이면 같은 문장을 세 번 듣는 셈이라, 두 번째부터는 아무도 안 듣는다.
 * 그래서 "무슨 게임인지"는 판 시작에 **한 번만** 여기서 끝내고, 실전에서는
 * 지금 눌러야 할 것만 한 줄씩 알려준다.
 *
 * 또 하나의 문제는 게임 규칙과 우리 장비 설명이 섞여 있던 것이다. 요트다이스를
 * 처음 하는 사람에게 "카메라가 인식합니다"는 규칙이 아니라 잡음이다. 여기서는
 * 게임 규칙(1·2·4번)과 이 테이블의 조작법(3번)을 카드 단위로 갈라 놓는다.
 *
 * 글보다 그림이 먼저다 — 각 장은 실제 주사위 눈으로 상황을 보여주고, 문장은
 * 그림을 거드는 정도만 쓴다.
 */

const GOLD = { face: 'var(--y-gold)', pip: 'oklch(0.20 0.03 60)', border: 'var(--y-gold)' }

const STEPS = [
  {
    key: 'what',
    kicker: '1 / 4',
    title: '주사위 5개로 족보를 만듭니다',
    body: `같은 눈을 모으거나 연속된 눈을 만들면 점수가 됩니다. 점수판 ${TOTAL_ROUNDS}칸을 `
      + '하나씩 채워가고, 다 채웠을 때 총점이 가장 높은 사람이 이깁니다.',
    narration:
      '요트다이스는 주사위 다섯 개로 족보를 만드는 게임입니다. '
      + '점수판 열두 칸을 하나씩 채워가고, 총점이 가장 높은 사람이 이깁니다.',
    visual: <WhatVisual />,
  },
  {
    key: 'turn',
    kicker: '2 / 4',
    title: '한 턴에 세 번까지 굴립니다',
    body: '마음에 드는 눈은 남기고 나머지만 다시 굴립니다. 세 번을 다 쓰지 않고 '
      + '중간에 멈춰도 됩니다.',
    narration:
      '한 턴에 주사위를 세 번까지 굴릴 수 있습니다. '
      + '마음에 드는 눈은 남기고 나머지만 다시 굴리면 됩니다.',
    visual: <TurnVisual />,
  },
  {
    key: 'table',
    kicker: '3 / 4',
    title: '주사위는 손으로, 화면은 점수만',
    body: '남길 주사위는 트레이 한쪽의 킵 존으로 옮겨두고, 나머지만 다시 굴리세요. '
      + '카메라가 알아서 읽습니다. '
      + '눈이 잘못 읽혔다면 화면의 “주사위 눈 수정”으로 바로잡을 수 있습니다.',
    narration:
      '주사위는 직접 손으로 굴리고, 남길 주사위는 트레이 한쪽의 킵 존으로 옮겨주세요. '
      + '카메라가 알아서 읽습니다. 태블릿에서는 점수 칸만 고르면 됩니다.',
    visual: <TableVisual />,
  },
  {
    key: 'score',
    kicker: '4 / 4',
    title: '점수 칸을 고르면 턴이 끝납니다',
    body: '점수판에 예상 점수가 미리 보입니다. 원하는 칸을 누르면 그 점수로 확정됩니다. '
      + `한 번 채운 칸은 다시 쓸 수 없고, 위쪽 여섯 칸 합이 ${BONUS_THRESHOLD}점을 넘으면 `
      + `보너스 ${BONUS_SCORE}점을 받습니다.`,
    narration:
      '굴림이 끝나면 점수판에서 칸을 하나 골라주세요. 예상 점수가 미리 표시됩니다. '
      + '한 번 채운 칸은 다시 쓸 수 없으니 신중하게 고르세요.',
    visual: <ScoreVisual />,
  },
]

export default function YachtTutorial({ onDone, onNarrate }) {
  const [index, setIndex] = useState(0)
  const step = STEPS[index]
  const isLast = index === STEPS.length - 1

  // 낭독은 카드가 바뀔 때 한 번만. onNarrate가 매 렌더 새로 만들어져도
  // 같은 문장을 다시 읽지 않도록 ref에 담아 의존성에서 뺀다.
  const narrateRef = useRef(onNarrate)
  useEffect(() => { narrateRef.current = onNarrate }, [onNarrate])
  useEffect(() => { narrateRef.current?.(STEPS[index].narration) }, [index])

  return (
    <div style={styles.overlay}>
      <style>{`
        @keyframes yt-in {
          0%   { opacity: 0; transform: translateY(18px) scale(0.985); }
          100% { opacity: 1; transform: none; }
        }
      `}</style>

      <div key={step.key} style={styles.card}>
        <div style={styles.kicker}>{step.kicker}</div>
        <h2 style={styles.title}>{step.title}</h2>
        <div style={styles.visual}>{step.visual}</div>
        <p style={styles.body}>{step.body}</p>

        <div style={styles.footer}>
          <button type="button" style={styles.skip} onClick={onDone}>
            건너뛰기
          </button>
          <div style={styles.dots}>
            {STEPS.map((s, i) => (
              <span key={s.key} style={styles.dot(i === index)} />
            ))}
          </div>
          <div style={styles.navRight}>
            {index > 0 && (
              <button type="button" style={styles.back} onClick={() => setIndex(i => i - 1)}>
                이전
              </button>
            )}
            <button
              type="button"
              style={styles.next}
              onClick={() => (isLast ? onDone() : setIndex(i => i + 1))}
            >
              {isLast ? '게임 시작' : '다음'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

/** 1장: 다섯 개가 같은 눈이면 최고 족보. 가장 강한 그림 하나로 시작한다. */
function WhatVisual() {
  return (
    <div style={styles.visualCol}>
      <DiceRow values={[4, 4, 4, 4, 4]} size={62} gap={10} {...GOLD} />
      <div style={styles.caption}>
        <strong style={styles.captionStrong}>Yacht</strong> · 50점
      </div>
    </div>
  )
}

/** 2장: 굴림 → 킵 → 재굴림. 세 줄을 세로로 놓아 시간 순서로 읽히게 한다. */
function TurnVisual() {
  const rows = [
    { label: '첫 굴림', dice: [2, 5, 5, 1, 3], kept: [] },
    { label: '5를 남기고', dice: [2, 5, 5, 1, 3], kept: [1, 2] },
    { label: '다시 굴림', dice: [5, 5, 5, 6, 2], kept: [0, 1, 2] },
  ]
  return (
    <div style={styles.turnRows}>
      {rows.map(row => (
        <div key={row.label} style={styles.turnRow}>
          <span style={styles.turnLabel}>{row.label}</span>
          <span style={styles.turnDice}>
            {row.dice.map((value, i) => (
              <DiceFace
                key={`${row.label}-${i}`}
                value={value}
                size={38}
                {...(row.kept.includes(i) ? GOLD : {})}
              />
            ))}
          </span>
        </div>
      ))}
    </div>
  )
}

/**
 * 3장: 트레이의 두 구역. 킵이 화면 조작이 아니라 물리적 이동임을 그림으로 못 박는다.
 *
 * 킵 존은 트레이 한쪽에 실제로 있는 자리다. 다만 시스템이 그 구역을 따로 읽는
 * 것은 아니고 굴릴 때마다 트레이 전체를 다시 인식하므로, 화면에는 "지금 놓인
 * 눈 다섯 개"만 나온다 — 어느 것이 킵된 것인지는 표시하지 않는다.
 */
function TableVisual() {
  return (
    <div style={styles.tray}>
      <div style={styles.trayZone}>
        <span style={styles.trayLabel}>굴림 존</span>
        <span style={styles.trayDice}>
          <DiceFace value={2} size={34} />
          <DiceFace value={6} size={34} />
        </span>
      </div>
      <div style={styles.trayArrow}>→</div>
      <div style={{ ...styles.trayZone, ...styles.trayZoneKeep }}>
        <span style={{ ...styles.trayLabel, color: 'var(--y-gold)' }}>킵 존</span>
        <span style={styles.trayDice}>
          <DiceFace value={5} size={34} {...GOLD} />
          <DiceFace value={5} size={34} {...GOLD} />
          <DiceFace value={5} size={34} {...GOLD} />
        </span>
      </div>
    </div>
  )
}

/** 4장: 점수판이 실제로 어떻게 보이는지. 예상 점수가 미리 뜬다는 것이 핵심이다. */
function ScoreVisual() {
  const rows = [
    { label: 'Fives', dice: [5], score: 15, pick: false },
    { label: 'Full House', dice: [2, 2, 5, 5, 5], score: 19, pick: true },
    { label: 'Choice', dice: [], score: 19, pick: false },
  ]
  return (
    <div style={styles.sheet}>
      {rows.map(row => (
        <div key={row.label} style={{ ...styles.sheetRow, ...(row.pick ? styles.sheetRowPick : {}) }}>
          <span style={styles.sheetLabel}>{row.label}</span>
          <span style={styles.sheetDice}>
            {row.dice.map((value, i) => (
              <DiceFace key={i} value={value} size={17} />
            ))}
          </span>
          <span style={{ ...styles.sheetScore, ...(row.pick ? { color: 'var(--y-gold)' } : {}) }}>
            {row.score}
          </span>
        </div>
      ))}
      <div style={styles.sheetHint}>누르면 그 점수로 확정됩니다</div>
    </div>
  )
}

const styles = {
  overlay: {
    position: 'fixed',
    inset: 0,
    zIndex: 70,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 20,
    background: 'oklch(0.15 0.025 168 / 0.92)',
  },
  card: {
    width: 'min(860px, 100%)',
    maxHeight: '100%',
    overflowY: 'auto',
    padding: '34px 40px 26px',
    background: 'var(--y-panel)',
    border: '1px solid var(--y-line)',
    borderRadius: 26,
    boxShadow: '0 32px 90px rgba(0,0,0,0.6)',
    animation: 'yt-in 340ms cubic-bezier(.2,.8,.25,1) both',
    textAlign: 'center',
  },
  kicker: {
    fontSize: 14,
    fontWeight: 800,
    letterSpacing: '0.14em',
    color: 'var(--y-gold)',
    marginBottom: 10,
  },
  // 글자 크기가 이 화면의 핵심이다. 테이블에 둘러앉은 사람이 몸을 기울이지
  // 않고 읽을 수 있어야 한다.
  title: {
    fontSize: 'clamp(28px, 3.6vw, 42px)',
    fontWeight: 850,
    lineHeight: 1.2,
    color: 'var(--y-text)',
    marginBottom: 24,
  },
  visual: { display: 'flex', justifyContent: 'center', marginBottom: 24 },
  visualCol: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 },
  caption: { fontSize: 20, fontWeight: 700, color: 'var(--y-text-soft)' },
  captionStrong: { color: 'var(--y-gold)', fontSize: 24, fontWeight: 850 },
  body: {
    margin: '0 auto 28px',
    maxWidth: 620,
    fontSize: 'clamp(17px, 1.9vw, 21px)',
    lineHeight: 1.65,
    color: 'var(--y-text-soft)',
  },
  turnRows: { display: 'grid', gap: 12 },
  turnRow: { display: 'flex', alignItems: 'center', gap: 16 },
  turnLabel: {
    width: 96,
    textAlign: 'right',
    fontSize: 15,
    fontWeight: 700,
    color: 'var(--y-text-mute)',
  },
  turnDice: { display: 'flex', gap: 7 },
  tray: {
    display: 'flex',
    alignItems: 'center',
    gap: 16,
    padding: 16,
    borderRadius: 18,
    background: 'oklch(0.24 0.035 168)',
    border: '1px solid var(--y-line-soft)',
  },
  trayZone: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 10,
    padding: '14px 18px',
    borderRadius: 14,
    border: '1px dashed var(--y-line)',
    minWidth: 140,
  },
  trayZoneKeep: {
    border: '1px dashed var(--y-gold)',
    background: 'color-mix(in oklch, var(--y-gold) 10%, transparent)',
  },
  trayLabel: { fontSize: 13, fontWeight: 800, color: 'var(--y-text-mute)' },
  trayDice: { display: 'flex', gap: 7 },
  trayArrow: { fontSize: 26, color: 'var(--y-gold)' },
  sheet: {
    width: 'min(420px, 100%)',
    padding: 12,
    borderRadius: 16,
    background: 'var(--y-panel-head)',
    border: '1px solid var(--y-line)',
    textAlign: 'left',
  },
  sheetRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '10px 12px',
    borderRadius: 10,
    fontSize: 16,
  },
  sheetRowPick: {
    background: 'color-mix(in oklch, var(--y-pick) 22%, transparent)',
    boxShadow: 'inset 0 0 0 1px color-mix(in oklch, var(--y-pick) 55%, transparent)',
  },
  sheetLabel: { width: 96, fontWeight: 700, color: 'var(--y-text)' },
  sheetDice: { flex: 1, display: 'flex', gap: 3, opacity: 0.75 },
  sheetScore: {
    fontFamily: 'var(--font-mono)',
    fontWeight: 800,
    color: 'var(--y-text-soft)',
  },
  sheetHint: {
    padding: '8px 12px 2px',
    fontSize: 13,
    color: 'var(--y-text-mute)',
  },
  footer: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 16,
    paddingTop: 20,
    borderTop: '1px solid var(--y-line-soft)',
  },
  dots: { display: 'flex', gap: 8 },
  dot: active => ({
    width: active ? 26 : 9,
    height: 9,
    borderRadius: 999,
    background: active ? 'var(--y-gold)' : 'var(--y-line)',
    transition: 'width 220ms ease, background 220ms ease',
  }),
  navRight: { display: 'flex', gap: 10 },
  skip: {
    padding: '12px 16px',
    fontSize: 15,
    fontWeight: 700,
    color: 'var(--y-text-mute)',
    background: 'transparent',
    border: 0,
    cursor: 'pointer',
  },
  back: {
    padding: '13px 22px',
    fontSize: 16,
    fontWeight: 750,
    color: 'var(--y-text-soft)',
    background: 'transparent',
    border: '1px solid var(--y-line)',
    borderRadius: 14,
    cursor: 'pointer',
  },
  next: {
    padding: '13px 30px',
    fontSize: 17,
    fontWeight: 850,
    color: 'oklch(0.20 0.03 60)',
    background: 'var(--y-gold)',
    border: 0,
    borderRadius: 14,
    cursor: 'pointer',
    boxShadow: '0 6px 18px color-mix(in oklch, var(--y-gold) 35%, transparent)',
  },
}
