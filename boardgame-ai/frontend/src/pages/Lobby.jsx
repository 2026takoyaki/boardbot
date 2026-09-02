import { useState } from 'react'
import {
  IconArrowLeft, IconUsers, IconClock, IconSparkle, IconBook, IconPlay,
} from '../components/common/Icons'
import { YachtDiceArt, WerewolfArt, ControlArt } from '../components/common/GameArt'
import SettingsMenu from '../components/common/SettingsMenu'
import AdminGate from '../components/common/AdminGate'

const GAMES = [
  {
    id: 'yacht',
    title: '요트 다이스',
    tagline: '행운과 전략의 만남',
    players: '1–6명',
    duration: '20–30분',
    difficulty: '초급',
    tags: ['주사위 자동 인식', '점수판 자동 집계'],
    accent: 'var(--yacht)',
    art: 'yacht',
    description:
      '5개의 주사위를 굴려 다양한 족보를 완성하세요. 차례당 3번씩 굴릴 수 있으며, 원하는 주사위는 킵 할 수도 있습니다.',
    maxPlayers: 6,
  },
  {
    id: 'werewolf',
    title: '한밤의 늑대인간',
    tagline: '한밤의 진실과 거짓',
    players: '4–10명',
    duration: '10–15분',
    difficulty: '중급',
    tags: ['카드·제스처 인식', '음성 진행'],
    accent: 'var(--werewolf)',
    art: 'wolf',
    description:
      '두번째 밤이 찾아오면 늑대인간이 깨어납니다. 본인의 역할을 수행하고, 낮이 밝아오면 누가 늑대인간인지 토론으로 밝혀내세요.',
    maxPlayers: 10,
  },
  {
    id: 'control',
    title: '컨트롤',
    tagline: '조명과 소리를 직접',
    players: '제한 없음',
    duration: '자유',
    difficulty: '—',
    tags: ['조명 직접 조절', '연출 버튼'],
    accent: 'var(--accent)',
    art: 'control',
    description:
      '게임 없이 방의 조명을 직접 맞추고, 축하·박수·파티 같은 연출을 버튼으로 터뜨립니다. 나가면 조명이 원래대로 돌아옵니다.',
    // 게임이 아니라 인원 제한이 없다. 아래에서 이 값이 없으면 인원 검사를 건너뛴다.
    maxPlayers: null,
    // 튜토리얼이 없다. 바로 시작만 있다.
    soloAction: true,
  },
]

export default function Lobby({
  players,
  connected,
  onBack,
  onSelectGame,   // (gameId, mode) => void   mode: 'play' | 'tutorial' | 'practice'
  onAdmin,        // 비밀번호를 통과했을 때만 불린다
  send,
}) {
  const [hovered, setHovered] = useState(null)
  // 관리자 콘솔은 게임 카드로 두지 않는다. 발표용이라 게임과 같은 급으로
  // 늘어놓으면 시연 중에 손님이 눌러볼 자리가 된다.
  const [askAdmin, setAskAdmin] = useState(false)
  const playerCount = players.filter((p) => p.playername).length

  return (
    <div className="scr scr-games fade-in">
      <div className="topbar">
        <button className="btn-back" onClick={onBack}>
          <IconArrowLeft size={16} /> 플레이어 등록
        </button>
        <div className="crumbs">
          <span style={{ opacity: 0.5 }}>플레이어 등록</span>
          <span className="sep">→</span>
          <span>게임 선택</span>
          <span className="sep">→</span>
          <span style={{ opacity: 0.5 }}>플레이</span>
        </div>
        <div className="right">
          <span><b>{playerCount}</b>명 플레이</span>
          <span style={{ opacity: 0.5 }}>|</span>
          <span>
            <span
              className={`status-dot ${connected ? 'ok' : 'err'}`}
              style={{ marginRight: 6 }}
            />
            {connected ? '카메라 정상' : '카메라 오류'}
          </span>
          {/* 게임 안에서만 소리를 줄일 수 있으면, 정작 로비 BGM이 큰 순간에
              방법이 없다. 게임 화면과 같은 메뉴를 여기에도 둔다. */}
          <SettingsMenu
            send={send}
            connected={connected}
            onAdmin={onAdmin ? () => setAskAdmin(true) : undefined}
          />
        </div>
      </div>

      {askAdmin && (
        <AdminGate
          onPass={() => { setAskAdmin(false); onAdmin() }}
          onCancel={() => setAskAdmin(false)}
        />
      )}

      <div className="gs-divider-top" />
      <div className="gs-hd">
        <h1 className="gs-title">어떤 게임을 시작할까요?</h1>
        <p className="gs-sub">바로 시작 버튼을 눌러 해당 게임을 시작하거나, 튜토리얼 모드로 규칙부터 익힐 수 있어요.</p>
      </div>

      <div className="gs-cards">
        {GAMES.map((g) => {
          // 컨트롤은 게임이 아니라 인원 제한이 없다(maxPlayers=null).
          const overCapacity = g.maxPlayers != null && playerCount > g.maxPlayers
          const disabled = !connected || overCapacity
          const disabledReason =
            !connected ? '카메라 오류 — 연결을 확인해 주세요'
            : overCapacity ? `최대 ${g.maxPlayers}명까지 가능합니다`
            : null
          return (
            <GameCard
              key={g.id}
              game={g}
              isHovered={hovered === g.id}
              onHover={(h) => setHovered(h ? g.id : null)}
              onStart={(mode) => onSelectGame(g.id, mode)}
              disabled={disabled}
              disabledReason={disabledReason}
            />
          )
        })}
      </div>

      <div className="gs-foot">
        <div className="gs-foot-info">
          <IconSparkle size={14} style={{ color: 'var(--accent)' }} />
          <span>곧 더 많은 게임이 추가됩니다</span>
        </div>
      </div>

      <style>{`
        .scr-games {
          position: absolute; inset: 0;
          padding-top: 56px;
          display: flex; flex-direction: column;
          --gs-rule: color-mix(in oklch, var(--border-soft) 50%, var(--border));
        }
        .gs-divider-top {
          height: 1px;
          margin: 0 24px;
          background: var(--gs-rule);
        }
        /* theme.css의 보조 버튼(.btn-secondary)과 같은 무게로 맞춘다.
           예전에는 --bg-surface에 --border-soft라 배경과 거의 같은 색이었고,
           옆의 밝은 시작 버튼과 나란히 놓이면 눌리는 물건으로 안 보였다. */
        .btn-back {
          appearance: none; border: 1px solid var(--border);
          background: var(--bg-elev); color: var(--fg);
          padding: 9px 16px; border-radius: var(--radius-sm);
          font-size: 14px; font-weight: 600;
          display: inline-flex; align-items: center; gap: 6px;
          font-family: inherit; cursor: pointer;
          white-space: nowrap;
          transition: background 120ms ease, border-color 120ms ease;
        }
        .btn-back:hover { background: var(--bg-hover); border-color: var(--fg-faint); }

        .gs-hd {
          padding: 16px 40px 8px;
          display: flex; flex-direction: column; gap: 6px;
        }
        .gs-title { font-size: 30px; font-weight: 700; letter-spacing: -0.025em; }
        .gs-sub { margin: 0; font-size: 16px; color: var(--fg-soft); }

        /* 카드는 **한 줄로만** 늘어서고, 한 번에 두 장이 화면을 채운다.
           게임을 추가할 때마다 카드가 좁아지면 원래 있던 두 게임까지 같이
           초라해진다. 카드 폭을 화면에 묶어두면 몇 개를 더 넣어도 그대로다.
           나머지는 옆으로 밀어서 본다.

           --peek 만큼 세 번째 카드가 살짝 걸쳐 보인다. 딱 두 장으로 잘라내면
           옆에 더 있다는 것을 알 방법이 없다 — 걸친 조각이 밀어보라고 말한다. */
        .gs-cards {
          flex: 1;
          min-height: 0;
          --gs-gap: 20px;
          --peek: 38px;
          display: grid;
          grid-auto-flow: column;
          grid-auto-columns: calc((100% - var(--gs-gap) - var(--peek)) / 2);
          gap: var(--gs-gap);
          padding: 16px 40px 20px;
          overflow-x: auto;
          overflow-y: hidden;
          overscroll-behavior-x: contain;
          -webkit-overflow-scrolling: touch;
          scroll-snap-type: x mandatory;
          /* 스냅 기준선을 패딩 안쪽으로 민다.
             이게 없으면 스냅이 첫 카드를 컨테이너 테두리에 딱 붙여서
             왼쪽 여백이 통째로 사라진다 — 카드가 화면 끝에 붙어 답답해진다. */
          scroll-padding-left: 40px;
          /* 스크롤바는 숨긴다. 태블릿을 손으로 밀어 쓰는 화면이라 막대가
             보일 이유가 없고, 카드 아래에 걸치면 지저분하다. */
          scrollbar-width: none;
        }
        .gs-cards::-webkit-scrollbar { display: none; }
        .gs-cards > * { scroll-snap-align: start; }
        /* 좁은 화면에서는 한 장씩. 두 장을 우겨넣으면 둘 다 못 읽는다. */
        @media (max-width: 820px) {
          .gs-cards {
            grid-auto-columns: calc(100% - var(--peek));
            padding-left: 24px;
            padding-right: 24px;
            scroll-padding-left: 24px;
          }
        }

        .gs-foot {
          height: 48px;
          display: flex; align-items: center;
          padding: 0 40px;
          color: var(--fg-mute);
          font-size: 14px;
          border-top: 1px solid var(--gs-rule);
        }
        .gs-foot-info { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
      `}</style>
    </div>
  )
}

function GameCard({ game, isHovered, onHover, onStart, disabled, disabledReason }) {
  return (
    <article
      className={`gcard accent-${game.id} ${isHovered ? 'hovered' : ''} ${disabled ? 'disabled' : ''}`}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      style={{ '--game-accent': game.accent }}
    >
      <div className="gcard-art">
        {game.art === 'yacht' && <YachtDiceArt />}
        {game.art === 'wolf'  && <WerewolfArt />}
        {game.art === 'control' && <ControlArt />}
        <div className="gcard-art-overlay" />
        <div className="gcard-art-meta">
          <div className="gcard-tagline">{game.tagline}</div>
        </div>
      </div>

      <div className="gcard-body">
        <div className="gcard-head">
          <h3 className="gcard-title">{game.title}</h3>
          <div className="gcard-stats">
            <span className="gstat"><IconUsers size={13} />{game.players}</span>
            <span className="gstat"><IconClock size={13} />{game.duration}</span>
            <span className="gstat"><IconSparkle size={13} />{game.difficulty}</span>
          </div>
        </div>

        <p className="gcard-desc">{game.description}</p>

        <div className="gcard-tags">
          {game.tags.map((t) => <span key={t} className="gtag">{t}</span>)}
        </div>

        {disabled && disabledReason && (
          <div className="gcard-warn">{disabledReason}</div>
        )}

        {/* 컨트롤은 배울 규칙이 없어 튜토리얼이 없다. 눌러도 같은 곳으로 가는
            버튼을 둘 두면 무엇이 다른지 묻게 만든다. */}
        <div className={`gcard-cta-row${game.soloAction ? ' solo' : ''}`}>
          {!game.soloAction && (
            <button
              className="gcard-cta gcard-cta-secondary"
              onClick={() => !disabled && onStart('tutorial')}
              disabled={disabled}
            >
              <IconBook size={16} />
              튜토리얼 모드
            </button>
          )}
          <button
            className="gcard-cta gcard-cta-primary"
            onClick={() => !disabled && onStart('play')}
            disabled={disabled}
          >
            <IconPlay size={14} />
            {game.soloAction ? '시작하기' : '바로 시작'}
          </button>
        </div>

        <style>{`
          .gcard {
            position: relative;
            background: var(--bg-surface);
            border: 1px solid var(--border-soft);
            border-radius: var(--radius-xl);
            overflow: hidden;
            display: flex; flex-direction: column;
            transition: transform 240ms cubic-bezier(.2,.7,.2,1.05), border-color 240ms ease;
          }
          .gcard.hovered:not(.disabled) {
            transform: translateY(-3px);
            border-color: color-mix(in oklch, var(--game-accent) 50%, var(--border));
          }
          .gcard.disabled { opacity: 0.6; }
          .gcard-art {
            position: relative;
            flex: 0 0 auto;
            height: 44%;
            min-height: 200px;
            overflow: hidden;
          }
          .gcard-art-overlay {
            position: absolute; inset: 0;
            background: linear-gradient(180deg, transparent 30%, rgba(0,0,0,0.35) 100%);
          }
          .gcard-art-meta { position: absolute; left: 22px; bottom: 18px; z-index: 2; }
          .gcard-tagline {
            font-size: 14px; font-weight: 600;
            letter-spacing: 0.06em;
            color: rgba(255,255,255,0.92);
            text-transform: uppercase;
            text-shadow: 0 2px 8px rgba(0,0,0,0.6);
            white-space: nowrap;
          }

          .gcard-body {
            padding: 18px 22px 20px;
            display: flex; flex-direction: column; gap: 14px;
            flex: 1;
          }
          .gcard-head { display: flex; flex-direction: column; gap: 8px; }
          .gcard-title { font-size: 28px; font-weight: 700; letter-spacing: -0.025em; }
          .gcard-stats {
            display: flex; gap: 16px;
            font-size: 14px; color: var(--fg-mute);
            flex-wrap: wrap;
          }
          .gstat {
            display: inline-flex; align-items: center; gap: 6px;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
          }
          .gcard-desc {
            margin: 0; font-size: 15px;
            line-height: 1.6; color: var(--fg-soft);
            text-wrap: pretty;
          }
          .gcard-tags { display: flex; flex-wrap: wrap; gap: 6px; }
          .gtag {
            font-size: 13px;
            padding: 5px 12px;
            border-radius: 999px;
            background: color-mix(in oklch, var(--game-accent) 14%, var(--bg-elev));
            color: color-mix(in oklch, var(--game-accent) 70%, var(--fg));
            border: 1px solid color-mix(in oklch, var(--game-accent) 25%, transparent);
            font-weight: 500;
            white-space: nowrap;
          }
          .gcard-warn {
            font-size: 14px;
            color: var(--warn);
            padding: 9px 14px;
            background: color-mix(in oklch, var(--warn) 8%, transparent);
            border-radius: 8px;
          }

          .gcard-cta-row {
            margin-top: auto;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
          }
          /* 버튼이 하나뿐인 카드(컨트롤). 반쪽만 차지하면 빈 자리가 실수처럼 보인다. */
          .gcard-cta-row.solo { grid-template-columns: 1fr; }
          .gcard-cta {
            appearance: none;
            border: 0;
            border-radius: var(--radius);
            padding: 16px 20px;
            font-size: 17px; font-weight: 600; letter-spacing: -0.01em;
            display: flex; align-items: center; justify-content: center; gap: 8px;
            cursor: pointer;
            transition: transform 100ms ease, background 160ms ease;
            white-space: nowrap;
            font-family: inherit;
          }
          .gcard-cta:active { transform: translateY(1px); }
          .gcard-cta:disabled { cursor: not-allowed; opacity: 0.5; }
          .gcard-cta-primary {
            background: linear-gradient(180deg,
              color-mix(in oklch, var(--game-accent) 88%, white 8%),
              var(--game-accent));
            color: #14110d;
            box-shadow: 0 1px 0 rgba(255,255,255,0.25) inset;
          }
          .gcard.accent-werewolf .gcard-cta-primary { color: #e9e4f0; }
          .gcard-cta-secondary {
            background: var(--bg-elev);
            color: var(--fg);
            border: 1px solid var(--border);
          }
          .gcard-cta-secondary:hover:not(:disabled) { background: var(--bg-hover); }
        `}</style>
      </div>
    </article>
  )
}
