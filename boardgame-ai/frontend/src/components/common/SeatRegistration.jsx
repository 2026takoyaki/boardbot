import { useMemo, useState } from 'react'
import {
  IconPlus, IconCheck, IconArrowRight, IconEdit, IconTrash, IconUsers,
} from './Icons'
import PersonaPicker from './PersonaPicker'
import SettingsMenu from './SettingsMenu'
import TableVisualization from './TableVisualization'
import HandRegistrationModal, { RANDOM_NICKNAMES } from './HandRegistrationModal'
import { colorForPlayerId } from './seatColors'
import { orderForTurn, physicalSeatOrder } from './turnOrder'

/** position이 없는 등록 중 플레이어를 위해 균등 분배(임시) */
function fillMissingPositions(players) {
  const N = players.length
  if (N === 0) return []
  return players.map((p, i) => ({
    ...p,
    position: p.position == null ? i / N : p.position,
  }))
}

export default function SeatRegistration({
  players,            // backend snapshot players (raw)
  registeringId,
  seatStep = 'idle',
  connected,
  firstPlayerId,
  direction,
  onChangeFirst,
  onChangeDirection,
  send,
  onStart,
}) {
  const [editingId, setEditingId] = useState(null)
  const [activeId, setActiveId] = useState(null)

  // backend players → UI players (id, name, position, color)
  const uiPlayers = useMemo(() => {
    const named = players
      .filter((p) => p.playername || p.player_id === registeringId)
      .map((p) => ({
        id: p.player_id,
        name: p.playername || '',
        position: p.position ?? null,
        registered: p.registered,
        color: colorForPlayerId(p.player_id),
        raw: p,
      }))
    return fillMissingPositions(named)
  }, [players, registeringId])

  const ordered = useMemo(
    () => orderForTurn(uiPlayers, firstPlayerId, direction),
    [uiPlayers, firstPlayerId, direction],
  )
  const physicalPlayers = useMemo(
    () => physicalSeatOrder(uiPlayers),
    [uiPlayers],
  )

  const totalPlayers = ordered.length
  const namedPlayers = ordered.filter((p) => p.name)
  const existingNameKey = namedPlayers.map((p) => p.name).join('|')
  const canStart =
    namedPlayers.length > 0 && namedPlayers.every((p) => p.registered)

  // sub는 오류일 때만 쓴다. 정상일 때의 상세("테이블 전체 인식 중")는 알아도
  // 할 일이 없어서 상단에서 뺐다 — 그래서 여기에도 두지 않는다.
  const cameraLabel = connected
    ? { dot: 'ok', text: '카메라 연결됨', sub: null }
    : { dot: 'err', text: '카메라 오류', sub: '연결 상태를 확인해 주세요' }

  const startRegistration = () => send('start_registration', {})
  const cancelRegistration = () => {
    if (registeringId) send('cancel_seat_registration', { player_id: registeringId })
    setEditingId(null)
  }
  const finalizePlayer = (name) => {
    if (!registeringId) return
    send('finalize_player', { player_id: registeringId, playername: name })
  }
  const submitEdit = (player_id, name) => {
    send('player_edit', { player_id, playername: name })
    setEditingId(null)
  }
  const removePlayer = (player_id) => {
    send('player_remove', { player_id })
    if (editingId === player_id) setEditingId(null)
  }
  const restartRegistration = (player_id) => {
    send('start_seat_registration', { player_id })
  }

  const showHandModal = !!registeringId
  const editingPlayer =
    editingId && uiPlayers.find((p) => p.id === editingId)

  const defaultName = useMemo(() => {
    const used = new Set(namedPlayers.map((p) => p.name))
    const pool = RANDOM_NICKNAMES.filter((nickname) => !used.has(nickname))
    const candidates = pool.length ? pool : RANDOM_NICKNAMES
    return candidates[Math.floor(Math.random() * candidates.length)]
  }, [registeringId, existingNameKey])

  return (
    <div className="scr scr-register">
      <div className="topbar">
        <div className="logo"><span>보드게임 AI</span></div>
        <div className="crumbs">
          <span>플레이어 등록</span>
          <span className="sep">→</span>
          <span style={{ opacity: 0.5 }}>게임 선택</span>
          <span className="sep">→</span>
          <span style={{ opacity: 0.5 }}>플레이</span>
        </div>
        <div className="right">
          {/* 알약 상자에 두 줄로 담겨 있었는데, 옆에 44px 톱니가 서면서
              둘의 생김새가 부딪혔다. 로비 상단(`4명 플레이 | ● 카메라 정상`)은
              이미 맨글자 한 줄이라, 그쪽에 맞춘다 — 상태 표시는 읽히기만 하면
              되고 눌리는 물건이 아니다. */}
          <span className="cam-stat">
            <span className={`status-dot ${cameraLabel.dot} pulse`} />
            {cameraLabel.text}
          </span>
          {/* 두 번째 줄은 문제가 있을 때만 남긴다. 정상일 때의 '테이블 전체
              인식 중'은 알아도 할 일이 없지만, 오류일 때는 지시문이다. */}
          {!connected && <span className="cam-sub">{cameraLabel.sub}</span>}
          {/* 로비·게임 화면과 같은 자리, 같은 메뉴. 소리를 줄이는 방법이
              화면마다 다르면 그때마다 다시 찾게 된다. */}
          <SettingsMenu send={send} connected={connected} />
        </div>
      </div>

      <div className="reg-page-hd">
        <h1 className="reg-title">플레이어 등록</h1>
      </div>
      <div className="reg-divider-top" />
      <div className="reg-grid">
        <div className="reg-left scroll">
          <div className="reg-section-hd">
            <h2 className="reg-section-title">등록된 플레이어</h2>
          </div>

          <div className="player-list">
            {ordered.length > 0 && (
              <div className="prow-head">
                <div className="ph-order">순서</div>
                <div className="ph-avatar" aria-hidden />
                <div className="ph-name">플레이어 이름</div>
                <div className="ph-actions">
                  <span>수정</span>
                  <span>삭제</span>
                </div>
              </div>
            )}

            {ordered.map((p, i) => (
              <PlayerRow
                key={p.id}
                player={p}
                index={i}
                isActive={activeId === p.id}
                onHover={() => setActiveId(p.id)}
                onLeave={() => setActiveId(null)}
                onEdit={() => setEditingId(p.id)}
                onRemove={() => removePlayer(p.id)}
                onReregister={() => restartRegistration(p.id)}
              />
            ))}

            {!showHandModal && (
              <div className="add-player-wrap">
                <button className="add-player" onClick={startRegistration}>
                  <IconPlus size={18} />
                  <span>플레이어 추가</span>
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="reg-right">
          <div className="reg-section-hd">
            <h2 className="reg-section-title">실제 좌석 배치</h2>
          </div>

          <div className="rr-table">
            <TableVisualization
              players={ordered}
              activeId={activeId}
              onSelect={setActiveId}
              shape="rect"
              showTablet={totalPlayers > 0}
            />
            {totalPlayers === 0 && (
              <div className="rr-empty">
                <IconUsers size={40} />
                <p>플레이어를 추가하면 좌석이 여기에 표시됩니다</p>
              </div>
            )}
          </div>

          <TurnControls
            players={physicalPlayers}
            orderedPlayers={ordered}
            firstPlayerId={firstPlayerId}
            onChangeFirst={onChangeFirst}
            direction={direction}
            onChangeDirection={onChangeDirection}
          />
        </div>
      </div>

      <div className="reg-foot">
        <div className="foot-info">
          {totalPlayers > 0 ? (
            <>
              <IconCheck size={16} style={{ color: 'var(--ok)' }} />
              <span><b>{namedPlayers.length}명</b>의 플레이어가 준비되었습니다</span>
            </>
          ) : (
            <span style={{ color: 'var(--fg-mute)' }}>
              플레이어를 한 명 이상 추가해 주세요
            </span>
          )}
        </div>
        <div className="reg-foot-actions">
          <PersonaPicker send={send} connected={connected} />
          <button
            className="btn btn-primary btn-lg btn-pill"
            disabled={!canStart}
            onClick={canStart ? onStart : undefined}
          >
            게임 선택 <IconArrowRight size={18} />
          </button>
        </div>
      </div>

      {showHandModal && (
        <HandRegistrationModal
          seatStep={seatStep}
          defaultName={defaultName}
          existingNames={uiPlayers
            .filter((p) => p.id !== registeringId && p.name)
            .map((p) => p.name)}
          onCancel={cancelRegistration}
          onSubmit={finalizePlayer}
        />
      )}

      {editingPlayer && (
        <EditNameModal
          initialName={editingPlayer.name}
          existingNames={uiPlayers
            .filter((p) => p.id !== editingPlayer.id && p.name)
            .map((p) => p.name)}
          onCancel={() => setEditingId(null)}
          onSubmit={(name) => submitEdit(editingPlayer.id, name)}
        />
      )}

      <style>{`
        .scr-register {
          position: absolute; inset: 0;
          display: flex; flex-direction: column;
          padding-top: 56px;
          --reg-rule: color-mix(in oklch, var(--border-soft) 50%, var(--border));
        }
        .reg-divider-top {
          height: 1px;
          margin: 0 24px;
          background: var(--reg-rule);
        }
        .reg-page-hd {
          padding: 14px 32px 14px;
          display: flex; align-items: center;
        }
        .reg-title {
          font-size: 32px; font-weight: 700; letter-spacing: -0.03em;
        }
        .reg-section-hd {
          padding: 0;
          display: flex; align-items: center;
          min-height: 28px;
        }
        .reg-section-title {
          font-size: 16px; font-weight: 600; letter-spacing: -0.01em;
          color: var(--fg-soft);
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }
        .scr-register .cam-stat {
          display: inline-flex; align-items: center; gap: 8px;
          color: var(--fg-soft);
          white-space: nowrap;
        }
        .scr-register .cam-sub { color: var(--err); }
        .reg-grid {
          flex: 1;
          display: grid;
          grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
          min-height: 0;
        }
        .reg-left {
          padding: 14px 24px 14px 32px;
          overflow-y: auto;
          display: flex; flex-direction: column; gap: 12px;
          border-right: 1px solid var(--reg-rule);
        }
        .player-list { display: flex; flex-direction: column; gap: 8px; }

        /* 컬럼 헤더 — PlayerRow와 동일 grid 트랙으로 정렬 */
        .prow-head {
          display: grid;
          grid-template-columns: 32px 36px 1fr auto;
          align-items: center;
          gap: 12px;
          padding: 4px 14px 8px;
          font-size: 11px;
          color: var(--fg-mute);
          font-weight: 600;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          border-bottom: 1px solid var(--border-soft);
          margin-bottom: 2px;
        }
        .prow-head .ph-order  { text-align: center; }
        .prow-head .ph-actions {
          display: grid;
          grid-template-columns: 36px 36px;
          gap: 2px;
          font-size: 11px;
        }
        .prow-head .ph-actions span { text-align: center; }

        .add-player-wrap {
          display: flex; justify-content: center;
          margin-top: 10px;
        }
        .add-player {
          appearance: none;
          border: 1px solid var(--border);
          background: var(--bg-hover);
          color: var(--fg);
          height: 44px;
          padding: 0 22px;
          border-radius: 999px;
          display: inline-flex; align-items: center; justify-content: center; gap: 8px;
          font: inherit;
          font-size: 15px; font-weight: 600; letter-spacing: -0.01em;
          cursor: pointer;
          transition: all 160ms ease;
          white-space: nowrap;
          box-shadow: 0 1px 0 rgba(255,255,255,.05) inset, 0 1px 3px rgba(0,0,0,.15);
        }
        .add-player:hover {
          background: color-mix(in oklch, var(--bg-hover) 80%, var(--accent));
          border-color: color-mix(in oklch, var(--accent) 40%, var(--border));
        }
        .add-player svg { color: var(--accent); }

        .reg-right {
          padding: 14px 32px 14px 24px;
          display: flex; flex-direction: column;
          min-height: 0;
          gap: 12px;
        }
        .rr-table {
          flex: 1;
          position: relative;
          background:
            radial-gradient(ellipse at 50% 30%, color-mix(in oklch, var(--accent) 4%, transparent), transparent 60%),
            var(--bg-app);
          border: 1px solid color-mix(in oklch, var(--border) 45%, var(--fg-faint));
          border-radius: var(--radius-lg);
          padding: 20px 32px;
          display: grid;
          place-items: center;
          container-type: inline-size;
          min-height: 0;
        }
        .rr-empty {
          position: absolute; inset: 0;
          display: flex; flex-direction: column;
          align-items: center; justify-content: center;
          gap: 12px;
          color: var(--fg-faint);
          font-size: 13px;
          pointer-events: none;
        }

        .reg-foot {
          height: 76px;
          padding: 0 32px;
          display: flex; align-items: center; gap: 16px;
          border-top: 1px solid var(--reg-rule);
          background: linear-gradient(180deg, transparent, color-mix(in oklch, var(--bg-deep) 50%, transparent));
        }
        .foot-info {
          display: flex; align-items: center; gap: 8px;
          font-size: 16px; color: var(--fg-soft);
          white-space: nowrap;
        }
        /* 진행자 선택(원형) + 게임 선택(알약형)을 한 덩어리로 오른쪽에 붙인다.
           목록이 이 안에서 위로 열리므로 relative 기준도 여기가 된다. */
        .reg-foot-actions {
          margin-left: auto;
          display: flex; align-items: center; gap: 12px;
        }
        /* 알약형. 옆의 원형 버튼과 나란히 놓였을 때 모서리 반지름이 이어져
           한 벌로 보인다 — 사각 버튼이면 둘이 따로 논다. */
        .reg-foot .btn-pill { border-radius: 999px; }
      `}</style>
    </div>
  )
}

function PlayerRow({ player, index, isActive, onHover, onLeave, onEdit, onRemove, onReregister }) {
  return (
    <div
      className={`prow ${isActive ? 'active' : ''}`}
      onMouseEnter={onHover}
      onMouseLeave={onLeave}
      style={{ '--row-color': player.color }}
    >
      <div className="prow-order">{index + 1}</div>
      <div className="prow-avatar">
        <span>{(player.name || '?').charAt(0)}</span>
      </div>
      <div className="prow-main">
        <div className="prow-name">
          {player.name || '등록 중…'}
          {!player.registered && (
            <button className="prow-rere" onClick={onReregister} title="재등록">↻</button>
          )}
        </div>
        {!player.registered && (
          <div className="prow-sub">등록 미완료</div>
        )}
      </div>
      <div className="prow-actions">
        <button className="btn-icn" onClick={onEdit} title="수정">
          <IconEdit size={16} />
        </button>
        <button className="btn-icn danger" onClick={onRemove} title="삭제">
          <IconTrash size={16} />
        </button>
      </div>

      <style>{`
        .prow {
          display: grid;
          grid-template-columns: 32px 36px 1fr auto;
          align-items: center;
          gap: 12px;
          padding: 10px 14px;
          background: var(--bg-surface);
          border: 1px solid var(--border-soft);
          border-radius: var(--radius);
          transition: all 160ms ease;
          position: relative;
        }
        .prow.active {
          border-color: color-mix(in oklch, var(--row-color) 50%, var(--border));
          background: color-mix(in oklch, var(--row-color) 6%, var(--bg-surface));
        }
        .prow-order {
          font-size: 15px; font-weight: 700;
          color: var(--row-color);
          font-variant-numeric: tabular-nums;
          text-align: center;
          letter-spacing: -0.01em;
        }
        .prow-avatar {
          width: 36px; height: 36px; border-radius: 50%;
          background: linear-gradient(145deg,
            color-mix(in oklch, var(--row-color) 95%, white 5%),
            color-mix(in oklch, var(--row-color) 100%, black 14%));
          color: #1a1410;
          display: grid; place-items: center;
          font-weight: 700; font-size: 15px;
          box-shadow: 0 1px 0 rgba(255,255,255,0.2) inset, 0 2px 6px rgba(0,0,0,0.3);
        }
        .prow-main { min-width: 0; }
        .prow-name {
          font-size: 17px; font-weight: 600; color: var(--fg);
          letter-spacing: -0.01em;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
          display: inline-flex; align-items: center; gap: 8px;
          max-width: 100%;
        }
        .prow-rere {
          appearance: none; border: 1px solid var(--border-soft);
          background: transparent;
          color: var(--fg-mute);
          width: 22px; height: 22px; border-radius: 50%;
          display: grid; place-items: center;
          cursor: pointer; font-size: 13px; line-height: 1;
          flex-shrink: 0;
        }
        .prow-rere:hover { color: var(--accent); border-color: var(--accent); }
        .prow-sub { font-size: 12px; color: var(--warn); margin-top: 2px; }
        .prow-actions {
          display: grid;
          grid-template-columns: 36px 36px;
          gap: 2px;
        }
        .btn-icn {
          appearance: none; border: 1px solid transparent;
          background: transparent;
          color: var(--fg-mute);
          width: 36px; height: 36px; border-radius: 8px;
          display: grid; place-items: center;
          cursor: pointer;
          transition: all 120ms ease;
          font-size: 16px;
        }
        .btn-icn:hover { background: var(--bg-elev); color: var(--fg); }
        .btn-icn.danger:hover { color: var(--err); background: color-mix(in oklch, var(--err) 14%, transparent); }
      `}</style>
    </div>
  )
}

function TurnControls({
  players,
  orderedPlayers,
  firstPlayerId,
  onChangeFirst,
  direction,
  onChangeDirection,
}) {
  const [open, setOpen] = useState(false)
  if (!players.length) return null
  const first = orderedPlayers[0] ?? players.find((p) => p.id === firstPlayerId) ?? players[0]
  const chooseDirection = (nextDirection) => {
    if (direction !== nextDirection) onChangeDirection(nextDirection)
  }

  return (
    <div className="turn-ctrls">
      <div className="tc-first">
        <span className="tc-eyebrow">시작 플레이어</span>
        <button className={`tc-first-pick ${open ? 'open' : ''}`} onClick={() => setOpen((o) => !o)}>
          <span className="tc-first-av" style={{ '--seat-color': first.color }}>
            {(first.name || '?').charAt(0)}
          </span>
          <span className="tc-first-name">{first.name || '등록 중'}</span>
          <span className="tc-chev" aria-hidden>▾</span>
        </button>
        {open && (
          <div className="tc-menu">
            {players.map((p) => (
              <button
                key={p.id}
                className={`tc-menu-item ${p.id === firstPlayerId ? 'active' : ''}`}
                onClick={() => { onChangeFirst(p.id); setOpen(false) }}
              >
                <span className="tc-menu-av" style={{ '--seat-color': p.color }}>
                  {(p.name || '?').charAt(0)}
                </span>
                <span className="tc-menu-name">{p.name || '등록 중'}</span>
                {p.id === firstPlayerId && (
                  <IconCheck size={14} style={{ marginLeft: 'auto', color: 'var(--accent)' }} />
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="tc-dir">
        <span className="tc-eyebrow">진행 방향</span>
        <div className="tc-dir-seg" role="radiogroup">
          <button
            type="button"
            className={`tc-dir-btn ${direction === 'cw' ? 'active' : ''}`}
            onPointerDown={() => chooseDirection('cw')}
            onClick={() => chooseDirection('cw')}
            role="radio"
            aria-checked={direction === 'cw'}
          >
            <DirIcon kind="cw" />
            <span>시계방향</span>
          </button>
          <button
            type="button"
            className={`tc-dir-btn ${direction === 'ccw' ? 'active' : ''}`}
            onPointerDown={() => chooseDirection('ccw')}
            onClick={() => chooseDirection('ccw')}
            role="radio"
            aria-checked={direction === 'ccw'}
          >
            <DirIcon kind="ccw" />
            <span>반시계방향</span>
          </button>
        </div>
      </div>

      <style>{`
        .turn-ctrls {
          margin-top: 14px;
          display: grid;
          grid-template-columns: minmax(0, 1fr) 304px;
          gap: 16px;
          align-items: start;
        }
        .tc-first, .tc-dir { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
        .tc-dir { width: 304px; }
        .tc-eyebrow {
          font-size: 11px; letter-spacing: 0.08em;
          text-transform: uppercase; font-weight: 600;
          color: var(--fg-mute);
          display: block;
        }
        .tc-first { position: relative; align-items: flex-start; }
        .tc-first-pick {
          appearance: none;
          background: var(--bg-surface);
          border: 1px solid var(--border);
          border-radius: 999px;
          height: 40px;
          padding: 0 14px 0 5px;
          color: var(--fg);
          display: inline-flex; align-items: center; gap: 8px;
          font: inherit;
          font-size: 14px; font-weight: 500;
          cursor: pointer;
          transition: all 120ms ease;
          width: auto; max-width: 100%;
        }
        .tc-first-pick:hover { background: var(--bg-elev); }
        .tc-first-av {
          width: 28px; height: 28px; border-radius: 50%;
          background: linear-gradient(145deg,
            color-mix(in oklch, var(--seat-color) 95%, white 5%),
            color-mix(in oklch, var(--seat-color) 100%, black 14%));
          color: #1a1410;
          display: grid; place-items: center;
          font-weight: 700; font-size: 13px;
          flex-shrink: 0;
        }
        .tc-first-name {
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
          min-width: 0;
        }
        .tc-chev {
          font-size: 11px; color: var(--fg-mute);
          margin-left: 2px;
          transition: transform 180ms ease;
        }
        .tc-first-pick.open .tc-chev { transform: rotate(180deg); }

        .tc-menu {
          position: absolute;
          bottom: calc(100% + 4px);
          left: 0;
          min-width: 200px; max-width: 280px;
          background: var(--bg-elev);
          border: 1px solid var(--border);
          border-radius: 10px;
          box-shadow: var(--shadow);
          padding: 4px;
          z-index: 30;
          max-height: 240px;
          overflow-y: auto;
        }
        .tc-menu-item {
          appearance: none; border: 0;
          background: transparent;
          color: var(--fg);
          width: 100%;
          padding: 7px 10px;
          border-radius: 7px;
          display: flex; align-items: center; gap: 8px;
          cursor: pointer;
          font: inherit; font-size: 15px;
          text-align: left;
        }
        .tc-menu-name {
          flex: 1; min-width: 0;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .tc-menu-item:hover { background: var(--bg-hover); }
        .tc-menu-item.active { background: color-mix(in oklch, var(--accent) 12%, transparent); }
        .tc-menu-av {
          width: 24px; height: 24px; border-radius: 50%;
          background: linear-gradient(145deg,
            color-mix(in oklch, var(--seat-color) 95%, white 5%),
            color-mix(in oklch, var(--seat-color) 100%, black 14%));
          color: #1a1410;
          display: grid; place-items: center;
          font-weight: 700; font-size: 12px;
          flex-shrink: 0;
        }

        .tc-dir-seg {
          display: inline-flex;
          background: var(--bg-surface);
          border: 1px solid var(--border);
          border-radius: 999px;
          padding: 3px; gap: 2px;
          height: 40px; align-items: center;
          position: relative;
          z-index: 2;
          width: 304px;
          flex-shrink: 0;
        }
        .tc-dir-btn {
          appearance: none; border: 0;
          background: transparent;
          color: var(--fg-mute);
          height: 32px;
          padding: 0 10px;
          flex: 1 1 0;
          justify-content: center;
          min-width: 0;
          border-radius: 999px;
          font: inherit; font-size: 13px; font-weight: 500;
          display: inline-flex; align-items: center; gap: 6px;
          cursor: pointer;
          touch-action: manipulation;
          user-select: none;
          transition: all 140ms ease;
          white-space: nowrap;
        }
        .tc-dir-btn:hover { color: var(--fg); }
        /* 고른 쪽은 **면으로** 알린다.
           이 화면에는 이미 테두리가 많다(패널·좌석판·알약 트랙·시작 플레이어).
           거기에 토글까지 테두리로 강조하면 선이 한 겹 더 늘어 난잡해진다.
           트랙(--bg-surface)보다 밝은 면을 얹으면 선을 하나도 더 그리지 않고
           "이쪽이 눌려 있다"가 읽힌다 — 세그먼트 컨트롤의 원래 방식이다.

           다만 주 버튼처럼 강조색으로 꽉 채우지는 않는다. 이건 '상태'지
           '다음으로 가는 행동'이 아니라서, 옆의 게임 선택과 무게가 같아지면
           어느 쪽을 눌러야 진행되는지가 흐려진다. */
        .tc-dir-btn.active {
          background: var(--bg-hover);
          color: var(--fg);
          font-weight: 600;
          box-shadow: 0 1px 3px rgba(0,0,0,0.3);
        }
        .tc-dir-btn svg { flex-shrink: 0; }
      `}</style>
    </div>
  )
}

function DirIcon({ kind, size = 14 }) {
  if (kind === 'cw') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M21 12a9 9 0 1 1-4.5-7.8" />
        <polyline points="21 4 21 9 16 9" />
      </svg>
    )
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M3 12a9 9 0 1 0 4.5-7.8" />
      <polyline points="3 4 3 9 8 9" />
    </svg>
  )
}

function EditNameModal({ initialName, existingNames, onCancel, onSubmit }) {
  const [name, setName] = useState(initialName)
  const isUsed = existingNames.includes(name.trim()) && name.trim().length > 0

  const submit = () => {
    const trimmed = name.trim()
    if (!trimmed || isUsed) return
    onSubmit(trimmed)
  }

  return (
    <>
      <div className="backdrop" onClick={onCancel} />
      <div className="enm-modal">
        <div className="enm-head">
          <div className="enm-title">이름 변경</div>
        </div>
        <div className="enm-body">
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
            maxLength={16}
            autoFocus
          />
          {isUsed && (
            <div className="enm-warn">
              <span className="status-dot warn" /> 이미 사용 중인 이름이에요.
            </div>
          )}
        </div>
        <div className="enm-foot">
          <button className="btn btn-ghost" onClick={onCancel}>취소</button>
          <button className="btn btn-primary" onClick={submit} disabled={!name.trim() || isUsed}>
            저장 <IconCheck size={18} />
          </button>
        </div>

        <style>{`
          .enm-modal {
            position: absolute;
            left: 50%; top: 50%;
            transform: translate(-50%, -50%);
            width: min(480px, 88%);
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-xl);
            box-shadow: var(--shadow-lg);
            z-index: 100;
            display: flex; flex-direction: column;
            overflow: hidden;
            animation: enm-pop 240ms cubic-bezier(.2,.7,.2,1.05) both;
          }
          @keyframes enm-pop {
            from { transform: translate(-50%, -50%) scale(0.96); }
            to   { transform: translate(-50%, -50%) scale(1); }
          }
          .enm-head {
            padding: 16px 20px;
            border-bottom: 1px solid var(--border-soft);
          }
          .enm-title {
            font-size: 17px; font-weight: 700; letter-spacing: -0.01em;
            color: var(--fg);
          }
          .enm-body {
            padding: 20px 24px;
            display: flex; flex-direction: column; gap: 12px;
          }
          .enm-warn {
            font-size: 14px; color: var(--warn);
            display: flex; align-items: center; gap: 8px;
          }
          .enm-foot {
            display: flex; gap: 10px; justify-content: flex-end;
            padding: 14px 20px;
            border-top: 1px solid var(--border-soft);
            background: color-mix(in oklch, var(--bg-deep) 30%, transparent);
          }
        `}</style>
      </div>
    </>
  )
}
