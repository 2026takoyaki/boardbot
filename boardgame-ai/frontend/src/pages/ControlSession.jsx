import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'
import { audio as audioApi, useAudioPlayer } from '../hooks/useAudioPlayer'
import GameTopBar from '../components/common/GameTopBar'

/**
 * 컨트롤 세션 — 진행자가 조명과 소리를 직접 다루는 화면.
 *
 * 게임이 아니다. FSM도 비전도 없고, 백엔드에서 하는 일은 두 가지뿐이다 —
 * 슬라이더 값을 전구에 그대로 넘기고, 버튼을 조명 큐 + 효과음으로 바꾼다.
 *
 * 나갈 때 조명은 백엔드가 되돌린다(웹소켓이 끊기는 모든 경로에서). 여기서는
 * 화면만 로비로 돌리면 된다.
 */

// 색 고르기. 색상환을 직접 돌리는 대신 미리 고른 색을 늘어놓는다 —
// 진행 중에 손으로 색을 맞추고 있을 시간이 없고, 방에 어울리는 색은
// 어차피 몇 개로 정해져 있다. 맨 앞은 인식용 백색(요트 기본값과 같다).
const SWATCHES = [
  { id: 'white',  label: '기본 백색', rgb: [255, 255, 255] },
  { id: 'warm',   label: '따뜻한 백색', rgb: [255, 214, 170] },
  { id: 'amber',  label: '앰버',     rgb: [255, 168, 40] },
  { id: 'gold',   label: '금색',     rgb: [255, 200, 90] },
  { id: 'red',    label: '빨강',     rgb: [255, 40, 40] },
  { id: 'pink',   label: '분홍',     rgb: [255, 70, 160] },
  { id: 'purple', label: '보라',     rgb: [150, 60, 220] },
  { id: 'blue',   label: '파랑',     rgb: [60, 110, 255] },
  { id: 'cyan',   label: '청록',     rgb: [40, 200, 230] },
  { id: 'green',  label: '초록',     rgb: [50, 210, 100] },
]

const DEFAULT_RGB = [255, 255, 255]
const DEFAULT_BRIGHTNESS = 100

/**
 * 전환 시간 — 새 값까지 몇 초에 걸쳐 물들일지.
 *
 * "즉시"와 "3초에 걸쳐"는 연출로서 전혀 다른 물건이라 사람이 골라야 한다.
 * 방을 서서히 어둡게 만드는 것과 탁 끄는 것은 같은 값이어도 뜻이 다르다.
 */
const FADES = [
  { id: 'snap', label: '즉시',   ms: 0 },
  { id: 'quick', label: '0.5초', ms: 500 },
  { id: 'slow',  label: '1.5초', ms: 1500 },
  { id: 'drift', label: '3초',   ms: 3000 },
]

// 이 시간보다 전환이 짧으면 **드래그 중에도 따라간다**. 손가락을 따라 방이
// 바뀌어야 미세 조정이 되기 때문이다.
//
// 길게 잡아둔 경우에는 손을 뗄 때만 보낸다. 끄는 동안 중간값을 계속 보내면
// 그때마다 페이드가 새로 시작해서, 정작 보려던 긴 전환이 영영 안 보인다.
const LIVE_FOLLOW_MAX_MS = 600

// 드래그 중 전송 간격. 전구는 분당 명령 수 제한이 있어 무제한으로 보낼 수 없다.
// 4번/초면 손가락을 따라오는 것으로 보이면서 1분을 꽉 끌어도 한계 안에 든다.
const LIVE_THROTTLE_MS = 250

// 손을 뗀 뒤 확정값을 보내기까지. 짧게 둬야 조작이 끊기지 않는다.
const SEND_DEBOUNCE_MS = 90

const rgbCss = (rgb) => `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`

export default function ControlSession({ onExit }) {
  const [rgb, setRgb] = useState(DEFAULT_RGB)
  const [brightness, setBrightness] = useState(DEFAULT_BRIGHTNESS)
  const [cues, setCues] = useState([])
  const [fadeId, setFadeId] = useState('quick')
  // 지금 도는 연출. 끝날 때까지 버튼을 잠가 조명 큐가 겹치지 않게 한다.
  const [busyCue, setBusyCue] = useState(null)

  const { send, connected, messages } = useWebSocket('/ws/control', {
    onAudioMessage: audioApi.enqueue,
  })
  useAudioPlayer(send)

  // 연출 목록의 주인은 백엔드다(bulb/scenes.py). 여기서 따로 갖고 있으면
  // 연출을 추가할 때 두 곳을 고쳐야 하고, 한쪽만 고치면 눌러도 아무 일이
  // 없는 버튼이 생긴다.
  const hello = useMemo(
    () => messages.find((m) => m.msg_type === 'hello')?.payload,
    [messages],
  )
  useEffect(() => {
    if (hello?.cues) setCues(hello.cues)
  }, [hello])

  // ── 조명 전송 ────────────────────────────────────────────────────────────
  const timerRef = useRef(0)
  const pendingRef = useRef(null)
  const lastSentAtRef = useRef(0)
  // 지금 고른 전환 시간. 전송 함수가 매번 최신 값을 봐야 해서 ref로 둔다.
  const fadeMsRef = useRef(FADES[1].ms)
  useEffect(() => {
    fadeMsRef.current = FADES.find((f) => f.id === fadeId)?.ms ?? 0
  }, [fadeId])

  const emit = useCallback((payload) => {
    lastSentAtRef.current = Date.now()
    send('CONTROL_SET_LIGHT', { ...payload, duration_ms: fadeMsRef.current })
  }, [send])

  /**
   * @param {boolean} live 드래그 중인가. 손을 뗀 확정값이면 false.
   */
  const pushLight = useCallback((nextRgb, nextBrightness, live = false) => {
    const payload = { color: nextRgb, brightness: nextBrightness }
    pendingRef.current = payload
    window.clearTimeout(timerRef.current)

    // 전환이 짧을 때만 드래그를 따라간다. 길게 잡아뒀으면 중간값을 보내는 순간
    // 페이드가 매번 새로 시작해 정작 보려던 긴 전환이 안 보인다.
    if (live && fadeMsRef.current <= LIVE_FOLLOW_MAX_MS) {
      if (Date.now() - lastSentAtRef.current >= LIVE_THROTTLE_MS) {
        emit(payload)
        return
      }
    }
    timerRef.current = window.setTimeout(() => {
      if (pendingRef.current) emit(pendingRef.current)
    }, SEND_DEBOUNCE_MS)
  }, [emit])

  useEffect(() => () => window.clearTimeout(timerRef.current), [])

  // 들어오자마자 현재 슬라이더 값으로 한 번 맞춘다. 안 그러면 화면은 백색을
  // 가리키는데 방은 직전 상태 그대로라 둘이 어긋난 채로 시작한다.
  const primedRef = useRef(false)
  useEffect(() => {
    if (!connected || primedRef.current) return
    primedRef.current = true
    send('CONTROL_SET_LIGHT', { color: DEFAULT_RGB, brightness: DEFAULT_BRIGHTNESS })
  }, [connected, send])

  const pickColor = (nextRgb) => {
    setRgb(nextRgb)
    pushLight(nextRgb, brightness)
  }

  // onChange는 드래그 중 계속 불린다. 확정은 손을 뗄 때(onPointerUp) 한 번 더 보낸다 —
  // 스로틀에 걸려 마지막 값이 안 나갔을 수 있어서, 이게 없으면 방이 슬라이더보다
  // 조금 앞이나 뒤에서 멈춘다.
  const changeBrightness = (value) => {
    const v = Number(value)
    setBrightness(v)
    pushLight(rgb, v, true)
  }

  const commitBrightness = () => pushLight(rgb, brightness, false)

  // ── 연출 버튼 ────────────────────────────────────────────────────────────
  const busyTimerRef = useRef(0)
  useEffect(() => () => window.clearTimeout(busyTimerRef.current), [])

  const fireCue = (cue) => {
    if (busyCue) return
    send('CONTROL_CUE', { cue: cue.id })
    setBusyCue(cue.id)
    // 백엔드가 알려준 길이만큼 잠근다. 여기서 숫자를 따로 갖고 있으면 연출
    // 길이를 바꿨을 때 화면만 옛 길이로 잠긴다.
    window.clearTimeout(busyTimerRef.current)
    busyTimerRef.current = window.setTimeout(
      () => setBusyCue(null),
      (cue.duration_ms || 2000) + 150,
    )
  }

  const swatchActive = (s) => s.rgb.every((v, i) => v === rgb[i])

  return (
    <div className="ctl-root">
      <GameTopBar
        theme="yacht"
        title="컨트롤"
        send={send}
        connected={connected}
        onExit={onExit}
        showStrategy={false}
      />

      {/* 두 칸으로 나눈다. 세로로 쌓으면 태블릿 높이(800px 안팎)를 넘겨
          스크롤이 생기는데, 조작판이 스크롤되면 버튼을 찾느라 화면을 밀게 된다. */}
      <div className="ctl-body">
        <div className="ctl-col ctl-col-left">
          {/* 지금 방이 무슨 색인지. 슬라이더 숫자보다 이게 먼저 읽힌다. */}
          <section className="ctl-panel ctl-preview" aria-label="현재 조명">
            <span className="ctl-eyebrow">지금 조명</span>
            <div
              className="ctl-orb"
              style={{
                background: rgbCss(rgb),
                // 0%면 완전히 꺼진 것으로 보여야 한다. 화면과 방이 어긋나면 안 된다.
                opacity: brightness === 0 ? 0.08 : 0.3 + (brightness / 100) * 0.7,
              }}
            />
            <b className="ctl-preview-val">{brightness === 0 ? '꺼짐' : `${brightness}%`}</b>
            <span className="ctl-preview-rgb">
              {rgb[0]}, {rgb[1]}, {rgb[2]}
            </span>
          </section>

          <section className="ctl-panel ctl-bright">
            <h2 className="ctl-h">밝기</h2>
            <div className="ctl-slider-row">
              <input
                type="range"
                min="0"
                max="100"
                step="1"
                value={brightness}
                onChange={(e) => changeBrightness(e.target.value)}
                onPointerUp={commitBrightness}
                onKeyUp={commitBrightness}
                aria-label="밝기"
                style={{ '--pct': `${brightness}%` }}
              />
              <span className="ctl-slider-val">{brightness}</span>
            </div>

            <h2 className="ctl-h ctl-h-sub">전환 시간</h2>
            <div className="ctl-fades" role="group" aria-label="전환 시간">
              {FADES.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  className={`ctl-fade${fadeId === f.id ? ' on' : ''}`}
                  onClick={() => setFadeId(f.id)}
                  aria-pressed={fadeId === f.id}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </section>
        </div>

        <div className="ctl-col ctl-col-right">
          <section className="ctl-panel ctl-colors">
            <h2 className="ctl-h">바탕 색</h2>
            <div className="ctl-swatches">
              {SWATCHES.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className={`ctl-swatch${swatchActive(s) ? ' on' : ''}`}
                  style={{ '--sw': rgbCss(s.rgb) }}
                  onClick={() => pickColor(s.rgb)}
                  aria-pressed={swatchActive(s)}
                  title={s.label}
                >
                  <span className="ctl-swatch-dot" />
                  <span className="ctl-swatch-label">{s.label}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="ctl-panel ctl-cue-panel">
            <h2 className="ctl-h">연출</h2>
            <div className="ctl-cues">
              {cues.length === 0 && (
                <div className="ctl-empty">
                  {connected ? '연출 목록을 받는 중…' : '서버에 연결하는 중…'}
                </div>
              )}
              {cues.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={`ctl-cue${busyCue === c.id ? ' running' : ''}`}
                  onClick={() => fireCue(c)}
                  disabled={Boolean(busyCue) || !connected}
                >
                  <span className="ctl-cue-label">{c.label}</span>
                  <span className="ctl-cue-dur">
                    {busyCue === c.id ? '재생 중' : `${(c.duration_ms / 1000).toFixed(1)}초`}
                  </span>
                </button>
              ))}
            </div>
            <p className="ctl-foot">
              연출이 끝나면 맞춘 색으로 돌아옵니다. 나가면 조명이 원래대로 됩니다.
            </p>
          </section>
        </div>
      </div>

      <style>{CSS}</style>
    </div>
  )
}

const CSS = `
  /* 화면에 고정한다. 조작판이 스크롤되면 버튼을 찾느라 화면을 밀게 되고,
     연출 버튼은 즉시 눌러야 하는 물건이라 그 한 동작이 그대로 늦어진다. */
  .ctl-root {
    position: absolute; inset: 0;
    background: var(--bg);
    color: var(--fg);
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }
  .ctl-body {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: minmax(260px, 340px) 1fr;
    gap: 16px;
    padding: 68px 24px 20px;
  }
  .ctl-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; }

  .ctl-panel {
    padding: 18px 20px;
    background: var(--bg-surface);
    border: 1px solid var(--border-soft);
    border-radius: var(--radius-xl);
    min-height: 0;
  }
  .ctl-h {
    margin: 0 0 12px;
    font-size: 12px; font-weight: 700;
    letter-spacing: 0.1em;
    color: var(--fg-mute);
    text-transform: uppercase;
  }

  /* ── 현재 조명 ─────────────────────────────────────────── */
  .ctl-preview {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    text-align: center;
  }
  .ctl-eyebrow {
    font-size: 11px; font-weight: 700;
    letter-spacing: 0.14em;
    color: var(--fg-mute);
    text-transform: uppercase;
  }
  .ctl-orb {
    /* 남는 세로를 채우되 정사각을 유지한다. 화면 높이가 달라도 원이 찌그러지지 않는다. */
    width: min(58%, 190px);
    aspect-ratio: 1;
    border-radius: 50%;
    box-shadow: 0 0 52px -8px currentColor;
    transition: background 260ms ease, opacity 260ms ease;
  }
  .ctl-preview-val {
    font-size: clamp(26px, 3.4vw, 38px);
    font-weight: 750;
    letter-spacing: -0.02em;
    font-variant-numeric: tabular-nums;
    line-height: 1.1;
  }
  .ctl-preview-rgb {
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 12.5px;
    color: var(--fg-mute);
    font-variant-numeric: tabular-nums;
  }

  /* ── 밝기 ──────────────────────────────────────────────── */
  .ctl-bright { flex-shrink: 0; }
  .ctl-slider-row { display: flex; align-items: center; gap: 16px; }
  .ctl-slider-row input[type="range"] {
    flex: 1;
    min-width: 0;
    appearance: none;
    height: 8px;
    border-radius: 999px;
    background: linear-gradient(
      to right,
      var(--accent) 0%, var(--accent) var(--pct),
      var(--bg-elev) var(--pct), var(--bg-elev) 100%
    );
    cursor: pointer;
  }
  .ctl-slider-row input[type="range"]::-webkit-slider-thumb {
    appearance: none;
    width: 26px; height: 26px;
    border-radius: 50%;
    background: var(--fg);
    border: 3px solid var(--bg-surface);
    box-shadow: 0 1px 6px rgba(0,0,0,0.3);
    cursor: grab;
  }
  .ctl-slider-row input[type="range"]:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
  .ctl-slider-val {
    min-width: 42px; text-align: right;
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 18px; font-weight: 700;
    font-variant-numeric: tabular-nums;
  }

  /* ── 전환 시간 ─────────────────────────────────────────── */
  .ctl-h-sub { margin-top: 18px; }
  .ctl-fades { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
  .ctl-fade {
    appearance: none;
    padding: 9px 4px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border-soft);
    background: var(--bg-elev);
    color: var(--fg-mute);
    font-family: inherit; font-size: 13px; font-weight: 700;
    font-variant-numeric: tabular-nums;
    cursor: pointer;
    transition: border-color 130ms ease, background 130ms ease, color 130ms ease;
  }
  .ctl-fade:hover { border-color: var(--fg-faint); background: var(--bg-hover); }
  .ctl-fade.on {
    border-color: var(--accent);
    background: color-mix(in oklch, var(--accent) 16%, var(--bg-elev));
    color: var(--fg);
  }
  .ctl-fade:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

  /* ── 색 ────────────────────────────────────────────────── */
  /* 남는 세로는 색 패널이 가져간다. 스와치가 10개라 늘어날 여지가 있고,
     연출 버튼은 상한이 있어 더 커지지 않는다. */
  .ctl-colors {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .ctl-swatches {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    grid-auto-rows: minmax(44px, 78px);
    align-content: center;
    gap: 8px;
  }
  .ctl-swatch {
    appearance: none;
    display: flex; align-items: center; gap: 8px;
    padding: 10px 11px;
    min-width: 0;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border-soft);
    background: var(--bg-elev);
    color: var(--fg);
    font-family: inherit; font-size: 13px; font-weight: 600;
    cursor: pointer;
    transition: border-color 130ms ease, background 130ms ease;
  }
  .ctl-swatch:hover { border-color: var(--fg-faint); background: var(--bg-hover); }
  .ctl-swatch.on { border-color: var(--accent); background: var(--bg-hover); }
  .ctl-swatch:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .ctl-swatch-dot {
    width: 18px; height: 18px;
    border-radius: 50%;
    background: var(--sw);
    flex-shrink: 0;
    /* 흰 스와치가 밝은 배경에서 사라지지 않도록 테두리를 항상 둔다. */
    box-shadow: inset 0 0 0 1px rgba(0,0,0,0.22);
  }
  .ctl-swatch-label { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  /* ── 연출 ──────────────────────────────────────────────── */
  .ctl-cue-panel {
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
  }
  .ctl-cues {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    /* 높이 상한을 둔다. 남는 세로를 그대로 먹이면 버튼 하나가 400px을 넘어
       "판" 처럼 보이고, 누를 곳이 어디인지 오히려 흐려진다. 아래 한계 안에서는
       화면이 커질수록 커져 손가락으로 누르기 좋아진다. */
    grid-auto-rows: minmax(96px, 150px);
    gap: 10px;
  }
  .ctl-cue {
    appearance: none;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 4px;
    padding: 12px;
    min-width: 0;
    border-radius: var(--radius-md, 12px);
    border: 1px solid var(--border);
    background: var(--bg-elev);
    color: var(--fg);
    font-family: inherit;
    cursor: pointer;
    transition: border-color 130ms ease, background 130ms ease, transform 130ms ease;
  }
  .ctl-cue:hover:not(:disabled) {
    border-color: var(--accent);
    background: var(--bg-hover);
    transform: translateY(-2px);
  }
  .ctl-cue:active:not(:disabled) { transform: translateY(0); }
  .ctl-cue:disabled { opacity: 0.4; cursor: not-allowed; }
  .ctl-cue:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .ctl-cue.running {
    opacity: 1;
    border-color: var(--accent);
    background: color-mix(in oklch, var(--accent) 16%, var(--bg-elev));
  }
  .ctl-cue-label {
    font-size: clamp(15px, 1.5vw, 19px);
    font-weight: 700;
    letter-spacing: -0.01em;
    white-space: nowrap;
  }
  .ctl-cue-dur {
    font-size: 12px;
    color: var(--fg-mute);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .ctl-cue.running .ctl-cue-dur { color: var(--accent); font-weight: 600; }

  .ctl-empty {
    grid-column: 1 / -1;
    display: grid; place-items: center;
    color: var(--fg-mute);
    font-size: 14px;
    border: 1px dashed var(--border);
    border-radius: var(--radius-sm);
  }

  .ctl-foot {
    flex-shrink: 0;
    margin: 12px 0 0;
    text-align: center;
    font-size: 12.5px;
    color: var(--fg-mute);
  }

  /* 좁아지면 한 칸으로. 색과 연출은 두 줄로 접힌다. */
  @media (max-width: 900px) {
    .ctl-body { grid-template-columns: 1fr; }
    .ctl-orb { width: min(34%, 120px); }
    .ctl-swatches { grid-template-columns: repeat(3, 1fr); }
    .ctl-cues { grid-template-columns: repeat(3, 1fr); }
  }

  @media (prefers-reduced-motion: reduce) {
    .ctl-orb, .ctl-cue, .ctl-swatch { transition: none; }
  }
`
