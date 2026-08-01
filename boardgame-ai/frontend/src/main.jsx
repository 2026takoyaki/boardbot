import React from 'react'
import ReactDOM from 'react-dom/client'
import './styles/theme.css'
import App from './App'
import MomentPreview from './pages/MomentPreview'

// 연출 조율용 미리보기. 백엔드·카메라 없이 모달만 띄운다.
// App은 마운트되는 순간 WS에 붙으므로 여기서 갈라내야 연결이 아예 일어나지 않는다.
const isMomentPreview =
  new URLSearchParams(location.search).get('preview') === 'moments'

ReactDOM.createRoot(document.getElementById('root')).render(
  isMomentPreview ? <MomentPreview /> : <App />
)
