import { useEffect, useRef, useState } from 'react'
import { IconUser, IconVolume, IconCheck, IconChevronUp } from './Icons'

/**
 * 페르소나 얼굴. 파일이 없으면 기본 아이콘으로 떨어진다.
 *
 * 폴더 이름이 `personas`가 아니라 `persona-icons`인 이유: 백엔드에 `GET
 * /personas`가 있어서, 같은 이름을 쓰면 `/personas/shagal.png` 요청이
 * 프록시를 타고 그 API로 가 404가 된다.
 *
 * 없는 파일을 미리 알 방법이 없으므로 onError로 판정한다. 페르소나를
 * 추가하고 그림을 아직 안 그렸을 때 얼굴만 비고 목록은 그대로 뜬다.
 */
function PersonaFace({ id, size }) {
  const [failed, setFailed] = useState(false)
  if (failed || !id) return <IconUser size={Math.round(size * 0.55)} />
  return (
    <img
      className="pp-face"
      src={`/persona-icons/${id}.png`}
      alt=""
      width={size}
      height={size}
      onError={() => setFailed(true)}
    />
  )
}

/**
 * 진행자(페르소나) 선택.
 *
 * 시스템의 목소리를 고르는 자리다. 네 에이전트가 한 사람으로 들려야 하므로
 * 목소리는 페르소나가 소유하고(core/persona.py), 여기서 고른 하나가 게임
 * 전체의 말투와 화면 문구를 함께 정한다.
 *
 * **고르는 것과 들어보는 것을 갈라놓았다.** 전환은 캐시를 통째로 다시 데우는
 * 일이라 몇십 초가 걸린다. 넷을 훑어보는 동안 매번 그걸 하면 고를 수가 없어서,
 * 스피커 버튼은 목소리만 갈아끼워 한 문장을 들려주고 전환하지 않는다.
 *
 * 목록이 위로 열리는 이유는 이 버튼이 화면 맨 아래 줄에 있기 때문이다.
 * 아래로 열면 화면 밖으로 나간다.
 */

export default function PersonaPicker({ send, connected }) {
  const [personas, setPersonas] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [open, setOpen] = useState(false)
  // 미리듣기를 누른 항목. 요청은 보냈지만 소리가 나기까지 합성 시간이 걸려서,
  // 아무 반응이 없으면 눌리지 않은 줄 알고 계속 누르게 된다.
  const [previewing, setPreviewing] = useState(null)
  // 처음 온 사람에게 "여기서 바꿀 수 있다"를 한 번 알려준다. 한 번 열어보면
  // 다시 뜨지 않는다 — 아는 사람에게 계속 말을 거는 것은 잔소리다.
  const [hint, setHint] = useState(false)
  const seenRef = useRef(false)
  const rootRef = useRef(null)

  useEffect(() => {
    let alive = true
    fetch('/personas')
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        if (!alive || !data?.personas) return
        setPersonas(data.personas)
        setActiveId(data.personas.find(p => p.active)?.id ?? null)
      })
      // 목록을 못 받으면 버튼만 조용히 사라진다. 진행자는 서버 기본값으로
      // 이미 정해져 있어서 게임은 그대로 굴러간다.
      .catch(() => {})
    return () => { alive = false }
  }, [])

  // 바깥을 누르면 닫는다. 목록이 열린 채로 남아 시작 버튼을 가리면 곤란하다.
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

  useEffect(() => {
    if (previewing === null) return undefined
    const timer = setTimeout(() => setPreviewing(null), 2600)
    return () => clearTimeout(timer)
  }, [previewing])

  /**
   * 안내 말풍선을 한 박자 늦게 띄운다.
   *
   * 화면이 뜨자마자 같이 나오면 로딩의 일부처럼 보여 그냥 지나친다. 좌석
   * 등록을 마치고 시선이 아래 버튼으로 내려올 즈음에 나타나야 읽힌다.
   */
  useEffect(() => {
    if (seenRef.current || personas.length === 0) return undefined
    const show = setTimeout(() => setHint(true), 1400)
    const hide = setTimeout(() => setHint(false), 11000)
    return () => { clearTimeout(show); clearTimeout(hide) }
  }, [personas.length])

  // 한 번이라도 열어봤으면 안내를 거둔다.
  useEffect(() => {
    if (!open) return
    seenRef.current = true
    setHint(false)
  }, [open])

  if (personas.length === 0) return null

  const active = personas.find(p => p.id === activeId) || personas[0]

  const choose = (id) => {
    // 화면은 누른 즉시 바뀐다. 서버는 목소리 캐시를 다시 데우느라 몇십 초를
    // 쓰는데, 그동안 선택이 반영되지 않으면 눌리지 않은 것처럼 보인다.
    setActiveId(id)
    setOpen(false)
    send?.('set_persona', { persona_id: id })
  }

  const preview = (e, id) => {
    e.stopPropagation()   // 미리듣기가 선택으로 번지지 않게
    setPreviewing(id)
    send?.('preview_persona', { persona_id: id })
  }

  return (
    <div className="pp-root" ref={rootRef}>
      {open && (
        <div className="pp-pop" role="listbox" aria-label="진행자 선택">
          <div className="pp-pop-hd">진행자</div>
          {personas.map(p => (
            <button
              key={p.id}
              className={`pp-item ${p.id === active.id ? 'sel' : ''}`}
              role="option"
              aria-selected={p.id === active.id}
              onClick={() => choose(p.id)}
            >
              <span className="pp-item-av"><PersonaFace id={p.id} size={40} /></span>
              <span className="pp-item-txt">
                <span className="pp-item-name">
                  {p.display_name}
                  {p.id === active.id && <IconCheck size={14} />}
                </span>
                <span className="pp-item-desc">{p.description}</span>
              </span>
              <span
                className={`pp-listen ${previewing === p.id ? 'on' : ''}`}
                role="button"
                tabIndex={0}
                aria-label={`${p.display_name} 미리듣기`}
                title="미리듣기"
                onClick={(e) => preview(e, p.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') preview(e, p.id)
                }}
              >
                <IconVolume size={16} />
              </span>
            </button>
          ))}
        </div>
      )}

      {hint && !open && (
        <div className="pp-hint" role="note">
          여기에서 게임 진행자를 바꿀 수 있어요
          <span className="pp-hint-tail" />
        </div>
      )}

      <button
        className={`pp-btn ${open ? 'open' : ''} ${hint ? 'hint' : ''}`}
        onClick={() => setOpen(o => !o)}
        disabled={!connected}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={`진행자 · ${active.display_name} — 눌러서 바꾸기`}
      >
        <PersonaFace id={active.id} size={56} />
        {/* 누르면 위로 열린다는 표시. 얼굴만 있으면 그냥 상태 표시로 읽힌다. */}
        <span className="pp-badge" aria-hidden="true">
          <IconChevronUp size={13} />
        </span>
      </button>

      <style>{`
        .pp-root { position: relative; display: flex; align-items: center; }

        /* 정사각형이 아닌 그림이 들어와도 찌그러지지 않게 잘라서 채운다.
           원형 마스크는 감싸는 쪽(.pp-btn/.pp-item-av)이 이미 걸고 있다.

           배경이 흰색인 이유: 캐릭터 그림이 투명 PNG라 어두운 화면 위에
           그대로 얹으면 얼굴만 허공에 뜬 것처럼 보인다. 흰 원 위에 올려야
           스티커처럼 한 덩어리로 읽힌다. */
        .pp-face {
          width: 100%; height: 100%;
          object-fit: cover;
          border-radius: 50%;
          display: block;
          background: #fff;
        }

        /* 원형. 옆의 알약형 시작 버튼과 형태로 구별된다 —
           하나는 "설정", 하나는 "다음으로 간다". */
        .pp-btn {
          appearance: none; cursor: pointer;
          width: 56px; height: 56px;
          border-radius: 50%;
          border: 1px solid var(--border);
          /* 캐릭터 그림이 투명 PNG라 흰 바탕을 깔아야 얼굴이 또렷하다.
             그림이 없을 때(폴백 아이콘)도 같은 흰 원이라 생김새가 일관된다. */
          background: #fff;
          color: #7a7a7a;
          display: flex; align-items: center; justify-content: center;
          font-family: inherit;
          transition: border-color 160ms ease, color 160ms ease, background 160ms ease;
          flex: 0 0 auto;
          padding: 0;
          /* 배지를 모서리에 걸기 위한 기준. overflow는 숨기지 않는다 —
             숨기면 배지가 잘린다. 얼굴은 .pp-face가 스스로 원형으로 자른다. */
          position: relative;
        }
        /* 배경은 흰색으로 고정한다. 호버로 바꾸면 얼굴 뒤 색이 출렁여
           그림이 흔들리는 것처럼 보인다. 테두리로만 반응한다. */
        .pp-btn:hover:not(:disabled) {
          border-color: var(--accent);
          box-shadow: 0 0 0 3px color-mix(in oklch, var(--accent) 22%, transparent);
        }
        .pp-btn.open {
          border-color: var(--accent);
          color: var(--accent);
        }
        .pp-btn:disabled { opacity: 0.45; cursor: not-allowed; }
        /* 안내가 떠 있는 동안만 테두리가 숨을 쉰다. 늘 움직이면 화면이
           산만해지고, 정작 급한 것(카메라 오류 등)이 묻힌다. */
        .pp-btn.hint {
          border-color: var(--accent);
          animation: pp-breathe 1900ms ease-in-out infinite;
        }
        @keyframes pp-breathe {
          0%, 100% { box-shadow: 0 0 0 0 color-mix(in oklch, var(--accent) 45%, transparent); }
          50%      { box-shadow: 0 0 0 7px color-mix(in oklch, var(--accent) 0%, transparent); }
        }

        /* 누르면 열린다는 표시. 얼굴 위에 얹지 않고 모서리에 붙여, 캐릭터를
           가리지 않으면서 "이건 조작하는 것"이라는 신호만 준다. */
        .pp-badge {
          position: absolute;
          right: -1px; bottom: -1px;
          width: 21px; height: 21px;
          border-radius: 50%;
          background: var(--accent);
          color: #14110d;
          border: 2px solid var(--bg-app, #14110d);
          display: flex; align-items: center; justify-content: center;
        }

        /* 말풍선. 버튼 위로 띄우되 목록이 열리는 자리와 겹치지 않게
           안내가 떠 있는 동안에는 목록이 닫혀 있다. */
        .pp-hint {
          position: absolute;
          bottom: calc(100% + 14px);
          right: -4px;
          width: max-content;
          max-width: 260px;
          padding: 10px 14px;
          border-radius: 12px;
          background: var(--accent);
          color: #14110d;
          font-size: 13.5px; font-weight: 600;
          line-height: 1.4;
          box-shadow: 0 10px 24px rgba(0,0,0,0.35);
          pointer-events: none;
          z-index: 51;
          animation: pp-hint-in 320ms cubic-bezier(.2,.9,.25,1.1) both;
        }
        @keyframes pp-hint-in {
          from { opacity: 0; transform: translateY(6px) scale(0.96); }
          to   { opacity: 1; transform: none; }
        }
        /* 꼬리가 버튼을 가리켜야 무엇에 대한 말인지 분명해진다. */
        .pp-hint-tail {
          position: absolute;
          right: 24px; bottom: -5px;
          width: 12px; height: 12px;
          background: var(--accent);
          transform: rotate(45deg);
          border-radius: 2px;
        }

        /* 화면 맨 아래 줄이라 위로 연다.
           오른쪽 끝을 버튼에 맞추고 왼쪽으로 펼친다 — 이 버튼은 항상 화면
           오른쪽 끝에 붙어 있어서, 왼쪽 기준으로 열면 목록이 화면 밖으로 나간다. */
        .pp-pop {
          position: absolute;
          bottom: calc(100% + 12px);
          right: 0;
          width: 360px;
          max-height: min(60vh, 420px);
          overflow-y: auto;
          background: var(--bg-surface);
          border: 1px solid var(--border);
          border-radius: 14px;
          box-shadow: 0 16px 40px rgba(0,0,0,0.38);
          padding: 6px;
          z-index: 50;
          animation: pp-in 160ms cubic-bezier(.2,.8,.25,1) both;
        }
        @keyframes pp-in {
          from { opacity: 0; transform: translateY(8px) scale(0.98); }
          to   { opacity: 1; transform: none; }
        }
        .pp-pop-hd {
          padding: 8px 10px 6px;
          font-size: 12px; font-weight: 700;
          letter-spacing: 0.08em; text-transform: uppercase;
          color: var(--fg-mute);
        }

        .pp-item {
          appearance: none; width: 100%;
          display: flex; align-items: center; gap: 12px;
          padding: 10px;
          border: 0; border-radius: 10px;
          background: transparent;
          color: var(--fg);
          text-align: left;
          cursor: pointer;
          font-family: inherit;
        }
        .pp-item:hover { background: var(--bg-hover); }
        .pp-item.sel { background: color-mix(in oklch, var(--accent) 12%, transparent); }

        .pp-item-av {
          flex: 0 0 auto;
          width: 40px; height: 40px;
          border-radius: 50%;
          background: #fff;
          border: 1px solid var(--border-soft);
          display: flex; align-items: center; justify-content: center;
          color: var(--fg-soft);
          overflow: hidden;
        }
        .pp-item.sel .pp-item-av {
          border-color: var(--accent);
          color: var(--accent);
        }

        .pp-item-txt { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
        .pp-item-name {
          font-size: 15px; font-weight: 600;
          display: flex; align-items: center; gap: 6px;
          color: var(--fg);
        }
        .pp-item.sel .pp-item-name { color: var(--accent); }
        .pp-item-desc {
          font-size: 12.5px; line-height: 1.45;
          color: var(--fg-mute);
          text-wrap: pretty;
        }

        .pp-listen {
          flex: 0 0 auto;
          width: 32px; height: 32px;
          border-radius: 50%;
          border: 1px solid var(--border-soft);
          background: var(--bg-surface);
          color: var(--fg-mute);
          display: flex; align-items: center; justify-content: center;
          cursor: pointer;
          transition: color 140ms ease, border-color 140ms ease;
        }
        .pp-listen:hover { color: var(--fg); border-color: var(--border); }
        /* 눌렀다는 것만 알리면 된다. 합성이 끝나 소리가 날 때까지의 빈 구간을
           메우는 표시라, 실제 재생 종료와 맞출 필요는 없다. */
        .pp-listen.on {
          color: var(--accent);
          border-color: var(--accent);
          animation: pp-pulse 900ms ease-in-out infinite;
        }
        @keyframes pp-pulse { 50% { opacity: 0.45; } }
      `}</style>
    </div>
  )
}
