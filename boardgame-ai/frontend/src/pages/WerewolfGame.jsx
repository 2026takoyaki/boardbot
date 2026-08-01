import { useEffect, useRef, useState } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'
import { audio as audioApi, useAudioPlayer } from '../hooks/useAudioPlayer'
import DevPanel from '../components/common/DevPanel'
import RoleRegistration from '../components/werewolf/RoleRegistration'
import RoleRegShowCard from '../components/werewolf/RoleRegShowCard'
import RoleRegConfirm from '../components/werewolf/RoleRegConfirm'
import RoleRegTransition from '../components/werewolf/RoleRegTransition'
import RoleRegRoleExplain from '../components/werewolf/RoleRegRoleExplain'
import CardSetupGuide from '../components/werewolf/CardSetupGuide'
import NightStart from '../components/werewolf/NightStart'
import NightEnd from '../components/werewolf/NightEnd'
import NightRoleAnnounce from '../components/werewolf/NightRoleAnnounce'
import DayDiscussion from '../components/werewolf/DayDiscussion'
import VoteCountdown from '../components/werewolf/VoteCountdown'
import VoteResult from '../components/werewolf/VoteResult'
import GameEndWW from '../components/werewolf/GameEndWW'
import FinalRoleReveal from '../components/werewolf/FinalRoleReveal'
import PhaseTransition from '../components/werewolf/PhaseTransition'
import WerewolfLoading from '../components/werewolf/WerewolfLoading'

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

const loadingStyle = {
  minHeight: '100vh',
  background: '#0d1520',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: '#eee',
  fontFamily: "'Segoe UI', sans-serif",
}

const NIGHT_PHASES = new Set(['night_start', ...Object.keys(NIGHT_PHASE_ROLES)])

const VOTE_PHASES = new Set(['vote', 'vote_countdown'])

function getTransitionType(from, to) {
  if (!from || !to) return null
  if (NIGHT_PHASES.has(from) && NIGHT_PHASES.has(to))        return 'eye_close'
  if (NIGHT_PHASES.has(from) && to === 'day_discussion')     return 'dawn'
  if (from === 'day_discussion'  && VOTE_PHASES.has(to))     return 'red_vignette'
  if (VOTE_PHASES.has(from)      && to === 'final_role_reveal') return 'flash_fade'
  if (VOTE_PHASES.has(from)      && to === 'result')           return 'flash_fade'
  if (from === 'final_role_reveal' && to === 'result')         return 'fade'
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

  // 역할 감지 상태: 백엔드 role_reg.detected_role 변화 추적
  const [detectedRoleId, setDetectedRoleId] = useState(null)
  const [roleRegTimedOut, setRoleRegTimedOut] = useState(false)
  // CONFIRM_ROLE 전송 후 다음 플레이어/게임 시작 전이를 기다리는 동안 true.
  // 이 구간에 RoleRegShowCard가 재마운트되며 "카드를 보여주세요" TTS가 재발화되는 것을 막는다.
  const [pendingConfirm, setPendingConfirm] = useState(false)
  const [showRoleTransition, setShowRoleTransition] = useState(false)
  const [roleTransitionPlayer, setRoleTransitionPlayer] = useState(null)
  // 튜토리얼: 역할 설명 페이지 상태 { role, confirmRoleId, confirmPlayerId, transitionPlayer }
  const [roleExplainState, setRoleExplainState] = useState(null)
  const prevDetectedRef = useRef(null)
  const prevPlayerRef = useRef(null)

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
  const roleReg = wwState?.role_reg
  const roleReveal = wwState?.role_reveal

  // 최종 역할 공개 감지 상태
  const [revealDetectedRoleId, setRevealDetectedRoleId] = useState(null)
  const [revealTimedOut, setRevealTimedOut] = useState(false)
  const prevRevealPlayerRef = useRef(null)
  const prevRevealDetectedRef = useRef(null)

  useEffect(() => {
    if (roleReveal?.player_id !== prevRevealPlayerRef.current) {
      prevRevealPlayerRef.current = roleReveal?.player_id ?? null
      prevRevealDetectedRef.current = null
      setRevealDetectedRoleId(null)
      setRevealTimedOut(false)
    }
    const detected = roleReveal?.detected_role
    if (detected && detected !== prevRevealDetectedRef.current) {
      prevRevealDetectedRef.current = detected
      setRevealDetectedRoleId(detected)
    }
  }, [roleReveal?.player_id, roleReveal?.detected_role])

  useEffect(() => {
    // 플레이어가 바뀌면 이전 감지 초기화
    if (roleReg?.player_id !== prevPlayerRef.current) {
      prevPlayerRef.current = roleReg?.player_id ?? null
      prevDetectedRef.current = null
      setDetectedRoleId(null)
      setRoleRegTimedOut(false)
      setPendingConfirm(false)  // 다음 플레이어로 진행됨 → 대기 해제
    }
    // 새 역할 감지 시 상태 업데이트
    const detected = roleReg?.detected_role
    if (detected && detected !== prevDetectedRef.current) {
      prevDetectedRef.current = detected
      setDetectedRoleId(detected)
    }
  }, [roleReg?.player_id, roleReg?.detected_role])

  // 백엔드가 다음 플레이어로 업데이트하면 전환 화면 자동 종료
  useEffect(() => {
    if (!showRoleTransition) return
    if (!roleReg?.player_id) return
    if (roleTransitionPlayer && roleReg.player_id !== roleTransitionPlayer.player_id) {
      setShowRoleTransition(false)
      setRoleTransitionPlayer(null)
    }
  }, [roleReg?.player_id]) // eslint-disable-line react-hooks/exhaustive-deps

  // phase가 바뀌면 트랜지션 시작
  useEffect(() => {
    if (!phase) return
    if (phase === 'role_registration') {
      // role_registration 진입 시 이전 displayedPhase 초기화
      // (card_setup 등 잔여값이 남아 game phase 전환 시 오표시되는 것 방지)
      setDisplayedPhase(null)
      prevPhaseRef.current = null
      setPendingConfirm(false)
      return
    }
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
          roles={wwState?.all_roles ?? []}
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

    if (ph === 'final_role_reveal') {
      if (showVoteResult) return <div style={loadingStyle}>게임 진행 중...</div>
      const currentRevealPlayer = players.find(p => p.player_id === roleReveal?.player_id)
      if (!currentRevealPlayer) return <div style={loadingStyle}>최종 역할 확인 중...</div>
      return (
        <FinalRoleReveal
          player={currentRevealPlayer}
          detectedRoleId={revealDetectedRoleId}
          timedOut={revealTimedOut}
          allRoles={roleReveal?.all_roles ?? []}
          send={send}
          onConfirm={(selectedRoleId) => {
            send('ROLE_REVEAL_CONFIRM', { role: selectedRoleId ?? revealDetectedRoleId }, currentRevealPlayer.player_id)
          }}
          onTimeout={() => setRevealTimedOut(true)}
        />
      )
    }

    if (ph === 'result') {
      // VoteResult 오버레이가 표시 중인 동안은 마운트하지 않음 (TTS 조기 발화 방지)
      if (showVoteResult) return <div style={loadingStyle}>게임 진행 중...</div>
      const finalRoles = Object.fromEntries(
        (wwState.players ?? []).map(p => [p.player_id, p.current_role])
      )
      const originalRoles = Object.fromEntries(
        (wwState.players ?? []).map(p => [p.player_id, p.original_role])
      )
      const resetAndCall = (cb) => { send('reset_game', {}); cb() }
      return (
        <GameEndWW
          players={players}
          finalRoles={finalRoles}
          originalRoles={originalRoles}
          winner={wwState.winner ?? 'village'}
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

  if (phase && phase !== 'role_registration') {
    const voteOverlayVotes = Object.fromEntries(
      (wwState?.players ?? [])
        .filter(p => p.voted_for != null)
        .map(p => [p.player_id, p.voted_for])
    )
    return (
      <>
        {renderGamePhase(displayedPhase ?? phase)}
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

  // ── 역할 등록 단계 ─────────────────────────────────────────────────────

  if (phase === 'role_registration') {
    const currentPlayer = players.find(p => p.player_id === roleReg?.player_id)

    // 튜토리얼: 역할 설명 화면
    if (roleExplainState) {
      return (
        <RoleRegRoleExplain
          role={roleExplainState.role}
          send={send}
          onComplete={() => {
            const { confirmRoleId, confirmPlayerId, transitionPlayer } = roleExplainState
            setRoleExplainState(null)
            setDetectedRoleId(null)
            setRoleRegTimedOut(false)
            if (transitionPlayer) {
              setRoleTransitionPlayer(transitionPlayer)
              setShowRoleTransition(true)
            } else {
              // 전환 화면이 없는 경우(튜토리얼) 다음 플레이어/게임 시작 전까지 대기 표시
              setPendingConfirm(true)
            }
            send('CONFIRM_ROLE', { role: confirmRoleId }, confirmPlayerId)
            // 튜토리얼은 RoleRegTransition(눈 감기 안내)을 띄우지 않으므로 긴 텀이 불필요.
            // 역할 설명 화면에서 이미 충분히 머물렀으니 짧게 전환한다(검은 대기 화면 최소화).
            if (!transitionPlayer) {
              setTimeout(() => send('REG_TRANSITION_ADVANCE', {}), 700)
            }
          }}
        />
      )
    }

    // 플레이어 전환 대기 화면
    if (showRoleTransition && roleTransitionPlayer) {
      return (
        <RoleRegTransition
          player={roleTransitionPlayer}
          send={send}
          onComplete={() => {
            setShowRoleTransition(false)
            setRoleTransitionPlayer(null)
          }}
        />
      )
    }

    // 역할 감지됨 또는 타임아웃 → 확인 화면
    if ((detectedRoleId || roleRegTimedOut) && currentPlayer) {
      return (
        <RoleRegConfirm
          player={currentPlayer}
          detectedRoleId={detectedRoleId}
          lowConfidence={roleReg?.detected_low_confidence ?? false}
          allRoles={wwState?.role_reg?.all_roles ?? wwState?.all_roles ?? []}
          send={send}
          wsState={wsState}
          isPracticeMode={isPracticeMode}
          onConfirm={(selectedRole) => {
            const nextIndex = (roleReg?.player_index ?? 0) + 1
            const hasNextPlayer = nextIndex < players.length
            if (isPracticeMode && selectedRole) {
              setRoleExplainState({
                role: selectedRole,
                confirmRoleId: selectedRole.id,
                confirmPlayerId: currentPlayer.player_id,
                transitionPlayer: null,
              })
            } else {
              if (hasNextPlayer) {
                setRoleTransitionPlayer(currentPlayer)
                setShowRoleTransition(true)
              } else {
                // 마지막 플레이어: night_start 전환 전까지 RoleRegShowCard 재마운트 방지
                setPendingConfirm(true)
              }
              send('CONFIRM_ROLE', { role: selectedRole?.id ?? detectedRoleId }, currentPlayer.player_id)
            }
          }}
        />
      )
    }

    // CONFIRM_ROLE 전송 후 다음 단계 전환 대기 — RoleRegShowCard 재마운트(TTS 재발화) 방지.
    // 테마 로딩 화면으로 잠깐만 노출된다(전환 텀은 onComplete에서 짧게 설정).
    if (pendingConfirm) {
      return <WerewolfLoading message="잠시만 기다려주세요" />
    }

    // 카드 스캔 화면
    if (currentPlayer) {
      return (
        <RoleRegShowCard
          player={currentPlayer}
          send={send}
          onBack={(roleReg?.player_index ?? 0) > 0 ? () => send('BACK_TO_PREV_PLAYER', {}) : null}
          onExit={onRestart}
          onDetected={(roleId) => setDetectedRoleId(roleId)}
          onTimeout={() => setRoleRegTimedOut(true)}
        />
      )
    }

    return <WerewolfLoading message="역할 등록 준비 중" />
  }

  // ── 초기: 역할 선택 ────────────────────────────────────────────────────

  return (
    <RoleRegistration
      players={players}
      send={send}
      connected={connected}
      onExit={onChangeGame}
      onStart={(roles) => {
        const playerOrder = players.map(p => p.player_id)
        send('START_ROLE_REGISTRATION', {
          selected_roles: roles.map(normalizeRoleId),
          player_order: playerOrder,
          // 룰/진행 에이전트 TTS가 플레이어 ID 대신 이름을 말하도록 이름 매핑을 함께 전달.
          players: players.map(p => ({ player_id: p.player_id, playername: p.playername })),
          practice_mode: isPracticeMode ?? false,
        })
      }}
    />
  )
}
