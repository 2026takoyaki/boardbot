import { useState, useEffect, useMemo, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useWebSocket } from './hooks/useWebSocket'
import { useAudioPlayer, audio as audioApi } from './hooks/useAudioPlayer'
import { useBenchBridge } from './hooks/useBenchBridge'
import { playSfx } from './sfx'
import DevPanel from './components/common/DevPanel'
import LightStrip from './components/common/LightStrip'
import SeatRegistration from './components/common/SeatRegistration'
import { colorForIndex } from './components/common/seatColors'
import { orderForTurn, physicalSeatOrder } from './components/common/turnOrder'
import Lobby from './pages/Lobby'
import Countdown from './pages/Countdown'
import WerewolfGame from './pages/WerewolfGame'
import YachtGame from './pages/YachtGame'

const WEREWOLF_PHASES = new Set([
  'card_setup',
  'night_start', 'night_doppelganger', 'night_werewolf', 'night_minion',
  'night_mason', 'night_seer', 'night_robber', 'night_troublemaker',
  'night_drunk', 'night_insomniac',
  'day_discussion', 'vote_countdown', 'vote', 'result',
])

export default function App() {
  const [page, setPage] = useState('seat')
  const [gameKey, setGameKey] = useState(0)
  const [isPracticeMode, setIsPracticeMode] = useState(false)
  const [yachtTutorialMode, setYachtTutorialMode] = useState(false)

  // 게임 시작 시점에 픽스되는 정렬된 플레이어 목록.
  // 카운트다운 → 게임 페이지로 넘어가는 동안 이 값 사용.
  const [orderedPlayersAtStart, setOrderedPlayersAtStart] = useState(null)
  const [pendingGame, setPendingGame] = useState(null)  // { gameId, mode, gameType }

  // 시작 플레이어 / 진행 방향 (lobby 입장 전 상태로 유지됨)
  const [firstPlayerId, setFirstPlayerId] = useState(null)
  const [direction, setDirection] = useState('cw')

  // 조명은 게임 소켓이 아니라 태블릿 소켓으로 온다. App은 어느 페이지에서도
  // 마운트돼 있어 게임 중에도 계속 받는다.
  const [light, setLight] = useState(null)
  const { state, connected, send } = useWebSocket('/ws/tablet', {
    onAudioMessage: audioApi.enqueue,
    onLightState: setLight,
  })
  useAudioPlayer(send)
  useBenchBridge(send)

  const phase = state?.phase ?? 'player_setup'
  const players = state?.players ?? []
  const registeringId = state?.registering_player_id ?? null
  const seatStep = state?.seat_step ?? 'idle'

  // 등록된 플레이어가 바뀌면 firstPlayerId가 유효한지 확인하고, 없으면 첫 번째 등록 플레이어로
  const registeredPlayers = useMemo(
    () => players.filter((p) => p.playername),
    [players],
  )
  useEffect(() => {
    if (registeredPlayers.length === 0) {
      if (firstPlayerId !== null) setFirstPlayerId(null)
      return
    }
    if (!registeredPlayers.find((p) => p.player_id === firstPlayerId)) {
      const byPos = physicalSeatOrder(registeredPlayers, 'player_id')
      setFirstPlayerId(byPos[0].player_id)
    }
  }, [registeredPlayers, firstPlayerId])

  // 손이 등록될 때마다. 백엔드가 오른손·왼손 각각에서 sound_seq를 올리므로
  // 한 사람당 두 번 울린다 — 한쪽만 인식된 상태에서 아무 반응이 없으면
  // 됐는지 안 됐는지 모른 채로 기다리게 된다.
  useEffect(() => {
    if (state?.sound === 'registered') playSfx('hand_register')
  }, [state?.sound_seq])

  /**
   * 공용 버튼 클릭음.
   *
   * 버튼이 `.btn`, `.gcard-cta`, `.pp-item` 등으로 흩어져 있어 한 곳에서 잡는다.
   * 컴포넌트마다 핸들러를 붙이면 새 버튼이 생길 때마다 빠뜨린다.
   *
   * 소리를 따로 내는 버튼(미리듣기 등)은 data-noclick으로 빠진다 — 자기 소리와
   * 클릭음이 겹쳐 울리면 둘 다 뭉개진다.
   */
  useEffect(() => {
    const onClick = (e) => {
      // 제외 판정은 **누른 지점**에서 위로 훑는다. 버튼을 먼저 찾고 거기서
      // 올라가면, 버튼 안쪽 요소에 붙은 표시를 지나쳐버린다(미리듣기 아이콘이
      // 그랬다 — span이라 부모 버튼이 먼저 잡혔다).
      if (e.target.closest?.('[data-noclick]')) return
      const el = e.target.closest?.('button')
      if (!el || el.disabled) return
      playSfx('ui_click')
    }
    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [])

  // 백엔드 phase가 늑대인간 게임 단계로 진입하면 page 동기화 (새로고침 복구 용도)
  // seat/lobby에서는 발동하지 않음 — 게임 선택 전 한밤 파이프라인이 켜지는 사이드이펙트 방지
  useEffect(() => {
    if (WEREWOLF_PHASES.has(phase) && page !== 'werewolf' && page !== 'seat' && page !== 'lobby') {
      setPage('werewolf')
    }
  }, [phase, page])

  // 좌석 등록 / 로비 화면에서 로비 BGM 재생. 게임 페이지로 나가면 backend가 stopBgm.
  // - 좌석 ↔ 로비 사이 내부 전환은 끊김 없이 유지 (재트리거 안 함).
  // - 게임/카운트다운에서 lobby-area로 복귀했을 때만 stopBgm → 0.5s 후 로비 BGM 시작.
  const prevLobbyAreaRef = useRef(false)
  useEffect(() => {
    const isLobbyArea = page === 'lobby' || page === 'seat'
    const wasLobbyArea = prevLobbyAreaRef.current
    prevLobbyAreaRef.current = isLobbyArea
    if (!isLobbyArea) return
    if (wasLobbyArea) return  // 좌석 ↔ 로비 내부 전환은 그대로 두기
    audioApi.stopBgm()
    const timer = setTimeout(() => {
      audioApi.playBgm('/bgm/lobby_loop.mp3', { loop: true, gain_db: -14 })
    }, 500)
    return () => clearTimeout(timer)
  }, [page])

  // 좌석 등록 페이지에서 사용할 콜백
  const goLobby = () => setPage('lobby')

  // Lobby에서 게임 카드 선택 → 카운트다운 진입
  const handleSelectGame = (gameId, mode) => {
    // 진행 순서 픽스
    const ordered = orderForTurn(registeredPlayers, firstPlayerId, direction, 'player_id')
    if (ordered.length === 0) return

    // UI용 플레이어 목록 (Countdown 화면 + 게임 페이지로 전달)
    const ui = ordered.map((p, i) => ({
      id: p.player_id,
      player_id: p.player_id,
      playername: p.playername,
      name: p.playername,
      position: p.position,
      color: colorForIndex(i),
      registered: p.registered,
    }))
    setOrderedPlayersAtStart(ui)

    // mode → 백엔드 game_type 매핑
    // 늑대인간 "튜토리얼 모드" = 연습 모드(frontend-only 플래그). game_type은 'werewolf' 그대로.
    let gameType = gameId
    if (gameId === 'yacht' && mode === 'tutorial') gameType = 'yacht_tutorial'
    setPendingGame({ gameId, mode, gameType })
    setIsPracticeMode(gameId === 'werewolf' && mode === 'tutorial')
    setYachtTutorialMode(gameId === 'yacht' && mode === 'tutorial')

    setPage('countdown')
  }

  // Countdown 0초 → 백엔드에 select_game 보내고 게임 페이지로 이동
  const handleCountdownReady = () => {
    if (!pendingGame) return
    send('select_game', { game_type: pendingGame.gameType })
    const target = pendingGame.gameId === 'yacht' ? 'yacht' : 'werewolf'
    setPage(target)
    setPendingGame(null)
  }

  // Countdown 취소 → lobby로 복귀 (백엔드 미통신, frontend state만 롤백)
  const handleCountdownCancel = () => {
    setPendingGame(null)
    setOrderedPlayersAtStart(null)
    setYachtTutorialMode(false)
    setIsPracticeMode(false)
    setPage('lobby')
  }

  let pageEl = null
  if (page === 'seat') {
    pageEl = (
      <SeatRegistration
        players={players}
        registeringId={registeringId}
        seatStep={seatStep}
        connected={connected}
        firstPlayerId={firstPlayerId}
        direction={direction}
        onChangeFirst={setFirstPlayerId}
        onChangeDirection={setDirection}
        send={send}
        onStart={goLobby}
      />
    )
  } else if (page === 'lobby') {
    pageEl = (
      <Lobby
        players={players}
        connected={connected}
        onBack={() => setPage('seat')}
        onSelectGame={handleSelectGame}
      />
    )
  } else if (page === 'countdown' && pendingGame && orderedPlayersAtStart) {
    pageEl = (
      <Countdown
        players={orderedPlayersAtStart}
        gameId={pendingGame.gameType}
        mode={pendingGame.mode}
        onCancel={handleCountdownCancel}
        onReady={handleCountdownReady}
      />
    )
  } else if (page === 'yacht') {
    const playersForGame = orderedPlayersAtStart ?? registeredPlayers
    pageEl = (
      <YachtGame
        players={playersForGame}
        tutorialMode={yachtTutorialMode}
        onExit={() => { setOrderedPlayersAtStart(null); setPage('lobby') }}
        onChangePlayers={() => { setOrderedPlayersAtStart(null); setPage('seat') }}
      />
    )
  } else if (page === 'werewolf') {
    const playersForGame = orderedPlayersAtStart ?? registeredPlayers
    pageEl = (
      <WerewolfGame
        key={gameKey}
        players={playersForGame}
        wsState={state}
        send={send}
        isPracticeMode={isPracticeMode}
        onChangePlayers={() => { setOrderedPlayersAtStart(null); setIsPracticeMode(false); setPage('seat') }}
        onChangeGame={() => { setOrderedPlayersAtStart(null); setIsPracticeMode(false); setPage('lobby') }}
        onRestart={() => setGameKey((k) => k + 1)}
      />
    )
  }

  return (
    <>
      {pageEl}
      <LightStrip light={light} />
      {/* 게임 페이지는 각자 자기 패널을 띄우므로 로비 영역에서만 렌더한다. */}
      {(page === 'seat' || page === 'lobby') && (
        <DevPanel
          title="로비"
          actions={[2, 3, 4, 5].map(count => ({
            label: `${count}명으로 시작`,
            hint: '플레이어를 만들고 좌석 등록까지 한 번에 끝낸다',
            run: () => fetch(`/dev/seat/${count}`, { method: 'POST' }),
          }))}
        />
      )}
      <OrientationLock />
    </>
  )
}

function OrientationLock() {
  const host = typeof document !== 'undefined'
    ? document.getElementById('orient-lock-root')
    : null
  if (!host) return null
  return createPortal(
    <div className="orient-lock" role="alert" aria-live="polite">
      <div className="orient-lock-card">
        <div className="orient-lock-icon" aria-hidden>
          <svg width="64" height="64" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
            <rect x="6" y="2.5" width="12" height="19" rx="2" />
            <path d="M11 18.5h2" />
          </svg>
        </div>
        <div>
          <div className="orient-lock-title">가로로 돌려주세요</div>
          <div className="orient-lock-sub">
            이 앱은 태블릿을 가로 방향에 두고 사용하도록 설계되었습니다.
          </div>
        </div>
      </div>
    </div>,
    host,
  )
}
