import { useState, useEffect, useRef } from 'react'
import { audio as audioApi } from '../../hooks/useAudioPlayer'
import { narrate, useLines } from '../../lines'

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
    <>
      <style>{`
        @keyframes moonGlowPulse {
          0%,100% { box-shadow: 0 0 48px 18px rgba(220,185,80,0.22); }
          50%      { box-shadow: 0 0 72px 28px rgba(220,185,80,0.38); }
        }
        @keyframes starFlicker { 0%,100%{opacity:.6} 50%{opacity:.2} }
        @keyframes fogDrift {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-8%); }
        }
        @keyframes cursorBlink { 0%,100%{opacity:1} 50%{opacity:0} }
        @keyframes roleSlideIn {
          from { opacity: 0; transform: translateY(20px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      <div style={s.page} onClick={confirming ? onComplete : undefined}>
        <button onClick={(e) => { e.stopPropagation(); onExit?.() }} style={exitBtn}>나가기</button>
        {!confirming && (
          <button style={skipBtn} onClick={(e) => { e.stopPropagation(); skipRef.current?.() }}>
            건너뛰기 ▶
          </button>
        )}
        <div style={s.sky} />
        <div style={s.moon} />

        {[
          {t:'7%',l:'10%',sz:2.2},{t:'13%',l:'32%',sz:1.4},
          {t:'5%',l:'55%',sz:1.8},{t:'19%',l:'75%',sz:1.2},
          {t:'25%',l:'18%',sz:1.0},{t:'9%', l:'44%',sz:1.5},
          {t:'28%',l:'90%',sz:2.0},{t:'4%', l:'82%',sz:1.4},
          {t:'35%',l:'60%',sz:1.2},{t:'40%',l:'5%', sz:1.8},
        ].map((st, i) => (
          <div key={i} style={{
            position:'absolute', top:st.t, left:st.l,
            width:st.sz, height:st.sz, borderRadius:'50%',
            background:'#fff', opacity:0.6,
            animation:`starFlicker ${2.2+i*0.35}s ease-in-out infinite`,
          }} />
        ))}

        <svg viewBox="0 0 800 160" preserveAspectRatio="xMidYMax slice" style={s.silhouette}>
          <polygon points="40,160 62,95 84,160"    fill="#06030f" />
          <polygon points="58,160 84,72 110,160"   fill="#06030f" />
          <polygon points="95,160 118,100 141,160" fill="#06030f" />
          <rect x="155" y="118" width="58" height="42" fill="#06030f" />
          <polygon points="150,120 184,92 218,120"  fill="#06030f" />
          <rect x="162" y="130" width="13" height="30" fill="#030108" />
          <rect x="245" y="86" width="32" height="74" fill="#06030f" />
          <polygon points="240,88 261,62 282,88"   fill="#06030f" />
          <rect x="300" y="112" width="52" height="48" fill="#06030f" />
          <polygon points="295,114 326,86 357,114" fill="#06030f" />
          <polygon points="372,160 394,90 416,160" fill="#06030f" />
          <polygon points="390,160 416,70 442,160" fill="#06030f" />
          <rect x="455" y="120" width="46" height="40" fill="#06030f" />
          <polygon points="450,122 478,98 506,122" fill="#06030f" />
          <rect x="524" y="96" width="72" height="64" fill="#06030f" />
          <polygon points="519,98 560,68 601,98"   fill="#06030f" />
          <rect x="552" y="74" width="16" height="26" fill="#06030f" />
          <polygon points="618,160 638,102 658,160" fill="#06030f" />
          <polygon points="646,160 670,84 694,160" fill="#06030f" />
          <rect x="710" y="118" width="54" height="42" fill="#06030f" />
          <polygon points="705,120 737,94 769,120" fill="#06030f" />
        </svg>

        <div style={{
          position:'absolute', bottom:0, left:'-8%',
          width:'116%', height:'30%',
          background:'linear-gradient(to top, rgba(60,30,90,0.5) 0%, rgba(40,20,70,0.22) 55%, transparent 100%)',
          animation:'fogDrift 18s linear infinite alternate',
          filter:'blur(14px)',
          pointerEvents:'none',
        }} />

        {/* 역할 설명 페이즈 */}
        {roleExplainIdx !== null && currentRoleInfo && (
          <div style={s.roleWrap} key={roleExplainIdx}>
            <div style={s.roleCounter}>
              역할 소개 {roleExplainIdx + 1} / {uniqueRoles.length}
            </div>
            <div style={s.roleBody}>
              <div style={{ ...s.roleImgBox, background: currentRoleInfo.gradient }}>
                <img src={currentRoleInfo.image} alt={currentRoleInfo.name} style={s.roleImg} />
              </div>
              <div style={s.roleTextCol}>
                <div style={s.roleName}>{currentRoleInfo.name}</div>
                <div style={s.roleSection}>
                  <div style={s.roleSectionTitle}>🌙 야간 행동</div>
                  <div style={s.roleSectionBody}>{currentRoleInfo.action}</div>
                </div>
                <div style={s.roleSection}>
                  <div style={s.roleSectionTitle}>🏆 승리 조건</div>
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
                  <div key={i} style={s.cardItem}>
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
    </>
  )
}

const s = {
  page: {
    height: '100vh',
    overflow: 'hidden',
    position: 'relative',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontFamily: "'Segoe UI', 'Apple SD Gothic Neo', sans-serif",
    userSelect: 'none',
  },

  sky: {
    position: 'absolute',
    inset: 0,
    background: [
      'radial-gradient(ellipse at 72% 8%, rgba(180,140,40,0.18) 0%, transparent 38%)',
      'radial-gradient(ellipse at 15% 85%, rgba(90,20,140,0.32) 0%, transparent 48%)',
      'linear-gradient(160deg, #160d38 0%, #0c1628 35%, #180c28 65%, #081420 100%)',
    ].join(', '),
  },

  moon: {
    position: 'absolute',
    top: 48,
    right: 90,
    width: 90,
    height: 90,
    borderRadius: '50%',
    background: 'radial-gradient(circle at 38% 36%, #fffde7, #f5e070 40%, #c8a820 80%)',
    animation: 'moonGlowPulse 3.5s ease-in-out infinite',
  },

  silhouette: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    width: '100%',
    height: 160,
    pointerEvents: 'none',
  },

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
    fontWeight: 600,
    color: '#F8F1DD',
    textAlign: 'center',
    letterSpacing: 1,
    textShadow: '0 0 32px rgba(220,185,120,0.4)',
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
    marginLeft: 2,
    fontWeight: 200,
    color: 'rgba(248,241,221,0.7)',
    animation: 'cursorBlink 0.7s step-start infinite',
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
    width: 76,
    height: 96,
    borderRadius: 10,
    overflow: 'hidden',
    background: 'rgba(255,255,255,0.06)',
    border: '1px solid rgba(220,185,120,0.25)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '0 4px 18px rgba(0,0,0,0.45)',
  },

  cardImg: {
    width: '100%',
    height: '100%',
    objectFit: 'contain',
  },

  cardName: {
    fontSize: 11,
    color: 'rgba(248,241,221,0.55)',
    textAlign: 'center',
  },

  hint: {
    margin: 0,
    fontSize: 15,
    color: 'rgba(248,241,221,0.38)',
    textAlign: 'center',
    letterSpacing: 0.5,
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
    animation: 'roleSlideIn 0.45s ease both',
  },

  roleCounter: {
    fontSize: 14,
    fontWeight: 700,
    letterSpacing: 2,
    color: 'rgba(220,185,120,0.55)',
    textTransform: 'uppercase',
  },

  roleBody: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 28,
    width: '100%',
  },

  roleImgBox: {
    width: 150,
    height: 190,
    borderRadius: 14,
    overflow: 'hidden',
    border: '2px solid rgba(255,255,255,0.15)',
    flexShrink: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '0 8px 32px rgba(0,0,0,0.55)',
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
    fontSize: 40,
    fontWeight: 800,
    color: '#F8F1DD',
    textShadow: '0 0 24px rgba(220,185,120,0.45)',
  },

  roleSection: {
    background: 'rgba(255,255,255,0.05)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: 12,
    padding: '16px 20px',
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },

  roleSectionTitle: {
    fontSize: 14,
    fontWeight: 700,
    letterSpacing: 1,
    color: 'rgba(220,185,80,0.75)',
  },

  roleSectionBody: {
    fontSize: 21,
    color: 'rgba(248,241,221,0.85)',
    lineHeight: 1.75,
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

const skipBtn = {
  position: 'absolute', bottom: 36, right: 36, zIndex: 10,
  padding: '10px 28px',
  border: '1px solid rgba(220,185,120,0.35)',
  borderRadius: 24,
  background: 'rgba(220,185,120,0.12)',
  color: 'rgba(248,241,221,0.75)',
  fontSize: 15, fontWeight: 600, cursor: 'pointer',
  letterSpacing: 1,
  backdropFilter: 'blur(6px)',
  transition: 'background 0.2s, color 0.2s',
}
