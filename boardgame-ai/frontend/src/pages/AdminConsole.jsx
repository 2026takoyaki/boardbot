import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'
import { audio as audioApi, useAudioPlayer } from '../hooks/useAudioPlayer'
import GameTopBar from '../components/common/GameTopBar'

/**
 * 관리자 콘솔 — 발표용 연출 버튼.
 *
 * 발표에서 시스템을 보여주려면 그 순간까지 게임을 굴려야 한다. 늑대인간 밤을
 * 보여주려면 사람을 앉히고 카드를 돌리고 역할 안내를 지나야 하는데, 발표
 * 시간에 그럴 자리가 없다. 여기서는 **그 순간만** 버튼 하나로 재현한다.
 *
 * 버튼 하나에 조명·목소리·효과음이 함께 나간다. 무엇이 나가는지는 백엔드가
 * 정한다(backend/show_acts.py) — 목록을 화면이 갖고 있으면 연출을 하나 더할
 * 때 두 곳을 고쳐야 하고, 한쪽만 고치면 눌러도 아무 일이 없는 버튼이 생긴다.
 *
 * 컨트롤 세션과 같은 소켓을 쓴다. 나갈 때 조명을 되돌리는 일은 백엔드가 한다.
 */

// 연출이 도는 동안 버튼을 잠근다. 다시 누르면 조명이 중간에 처음부터 다시
// 시작해서, 정작 보여주려던 장면이 발표장에서 깨진다.
//
// 잠금을 푸는 것은 **목소리가 끝났을 때**다. 시간을 재서 풀지 않는 이유는
// 백엔드가 연출의 끝을 정확히 모르기 때문이다(효과음 길이를 몰라서 — 아래
// playOverlappingSfx 참고). 재생기가 끝을 알려주므로 그걸 쓴다.
//
// 아래는 안전망일 뿐이다. 목소리가 아예 안 나오는 경우(음원 없음)에도 버튼이
// 영영 잠기지 않게 한다.
const LOCK_FAILSAFE_MS = 15000


export default function AdminConsole({ onExit }) {
  const [acts, setActs] = useState([])
  const [running, setRunning] = useState(null)
  // 소등 스위치. 켜면 방이 꺼지고 연출 버튼이 전부 잠긴다.
  //
  // 잠그는 이유: 연출은 저마다 방을 특정 색으로 몰고 간다. 소등한 채로 눌리면
  // 방이 곧바로 밝아져서, 스위치는 켜져 있는데 방은 켜져 있는 상태가 된다.
  // 화면과 방이 어긋나는 것이 이 콘솔에서 제일 나쁘다.
  const [blackout, setBlackout] = useState(false)

  // 지금 도는 연출의 겹침 값. 효과음 메시지에는 어느 연출인지 안 적혀 있어서
  // (연출은 한 번에 하나만 도므로) 누를 때 여기 적어 둔다.
  const overlapRef = useRef(0)
  const sfxRef = useRef(null)
  const sendRef = useRef(null)

  /**
   * 효과음은 공용 재생기를 거치지 않고 여기서 직접 튼다.
   *
   * 공용 재생기는 Audio 하나를 돌려쓰며 한 번에 하나만 재생하고, 다음 항목은
   * 재생 완료 통보(ack)를 받아야 나간다. 그래서 그 길로는 효과음과 목소리가
   * 절대 겹칠 수 없다 — 늑대 울음이 완전히 잦아든 뒤에야 진행자가 입을 연다.
   *
   * 대신 여기서 따로 틀고, **끝나기 조금 전에 완료 통보를 보내** 목소리를
   * 일찍 끌어온다. 울음 끝물에 말이 얹혀 한 덩어리로 들린다. 순서와 내용의
   * 주인은 여전히 백엔드다(backend/control_session.py).
   */
  const playOverlappingSfx = useCallback((url, playbackId) => {
    sfxRef.current?.stop()
    let acked = false
    let timer = 0
    const ack = () => {
      if (acked) return
      acked = true
      window.clearTimeout(timer)
      sendRef.current?.('audio_ack', { playback_id: playbackId, status: 'played' })
    }
    const el = new Audio(url)
    el.volume = audioApi.volumes().sfx
    // 길이를 알아야 언제 통보할지 정할 수 있다. 파일이 없거나(등록만 해 둔
    // 효과음) 못 읽으면 곧바로 통보해서 목소리가 막히지 않게 한다.
    el.addEventListener('loadedmetadata', () => {
      const ms = Number.isFinite(el.duration) ? el.duration * 1000 : 0
      timer = window.setTimeout(ack, Math.max(0, ms - overlapRef.current))
    })
    el.addEventListener('ended', ack)
    el.addEventListener('error', ack)
    el.play().catch(ack)
    sfxRef.current = { stop: () => { try { el.pause() } catch { /* 이미 끝남 */ } ack() } }
  }, [])

  const onAudioMessage = useCallback((msg) => {
    if (msg.msg_type === 'sfx_play') {
      const { audio_url, playback_id } = msg.payload || {}
      if (audio_url && playback_id) {
        playOverlappingSfx(audio_url, playback_id)
        return
      }
    }
    audioApi.enqueue(msg)
  }, [playOverlappingSfx])

  const { send, connected, messages } = useWebSocket('/ws/control', { onAudioMessage })
  useAudioPlayer(send)
  useEffect(() => { sendRef.current = send }, [send])
  useEffect(() => () => sfxRef.current?.stop(), [])

  const hello = useMemo(
    () => messages.find((m) => m.msg_type === 'hello')?.payload,
    [messages],
  )
  useEffect(() => {
    if (hello?.acts) setActs(hello.acts)
  }, [hello])

  // 바탕 조명의 색·밝기·페이드는 전부 백엔드가 갖는다(bulb/scenes.py). 여기서
  // 숫자를 들고 슬라이더 경로로 보내면 색온도가 빠져 전구마다 흰색이 갈린다.
  const setRoom = useCallback((dark) => send('CONTROL_SHOW_REST', { dark }), [send])
  const restLight = useCallback(() => setRoom(false), [setRoom])

  const toggleBlackout = () => {
    const next = !blackout
    setBlackout(next)
    setRoom(next)
  }

  /**
   * 들어오면 방을 바탕으로 맞춘다.
   *
   * 로비와 같은 백색이라 들어오는 순간에는 아무 일도 일어나지 않는다. 그게
   * 목적이다 — 관리자 화면에 들어갔다는 이유로 무대가 먼저 바뀌면 안 된다.
   * 그래도 한 번 맞추는 이유는, 직전 연출이 방을 다른 색으로 두고 나갔을 수
   * 있어서다. 어디서 들어오든 같은 자리에서 시작해야 한다.
   */
  const primedRef = useRef(false)
  useEffect(() => {
    if (!connected || primedRef.current) return
    primedRef.current = true
    restLight()
  }, [connected, restLight])

  const lockRef = useRef(0)
  const unlockRef = useRef(null)
  useEffect(() => () => {
    window.clearTimeout(lockRef.current)
    unlockRef.current?.()
  }, [])

  const fire = (act) => {
    if (running || blackout) return
    overlapRef.current = act.voice_overlap_ms ?? 0
    send('CONTROL_SHOW', { act: act.id })
    setRunning(act.id)

    // 말이 끝나면 푼다. 소리가 꺼져 있으면(진행자 음량 0) 재생기가 건너뛰면서
    // 같은 신호를 보내므로, 그 경우에도 버튼은 제때 풀린다.
    unlockRef.current?.()
    unlockRef.current = audioApi.onNextTtsEnded(() => {
      unlockRef.current = null
      window.clearTimeout(lockRef.current)
      setRunning(null)
    })
    window.clearTimeout(lockRef.current)
    lockRef.current = window.setTimeout(() => {
      unlockRef.current?.()
      unlockRef.current = null
      setRunning(null)
    }, (act.duration_ms || 4000) + LOCK_FAILSAFE_MS)
  }

  return (
    // data-noclick: 이 화면에서는 공용 버튼 클릭음이 울리지 않는다(App.jsx).
    // 발표 중에 누르는 자리라, 클릭음이 그때마다 연출 소리 앞에 끼어든다.
    // 연출의 효과음은 그대로 나간다 — 막는 것은 UI 소리뿐이다.
    <div className="ac-root" data-noclick>
      <GameTopBar
        theme="werewolf"
        title="발표 연출"
        send={send}
        connected={connected}
        onExit={onExit}
        showStrategy={false}
      />

      <div className="ac-body">
        {/* 제목은 상단바가 이미 달고 있다. 여기서 한 번 더 쓰면 같은 말이
            두 줄 차지하고, 그만큼 버튼이 작아진다. */}
        <p className="ac-sub">
          누르면 조명·진행자 목소리·효과음이 함께 나갑니다. 실제 게임이 쓰는 연출 그대로입니다.
        </p>

        <div className="ac-grid">
          {acts.length === 0 && (
            <div className="ac-empty">
              {connected ? '연출 목록을 받는 중…' : '서버에 연결하는 중…'}
            </div>
          )}
          {acts.map((a) => (
            <button
              key={a.id}
              type="button"
              className={`ac-act${running === a.id ? ' running' : ''}`}
              onClick={() => fire(a)}
              disabled={Boolean(running) || !connected || blackout}
            >
              <div className="ac-act-hd">
                <span className="ac-act-label">{a.label}</span>
                <span className="ac-act-persona">{a.persona}</span>
              </div>
              <p className="ac-act-text">“{a.text}”</p>
              <div className="ac-act-ft">
                <span className="ac-act-hint">{a.hint}</span>
                <span className="ac-act-dur">
                  {running === a.id ? '재생 중' : `${(a.duration_ms / 1000).toFixed(1)}초`}
                </span>
              </div>
              {/* 음원이 없으면 조명과 자막만 나간다. 발표장에서 처음 알게 되면
                  늦으므로 누르기 전에 보이게 둔다. */}
              {a.has_voice === false && <span className="ac-act-warn">음원 없음</span>}
            </button>
          ))}
        </div>

        <div className="ac-foot">
          {/* 소등은 눌러서 켜고 끄는 **상태**다. 한 번 누르면 끝나는 동작으로
              보이면 안 된다 — 지금 잠겨 있다는 것이 버튼에 남아 있어야 위의
              연출들이 왜 안 눌리는지 알 수 있다. */}
          <button
            type="button"
            className={`ac-toggle${blackout ? ' on' : ''}`}
            onClick={toggleBlackout}
            disabled={!connected}
            aria-pressed={blackout}
          >
            <span className="ac-toggle-sw" aria-hidden><span className="ac-toggle-knob" /></span>
            소등
          </button>

          {/* 연출은 스스로 바탕으로 돌아온다. 그래도 되돌릴 자리를 두는 이유는
              연결이 끊기거나 소리가 꺼져 있어 끝 신호를 못 받는 경우다. */}
          <button
            type="button"
            className="ac-reset"
            onClick={restLight}
            disabled={!connected || blackout}
          >
            조명 원래대로
          </button>

          <span className="ac-foot-note">
            {blackout
              ? '소등 중입니다. 연출을 쓰려면 소등을 끄세요.'
              : '연출이 끝나면 조명이 알아서 돌아옵니다. 나가면 로비 조명으로 복귀합니다.'}
          </span>
        </div>
      </div>

      <style>{CSS}</style>
    </div>
  )
}

const CSS = `
  /* 화면에 고정한다. 발표 중에 스크롤해서 버튼을 찾는 일이 있으면 안 된다. */
  .ac-root {
    position: absolute; inset: 0;
    background: var(--bg);
    color: var(--fg);
    overflow: hidden;
    display: flex; flex-direction: column;
  }
  .ac-body {
    flex: 1; min-height: 0;
    display: flex; flex-direction: column;
    gap: 16px;
    padding: 66px 32px 22px;
  }

  .ac-sub { margin: 0; flex-shrink: 0; font-size: 14.5px; color: var(--fg-soft); }

  /* 전부 한 화면에 보여야 한다. 발표자가 다음 버튼을 눈으로 찾는 시간이
     그대로 발표의 빈 자리가 된다. */
  .ac-grid {
    flex: 1; min-height: 0;
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    grid-auto-rows: 1fr;
    gap: 14px;
  }
  /* 홀수 번째로 마지막에 남는 카드는 한 줄을 다 쓴다. 반쪽만 채우고 옆을
     비워두면 자리가 빠진 것처럼 보인다. 지금은 전략 조언이 그 자리인데,
     대사가 제일 길어서 넓은 카드가 마침 맞다. */
  .ac-act:last-child:nth-child(odd) { grid-column: 1 / -1; }

  .ac-act {
    position: relative;
    appearance: none;
    display: flex; flex-direction: column;
    gap: 10px;
    padding: 20px 22px;
    min-width: 0; min-height: 0;
    text-align: left;
    border: 1px solid var(--border);
    border-radius: var(--radius-xl);
    background: var(--bg-surface);
    color: var(--fg);
    font-family: inherit;
    cursor: pointer;
    transition: border-color 130ms ease, background 130ms ease, transform 130ms ease;
  }
  .ac-act:hover:not(:disabled) {
    border-color: var(--accent);
    background: var(--bg-elev);
    transform: translateY(-2px);
  }
  .ac-act:active:not(:disabled) { transform: translateY(0); }
  .ac-act:disabled { opacity: 0.42; cursor: not-allowed; }
  .ac-act:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
  .ac-act.running {
    opacity: 1;
    border-color: var(--accent);
    background: color-mix(in oklch, var(--accent) 14%, var(--bg-surface));
  }

  .ac-act-hd { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
  .ac-act-label { font-size: 21px; font-weight: 750; letter-spacing: -0.02em; }
  .ac-act-persona {
    font-size: 12px; font-weight: 700;
    padding: 3px 9px;
    border-radius: 999px;
    background: color-mix(in oklch, var(--accent) 15%, var(--bg-elev));
    color: color-mix(in oklch, var(--accent) 72%, var(--fg));
    white-space: nowrap;
  }

  /* 무엇이 나갈지 누르기 전에 읽혀야 한다. 발표자는 이 문장에 맞춰 다음 말을
     준비하므로, 자막이 아니라 대본에 가깝다. 그래서 카드의 주인공 자리를 주고
     남는 세로 한가운데에 앉힌다 — 위로 붙여두면 아래가 텅 빈 것으로 보인다. */
  .ac-act-text {
    margin: 0;
    flex: 1; min-height: 0;
    display: grid; align-content: center;
    font-size: clamp(16px, 1.4vw, 19px);
    line-height: 1.6;
    color: var(--fg);
    text-wrap: pretty;
    overflow: hidden;
  }

  .ac-act-ft {
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px;
    font-size: 12.5px;
  }
  .ac-act-hint { color: var(--fg-mute); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ac-act-dur { color: var(--fg-mute); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .ac-act.running .ac-act-dur { color: var(--accent); font-weight: 700; }

  .ac-act-warn {
    position: absolute; top: 14px; right: 16px;
    font-size: 11px; font-weight: 700;
    padding: 3px 8px;
    border-radius: 999px;
    background: color-mix(in oklch, var(--warn) 16%, transparent);
    color: var(--warn);
  }

  .ac-empty {
    grid-column: 1 / -1;
    display: grid; place-items: center;
    color: var(--fg-mute);
    font-size: 14px;
    border: 1px dashed var(--border);
    border-radius: var(--radius-xl);
  }

  .ac-foot {
    flex-shrink: 0;
    display: flex; align-items: center; gap: 14px;
  }
  .ac-reset {
    appearance: none;
    padding: 11px 18px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--bg-elev);
    color: var(--fg);
    font-family: inherit; font-size: 14px; font-weight: 650;
    cursor: pointer;
    transition: border-color 130ms ease, background 130ms ease;
  }
  .ac-reset:hover:not(:disabled) { border-color: var(--fg-faint); background: var(--bg-hover); }
  .ac-reset:disabled { opacity: 0.5; cursor: not-allowed; }
  .ac-foot-note { font-size: 13px; color: var(--fg-mute); min-width: 0; }

  /* 소등 스위치. 켜져 있는 동안 위의 연출이 전부 잠기므로, 지금 어느 쪽인지가
     멀리서도 읽혀야 한다 — 스위치 모양을 쓰는 이유다. */
  .ac-toggle {
    appearance: none;
    display: inline-flex; align-items: center; gap: 10px;
    padding: 10px 18px 10px 12px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--bg-elev);
    color: var(--fg);
    font-family: inherit; font-size: 14px; font-weight: 700;
    cursor: pointer;
    white-space: nowrap;
    transition: border-color 130ms ease, background 130ms ease, color 130ms ease;
  }
  .ac-toggle:hover:not(:disabled) { border-color: var(--fg-faint); background: var(--bg-hover); }
  .ac-toggle:disabled { opacity: 0.5; cursor: not-allowed; }
  .ac-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .ac-toggle.on {
    border-color: var(--accent);
    background: color-mix(in oklch, var(--accent) 18%, var(--bg-elev));
  }
  .ac-toggle-sw {
    width: 38px; height: 22px;
    flex-shrink: 0;
    border-radius: 999px;
    background: color-mix(in oklch, var(--fg-mute) 34%, transparent);
    position: relative;
    transition: background 180ms ease;
  }
  .ac-toggle.on .ac-toggle-sw { background: var(--accent); }
  .ac-toggle-knob {
    position: absolute; top: 3px; left: 3px;
    width: 16px; height: 16px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 3px rgba(0,0,0,0.4);
    transition: transform 180ms cubic-bezier(.2,.8,.25,1);
  }
  .ac-toggle.on .ac-toggle-knob { transform: translateX(16px); }

  /* 좁아지면 한 줄에 하나씩. 넷을 우겨넣으면 대본이 안 읽힌다. */
  @media (max-width: 860px) {
    .ac-grid { grid-template-columns: 1fr; }
    .ac-body { padding: 68px 20px 18px; }
  }

  @media (prefers-reduced-motion: reduce) {
    .ac-act, .ac-toggle, .ac-toggle-sw, .ac-toggle-knob { transition: none; }
  }
`
