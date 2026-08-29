import { useEffect, useRef, useState } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'
import { audio as audioApi, useAudioPlayer } from '../hooks/useAudioPlayer'
import DevPanel from '../components/common/DevPanel'
import GameTopBar from '../components/common/GameTopBar'
import RoleRegistration from '../components/werewolf/RoleRegistration'
import CardSetupGuide from '../components/werewolf/CardSetupGuide'
import NightStart from '../components/werewolf/NightStart'
import NightEnd from '../components/werewolf/NightEnd'
import NightRoleAnnounce from '../components/werewolf/NightRoleAnnounce'
import DayDiscussion from '../components/werewolf/DayDiscussion'
import VoteCountdown from '../components/werewolf/VoteCountdown'
import VoteResult from '../components/werewolf/VoteResult'
import GameEndWW from '../components/werewolf/GameEndWW'
import PhaseTransition from '../components/werewolf/PhaseTransition'

const NIGHT_PHASE_ROLES = {
  night_doppelganger: 'doppelganger',
  night_werewolf: 'werewolf',
  night_minion: 'minion',
  night_mason: 'mason',
  night_seer: 'seer',
  night_robber: 'robber',
  night_troublemaker: 'troublemaker',
  night_drunk: 'drunk',
  night_insomniac: 'insomniac',
}

const normalizeRoleId = (id) => (id ?? '').replace(/_\d+$/, '')

// 페이즈 사이의 빈 자리. 배경이 통째로 갈리면 전환이 끊겨 보이므로 밤하늘과
// 같은 색을 깔고 글자만 얹는다.
const loadingStyle = {
  position: 'absolute',
  inset: 0,
  background: 'linear-gradient(172deg, #0b0a24 0%, #0d1030 40%, #05080f 100%)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: 'rgba(245,239,227,0.55)',
  fontFamily: 'var(--font)',
  fontSize: 16,
  fontWeight: 600,
  letterSpacing: '-0.01em',
}

const NIGHT_PHASES = new Set(['night_start', ...Object.keys(NIGHT_PHASE_ROLES)])

const VOTE_PHASES = new Set(['vote', 'vote_countdown'])

function getTransitionType(from, to) {
  if (!from || !to) return null
  if (NIGHT_PHASES.has(from) && NIGHT_PHASES.has(to))        return 'eye_close'
  if (NIGHT_PHASES.has(from) && to === 'day_discussion')     return 'dawn'
  if (from === 'day_discussion'  && VOTE_PHASES.has(to))     return 'red_vignette'
  if (VOTE_PHASES.has(from)      && to === 'result')         return 'flash_fade'
  return 'fade'
}

// wsState: /ws/tablet 상태 (gesture_confirmed 등 로비 이벤트용)
export default function WerewolfGame({ players, onChangePlayers, onChangeGame, onRestart, wsState, isPracticeMode }) {
  const { state: wwState, send, connected } = useWebSocket('/ws/werewolf', {
    onAudioMessage: audioApi.enqueue,
  })
  // /ws/werewolf 채널로도 audio_ack가 흐르도록 등록.
  useAudioPlayer(send)
  const [showVoteResult, setShowVoteResult] = useState(false)
  const voteResultConfirmedRef = useRef(false)

  // 트랜지션 상태
  const [transitioning, setTransitioning] = useState(false)
  const [transitionType, setTransitionType] = useState('fade')
  const [transitionKey, setTransitionKey] = useState(0)
  const [displayedPhase, setDisplayedPhase] = useState(null)
  const [nightEndReady, setNightEndReady] = useState(false)
  const prevPhaseRef = useRef(null)
  const nightEndRef = useRef(false)
  const nightEndShowingRef = useRef(false)

  const phase = wwState?.phase

  // phase가 바뀌면 트랜지션 시작
  useEffect(() => {
    if (!phase) return
    const from = prevPhaseRef.current
    const to = phase
    prevPhaseRef.current = to

    if (NIGHT_PHASES.has(from) && to === 'day_discussion') {
      nightEndRef.current = true
      setNightEndReady(false)
    }

    if (VOTE_PHASES.has(from) && !VOTE_PHASES.has(to)) {
      if (!voteResultConfirmedRef.current) {
        setShowVoteResult(true)
      }
      voteResultConfirmedRef.current = false
    }

    const type = getTransitionType(from, to)
    if (!type) {
      setDisplayedPhase(to)
      return
    }
    if (from) setDisplayedPhase(from)
    setTransitionType(type)
    setTransitionKey(k => k + 1)
    setTransitioning(true)
  }, [phase])

  // ── 게임 FSM 단계 렌더링 ──────────────────────────────────────────────
  const handleExit = () => {
    send('RESTART', {})
    onChangeGame()
  }

  const renderGamePhase = (ph) => {
    if (!ph) return <div style={loadingStyle}>게임 진행 중...</div>

    if (ph === 'card_setup') {
      return (
        <CardSetupGuide
          roles={wwState?.deck_roles ?? []}
          onComplete={() => send('CARD_SETUP_DONE', {})}
          send={send}
          wsState={wsState}
          onExit={handleExit}
          isPracticeMode={isPracticeMode}
        />
      )
    }

    if (NIGHT_PHASE_ROLES[ph]) {
      return (
        <NightRoleAnnounce
          roleId={NIGHT_PHASE_ROLES[ph]}
          // 몇 초 뒤에 넘어가는지는 타이머를 가진 백엔드가 알려준다. 여기서
          // 숫자를 따로 갖고 있으면 백엔드만 바꿨을 때 조용히 어긋난다.
          durationSec={wwState?.phase_duration}
          onComplete={() => send('start_now', {})}
          onExit={handleExit}
          isPracticeMode={isPracticeMode}
        />
      )
    }

    if (ph === 'night_start') {
      return <NightStart send={send} onComplete={() => send('start_now', {})} onExit={handleExit} isPracticeMode={isPracticeMode} />
    }

    if (ph === 'night_end') {
      return (
        <NightEnd
          onComplete={() => {
            if (isPracticeMode) {
              // 튜토리얼: 토론(day_discussion) 단계를 건너뛰고 바로 투표로 전이
              send('start_now', {})
            } else {
              setDisplayedPhase('day_discussion')
            }
          }}
          send={send}
          isPracticeMode={isPracticeMode}
        />
      )
    }

    if (ph === 'day_discussion') {
      return (
        <DayDiscussion
          timeLeft={wwState.timer_remaining}
          onAddTime={() => send('add_30_sec', {})}
          onVote={() => send('start_now', {})}
          onExit={handleExit}
        />
      )
    }

    if (ph === 'vote' || ph === 'vote_countdown') {
      const votes = Object.fromEntries(
        (wwState.players ?? [])
          .filter(p => p.voted_for != null)
          .map(p => [p.player_id, p.voted_for])
      )
      if (wwState.votes_locked) {
        return (
          <VoteResult
            players={players}
            votes={votes}
            editable={true}
            send={send}
            onConfirm={() => { voteResultConfirmedRef.current = true }}
          />
        )
      }
      return (
        <VoteCountdown
          players={players}
          votes={votes}
          send={send}
          onExit={handleExit}
          countdownRemaining={wwState.countdown_remaining ?? undefined}
        />
      )
    }

    if (ph === 'result') {
      // VoteResult 오버레이가 표시 중인 동안은 마운트하지 않음 (TTS 조기 발화 방지)
      if (showVoteResult) return <div style={loadingStyle}>게임 진행 중...</div>
      const finalVotes = Object.fromEntries(
        (wwState.players ?? [])
          .filter(p => p.voted_for != null)
          .map(p => [p.player_id, p.voted_for])
      )
      const resetAndCall = (cb) => { send('reset_game', {}); cb() }
      return (
        <GameEndWW
          players={players}
          votes={finalVotes}
          executed={wwState.executed ?? []}
          deckRoles={wwState.deck_roles ?? []}
          onChangePlayers={() => resetAndCall(onChangePlayers)}
          onChangeGame={() => resetAndCall(onChangeGame)}
          onRestart={() => resetAndCall(onRestart)}
          send={send}
        />
      )
    }

    return <div style={loadingStyle}>게임 진행 중...</div>
  }

  // ── 게임 진행 중 (트랜지션 포함) ──────────────────────────────────────

  if (phase) {
    const voteOverlayVotes = Object.fromEntries(
      (wwState?.players ?? [])
        .filter(p => p.voted_for != null)
        .map(p => [p.player_id, p.voted_for])
    )
    return (
      <>
        {renderGamePhase(displayedPhase ?? phase)}
        {/* 상단바는 페이즈 바깥에 한 번만 둔다. 전에는 화면마다 '나가기'를
            한 개씩 들고 있어서(여섯 벌) 페이즈가 넘어갈 때마다 버튼이
            사라졌다 다시 그려졌고, 요트에 있는 소리·전략 조작은 아예 없었다. */}
        <GameTopBar
          theme="werewolf"
          send={send}
          connected={connected}
          onExit={handleExit}
        />
        <DevPanel
          title={`늑대인간 · ${phase}`}
          actions={[
            {
              label: '다음 페이즈',
              hint: '밤 페이즈 타이머(8~15초)를 기다리지 않고 넘긴다',
              run: () => send('DEV_NEXT_PHASE'),
            },
          ]}
        />
        {showVoteResult && !transitioning && (
          <div style={{ position: 'fixed', inset: 0, zIndex: 50 }}>
            <VoteResult
              players={players}
              votes={voteOverlayVotes}
              onComplete={() => setShowVoteResult(false)}
            />
          </div>
        )}
        {transitioning && (
          <PhaseTransition
            key={transitionKey}
            type={transitionType}
            onMidpoint={() => {
              if (nightEndRef.current) {
                nightEndRef.current = false
                nightEndShowingRef.current = true
                setDisplayedPhase('night_end')
              } else {
                setDisplayedPhase(phase)
              }
            }}
            onDone={() => {
              setTransitioning(false)
              if (nightEndShowingRef.current) {
                nightEndShowingRef.current = false
                setNightEndReady(true)
              }
            }}
          />
        )}
      </>
    )
  }

  // ── 초기: 역할 덱 선택 ──────────────────────────────────────────────────
  // 여기서 고른 카드 구성은 밤 페이즈 호명 순서를 정하는 데만 쓰인다.
  // 누가 어떤 카드를 받는지는 시스템이 알지 못한다.

  return (
    <>
    <GameTopBar theme="werewolf" send={send} connected={connected} onExit={onChangeGame} />
    <RoleRegistration
      players={players}
      send={send}
      connected={connected}
      onStart={(roles) => {
        const playerOrder = players.map(p => p.player_id)
        send('START_CARD_SETUP', {
          selected_roles: roles.map(normalizeRoleId),
          player_order: playerOrder,
          // 룰/진행 에이전트 TTS가 플레이어 ID 대신 이름을 말하도록 이름 매핑을 함께 전달.
          players: players.map(p => ({ player_id: p.player_id, playername: p.playername })),
          practice_mode: isPracticeMode ?? false,
        })
      }}
    />
    </>
  )
}
