/**
 * 멘트 카탈로그 — 백엔드 agents/tools/lines.py가 접속 시 hello로 내려준다.
 *
 * 문장의 소유자는 백엔드다. 프론트는 화면에 그리기 위해 사본을 받아 쓸 뿐이고,
 * 음성은 문장이 아니라 line_id로 요청한다(NARRATION_REQUEST). 그래야 페르소나를
 * 바꿨을 때 프론트를 건드리지 않아도 화면과 음성이 함께 바뀐다.
 *
 * 발화마다 서버에 문장을 물어보지 않는 이유: 타이핑 애니메이션처럼 즉시 글자가
 * 필요한 화면이 있어서, 왕복 지연이 그대로 연출 지연이 된다.
 */

import { useEffect, useReducer } from 'react'

let catalog = {}
const listeners = new Set()

/** hello 수신 시 useWebSocket이 호출. */
export function setLineCatalog(next) {
  if (!next || typeof next !== 'object') return
  catalog = next
  listeners.forEach(fn => fn())
}

export function hasLines() {
  return Object.keys(catalog).length > 0
}

/**
 * line_id를 문장으로. 없는 id면 빈 문자열 — 화면이 깨지는 대신 조용히 비운다.
 * 값이 없는 슬롯도 빈 문자열로 채운다(파이썬 쪽 fill()과 같은 규칙).
 */
export function renderLine(lineId, params = {}) {
  const template = catalog[lineId]
  if (typeof template !== 'string') return ''
  return template.replace(/\{(\w+)\}/g, (_, key) =>
    params[key] == null ? '' : String(params[key]),
  )
}

/**
 * 카탈로그가 도착하면 리렌더되는 렌더 함수를 준다.
 * 컴포넌트는 `const line = useLines()` 후 `line('werewolf.morning')`.
 */
export function useLines() {
  const [, force] = useReducer(x => x + 1, 0)
  useEffect(() => {
    listeners.add(force)
    return () => listeners.delete(force)
  }, [])
  return renderLine
}

/** 음성 발화 요청. 문장이 아니라 line_id를 보낸다. */
export function narrate(send, lineId, params = {}) {
  send?.('NARRATION_REQUEST', { line_id: lineId, params })
}
