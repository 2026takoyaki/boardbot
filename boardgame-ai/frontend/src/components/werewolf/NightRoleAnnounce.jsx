import { useState, useEffect } from 'react'
import { audio } from '../../hooks/useAudioPlayer'
import WerewolfScene from './WerewolfScene'
import * as ui from './wwUi'

// 튜토리얼 모드는 눈을 감지 않고 진행하므로 "깨어나세요" 대신 차례 안내,
// action도 해당 역할 플레이어가 직접 행동을 수행하는 방식으로 설명한다.
const ROLE_NIGHT_DATA = {
  doppelganger: {
    name: '도플갱어',
    image: '/roles/doppelganger.png',
    announce: '도플갱어는 깨어나세요.',
    action: '다른 플레이어 1명의 카드를 확인하세요.\n그 역할이 됩니다.',
    tutorialAnnounce: '도플갱어는 기본적으로 마을주민팀이지만 팀이 바뀔 수 있는 역할입니다.',
    tutorialAction: '밤 시간에 다른 플레이어 1명의 카드를 확인하고 본인도 그 역할이 됩니다.\n확인한 역할이 늑대인간·하수인이면 늑대인간팀, 무두장이면 무두장이팀으로 변경됩니다.\n낮 시간에 바뀐 역할을 주장하며 혼란을 줄 수 있습니다.',
  },
  werewolf: {
    name: '늑대인간',
    image: '/roles/werewolf.png',
    announce: '늑대인간은 깨어나세요.',
    action: '서로를 확인하고 다시 눈을 감으세요.',
    tutorialAnnounce: '늑대인간은 늑대인간팀 역할입니다.',
    tutorialAction: '밤 시간에 눈을 떠 다른 늑대인간들과 서로를 확인합니다.\n낮 시간에 마을주민인 척 행동하며 다른 늑대인간들과 협력해 마을주민들을 처단하도록 유도합니다.',
  },
  minion: {
    name: '하수인',
    image: '/roles/minion.png',
    announce: '하수인은 깨어나세요.',
    action: '늑대인간들은 엄지를 들어올려\n자신을 알려주세요.',
    tutorialAnnounce: '하수인은 늑대인간팀 역할입니다.',
    tutorialAction: '밤 시간에 늑대인간들이 엄지를 들면 눈을 떠 누가 늑대인간인지 확인합니다.\n단, 늑대인간들은 하수인이 누구인지 모릅니다.\n낮 시간에 늑대인간으로 의심받을 행동을 하여 늑대인간 대신 본인이 처단당하도록 유도합니다.',
  },
  mason: {
    name: '프리메이슨',
    image: '/roles/mason.png',
    announce: '프리메이슨은 깨어나세요.',
    action: '서로를 확인하고 다시 눈을 감으세요.',
    tutorialAnnounce: '프리메이슨은 마을주민팀 역할입니다.',
    tutorialAction: '프리메이슨은 항상 두 명입니다.\n밤 시간에 다른 프리메이슨과 눈을 마주치며 서로를 확인합니다.\n낮 시간에 서로를 믿고 협력하며 함께 늑대인간을 찾아냅니다.',
  },
  seer: {
    name: '예언자',
    image: '/roles/seer.png',
    announce: '예언자는 깨어나세요.',
    action: '다른 플레이어 1명 또는\n중앙 카드 2장을 확인할 수 있습니다.',
    tutorialAnnounce: '예언자는 마을주민팀 역할입니다.',
    tutorialAction: '밤 시간에 다른 플레이어 1명의 카드를 확인하거나, 중앙 카드 2장을 확인할 수 있습니다.\n낮 시간에 본인이 확인한 정보를 바탕으로 마을주민들의 추리를 돕습니다.',
  },
  robber: {
    name: '강도',
    image: '/roles/robber.png',
    announce: '강도는 깨어나세요.',
    action: '다른 플레이어 1명의 카드와\n자신의 카드를 교환할 수 있습니다.',
    tutorialAnnounce: '강도는 마을주민팀 역할입니다.',
    tutorialAction: '밤 시간에 다른 플레이어 1명의 카드를 자신의 카드와 맞교환하고 바뀐 역할을 확인합니다.\n단, 카드를 빼앗긴 플레이어는 이 사실을 모릅니다.\n낮 시간에 바뀐 역할로 행동하며 역할을 빼앗긴 플레이어에게 혼란을 줍니다.',
  },
  troublemaker: {
    name: '말썽쟁이',
    image: '/roles/troublemaker.png',
    announce: '말썽쟁이는 깨어나세요.',
    action: '자신을 제외한 두 플레이어의\n카드를 서로 교환하세요.',
    tutorialAnnounce: '말썽쟁이는 마을주민팀 역할입니다.',
    tutorialAction: '밤 시간에 자신을 제외한 두 플레이어의 카드를 맞교환하며 두 플레이어의 역할은 확인하지 않습니다.\n단, 역할이 맞교환된 두 플레이어는 이 사실을 모릅니다.\n낮 시간에 플레이어들이 본인의 역할을 잘못 알고 행동하도록 합니다.',
  },
  drunk: {
    name: '주정뱅이',
    image: '/roles/drunk.png',
    announce: '주정뱅이는 깨어나세요.',
    action: '중앙 카드 1장을 가져와\n자신의 카드와 교환하세요.\n새 카드는 볼 수 없습니다.',
    tutorialAnnounce: '주정뱅이는 마을주민팀 역할입니다.',
    tutorialAction: '밤 시간에 중앙 카드 1장과 자신의 카드를 교환하며 본인의 바뀐 역할은 확인하지 않습니다.\n낮 시간에 자신이 어떤 역할인지 전혀 모른 채 추리에 참여해야 하는 역할입니다.',
  },
  insomniac: {
    name: '불면증환자',
    image: '/roles/insomniac.png',
    announce: '불면증환자는 깨어나세요.',
    action: '자신의 카드를 확인하세요.',
    tutorialAnnounce: '불면증환자는 마을주민팀 역할입니다.',
    tutorialAction: '밤 시간이 끝날 무렵 가장 마지막으로 자신의 카드를 확인합니다.\n카드가 바뀌어 있다면 누군가 본인의 역할을 교환했다는 것을 알 수 있습니다.\n낮 시간에 이 정보를 바탕으로 마을주민들의 추리를 돕습니다.',
  },
}

const PASSIVE_ROLES = new Set(['werewolf', 'minion', 'mason'])
const PASSIVE_DURATION = 10  // 백엔드 PASSIVE_PHASE_DURATION과 일치
const ACTIVE_DURATION = 12   // 백엔드 ACTIVE_PHASE_TIMEOUT과 일치
const PRACTICE_POST_TTS_SECONDS = 5  // 튜토리얼: 안내 TTS 종료 후 자동 전이까지 대기

const KOREAN_NUMS = { 1: '한', 2: '두', 3: '세' }
function toKoreanTTS(text) {
  return text.replace(/([123])(명|장|개)/g, (_, n, counter) => `${KOREAN_NUMS[Number(n)]} ${counter}`)
}

export default function NightRoleAnnounce({ roleId, onComplete, isPracticeMode }) {
  const role = ROLE_NIGHT_DATA[roleId]
  const isPassive = PASSIVE_ROLES.has(roleId)
  const duration = isPassive ? PASSIVE_DURATION : ACTIVE_DURATION
  const [countdown, setCountdown] = useState(duration)
  // 튜토리얼: 안내 TTS가 끝난 뒤부터 카운트다운/자동 전이를 시작한다.
  const [practiceCounting, setPracticeCounting] = useState(false)

  // 역할 안내 TTS는 ProgressAgent가 담당 — 프론트에서 TTS_REQUEST 중복 발화 제거

  useEffect(() => {
    // 일반 모드: 백엔드 타이머가 전환을 담당. 여기서는 표시용 카운트다운만 운영.
    if (!isPracticeMode) {
      const dur = PASSIVE_ROLES.has(roleId) ? PASSIVE_DURATION : ACTIVE_DURATION
      setCountdown(dur)
      const interval = setInterval(() => {
        setCountdown(prev => Math.max(0, prev - 1))
      }, 1000)
      return () => clearInterval(interval)
    }

    // 튜토리얼 모드: 백엔드 고정 타이머가 없으므로 안내 TTS가 끝까지 재생된 뒤
    // PRACTICE_POST_TTS_SECONDS 카운트다운 후 onComplete(start_now)로 전이를 주도한다.
    // (액티브 역할은 그 전에 카드 감지로 전이되면 컴포넌트가 언마운트되어 정리됨.)
    setPracticeCounting(false)
    setCountdown(PRACTICE_POST_TTS_SECONDS)
    let interval = null
    let completeTimer = null
    let unsubscribeEnd = null

    const startCountdown = () => {
      setPracticeCounting(true)
      interval = setInterval(() => {
        setCountdown(prev => Math.max(0, prev - 1))
      }, 1000)
      completeTimer = setTimeout(onComplete, PRACTICE_POST_TTS_SECONDS * 1000)
    }

    // 안전장치: 안내 TTS가 전혀 시작되지 않으면(합성 실패 등) 멈추지 않도록 폴백.
    const startWatchdog = setTimeout(startCountdown, 10000)

    // 안내 TTS가 "시작"된 뒤에 종료를 기다린다. 마운트 시점에 직전 발화가 남아 있어도
    // 그 종료로 조기 전이되는 것을 막는다(이미 재생 중인 발화는 start 콜백이 소비됨).
    const unsubscribeStart = audio.onNextTtsStarted(() => {
      clearTimeout(startWatchdog)
      unsubscribeEnd = audio.onNextTtsEnded(startCountdown)
    })

    return () => {
      clearTimeout(startWatchdog)
      unsubscribeStart()
      if (unsubscribeEnd) unsubscribeEnd()
      if (interval) clearInterval(interval)
      if (completeTimer) clearTimeout(completeTimer)
    }
  }, [roleId]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!role) return null

  const displayAnnounce = isPracticeMode ? (role.tutorialAnnounce ?? role.announce) : role.announce
  const displayAction = isPracticeMode ? (role.tutorialAction ?? role.action) : role.action
  const counting = !isPracticeMode || practiceCounting
  const totalSeconds = isPracticeMode ? PRACTICE_POST_TTS_SECONDS : duration
  // 남은 시간은 숫자보다 막대가 먼저 읽힌다. 숫자는 확인용으로 옆에 남긴다.
  const remainRatio = counting ? Math.max(0, Math.min(1, countdown / totalSeconds)) : 1

  return (
    <div className="ww-root" style={ui.page}>
      <WerewolfScene mood="night" />
      <style>{CSS}</style>

      <div style={{ ...ui.stage, gap: 26 }}>
        {/* 카드는 왼쪽에 크게, 설명은 오른쪽에 크게. 가로로 놓인 태블릿에서
            세로로 쌓으면 카드도 글자도 어중간하게 작아진다 — 둘을 나란히
            놓아야 카드는 카드대로 크고, 문장은 문장대로 읽힌다. */}
        <div style={styles.split}>
          {/* 왼쪽 — 카드가 뒤집히며 나온다. 실제 카드를 다루는 게임이니 화면의
              카드도 카드처럼 움직여야 한다. 페이드인은 종이가 아니라 이미지다. */}
          <div style={styles.cardStage} key={roleId}>
            {/* 호명된 역할만 달빛을 받는다. 카드 뒤에 빛기둥을 세워
                "지금은 이 카드의 차례"라는 것을 글자 없이 말한다. */}
            <div className="ww-spotlight" />
            <div className="ww-card-flip" style={styles.card}>
              <img src={role.image} alt={role.name} style={styles.image} />
              <span className="ww-card-shine" />
            </div>
            <div className="ww-card-shadow" />
          </div>

          {/* 오른쪽 — 역할 이름부터 행동 지시까지 한 덩어리로 읽힌다 */}
          <div style={styles.info}>
            <div style={styles.roleName} className="ww-anim-down">{role.name}</div>

            <div className="ww-rule" style={styles.rule}><i /></div>

            <p style={styles.announceText} className="ww-anim-in">{displayAnnounce}</p>
            <p style={styles.actionText} className="ww-anim-in">{displayAction}</p>

            <div style={styles.timerRow} className="ww-anim-in">
              <div style={styles.track}>
                <div
                  style={{
                    ...styles.trackFill,
                    width: `${remainRatio * 100}%`,
                    // 마지막 3초는 색이 달아오른다. 숫자를 읽지 않아도 급한 줄 안다.
                    background: counting && countdown <= 3
                      ? 'linear-gradient(90deg, var(--w-blood-deep), var(--w-blood))'
                      : 'linear-gradient(90deg, var(--w-gold-deep), var(--w-gold))',
                  }}
                />
              </div>
              <span style={styles.timerText}>
                {counting ? `${countdown}초` : '안내 중'}
              </span>
            </div>
          </div>
        </div>

        <button onClick={onComplete} className="ww-hover ww-press" style={styles.skipBtn}>
          건너뛰기 →
        </button>
      </div>
    </div>
  )
}

const styles = {
  // 카드와 설명을 나란히. 카드 열은 내용만큼만 차지하고 남는 폭은 전부 글이
  // 가져간다 — 튜토리얼의 긴 설명이 들어와도 카드가 밀려 쪼그라들지 않는다.
  split: {
    display: 'grid',
    gridTemplateColumns: 'auto minmax(0, 1fr)',
    alignItems: 'center',
    gap: 'clamp(32px, 5vw, 64px)',
    width: 'min(1120px, 92vw)',
  },

  cardStage: {
    position: 'relative',
    perspective: 1100,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
  },

  card: {
    position: 'relative',
    // 화면 높이에 맞춰 줄어든다. 카드 비율(0.8)은 고정이라 어느 크기에서도
    // 실제 카드와 같은 모양이다.
    width: 'clamp(230px, 26vw, 330px)',
    height: 'clamp(288px, 32.5vw, 412px)',
    borderRadius: 22,
    overflow: 'hidden',
    background: 'linear-gradient(160deg, rgba(56,46,72,0.9), rgba(14,12,24,0.95))',
    border: '1px solid var(--w-line-strong)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '0 30px 76px rgba(0,0,0,0.62), 0 0 54px rgba(240,207,122,0.16)',
  },

  image: {
    width: '100%',
    height: '100%',
    objectFit: 'contain',
    filter: 'drop-shadow(0 12px 18px rgba(0,0,0,0.55))',
  },

  info: {
    minWidth: 0,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-start',
    gap: 16,
  },

  roleName: {
    fontSize: 'clamp(34px, 4.4vw, 52px)',
    fontWeight: 850,
    letterSpacing: '-0.02em',
    lineHeight: 1.1,
    color: 'var(--w-gold)',
    textShadow: '0 0 46px rgba(240,207,122,0.45), 0 3px 14px rgba(0,0,0,0.6)',
  },

  rule: {
    width: '100%',
    animation: 'ww-in 700ms ease-out 0.35s both',
  },

  announceText: {
    margin: 0,
    fontSize: 'clamp(21px, 2.5vw, 30px)',
    fontWeight: 750,
    letterSpacing: '-0.01em',
    lineHeight: 1.4,
    color: 'var(--w-ink)',
    textAlign: 'left',
    wordBreak: 'keep-all',
    textShadow: '0 2px 14px rgba(0,0,0,0.65)',
    animationDelay: '0.3s',
  },

  actionText: {
    margin: 0,
    fontSize: 'clamp(16px, 1.72vw, 21px)',
    fontWeight: 500,
    color: 'var(--w-ink-soft)',
    textAlign: 'left',
    lineHeight: 1.8,
    whiteSpace: 'pre-line',
    wordBreak: 'keep-all',
    textShadow: '0 2px 12px rgba(0,0,0,0.6)',
    animationDelay: '0.42s',
  },

  timerRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    width: '100%',
    maxWidth: 360,
    marginTop: 4,
    animationDelay: '0.54s',
  },

  track: {
    flex: 1,
    height: 4,
    borderRadius: 999,
    background: 'rgba(255,255,255,0.10)',
    overflow: 'hidden',
  },

  trackFill: {
    height: '100%',
    borderRadius: 999,
    // 1초마다 오는 갱신이라 linear여야 눈금이 고르게 흐른다.
    transition: 'width 1s linear, background 400ms ease',
  },

  timerText: {
    fontSize: 12,
    fontWeight: 750,
    letterSpacing: '0.08em',
    color: 'var(--w-ink-mute)',
    fontVariantNumeric: 'tabular-nums',
    width: 42,
    textAlign: 'right',
  },

  skipBtn: {
    padding: '9px 22px',
    border: '1px solid rgba(255,255,255,0.14)',
    borderRadius: 999,
    background: 'rgba(10,8,16,0.4)',
    color: 'var(--w-ink-mute)',
    fontFamily: 'inherit',
    fontSize: 13,
    fontWeight: 650,
    cursor: 'pointer',
    animation: 'ww-in 600ms ease-out 0.9s both',
  },
}

const CSS = `
  /* 카드 위로 떨어지는 달빛 기둥. 카드 칸 안에 두므로 카드가 어디로 가든
     빛도 따라간다 — 화면 가운데에 고정하면 카드가 왼쪽으로 간 순간 어긋난다. */
  .ww-spotlight {
    position: absolute;
    top: -46%;
    left: 50%;
    width: 230%;
    height: 200%;
    transform: translateX(-50%);
    background: radial-gradient(ellipse 34% 52% at 50% 34%, rgba(255,236,180,0.20), transparent 72%);
    filter: blur(8px);
    pointer-events: none;
    animation: ww-in 900ms ease-out both;
  }

  /* 카드가 옆으로 한 바퀴 돌며 앉는다 */
  @keyframes ww-flip {
    0%   { opacity: 0; transform: rotateY(-96deg) translateY(22px) scale(0.9); }
    58%  { opacity: 1; transform: rotateY(10deg)  translateY(-6px) scale(1.02); }
    78%  { transform: rotateY(-3deg) translateY(0) scale(1); }
    100% { transform: rotateY(0deg); }
  }
  .ww-card-flip {
    transform-style: preserve-3d;
    animation: ww-flip 900ms cubic-bezier(.2,.8,.25,1.05) both;
  }

  /* 카드 표면을 훑는 반사광 — 코팅된 카드로 보이게 하는 한 줄 */
  .ww-card-shine {
    position: absolute;
    top: -60%; left: -40%;
    width: 46%; height: 220%;
    background: linear-gradient(90deg, transparent, rgba(255,246,214,0.30), transparent);
    transform: rotate(18deg);
    animation: ww-shine 3.8s ease-in-out 1s infinite;
  }
  @keyframes ww-shine {
    0%, 62% { transform: translateX(0) rotate(18deg); opacity: 0; }
    66%     { opacity: 1; }
    92%     { transform: translateX(420px) rotate(18deg); opacity: 0; }
    100%    { opacity: 0; }
  }

  /* 카드가 바닥에 드리우는 그림자. 카드가 공중에 떠 있지 않게 잡아준다. */
  .ww-card-shadow {
    width: 76%;
    height: 18px;
    margin-top: 16px;
    border-radius: 50%;
    background: radial-gradient(ellipse at center, rgba(0,0,0,0.55), transparent 72%);
    filter: blur(5px);
    animation: ww-in 900ms ease-out 0.2s both;
  }
`
