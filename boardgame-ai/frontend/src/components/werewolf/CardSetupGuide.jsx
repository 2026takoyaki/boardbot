import { useState, useEffect, useRef } from 'react'
import { audio as audioApi } from '../../hooks/useAudioPlayer'
import { narrate, useLines } from '../../lines'
import WerewolfScene from './WerewolfScene'
import * as ui from './wwUi'

const ROLE_NAMES = {
  doppelganger: '도플갱어',
  werewolf:     '늑대인간',
  minion:       '하수인',
  mason:        '프리메이슨',
  seer:         '예언자',
  robber:       '강도',
  troublemaker: '말썽쟁이',
  drunk:        '주정뱅이',
  insomniac:    '불면증환자',
  tanner:       '무두장이',
  hunter:       '사냥꾼',
  villager:     '마을주민',
}

const ROLE_INFO = {
  doppelganger: {
    name: '도플갱어', image: '/roles/doppelganger.png',
    gradient: 'linear-gradient(135deg, #4a1a6b, #2a0a3a)',
    action: '밤에 깨어나 다른 플레이어 한 명의 카드를 확인합니다. 확인한 즉시 그 역할이 되어 해당 역할의 행동을 수행합니다.',
    winCondition: '복사한 역할의 팀이 승리하면 함께 승리합니다.',
  },
  werewolf: {
    name: '늑대인간', image: '/roles/werewolf.png',
    gradient: 'linear-gradient(135deg, #6b1a1a, #3a0a0a)',
    action: '밤에 깨어나 동료 늑대인간과 눈을 맞춥니다. 혼자인 경우 중앙 카드 한 장을 몰래 확인할 수 있습니다.',
    winCondition: '투표 결과 늑대인간 팀 중 아무도 처형되지 않으면 늑대인간 팀 승리입니다.',
  },
  minion: {
    name: '하수인', image: '/roles/minion.png',
    gradient: 'linear-gradient(135deg, #5a1a7a, #2a0a4a)',
    action: '밤에 깨어나 늑대인간이 누구인지 확인합니다. 단, 늑대인간은 하수인이 누구인지 모릅니다.',
    winCondition: '늑대인간이 처형되지 않으면 늑대인간 팀 승리입니다. 단, 늑대인간이 없는데 자신이 처형되면 마을 팀이 승리합니다.',
  },
  mason: {
    name: '프리메이슨', image: '/roles/mason.png',
    gradient: 'linear-gradient(135deg, #1a3a5a, #0a1a3a)',
    action: '밤에 깨어나 동료 프리메이슨과 눈을 맞춥니다. 서로가 같은 편임을 확인합니다.',
    winCondition: '마을 팀이 늑대인간을 처형하면 승리합니다. 서로를 신뢰하며 함께 늑대인간을 찾으세요.',
  },
  seer: {
    name: '예언자', image: '/roles/seer.png',
    gradient: 'linear-gradient(135deg, #1a3a7a, #0a1a4a)',
    action: '밤에 깨어나 다른 플레이어 한 명의 카드를 확인하거나, 중앙에 놓인 카드 중 두 장을 확인할 수 있습니다.',
    winCondition: '마을 팀이 늑대인간을 처형하면 승리합니다.',
  },
  robber: {
    name: '강도', image: '/roles/robber.png',
    gradient: 'linear-gradient(135deg, #3a3a1a, #1a1a0a)',
    action: '밤에 깨어나 다른 플레이어 한 명의 카드와 자신의 카드를 교환합니다. 가져온 새 카드를 확인합니다.',
    winCondition: '교환 후 자신의 최종 역할 팀이 승리하면 함께 승리합니다.',
  },
  troublemaker: {
    name: '말썽쟁이', image: '/roles/troublemaker.png',
    gradient: 'linear-gradient(135deg, #1a5a4a, #0a2a2a)',
    action: '밤에 깨어나 자신을 제외한 두 플레이어의 카드를 서로 몰래 교환합니다.',
    winCondition: '마을 팀이 늑대인간을 처형하면 승리합니다.',
  },
  drunk: {
    name: '주정뱅이', image: '/roles/drunk.png',
    gradient: 'linear-gradient(135deg, #5a3a1a, #2a1a0a)',
    action: '밤에 깨어나 중앙 카드 중 한 장을 가져와 자신의 카드와 교환합니다. 새로 받은 카드가 무엇인지 알 수 없습니다.',
    winCondition: '자신의 최종 역할 팀이 승리하면 함께 승리합니다.',
  },
  insomniac: {
    name: '불면증환자', image: '/roles/insomniac.png',
    gradient: 'linear-gradient(135deg, #1a2a5a, #0a0a2a)',
    action: '모든 야간 행동이 끝난 후 마지막으로 깨어나 자신의 현재 카드를 확인합니다.',
    winCondition: '마을 팀이 늑대인간을 처형하면 승리합니다.',
  },
  tanner: {
    name: '무두장이', image: '/roles/tanner.png',
    gradient: 'linear-gradient(135deg, #3a2a1a, #1a0a0a)',
    action: '야간 행동이 없습니다. 낮에 토론에서 의심받도록 유도하여 처형되는 것이 목표입니다.',
    winCondition: '투표로 자신이 처형되면 무두장이 단독 승리합니다.',
  },
  hunter: {
    name: '사냥꾼', image: '/roles/hunter.png',
    gradient: 'linear-gradient(135deg, #1a4a1a, #0a2a0a)',
    action: '야간 행동이 없습니다. 낮 토론에서 의심스러운 플레이어를 지목해두세요.',
    winCondition: '마을 팀이 늑대인간을 처형하면 승리합니다. 자신이 처형될 경우 지목한 플레이어도 함께 처형됩니다.',
  },
  villager: {
    name: '마을주민', image: '/roles/villager.png',
    gradient: 'linear-gradient(135deg, #1a5a1a, #0a2a0a)',
    action: '야간 행동이 없습니다. 눈을 감고 조용히 기다립니다.',
    winCondition: '마을 팀이 늑대인간을 처형하면 승리합니다.',
  },
}

// 문장이 아니라 line_id를 들고 있다. 문장은 백엔드(agents/tools/lines.py)가 소유하고
// 접속 시 카탈로그로 내려온다 — 화면 타이핑과 음성이 같은 문장을 쓰므로
// 페르소나를 바꾸면 둘 다 함께 바뀐다.
const STEPS_NORMAL = [
  { id: 'setup_intro',      showCards: true },
  { id: 'setup_flip',       holdMs: 10000 },
  { id: 'setup_take',       holdMs: 10000 },
  { id: 'setup_place',      holdMs: 10000 },
  { id: 'setup_center',     holdMs: 10000 },
  { id: 'setup_close_eyes', holdMs: 3000 },
]

const STEPS_PRACTICE = [
  { id: 'setup_intro',      showCards: true },
  { id: 'setup_flip',       holdMs: 10000 },
  { id: 'setup_take',       holdMs: 10000 },
  { id: 'setup_no_hide',    holdMs: 10000 },
  { id: 'setup_place',      holdMs: 10000 },
  { id: 'setup_center',     holdMs: 10000 },
  { id: 'setup_close_eyes' },
]

const KOREAN_ORDINALS = ['첫 번째', '두 번째', '세 번째', '네 번째', '다섯 번째', '여섯 번째', '일곱 번째', '여덟 번째', '아홉 번째', '열 번째', '열한 번째', '열두 번째']

const CHAR_MS = 60
const HOLD_MS = 5000
const FADE_MS = 600
const ROLE_EXPLAIN_DELAY_MS = 4000
// TTS 시작/종료 신호가 끝내 오지 않는 경우(합성 실패·TTS 비활성 등)의 안전장치.
const ROLE_EXPLAIN_SAFETY_MS = 30000

export default function CardSetupGuide({ roles = [], onComplete, send, wsState, onExit, isPracticeMode }) {
  const line = useLines()
  const game = isPracticeMode ? 'werewolf_practice' : 'werewolf'
  const SENTENCES = isPracticeMode ? STEPS_PRACTICE : STEPS_NORMAL
  const CONFIRM_TEXT = line(`${game}.setup_confirm`)
  const [step, setStep]                         = useState(0)
  const [typed, setTyped]                       = useState('')
  const [visible, setVisible]                   = useState(false)
  const [confirming, setConfirming]             = useState(false)
  const [roleExplainIdx, setRoleExplainIdx]     = useState(null)
  const prevGestureRef  = useRef(wsState?.gesture_confirmed ?? null)
  const skipRef         = useRef(null)
  const roleTimer4sRef  = useRef(null)

  // 중복 제거한 역할 목록 (역할 설명은 역할 종류당 1회)
  const uniqueRoles = [...new Set(roles)]

  // 현재 스텝의 line_id와 문장. 카탈로그가 늦게 도착할 수 있어 effect의
  // 의존성으로도 쓴다 — deps에 없으면 아래 `if (!stepText) return`에 걸린
  // 스텝이 영원히 재시도되지 않아 진행이 멈춘다.
  const stepLineId = SENTENCES[step] ? `${game}.${SENTENCES[step].id}` : ''
  const stepText = stepLineId ? line(stepLineId) : ''

  // 문장 진행 페이즈
  useEffect(() => {
    if (roleExplainIdx !== null) return
    if (step >= SENTENCES.length) {
      setConfirming(true)
      return
    }

    const sentence = SENTENCES[step]
    const text = stepText
    if (!text) return

    setTyped('')
    setVisible(true)

    narrate(send, stepLineId)

    let charIdx = 0
    const typeTimer = setInterval(() => {
      charIdx++
      setTyped(text.slice(0, charIdx))
      if (charIdx >= text.length) clearInterval(typeTimer)
    }, CHAR_MS)

    const typingMs = text.length * CHAR_MS
    const holdMs   = sentence.holdMs ?? HOLD_MS

    // 스텝 0 완료 후 튜토리얼 모드에서 역할 설명 페이즈로 전환
    const goNext = () => {
      if (isPracticeMode && step === 0 && uniqueRoles.length > 0) {
        setRoleExplainIdx(0)
      } else {
        setStep(s => s + 1)
      }
    }

    const fadeOut = setTimeout(() => setVisible(false), typingMs + holdMs)
    const next    = setTimeout(goNext, typingMs + holdMs + FADE_MS)

    skipRef.current = () => {
      audioApi.interrupt()
      clearInterval(typeTimer)
      clearTimeout(fadeOut)
      clearTimeout(next)
      setTyped(text)
      setVisible(false)
      setTimeout(goNext, FADE_MS)
    }

    return () => {
      clearInterval(typeTimer)
      clearTimeout(fadeOut)
      clearTimeout(next)
      skipRef.current = null
    }
  }, [step, roleExplainIdx, stepText, stepLineId])

  // 역할 설명 페이즈
  useEffect(() => {
    if (roleExplainIdx === null) return

    // 모든 역할 설명 완료 → 스텝 1부터 재개
    if (roleExplainIdx >= uniqueRoles.length) {
      setRoleExplainIdx(null)
      setStep(1)
      return
    }

    const roleId = uniqueRoles[roleExplainIdx]
    const info   = ROLE_INFO[roleId]

    if (!info) {
      setRoleExplainIdx(i => i + 1)
      return
    }

    const korNum  = KOREAN_ORDINALS[roleExplainIdx] ?? `${roleExplainIdx + 1}번째`
    const ttsText = `${korNum} 역할, ${info.name}. ${info.action} ${info.winCondition}`

    let unregisterEnd = null
    let safetyTimer = null

    const advanceAfterDelay = () => {
      roleTimer4sRef.current = setTimeout(() => {
        roleTimer4sRef.current = null
        setRoleExplainIdx(i => i + 1)
      }, ROLE_EXPLAIN_DELAY_MS)
    }

    // 이 역할의 TTS가 실제로 재생을 시작한 뒤에야 종료를 기다린다.
    // (직전 문장/역할의 TTS 종료 이벤트에 걸려 조기 전환되는 것을 방지)
    const unregisterStart = audioApi.onNextTtsStarted(() => {
      unregisterEnd = audioApi.onNextTtsEnded(advanceAfterDelay)
    })

    send?.('TTS_REQUEST', { text: ttsText })

    // TTS 시작/종료 신호가 끝내 오지 않아도 멈추지 않도록.
    safetyTimer = setTimeout(() => {
      safetyTimer = null
      setRoleExplainIdx(i => i + 1)
    }, ROLE_EXPLAIN_SAFETY_MS)

    const cleanup = () => {
      unregisterStart()
      unregisterEnd?.()
      if (safetyTimer) {
        clearTimeout(safetyTimer)
        safetyTimer = null
      }
      if (roleTimer4sRef.current) {
        clearTimeout(roleTimer4sRef.current)
        roleTimer4sRef.current = null
      }
    }

    skipRef.current = () => {
      cleanup()
      audioApi.interrupt()
      setRoleExplainIdx(i => i + 1)
    }

    return () => {
      cleanup()
      skipRef.current = null
    }
  }, [roleExplainIdx])

  // 확인 단계 진입: 타이핑 애니메이션 + TTS + 제스처 가드 초기화
  useEffect(() => {
    if (!confirming) return
    // 카탈로그를 아직 못 받았으면 기다린다 — 빈 문장을 타이핑하면 OK 사인
    // 안내가 사라져 진행이 막힌다.
    if (!CONFIRM_TEXT) return
    setTyped('')
    setVisible(true)
    send?.('CARD_SETUP_CONFIRM_READY', {})
    narrate(send, `${game}.setup_confirm`)
    let charIdx = 0
    const typeTimer = setInterval(() => {
      charIdx++
      setTyped(CONFIRM_TEXT.slice(0, charIdx))
      if (charIdx >= CONFIRM_TEXT.length) clearInterval(typeTimer)
    }, CHAR_MS)
    return () => clearInterval(typeTimer)
  }, [confirming, CONFIRM_TEXT])

  // OK 싸인 감지 → 즉시 진행
  useEffect(() => {
    const cur = wsState?.gesture_confirmed ?? null
    if (confirming && cur && cur !== prevGestureRef.current) {
      onComplete()
    }
    prevGestureRef.current = cur
  }, [wsState?.gesture_confirmed, confirming])

  const sentence        = step < SENTENCES.length ? SENTENCES[step] : null
  const currentRoleInfo = roleExplainIdx !== null && roleExplainIdx < uniqueRoles.length
    ? ROLE_INFO[uniqueRoles[roleExplainIdx]]
    : null

  return (
    <div className="ww-root" style={s.page} onClick={confirming ? onComplete : undefined}>
      <WerewolfScene mood="night" />
      <style>{CSS}</style>

      <button
        className="ww-hover ww-press"
        onClick={(e) => { e.stopPropagation(); onExit?.() }}
        style={ui.exitButton}
      >
        나가기
      </button>
      {!confirming && (
        <button
          className="ww-hover ww-press"
          style={skipBtn}
          onClick={(e) => { e.stopPropagation(); skipRef.current?.() }}
        >
          건너뛰기 ▶
        </button>
      )}

      {/* 역할 설명 페이즈 */}
      {roleExplainIdx !== null && currentRoleInfo && (
        <div style={s.roleWrap} key={roleExplainIdx}>
          <div style={s.roleCounter}>
            <span style={ui.eyebrowDot} />
            역할 소개 {roleExplainIdx + 1} / {uniqueRoles.length}
          </div>
          <div style={s.roleBody}>
            <div style={{ ...s.roleImgBox, background: currentRoleInfo.gradient }}>
              <img src={currentRoleInfo.image} alt={currentRoleInfo.name} style={s.roleImg} />
              <span className="ww-card-gloss" />
            </div>
            <div style={s.roleTextCol}>
              <div style={s.roleName}>{currentRoleInfo.name}</div>
              <div style={s.roleSection} className="ww-panel">
                <div style={s.roleSectionTitle}>야간 행동</div>
                <div style={s.roleSectionBody}>{currentRoleInfo.action}</div>
              </div>
              <div style={s.roleSection} className="ww-panel">
                <div style={s.roleSectionTitle}>승리 조건</div>
                <div style={s.roleSectionBody}>{currentRoleInfo.winCondition}</div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 문장 진행 페이즈 */}
      {roleExplainIdx === null && (
        <div style={{
          ...s.inner,
          opacity: visible ? 1 : 0,
          transition: `opacity ${FADE_MS}ms ease`,
        }}>
          <p style={s.sentence}>
            {typed}
            {!confirming && sentence && <span style={s.cursor}>|</span>}
          </p>

          {confirming && CONFIRM_TEXT && typed.length >= CONFIRM_TEXT.length && (
            <p style={s.hint}>화면을 터치하거나 OK 싸인을 해주세요</p>
          )}

          {sentence?.showCards && roles.length > 0 && (
            <div style={s.cardGrid}>
              {roles.map((roleId, i) => (
                <div
                  key={i}
                  style={{ ...s.cardItem, animationDelay: `${i * 55}ms` }}
                  className="ww-deal"
                >
                  <div style={s.cardImgBox}>
                    <img
                      src={`/roles/${roleId}.png`}
                      alt={ROLE_NAMES[roleId] || roleId}
                      style={s.cardImg}
                    />
                  </div>
                  <div style={s.cardName}>{ROLE_NAMES[roleId] || roleId}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const s = {
  page: ui.page,

  inner: {
    position: 'relative',
    zIndex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 36,
    maxWidth: 900,
    width: '90%',
    marginBottom: 80,
  },

  sentence: {
    margin: 0,
    // 문장 길이가 고정이 아니다 — 페르소나에 따라 같은 안내가 길어질 수 있어
    // 뷰포트 폭에 맞춰 줄어들게 둔다. nowrap이면 긴 문장이 화면 밖으로 나간다.
    fontSize: 'clamp(24px, 3.4vw, 38px)',
    fontWeight: 650,
    color: 'var(--w-ink)',
    textAlign: 'center',
    letterSpacing: '-0.01em',
    textShadow: '0 0 42px rgba(240,207,122,0.35), 0 3px 14px rgba(0,0,0,0.6)',
    lineHeight: 1.6,
    // 두 줄까지는 자리를 미리 잡아둔다. 타이핑 도중 줄이 늘면 아래 카드가
    // 밀려 내려가 화면이 출렁인다.
    minHeight: 124,
    // 단어 중간에서 끊기지 않게. 한국어는 어절 단위로 끊겨야 읽힌다.
    wordBreak: 'keep-all',
    overflowWrap: 'break-word',
  },

  cursor: {
    display: 'inline-block',
    marginLeft: 3,
    fontWeight: 200,
    color: 'var(--w-gold)',
    animation: 'ww-caret 0.72s step-start infinite',
  },

  cardGrid: {
    display: 'flex',
    flexWrap: 'wrap',
    justifyContent: 'center',
    gap: 14,
    maxWidth: 820,
  },

  cardItem: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 6,
  },

  cardImgBox: {
    width: 78,
    height: 98,
    borderRadius: 12,
    overflow: 'hidden',
    background: 'linear-gradient(160deg, rgba(56,46,72,0.85), rgba(14,12,24,0.9))',
    border: '1px solid var(--w-line)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
  },

  cardImg: {
    width: '100%',
    height: '100%',
    objectFit: 'contain',
  },

  cardName: {
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--w-ink-mute)',
    textAlign: 'center',
  },

  hint: {
    margin: 0,
    fontSize: 15,
    color: 'var(--w-ink-faint)',
    textAlign: 'center',
    letterSpacing: '-0.01em',
    animation: 'ww-in 500ms ease-out both',
  },

  // 역할 설명 페이즈 스타일
  roleWrap: {
    position: 'relative',
    zIndex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 20,
    maxWidth: 940,
    width: '92%',
    marginBottom: 60,
    animation: 'ww-in 560ms cubic-bezier(.2,.7,.2,1) both',
  },

  roleCounter: {
    ...ui.eyebrow,
    fontSize: 12,
  },

  roleBody: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 28,
    width: '100%',
  },

  roleImgBox: {
    position: 'relative',
    overflow: 'hidden',
    width: 150,
    height: 190,
    borderRadius: 16,
    border: '1px solid var(--w-line-strong)',
    flexShrink: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '0 18px 44px rgba(0,0,0,0.55), 0 0 30px rgba(240,207,122,0.12)',
    animation: 'ww-pop 620ms cubic-bezier(.2,.9,.25,1.25) both',
  },

  roleImg: {
    width: '100%',
    height: '100%',
    objectFit: 'contain',
  },

  roleTextCol: {
    display: 'flex',
    flexDirection: 'column',
    gap: 14,
    flex: 1,
  },

  roleName: {
    fontSize: 38,
    fontWeight: 850,
    letterSpacing: '-0.02em',
    color: 'var(--w-ink)',
    textShadow: '0 0 34px rgba(240,207,122,0.4)',
    animation: 'ww-in 520ms ease-out 80ms both',
  },

  roleSection: {
    borderRadius: 14,
    padding: '15px 20px',
    display: 'flex',
    flexDirection: 'column',
    gap: 7,
    animation: 'ww-in 520ms ease-out 180ms both',
  },

  roleSectionTitle: {
    fontSize: 11.5,
    fontWeight: 800,
    letterSpacing: '0.18em',
    color: 'var(--w-gold)',
  },

  roleSectionBody: {
    fontSize: 20,
    fontWeight: 500,
    color: 'var(--w-ink-soft)',
    lineHeight: 1.75,
    wordBreak: 'keep-all',
  },
}

const skipBtn = {
  ...ui.ghostButton,
  position: 'absolute', bottom: 32, right: 32, zIndex: 10,
  padding: '10px 26px',
  borderRadius: 999,
  fontSize: 14,
}

const CSS = `
  @keyframes ww-caret { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

  /* 카드가 한 장씩 깔린다. 열여섯 장이 한꺼번에 나타나면 '목록'이지만
     차례로 놓이면 '나눠주는 중'으로 보인다. */
  @keyframes ww-deal {
    0%   { opacity: 0; transform: translateY(-18px) rotate(-6deg) scale(0.9); }
    70%  { opacity: 1; transform: translateY(2px) rotate(1deg) scale(1); }
    100% { opacity: 1; transform: none; }
  }
  .ww-deal { animation: ww-deal 480ms cubic-bezier(.2,.8,.3,1.05) both; }

  /* 역할 카드 표면의 광택 */
  .ww-card-gloss {
    position: absolute;
    inset: 0;
    background: linear-gradient(150deg, rgba(255,255,255,0.16) 0%, transparent 42%);
    pointer-events: none;
  }
`
