import { useEffect, useRef, useState } from 'react'
import { audio as audioApi } from '../../hooks/useAudioPlayer'
import { useStrategyCoaching } from '../../hooks/useStrategyCoaching'
import { playSfx } from '../../sfx'
import { IconVolume, IconMusic, IconSparkle, IconArrowLeft, IconClose, IconLock } from './Icons'

/**
 * 톱니 버튼 + 설정 패널.
 *
 * 로비·좌석 등록·요트·늑대인간이 **같은 물건**을 쓴다. 소리를 줄이는 방법이
 * 화면마다 다르면(어떤 화면엔 아예 없으면) 사람은 그때마다 다시 찾는다.
 * 실제로 소리 조작이 요트에만 있었고, 로비에서 배경음이 큰데 줄일 방법이
 * 없었다.
 *
 * 화면마다 다른 것은 **팔레트와 항목 구성**뿐이다.
 *
 *     로비/좌석   소리만
 *     게임 중     전략 토글 + 소리 + 나가기
 *
 * 색을 리터럴로 들고 있는 이유: 이 메뉴는 늑대인간에서 `.ww-root` 바깥에
 * 마운트된다. 게임 팔레트 변수(`--w-*`)를 쓰면 스코프에 없어 색이 통째로
 * 무효가 되고, 특히 음량 슬라이더는 트랙도 손잡이도 안 보였다.
 */
const THEMES = {
  app: {
    '--sm-fg': 'var(--fg)',
    '--sm-fg-mute': 'var(--fg-mute)',
    '--sm-accent': 'var(--accent)',
    '--sm-line': 'var(--border)',
    '--sm-surface': 'var(--bg-surface)',
    '--sm-btn-bg': 'var(--bg-elev)',
    '--sm-danger': 'var(--err)',
    '--sm-hover': 'var(--bg-hover)',
  },
  yacht: {
    '--sm-fg': 'rgba(238,233,220,0.88)',
    '--sm-fg-mute': 'rgba(238,233,220,0.5)',
    '--sm-accent': '#e8c765',
    '--sm-line': 'rgba(238,233,220,0.16)',
    '--sm-surface': '#1a3126',
    '--sm-btn-bg': 'rgba(0,0,0,0.24)',
    '--sm-danger': '#e08a63',
    '--sm-hover': 'rgba(255,255,255,0.06)',
  },
  werewolf: {
    '--sm-fg': 'rgba(245,239,227,0.88)',
    '--sm-fg-mute': 'rgba(245,239,227,0.48)',
    '--sm-accent': '#f0cf7a',
    '--sm-line': 'rgba(255,255,255,0.16)',
    '--sm-surface': '#151120',
    '--sm-btn-bg': 'rgba(10,8,16,0.52)',
    '--sm-danger': '#ff8a5c',
    '--sm-hover': 'rgba(255,255,255,0.06)',
  },
}

function IconGear({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3.2" />
      <path d="M19.4 15a1.6 1.6 0 0 0 .32 1.77l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.6 1.6 0 0 0-1.77-.32 1.6 1.6 0 0 0-1 1.47V21a2 2 0 1 1-4 0v-.11a1.6 1.6 0 0 0-1.05-1.46 1.6 1.6 0 0 0-1.76.32l-.07.06a2 2 0 1 1-2.83-2.83l.06-.06a1.6 1.6 0 0 0 .33-1.77 1.6 1.6 0 0 0-1.47-1H3a2 2 0 1 1 0-4h.11a1.6 1.6 0 0 0 1.46-1.05 1.6 1.6 0 0 0-.32-1.76l-.06-.07a2 2 0 1 1 2.83-2.83l.06.06a1.6 1.6 0 0 0 1.77.33H9a1.6 1.6 0 0 0 1-1.47V3a2 2 0 1 1 4 0v.11a1.6 1.6 0 0 0 1 1.47 1.6 1.6 0 0 0 1.77-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.6 1.6 0 0 0-.33 1.77V9a1.6 1.6 0 0 0 1.47 1H21a2 2 0 1 1 0 4h-.11a1.6 1.6 0 0 0-1.47 1Z" />
    </svg>
  )
}

/** 켜짐/꺼짐 스위치. 체크박스보다 지금 상태가 멀리서도 읽힌다. */
function Switch({ on }) {
  return (
    <span className={`sm-sw ${on ? 'on' : ''}`} aria-hidden>
      <span className="sm-sw-knob" />
    </span>
  )
}

/**
 * 음량 한 줄. 0으로 내리면 그 채널이 꺼진다.
 *
 * onPreview는 손을 뗀 순간 한 번 불린다. 끌고 있는 동안 울리면 값이 바뀔
 * 때마다 소리가 겹쳐 무엇을 맞추고 있는지 알 수 없다.
 */
function VolumeRow({ icon, label, value, onChange, onPreview }) {
  const percent = Math.round(value * 100)
  return (
    <div className="sm-vol">
      <span className={`sm-vol-ic ${value > 0 ? 'on' : ''}`} aria-hidden>{icon}</span>
      <span className="sm-vol-label">{label}</span>
      <input
        className="sm-slider"
        type="range"
        min="0"
        max="100"
        step="5"
        value={percent}
        aria-label={`${label} 음량`}
        // 채워진 만큼 색이 차오른다. 트랙이 한 가지 색이면 손잡이 위치를
        // 눈으로 좇아야 하고, 0과 100이 한눈에 구별되지 않는다.
        style={{ '--fill': `${percent}%` }}
        onChange={(e) => onChange(Number(e.target.value) / 100)}
        onPointerUp={onPreview}
        onKeyUp={onPreview}
      />
      <span className="sm-vol-num">{percent}</span>
    </div>
  )
}

export default function SettingsMenu({
  theme = 'app',
  send,
  connected = true,
  /** 전략 조언 토글을 보일지. 게임 중에만 뜻이 있다. */
  showStrategy = false,
  /** 넘기면 '게임 나가기' 줄이 생긴다. 로비에는 나갈 곳이 없다. */
  onExit,
  /**
   * 넘기면 '관리자' 줄이 생긴다. 로비에서만 넘긴다 — 발표 연출은 게임을
   * 시작하기 전에 쓰는 물건이라, 게임 중에 그 자리를 두면 잘못 눌러 판이
   * 깨질 자리만 늘어난다. 비밀번호는 부르는 쪽이 묻는다(AdminGate).
   */
  onAdmin,
}) {
  const [open, setOpen] = useState(false)
  const [vol, setVol] = useState(() => audioApi.volumes())
  const [strategyOn, toggleStrategy] = useStrategyCoaching(showStrategy ? send : null, connected)
  const rootRef = useRef(null)

  // 음량은 모듈 싱글턴이 갖고 있다. 다른 곳에서 바뀌어도 슬라이더가 따라오도록
  // 구독한다 — 이 메뉴가 여러 화면에 있으므로 값의 주인은 저쪽이어야 한다.
  useEffect(() => audioApi.onVolumeChange(setVol), [])

  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => {
      if (!rootRef.current?.contains(e.target)) setOpen(false)
    }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  /**
   * 음량 0은 '조용히'가 아니라 '끈다'로 해석한다.
   *
   * 말을 0으로 내려놓고도 백엔드가 발화 길이만큼 기다리면, 아무 소리 없는
   * 정적이 그대로 진행 속도가 된다. 시연 중에 말을 줄이는 사람은 조용하기를
   * 원하는 게 아니라 **빨리 넘어가기**를 원한다. 배경음도 같은 이유로 백엔드
   * 재생 자체를 멈춘다 — 볼륨 0인 트랙을 계속 돌릴 이유가 없다.
   */
  const changeTts = (v) => {
    audioApi.setVolume('tts', v)
    audioApi.setTtsEnabled(v > 0)
  }
  const changeBgm = (v) => {
    audioApi.setVolume('bgm', v)
    send?.('BGM_SET', { enabled: v > 0 })
  }

  // 늑대인간에는 배경 전체가 클릭 대상인 화면이 있다(결과 발표 등).
  // 눌린 곳이 이 메뉴면 그 화면까지 번지지 않게 막는다.
  const stop = (fn) => (e) => { e.stopPropagation(); fn?.() }

  return (
    <div className="sm-root" ref={rootRef} style={THEMES[theme] ?? THEMES.app}>
      <button
        type="button"
        className={`sm-gear ${open ? 'on' : ''}`}
        onClick={stop(() => setOpen(o => !o))}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label="설정"
        title="설정"
      >
        <IconGear size={20} />
      </button>

      {open && (
        <div className="sm-panel" role="dialog" aria-label="설정">
          <div className="sm-panel-hd">
            설정
            <button
              type="button"
              className="sm-x"
              onClick={stop(() => setOpen(false))}
              aria-label="닫기"
            >
              <IconClose size={15} />
            </button>
          </div>

          {showStrategy && (
            <>
              <button
                type="button"
                className="sm-line-btn"
                onClick={stop(toggleStrategy)}
                aria-pressed={strategyOn}
              >
                <span className={`sm-line-ic ${strategyOn ? 'on' : ''}`}><IconSparkle size={17} /></span>
                <span className="sm-line-txt">
                  <span className="sm-line-name">전략 조언</span>
                  {/* 한 줄에 들어가는 길이로 자른다. 두 줄로 넘어가면
                      마지막 줄에 두 글자만 남아 잘린 것처럼 보인다. */}
                  <span className="sm-line-desc">상황에 맞는 조언을 해줍니다</span>
                </span>
                <Switch on={strategyOn} />
              </button>
              <div className="sm-div" />
            </>
          )}

          <div className="sm-sec">소리</div>
          <VolumeRow
            icon={<IconVolume size={16} />}
            label="진행자"
            value={vol.tts}
            onChange={changeTts}
          />
          <VolumeRow
            icon={<IconSparkle size={16} />}
            label="효과음"
            value={vol.sfx}
            onChange={(v) => audioApi.setVolume('sfx', v)}
            // 진행자·배경음은 맞추는 동안 계속 들리지만 효과음은 아니다.
            // 손을 뗄 때 한 번 들려주지 않으면 눈금만 보고 맞춰야 한다.
            onPreview={() => playSfx('ui_click')}
          />
          <VolumeRow
            icon={<IconMusic size={16} />}
            label="배경음"
            value={vol.bgm}
            onChange={changeBgm}
          />
          <div className="sm-note">0으로 내리면 꺼집니다</div>

          {onAdmin && (
            <>
              <div className="sm-div" />
              <button
                type="button"
                className="sm-line-btn"
                onClick={stop(() => { setOpen(false); onAdmin() })}
              >
                <span className="sm-line-ic"><IconLock size={17} /></span>
                <span className="sm-line-txt">
                  <span className="sm-line-name">관리자</span>
                  <span className="sm-line-desc">발표 연출 콘솔 · 비밀번호 필요</span>
                </span>
              </button>
            </>
          )}

          {onExit && (
            <>
              <div className="sm-div" />
              <button type="button" className="sm-line-btn sm-exit" onClick={stop(onExit)}>
                <span className="sm-line-ic"><IconArrowLeft size={17} /></span>
                <span className="sm-line-txt">
                  <span className="sm-line-name">게임 나가기</span>
                </span>
              </button>
            </>
          )}
        </div>
      )}

      <style>{CSS}</style>
    </div>
  )
}

const CSS = `
  .sm-root { position: relative; display: flex; align-items: center; }

  .sm-gear {
    appearance: none;
    width: 44px; height: 44px;
    display: grid; place-items: center;
    border: 1px solid var(--sm-line);
    border-radius: 12px;
    background: var(--sm-btn-bg);
    color: var(--sm-fg-mute);
    cursor: pointer;
    padding: 0;
    -webkit-backdrop-filter: blur(10px);
    backdrop-filter: blur(10px);
    transition: color 160ms ease, border-color 160ms ease, background 160ms ease;
  }
  .sm-gear:hover { color: var(--sm-fg); border-color: var(--sm-accent); }
  .sm-gear.on {
    color: var(--sm-accent);
    border-color: var(--sm-accent);
    background: color-mix(in srgb, var(--sm-accent) 18%, transparent);
  }

  /* 열려 있는 동안 톱니가 돌아가 있다. 패널이 어디서 나왔는지 화살표 없이도
     이 버튼과 이어진다.
     도는 것은 **아이콘뿐**이다. 버튼째 돌리면 둥근 사각 테두리가 같이 기울어
     마름모가 되고, 옆 버튼과 각이 어긋나 보인다.
     30°인 이유: 이 톱니는 이가 여덟 개라 45°를 돌리면 제자리와 똑같아진다. */
  .sm-gear svg { transition: transform 260ms cubic-bezier(.2,.8,.25,1); }
  .sm-gear.on svg { transform: rotate(30deg); }

  .sm-panel {
    position: absolute;
    top: calc(100% + 9px);
    right: 0;
    width: 292px;
    padding: 8px;
    border: 1px solid var(--sm-line);
    border-radius: 16px;
    background: var(--sm-surface);
    box-shadow: 0 20px 48px rgba(0,0,0,0.5);
    z-index: 60;
    animation: sm-in 160ms cubic-bezier(.2,.8,.25,1) both;
  }
  @keyframes sm-in {
    from { opacity: 0; transform: translateY(-8px) scale(0.97); }
    to   { opacity: 1; transform: none; }
  }

  .sm-panel-hd {
    display: flex; align-items: center; justify-content: space-between;
    padding: 5px 6px 9px;
    font-size: 11px; font-weight: 800;
    letter-spacing: 0.16em;
    color: var(--sm-fg-mute);
  }
  .sm-x {
    appearance: none; border: 0; background: transparent;
    color: var(--sm-fg-mute); cursor: pointer; padding: 4px;
    display: flex; border-radius: 7px;
  }
  .sm-x:hover { color: var(--sm-fg); background: var(--sm-hover); }

  .sm-div { height: 1px; margin: 7px 2px; background: var(--sm-line); }

  /* 패널 안의 한 줄짜리 항목. 전략 토글과 나가기가 같은 규격을 쓴다. */
  .sm-line-btn {
    appearance: none;
    width: 100%;
    display: flex; align-items: center; gap: 11px;
    padding: 10px 8px;
    border: 0; border-radius: 11px;
    background: transparent;
    color: var(--sm-fg);
    font-family: inherit;
    text-align: left;
    cursor: pointer;
  }
  .sm-line-btn:hover { background: var(--sm-hover); }

  .sm-line-ic {
    flex: 0 0 auto;
    width: 34px; height: 34px;
    display: grid; place-items: center;
    border-radius: 10px;
    background: color-mix(in srgb, var(--sm-fg-mute) 14%, transparent);
    color: var(--sm-fg-mute);
    transition: color 160ms ease, background 160ms ease;
  }
  .sm-line-ic.on {
    color: var(--sm-accent);
    background: color-mix(in srgb, var(--sm-accent) 20%, transparent);
  }

  .sm-line-txt { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .sm-line-name { font-size: 14.5px; font-weight: 700; }
  .sm-line-desc { font-size: 11.5px; line-height: 1.35; color: var(--sm-fg-mute); }

  .sm-exit .sm-line-name { color: var(--sm-danger); }
  .sm-exit .sm-line-ic { color: var(--sm-danger); }

  .sm-sw {
    flex: 0 0 auto;
    width: 42px; height: 24px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--sm-fg-mute) 34%, transparent);
    display: block;
    position: relative;
    transition: background 180ms ease;
  }
  .sm-sw.on { background: var(--sm-accent); }
  .sm-sw-knob {
    position: absolute;
    top: 3px; left: 3px;
    width: 18px; height: 18px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 3px rgba(0,0,0,0.4);
    transition: transform 180ms cubic-bezier(.2,.8,.25,1);
  }
  .sm-sw.on .sm-sw-knob { transform: translateX(18px); }

  .sm-sec {
    padding: 4px 8px 2px;
    font-size: 11px; font-weight: 800;
    letter-spacing: 0.16em;
    color: var(--sm-fg-mute);
  }

  .sm-vol {
    display: grid;
    grid-template-columns: 18px 46px 1fr 26px;
    align-items: center;
    gap: 9px;
    padding: 6px 8px;
  }
  .sm-vol-ic { display: flex; color: var(--sm-fg-mute); }
  .sm-vol-ic.on { color: var(--sm-accent); }
  .sm-vol-label { font-size: 13px; font-weight: 650; color: var(--sm-fg); }
  .sm-vol-num {
    font-size: 12px; font-weight: 700;
    text-align: right;
    color: var(--sm-fg-mute);
    font-variant-numeric: tabular-nums;
  }

  /* 손가락으로 끌 수 있어야 한다. 기본 range는 트랙이 4px이라 태블릿에서
     잡히지 않고, 잡아도 옆의 버튼이 먼저 반응한다. */
  .sm-slider {
    appearance: none; -webkit-appearance: none;
    width: 100%; height: 22px;
    background: transparent;
    cursor: pointer;
    margin: 0;
  }
  .sm-slider::-webkit-slider-runnable-track {
    height: 6px; border-radius: 999px;
    background: linear-gradient(
      to right,
      var(--sm-accent) 0 var(--fill),
      color-mix(in srgb, var(--sm-fg-mute) 30%, transparent) var(--fill) 100%
    );
  }
  .sm-slider::-moz-range-track {
    height: 6px; border-radius: 999px;
    background: linear-gradient(
      to right,
      var(--sm-accent) 0 var(--fill),
      color-mix(in srgb, var(--sm-fg-mute) 30%, transparent) var(--fill) 100%
    );
  }
  .sm-slider::-webkit-slider-thumb {
    appearance: none; -webkit-appearance: none;
    width: 18px; height: 18px; margin-top: -6px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 4px rgba(0,0,0,0.5);
  }
  .sm-slider::-moz-range-thumb {
    width: 18px; height: 18px;
    border: 0;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 4px rgba(0,0,0,0.5);
  }

  .sm-note {
    padding: 4px 8px 2px;
    font-size: 11.5px;
    color: var(--sm-fg-mute);
  }

  @media (prefers-reduced-motion: reduce) {
    .sm-panel { animation-duration: 1ms; }
    .sm-gear svg { transition: none; }
  }
`
