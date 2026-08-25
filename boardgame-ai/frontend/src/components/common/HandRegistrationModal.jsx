import { useState, useEffect } from 'react'
import {
  IconCheck, IconClose, IconShuffle,
} from './Icons'

const HAND_VIDEO_SRC = {
  v:  '/media/right_hand_info.mp4',
  ok: '/media/left_hand_info.mp4',
}

export const RANDOM_NICKNAMES = [
  '푸른 오징어', '용맹한 다람쥐', '수상한 너구리', '잠 못드는 두루미',
  '달리는 호랑이', '느긋한 펭귄', '냉정한 늑대', '엉뚱한 부엉이',
  '춤추는 사슴', '조용한 여우', '신중한 거북이', '장난꾸러기 토끼',
  '노련한 매', '빛나는 반딧불', '고요한 학', '용감한 까마귀',
  '한가로운 고양이', '기민한 살쾡이', '솔직한 곰', '수줍은 미어캣',
]

/**
 * seatStep: 'idle' | 'right_pending' | 'right_done' | 'completed'
 *   right_pending → step 0 (V)
 *   right_done    → step 1 (OK)
 *   completed     → step 2 (name)
 *
 * mode='edit'은 기존 플레이어 이름만 변경하는 단순 폼.
 */
export default function HandRegistrationModal({
  seatStep = 'right_pending',
  mode = 'new',          // 'new' | 'edit'
  initialName = '',
  defaultName = '',
  existingNames = [],
  onCancel,
  onSubmit,              // (name) => void
}) {
  const stepFromSeat = (
    mode === 'edit' ? 2
    : seatStep === 'completed' ? 2
    : seatStep === 'right_done' ? 1
    : 0
  )

  const [name, setName] = useState(initialName)

  // 등록 모드에서는 백엔드 seatStep에 의해 단계가 결정됨.
  // edit 모드에서는 그냥 이름 폼만.
  const step = stepFromSeat

  const randomNickname = () => {
    const used = new Set(existingNames)
    const pool = RANDOM_NICKNAMES.filter((n) => !used.has(n))
    const arr = pool.length ? pool : RANDOM_NICKNAMES
    setName(arr[Math.floor(Math.random() * arr.length)])
  }

  const submitName = () => {
    const trimmed = (name || '').trim() || defaultName
    if (!trimmed) return
    onSubmit(trimmed)
  }

  // step이 2(completed)로 진입했을 때 input 자동 포커스
  useEffect(() => {
    if (step === 2) setName((n) => n || '')
  }, [step])

  return (
    <>
      <div className="backdrop" onClick={onCancel} />
      <div className="hrm-modal hrm-modal-enter">
        <div className="hrm-head">
          <div className="hrm-title">
            <span className="status-dot ok pulse" style={{ marginRight: 8 }} />
            플레이어 등록
          </div>
          <button className="hrm-close" onClick={onCancel} aria-label="닫기">
            <IconClose size={18} />
          </button>
        </div>

        <div className="hrm-steps">
          <StepDot label="오른손 V" active={step === 0} done={step > 0} />
          <span className="step-bar" data-done={step > 0} />
          <StepDot label="왼손 OK" active={step === 1} done={step > 1} />
          <span className="step-bar" data-done={step > 1} />
          <StepDot label="이름 입력" active={step === 2} done={false} />
        </div>

        <div className="hrm-body">
          {step < 2 ? (
            <HandStep kind={step === 0 ? 'v' : 'ok'} />
          ) : (
            <NameStep
              name={name}
              setName={setName}
              defaultName={defaultName}
              onRandom={randomNickname}
              existingNames={existingNames}
              onEnter={submitName}
            />
          )}
        </div>

        <div className="hrm-foot">
          <button className="btn btn-ghost" onClick={onCancel}>취소</button>
          {step === 2 ? (
            <button
              className="btn btn-primary"
              onClick={submitName}
            >
              등록 완료 <IconCheck size={18} />
            </button>
          ) : (
            <button className="btn" disabled style={{ opacity: 0.6 }}>
              <span className="hrm-spin" /> 카메라로 인식 중…
            </button>
          )}
        </div>

        <style>{`
          .hrm-modal {
            position: absolute;
            left: 50%; top: 50%;
            transform: translate(-50%, -50%);
            width: min(640px, 88%);
            max-height: 86%;
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-xl);
            box-shadow: var(--shadow-lg);
            z-index: 100;
            display: flex; flex-direction: column;
            overflow: hidden;
          }
          @keyframes hrm-pop {
            from { transform: translate(-50%, -50%) scale(0.96); }
            to   { transform: translate(-50%, -50%) scale(1); }
          }
          .hrm-modal-enter { animation: hrm-pop 280ms cubic-bezier(.2,.7,.2,1.05) both; }
          .hrm-head {
            display: flex; align-items: center; justify-content: space-between;
            padding: 16px 20px;
            border-bottom: 1px solid var(--border-soft);
          }
          .hrm-title {
            display: flex; align-items: center;
            font-size: 16px; font-weight: 600; letter-spacing: -0.01em;
            white-space: nowrap;
          }
          .hrm-close {
            appearance: none; border: 1px solid var(--border-soft);
            background: var(--bg-elev);
            color: var(--fg-soft);
            width: 32px; height: 32px;
            border-radius: 8px;
            display: grid; place-items: center;
            cursor: pointer;
          }
          .hrm-close:hover { background: var(--bg-hover); color: var(--fg); }
          .hrm-steps {
            display: flex; align-items: center; gap: 8px;
            padding: 14px 24px 6px;
          }
          .step-bar {
            flex: 1; height: 2px;
            background: var(--border);
            border-radius: 1px;
            transition: background 240ms ease;
          }
          .step-bar[data-done="true"] { background: var(--accent); }
          .hrm-body {
            padding: 20px 24px 24px;
            min-height: 320px;
            display: flex; flex-direction: column;
            justify-content: center;
          }
          .hrm-foot {
            display: flex; gap: 10px; justify-content: space-between;
            padding: 14px 20px;
            border-top: 1px solid var(--border-soft);
            background: color-mix(in oklch, var(--bg-deep) 30%, transparent);
          }
          .hrm-spin {
            display: inline-block;
            width: 12px; height: 12px;
            border-radius: 50%;
            border: 2px solid var(--fg-faint);
            border-top-color: var(--fg);
            animation: spin 0.8s linear infinite;
          }
        `}</style>
      </div>
    </>
  )
}

function StepDot({ label, active, done }) {
  return (
    <div className={`step-dot ${active ? 'active' : ''} ${done ? 'done' : ''}`}>
      <div className="sd-mark">
        {done ? <IconCheck size={12} /> : <span className="sd-dot" />}
      </div>
      <div className="sd-label">{label}</div>
      <style>{`
        .step-dot { display: flex; align-items: center; gap: 6px; }
        .sd-mark {
          width: 18px; height: 18px; border-radius: 50%;
          background: var(--bg-elev);
          border: 1.5px solid var(--border);
          display: grid; place-items: center;
          color: var(--fg-mute);
          transition: all 200ms ease;
        }
        .step-dot.active .sd-mark {
          background: #22c55e;
          border-color: #22c55e;
          color: #052e16;
          box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.24);
        }
        .step-dot.done .sd-mark {
          background: #16a34a;
          border-color: #16a34a;
          color: #052e16;
        }
        .sd-dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
        .sd-label { font-size: 12px; color: var(--fg-mute); font-weight: 500; white-space: nowrap; }
        .step-dot.active .sd-label { color: var(--fg); }
      `}</style>
    </div>
  )
}

function HandStep({ kind }) {
  const isV = kind === 'v'
  const titleMain = isV
    ? '오른손을 뻗어 V 사인을 보여 주세요'
    : '이번엔 왼손을 뻗어 OK 사인을 보여 주세요'
  const titleSub = isV
    ? '테이블 중앙으로 손을 뻗어 카메라가 잘 보이게 해주세요'
    : ''

  // 오른손(V) → 손 아이콘 오른쪽 / 왼손(OK) → 손 아이콘 왼쪽 (실제 손 위치와 일치)
  return (
    <div className={`hs-wrap ${isV ? 'hs-hand-right' : 'hs-hand-left'}`} key={kind}>
      <div className="hs-camera">
        <div className="hs-frame">
          <div className="hs-corner tl" />
          <div className="hs-corner tr" />
          <div className="hs-corner bl" />
          <div className="hs-corner br" />
          <video
            key={kind}
            className="hs-hand-video"
            src={HAND_VIDEO_SRC[kind]}
            autoPlay
            muted
            loop
            playsInline
            preload="auto"
          />
        </div>
        <div className="hs-bar-label">
          <span className="status-dot ok pulse" /> 인식 중…
        </div>
      </div>

      <div className={`hs-text ${titleSub ? '' : 'hs-no-sub'}`}>
        <div className="hs-eyebrow">{isV ? '1 / 2' : '2 / 2'}</div>
        <h2 className="hs-title">{titleMain}</h2>
        {titleSub && <p className="hs-sub">{titleSub}</p>}
        <ul className="hs-tips">
          <li><span className="hs-bullet" /> 손가락을 또렷하게 펴 주세요</li>
          <li><span className="hs-bullet" /> 다른 사람은 잠시 손을 치워 주세요</li>
        </ul>
      </div>

      <style>{`
        .hs-wrap {
          display: grid;
          gap: 28px;
          align-items: center;
        }
        /* 왼손 단계: [손] [텍스트] */
        .hs-wrap.hs-hand-left  { grid-template-columns: 240px 1fr; }
        /* 오른손 단계: [텍스트] [손]  — 텍스트는 항상 왼쪽 정렬 유지 */
        .hs-wrap.hs-hand-right { grid-template-columns: 1fr 240px; }
        .hs-wrap.hs-hand-right .hs-camera { order: 2; }
        .hs-wrap.hs-hand-right .hs-text   { order: 1; padding: 0 6px 0 0; }
        @keyframes hs-slide-in-left {
          from { opacity: 0; transform: translateX(-18px); }
          to   { opacity: 1; transform: none; }
        }
        @keyframes hs-slide-in-right {
          from { opacity: 0; transform: translateX(18px); }
          to   { opacity: 1; transform: none; }
        }
        .hs-wrap.hs-hand-left  .hs-camera { animation: hs-slide-in-left 240ms cubic-bezier(.2,.7,.2,1.05) both; }
        .hs-wrap.hs-hand-left  .hs-text   { animation: hs-slide-in-right 240ms cubic-bezier(.2,.7,.2,1.05) both; }
        .hs-wrap.hs-hand-right .hs-camera { animation: hs-slide-in-right 240ms cubic-bezier(.2,.7,.2,1.05) both; }
        .hs-wrap.hs-hand-right .hs-text   { animation: hs-slide-in-left 240ms cubic-bezier(.2,.7,.2,1.05) both; }
        .hs-camera { display: flex; flex-direction: column; gap: 10px; }
        .hs-frame {
          position: relative;
          width: 240px; height: 200px;
          background:
            radial-gradient(ellipse at 50% 100%, rgba(0,0,0,0.4), transparent 60%),
            linear-gradient(180deg, var(--bg-deep), var(--bg-app));
          border: 1px solid var(--border);
          border-radius: var(--radius);
          overflow: hidden;
        }
        .hs-corner {
          position: absolute;
          width: 14px; height: 14px;
          border: 2px solid var(--accent);
          opacity: 0.7;
        }
        .hs-corner.tl { top: 10px; left: 10px; border-right: 0; border-bottom: 0; }
        .hs-corner.tr { top: 10px; right: 10px; border-left: 0; border-bottom: 0; }
        .hs-corner.bl { bottom: 10px; left: 10px; border-right: 0; border-top: 0; }
        .hs-corner.br { bottom: 10px; right: 10px; border-left: 0; border-top: 0; }
        /* 프레임을 꽉 채운다.
         *
         * contain이면 영상 비율(1280×828 ≈ 1.55)과 프레임(240×200 = 1.2)이
         * 달라 프레임 위아래에 빈 띠가 생기고, 모서리 조준선 안이 비어 보인다.
         * cover는 세로를 채우고 좌우를 잘라낸다 — 손은 한가운데에 있어서
         * 안내에는 지장이 없다.
         *
         * **여기서 더 키우지 말 것.** 영상 파일 안에도 그림 둘레에 여백이
         * 있는데(세로 161~678행), 그건 테이블이 공간에 놓여 보이게 하는
         * 의도된 여백이다. 그걸 없애겠다고 확대하면 테이블 모서리가 잘려
         * 무엇을 보고 있는지 알 수 없게 된다.
         */
        .hs-hand-video {
          position: absolute; inset: 0;
          width: 100%; height: 100%;
          object-fit: cover;
          background: transparent;
          pointer-events: none;
        }
        .hs-bar-label {
          font-size: 13px;
          color: var(--fg-mute);
          text-align: center;
          display: inline-flex; align-items: center; justify-content: center;
          gap: 8px;
        }
        .hs-text { padding-right: 6px; }
        .hs-eyebrow {
          font-size: 11px; color: var(--accent);
          letter-spacing: 0.14em; text-transform: uppercase;
          font-weight: 600; margin-bottom: 8px;
        }
        .hs-title {
          font-size: 21px; font-weight: 700;
          letter-spacing: -0.02em; line-height: 1.3;
          text-wrap: balance;
        }
        .hs-sub {
          margin: 8px 0 16px; font-size: 14px;
          color: var(--fg-soft); line-height: 1.55;
        }
        .hs-no-sub .hs-title {
          margin-bottom: 10px;
        }
        .hs-tips {
          list-style: none; padding: 0; margin: 0;
          display: flex; flex-direction: column; gap: 6px;
          font-size: 13px; color: var(--fg-mute);
        }
        .hs-tips li { display: flex; align-items: center; gap: 8px; }
        .hs-bullet { width: 4px; height: 4px; border-radius: 50%; background: var(--accent); }
      `}</style>
    </div>
  )
}

function NameStep({ name, setName, defaultName, onRandom, existingNames, onEnter }) {
  const isUsed =
    existingNames.includes((name || '').trim()) && (name || '').trim().length > 0

  return (
    <div className="ns-wrap fade-in">
      <div className="ns-head">
        <div className="ns-eyebrow">3 / 3</div>
        <h2 className="ns-title">플레이어 이름을 정해 주세요</h2>
        <p className="ns-sub">게임 화면과 알림에 표시될 이름입니다</p>
      </div>

      <div className="ns-input-row">
        <input
          className="input ns-input"
          placeholder={defaultName || '이름 입력 (예: 민준, 캡틴…)'}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') onEnter() }}
          maxLength={16}
          autoFocus
        />
        <button className="btn ns-rand" onClick={onRandom} title="랜덤 이름">
          <IconShuffle size={16} />
          랜덤
        </button>
      </div>

      {isUsed && (
        <div className="ns-warn">
          <span className="status-dot warn" /> 이미 사용 중인 이름이에요. 다른 이름을 선택해 주세요.
        </div>
      )}

      <style>{`
        .ns-wrap { display: flex; flex-direction: column; gap: 18px; }
        .ns-head { display: flex; flex-direction: column; gap: 4px; }
        .ns-eyebrow {
          font-size: 11px; color: var(--accent);
          letter-spacing: 0.14em; text-transform: uppercase; font-weight: 600;
        }
        .ns-title { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; }
        .ns-sub { margin: 0; font-size: 14px; color: var(--fg-soft); }
        .ns-input-row { display: flex; gap: 8px; }
        .ns-input { flex: 1; font-size: 18px; padding: 14px 18px; }
        .ns-rand { flex-shrink: 0; }
        .ns-warn {
          font-size: 13px; color: var(--warn);
          display: flex; align-items: center; gap: 8px;
        }
      `}</style>
    </div>
  )
}
