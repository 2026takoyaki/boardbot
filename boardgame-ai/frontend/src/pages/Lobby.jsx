import { useState } from 'react'
import {
  IconArrowLeft, IconUsers, IconClock, IconSparkle, IconBook, IconPlay,
} from '../components/common/Icons'
import { YachtDiceArt, WerewolfArt } from '../components/common/GameArt'
import SettingsMenu from '../components/common/SettingsMenu'

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
]

export default function Lobby({
  players,
  connected,
  onBack,
  onSelectGame,   // (gameId, mode) => void   mode: 'play' | 'tutorial' | 'practice'
  send,
}) {
  const [hovered, setHovered] = useState(null)
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
          <SettingsMenu send={send} connected={connected} />
        </div>
      </div>

      <div className="gs-divider-top" />
      <div className="gs-hd">
        <h1 className="gs-title">어떤 게임을 시작할까요?</h1>
        <p className="gs-sub">바로 시작 버튼을 눌러 해당 게임을 시작하거나, 튜토리얼 모드로 규칙부터 익힐 수 있어요.</p>
      </div>

      <div className="gs-cards">
        {GAMES.map((g) => {
          const overCapacity = playerCount > g.maxPlayers
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

        .gs-cards {
          flex: 1;
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 20px;
          padding: 16px 40px 20px;
          min-height: 0;
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

        <div className="gcard-cta-row">
          <button
            className="gcard-cta gcard-cta-secondary"
            onClick={() => !disabled && onStart('tutorial')}
            disabled={disabled}
          >
            <IconBook size={16} />
            튜토리얼 모드
          </button>
          <button
            className="gcard-cta gcard-cta-primary"
            onClick={() => !disabled && onStart('play')}
            disabled={disabled}
          >
            <IconPlay size={14} />
            바로 시작
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
