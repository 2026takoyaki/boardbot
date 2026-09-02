import { useEffect, useRef, useState } from 'react'
import { IconClose, IconLock } from './Icons'

/**
 * 관리자 콘솔 앞에 세우는 비밀번호 창.
 *
 * **이건 보안이 아니다.** 비밀번호는 프론트엔드 번들 안에 그대로 들어 있고,
 * 백엔드는 관리자 소켓을 따로 막지 않는다. 애초에 이 시스템 전체가 시연장
 * 내부망에서 인증 없이 도는 물건이라, 여기만 진짜로 잠가봐야 얻는 것이 없다.
 *
 * 이 창이 막는 것은 **손이 미끄러지는 일**이다. 관리자 콘솔은 누르는 즉시 방
 * 조명이 통째로 바뀌고 스피커에서 소리가 난다. 시연 중에 태블릿을 만지던
 * 사람이 설정을 뒤지다 실수로 들어가면 그 순간 진행이 깨진다. 네 자리를
 * 요구하는 것만으로 그 실수는 사라진다.
 *
 * 그래서 기억해두지 않는다 — 들어갈 때마다 다시 묻는다.
 */
const PASSCODE = '0402'
const LENGTH = PASSCODE.length

export default function AdminGate({ onPass, onCancel }) {
  const [value, setValue] = useState('')
  const [wrong, setWrong] = useState(false)
  const inputRef = useRef(null)

  useEffect(() => {
    inputRef.current?.focus()
    const onKey = (e) => { if (e.key === 'Escape') onCancel?.() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onCancel])

  // 네 자리를 다 채우면 확인 버튼 없이 바로 통과시킨다. 자릿수가 정해져 있어
  // "다 넣었다"를 화면이 알 수 있고, 한 동작이라도 줄어야 한다.
  const change = (raw) => {
    const digits = raw.replace(/\D/g, '').slice(0, LENGTH)
    setValue(digits)
    if (wrong) setWrong(false)
    if (digits.length < LENGTH) return
    if (digits === PASSCODE) {
      onPass?.()
      return
    }
    setWrong(true)
    // 지우지 않으면 다음 시도가 앞 숫자에 이어 붙어 영영 안 맞는다.
    setValue('')
  }

  return (
    <div className="ag-veil" role="dialog" aria-modal="true" aria-label="관리자 확인">
      <div className={`ag-card${wrong ? ' wrong' : ''}`}>
        <button type="button" className="ag-x" onClick={onCancel} aria-label="닫기">
          <IconClose size={16} />
        </button>

        <span className="ag-ic" aria-hidden><IconLock size={22} /></span>
        <h2 className="ag-title">관리자 확인</h2>
        <p className="ag-sub">발표 연출 콘솔입니다. 비밀번호를 입력하세요.</p>

        {/* 점 네 개가 실제 칸이고, 입력은 그 위에 투명하게 덮인다.
            태블릿에서 숫자 자판이 뜨려면 진짜 input이 있어야 한다. */}
        <div className="ag-dots" aria-hidden>
          {Array.from({ length: LENGTH }, (_, i) => (
            <span key={i} className={`ag-dot${i < value.length ? ' on' : ''}`} />
          ))}
          <input
            ref={inputRef}
            className="ag-input"
            type="password"
            inputMode="numeric"
            autoComplete="off"
            value={value}
            onChange={(e) => change(e.target.value)}
            aria-label="비밀번호"
          />
        </div>

        <div className="ag-msg" role="status">
          {wrong ? '비밀번호가 다릅니다' : ' '}
        </div>
      </div>

      <style>{CSS}</style>
    </div>
  )
}

const CSS = `
  .ag-veil {
    position: fixed; inset: 0;
    z-index: 200;
    display: grid; place-items: center;
    background: rgba(0, 0, 0, 0.62);
    -webkit-backdrop-filter: blur(3px);
    backdrop-filter: blur(3px);
    animation: ag-fade 140ms ease both;
  }
  @keyframes ag-fade { from { opacity: 0 } to { opacity: 1 } }

  .ag-card {
    position: relative;
    width: min(360px, calc(100vw - 48px));
    padding: 30px 28px 22px;
    display: flex; flex-direction: column; align-items: center;
    border: 1px solid var(--border);
    border-radius: var(--radius-xl);
    background: var(--bg-surface);
    box-shadow: 0 28px 70px rgba(0,0,0,0.55);
    text-align: center;
    animation: ag-rise 180ms cubic-bezier(.2,.8,.25,1) both;
  }
  @keyframes ag-rise {
    from { opacity: 0; transform: translateY(10px) scale(0.98) }
    to   { opacity: 1; transform: none }
  }
  /* 틀렸을 때 한 번 흔든다. 문구만 바뀌면 눈이 그 자리를 안 보고 있어
     아무 반응이 없는 것으로 느껴진다. */
  .ag-card.wrong { animation: ag-shake 300ms ease both; }
  @keyframes ag-shake {
    20% { transform: translateX(-7px) } 45% { transform: translateX(6px) }
    70% { transform: translateX(-3px) } 100% { transform: none }
  }

  .ag-x {
    position: absolute; top: 10px; right: 10px;
    appearance: none; border: 0; background: transparent;
    color: var(--fg-mute); cursor: pointer;
    padding: 7px; display: flex; border-radius: 9px;
  }
  .ag-x:hover { color: var(--fg); background: var(--bg-hover); }

  .ag-ic {
    width: 46px; height: 46px;
    display: grid; place-items: center;
    border-radius: 14px;
    background: color-mix(in oklch, var(--accent) 16%, transparent);
    color: var(--accent);
    margin-bottom: 14px;
  }
  .ag-title { font-size: 20px; font-weight: 750; letter-spacing: -0.02em; }
  .ag-sub { margin: 6px 0 0; font-size: 13.5px; color: var(--fg-soft); }

  .ag-dots {
    position: relative;
    margin-top: 22px;
    display: flex; gap: 14px;
  }
  .ag-dot {
    width: 15px; height: 15px;
    border-radius: 50%;
    border: 1.5px solid var(--fg-faint);
    transition: background 130ms ease, border-color 130ms ease, transform 130ms ease;
  }
  .ag-dot.on {
    background: var(--accent);
    border-color: var(--accent);
    transform: scale(1.12);
  }
  /* 점 위를 통째로 덮어 어디를 눌러도 자판이 뜬다. */
  .ag-input {
    position: absolute; inset: -12px;
    width: calc(100% + 24px);
    opacity: 0;
    border: 0; background: transparent;
    font-size: 16px;  /* iOS가 확대하지 않는 최소 크기 */
    cursor: pointer;
  }
  .ag-dots:focus-within .ag-dot { border-color: var(--accent); }

  .ag-msg {
    margin-top: 16px;
    font-size: 13px; font-weight: 600;
    color: var(--err);
    min-height: 18px;
  }

  @media (prefers-reduced-motion: reduce) {
    .ag-veil, .ag-card, .ag-card.wrong { animation: none; }
    .ag-dot { transition: none; }
  }
`
