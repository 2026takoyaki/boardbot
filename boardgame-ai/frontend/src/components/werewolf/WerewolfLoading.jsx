import WerewolfScene from './WerewolfScene'
import * as ui from './wwUi'

// 늑대인간 공용 대기/로딩 화면. 다른 페이즈와 같은 무대(WerewolfScene) 위에
// 메시지만 띄운다 — 막간이라고 배경이 달라지면 화면이 툭 끊긴다.
// 플레이어 전환 대기·게임 시작 대기 등 짧은 막간에 사용.
export default function WerewolfLoading({ message = '잠시만 기다려주세요' }) {
  return (
    <div className="ww-root" style={ui.page}>
      <WerewolfScene mood="night" />
      <style>{`
        @keyframes wlDots {
          0%, 100% { opacity: 0.22; transform: translateY(0); }
          50%      { opacity: 1;    transform: translateY(-4px); }
        }
      `}</style>

      <div style={{ ...ui.stage, gap: 20 }} className="ww-anim-in">
        <div style={styles.message}>{message}</div>
        <div style={styles.dots}>
          <span style={{ ...styles.dot, animationDelay: '0s' }} />
          <span style={{ ...styles.dot, animationDelay: '0.16s' }} />
          <span style={{ ...styles.dot, animationDelay: '0.32s' }} />
        </div>
      </div>
    </div>
  )
}

const styles = {
  message: {
    fontSize: 28,
    fontWeight: 750,
    letterSpacing: '-0.01em',
    color: 'var(--w-ink)',
    textShadow: '0 0 38px rgba(240,207,122,0.3), 0 2px 12px rgba(0,0,0,0.6)',
  },
  dots: {
    display: 'flex',
    gap: 9,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: 'var(--w-gold)',
    animation: 'wlDots 1.15s ease-in-out infinite',
  },
}
