import SettingsMenu from './SettingsMenu'
import { IconRefresh } from './Icons'

/**
 * 게임 화면 상단 조작 줄.
 *
 * 전에는 요트가 자기 상단바를 갖고, 늑대인간은 화면마다 '나가기' 버튼을 한
 * 개씩 복사해 갖고 있었다(여섯 벌). 같은 기기에서 같은 밤에 도는 두 게임인데
 * 요트에만 소리 조작이 있고, 늑대인간에서는 화면마다 나가기 자리가 미세하게
 * 달랐다. 여기 한 벌만 둔다.
 *
 * 설정(전략·소리·나가기)은 SettingsMenu가 통째로 갖는다 — 로비와 좌석
 * 등록 화면도 같은 메뉴를 쓰기 때문이다. 여기 남는 것은 **게임 중에만
 * 뜻이 있는 것**뿐이다.
 *
 * 되돌리기가 톱니 밖에 있는 이유: 그건 설정이 아니라 수(手)라서, 잘못
 * 눌렀을 때 한 번에 닿아야 한다. 설정을 열어 찾을 만큼 한가한 순간이 아니다.
 */
const TITLE_COLOR = {
  yacht: 'rgba(238,233,220,0.88)',
  werewolf: 'rgba(245,239,227,0.88)',
}

export default function GameTopBar({
  theme = 'yacht',
  title,
  send,
  connected = true,
  onExit,
  onUndo,
  canUndo = true,
  showStrategy = true,
}) {
  // 늑대인간에서는 배경 아무 데나 눌러 넘기는 화면이 있다. 이 바를 눌렀을 때
  // 그 화면까지 번지지 않게 막는다.
  const stopUndo = (e) => { e.stopPropagation(); onUndo?.() }

  return (
    <div className="tb-root" style={{ '--tb-title': TITLE_COLOR[theme] ?? TITLE_COLOR.yacht }}>
      {title && <span className="tb-title">{title}</span>}

      <div className="tb-actions">
        {onUndo && (
          <button
            type="button"
            className={`tb-undo tb-undo-${theme}`}
            onClick={stopUndo}
            disabled={!canUndo}
          >
            <IconRefresh size={16} />
            되돌리기
          </button>
        )}

        <SettingsMenu
          theme={theme}
          send={send}
          connected={connected}
          showStrategy={showStrategy}
          onExit={onExit}
        />
      </div>

      <style>{CSS}</style>
    </div>
  )
}

const CSS = `
  /* 줄 전체는 클릭을 통과시킨다. 늑대인간 결과 화면처럼 배경 아무 데나
     눌러 넘기는 화면에서, 빈 곳이 막히면 화면이 멈춘 것으로 보인다. */
  .tb-root {
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 58px;
    padding: 0 20px;
    display: flex;
    align-items: center;
    gap: 10px;
    z-index: 40;
    pointer-events: none;
    font-family: var(--font);
  }
  .tb-root > *, .tb-actions > * { pointer-events: auto; }

  .tb-title {
    font-size: 20px;
    font-weight: 850;
    letter-spacing: -0.02em;
    color: var(--tb-title);
  }

  .tb-actions {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  /* 44px은 손가락으로 눌러 빗나가지 않는 최소치다. 태블릿을 세워두고 옆에서
     누르는 자리라 마우스 기준으로 잡으면 매번 두 번씩 누르게 된다. */
  .tb-undo {
    appearance: none;
    height: 44px;
    padding: 0 15px;
    display: inline-flex;
    align-items: center;
    gap: 7px;
    border-radius: 12px;
    font-family: inherit;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: -0.01em;
    cursor: pointer;
    -webkit-backdrop-filter: blur(10px);
    backdrop-filter: blur(10px);
    transition: border-color 140ms ease, color 140ms ease;
  }
  .tb-undo:active:not(:disabled) { transform: translateY(1px); }
  .tb-undo:disabled { opacity: 0.38; cursor: not-allowed; }

  .tb-undo-yacht {
    border: 1px solid rgba(238,233,220,0.16);
    background: rgba(0,0,0,0.24);
    color: rgba(238,233,220,0.88);
  }
  .tb-undo-yacht:hover:not(:disabled) { border-color: #e8c765; color: #e8c765; }

  .tb-undo-werewolf {
    border: 1px solid rgba(255,255,255,0.16);
    background: rgba(10,8,16,0.52);
    color: rgba(245,239,227,0.88);
  }
  .tb-undo-werewolf:hover:not(:disabled) { border-color: #f0cf7a; color: #f0cf7a; }
`
