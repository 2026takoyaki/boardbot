# 보완 계획 (2026-07 종합 검토)

> 1학기 종료 시점 전체 코드베이스 검토 결과와 CO-SHOW 예선 대비 보완 로드맵.
> 검토 범위: agents/, audio/, backend/, vision/, games/, tests/, CI, frontend 구조.

---

## 0. 이번 검토에서 바로 수정한 것

| 파일 | 내용 |
|---|---|
| `tests/test_yacht_routing.py` | `YachtRunner` 시그니처 변경(config 필수화) 미반영으로 테스트 4개 실패 → config 전달 + FUSION_CONTEXT가 ws가 아닌 bridge로 가는 현재 계약에 맞게 검증 방식 수정. **197개 전부 통과** |
| `backend/server.py` | `/ws/werewolf`의 `send_hello()`가 try 밖에 있어 접속 직후 끊기면 이벤트 핸들러·파이프라인·오디오 정리(finally)가 통째로 누락 → try 안으로 이동 (yacht 소켓과 동일 패턴) |
| `audio/catalog.py` | ".env TTS_* 오버라이드 가능" 주석이 실제 미구현인데 구현된 것처럼 기술 → 사실대로 정정 |

---

## 1. 총평

**잘 되어 있는 것 (지킬 것):**
- 계층 분리: core(계약) / bridge / vision / games / backend / agents / audio — vision↔games 직접 import 금지 규칙, FusionContext·GameEvent 계약이 일관됨.
- 오디오 서브시스템: 우선순위 큐 + ack 기반 진행 + CRITICAL 인터럽트 + static/session/dynamic 3계층 TTS 캐시 + BGM 더킹. 완성도 높음.
- 비전 후처리: 안정화 카운터, grace 유예, in_game_roles 필터, low_confidence 플래그 + 수동 보정 UX 등 오인식 방어층이 두터움.
- 테스트 197개 + 벤치마크 인프라(BENCH_TRACE) 보유.

**구조적 핵심 진단 3가지:**
1. **"멀티에이전트"가 이름만 멀티에이전트.** 실체는 우선순위 콜백 4개(Rules/Tempo/Progress/Strategy). LLM은 Strategy에만, 그마저 키 없으면 규칙 기반. 페르소나 없음. → 프로젝트 정체성("멀티에이전트 진행 시스템")과 구현의 갭이 가장 큼.
2. **단일 세션 전제 + 좀비 탭 취약.** 세션 생성자에서 무조건 `attach_broadcast`, werewolf 접속 즉시 `pipeline_switcher("werewolf")`, 종료 시 무조건 `(None)`. 프론트 `useWebSocket`은 자동 재연결 → 닫지 않은 옛 탭이 로비/진행 중 게임의 파이프라인·오디오를 뺏는 함정이 여전히 존재.
3. **품질 게이트 구멍.** CI가 contract 테스트+core/bridge 린트만 수행 → 깨진 테스트 4개가 main에 존재했음. `pyproject.toml` 의존성(openai만)과 `requirements.txt` 불일치. `training/*/data.yaml`이 빈 파일이라 YOLO 학습 재현 불가.

---

## 2. 보완 영역별 상세 계획

### A. 멀티에이전트 LLM·페르소나 적용 — P0 (정체성)

**현황**
- `agents/orchestrator.py`: 우선순위 중재(Rules CRITICAL > Tempo HIGH > Progress NORMAL > Strategy LOW). 구조 자체는 확장에 적합.
- `agents/strategy_agent.py`: OpenAI(gpt-5.4-mini) → 5초 타임아웃 → 규칙 기반 폴백. **실패가 조용히 폴백되므로 "LLM이 적용 안 된 것처럼" 보일 수 있음.**
- Rules/Progress/Tempo: 전부 하드코딩 문자열. 페르소나 없음.
- 오디오 쪽은 이미 준비됨: agent별 보이스 매핑(`VOICE_BY_AGENT`), `enqueue_llm_line()` 진입점 존재.

**작업 항목**
1. [ ] **LLM 호출 실동작 검증**: OPENAI_API_KEY 설정 후 전략 코칭 켜고 로그 확인. `max_tokens`/`temperature` 파라미터가 최신 모델에서 거부될 가능성 점검(신모델 계열은 `max_completion_tokens` 요구, temperature 제약). 실패 시 예외가 폴백으로 삼켜지므로 단독 스크립트로 먼저 확인.
2. [ ] **LLM 클라이언트 공용화**: `agents/llm.py`로 분리(모델명·타임아웃·재시도·로깅 一元化). Strategy 외 에이전트도 쓸 수 있게.
3. [ ] **페르소나 시스템**: `agents/personas.py` — 페르소나 = {이름, 말투 시스템프롬프트, VoiceConfig, 고정멘트 세트}. 예: 진행자 "미아"(활기), 심판 "단테"(진중), 해설 "루나"(장난기).
4. [ ] **ProgressAgent 하이브리드화**: 페이즈 고정 멘트는 기존 static 캐시 유지(지연 0), 상황 의존 멘트(점수 하이라이트, 역전 순간, 밤 분위기 내레이션)는 LLM 생성 → dynamic 캐시. 실패 시 현행 템플릿 폴백 — 기존 안정성 그대로.
5. [ ] **에이전트 간 상호작용 데모 1개**: 예) 게임 종료 시 진행자↔해설자 2인 대화로 하이라이트 리캡(sequence_id 직렬화 재생 — AudioManager가 이미 지원). CO-SHOW 시연 임팩트 최대 지점.

**리스크/대책**: LLM 지연 → 이미 Strategy가 쓰는 백그라운드 태스크 패턴 재사용, 게임 흐름 비차단. 비용 → 짧은 max tokens + 캐시.

**실시간성 설계 원칙 (LLM 멘트에 필수 적용):**
- 목표 수치: 고정 멘트 = 캐시 hit 즉시(현재 달성), LLM 상황 멘트 = 이벤트→첫 음성 재생 **2초 이내**, 초과 시 템플릿 폴백.
- **2단 발화 패턴**: 반응성이 중요한 순간(규칙 위반, 족보 완성)은 ① 캐시된 짧은 즉답("잠깐만요!", "오, 풀하우스!")을 0지연으로 먼저 발화 → ② LLM 생성 상세 멘트를 뒤따라 재생(sequence_id 직렬화가 이미 지원).
- **사전 생성 풀 하이브리드**: 매 턴 실시간 생성 대신, 게임 시작/좌석 등록 시점에 상황 버킷별(턴 안내·리액션·위반 경고) 변형 멘트 10~20개를 LLM으로 미리 생성해 prewarm → 런타임엔 풀에서 랜덤 선택+이름 치환(캐시 hit). "매번 다른 말"과 "0지연"을 동시에 달성. 진짜 실시간 생성은 게임 종료 리캡처럼 지연 허용 구간에만.
- **문장 단위 파이프라이닝**: 긴 LLM 멘트는 문장별로 나눠 합성 — 문장1 재생 중 문장2 합성(체감 지연 = 첫 문장 합성 시간만).

---

### B. 늑대인간 카드 식별률 — P0 (데모 신뢰성)

**현황**
- 단일 스테이지 YOLO(`werewolf_v8.pt`, 13클래스, conf 0.5, imgsz 640). 오버헤드 뷰에서 카드가 작게 잡히고 일러스트가 유사해 role 분류가 어려움.
- 후처리 방어(grace 1.5s, stable_frames, in_game_roles 제한, low_confidence 수동보정)는 잘 갖춰짐 — 병목은 모델 자체.
- `training/werewolf/data.yaml`이 **빈 파일** → 학습 재현 불가.

**작업 항목**
1. [ ] **데이터셋 재정비**: data.yaml 복원 + 데이터셋 출처(Roboflow 등) README 기록. 조도 3단계 × 카드 각도/거리 다양화로 재수집, HSV/블러/원근 증강.
2. [ ] **2-stage 전환 검토(권장)**: ① YOLO는 `card_front`/`card_back` 2클래스만(위치 검출은 쉬움) → ② crop을 원근 보정(rectify) 후 경량 분류기(12 role, MobileNet급)로 식별. 카드 crop 기준 해상도가 확보돼 식별률이 구조적으로 오름. `CardTracker`는 cls_name 공급원만 바뀌므로 인터페이스 유지 가능.
3. [ ] **저비용 A/B 먼저**: imgsz 640→960/1280 상향 + conf 스윕. frame_skip 있으므로 FPS 여유 측정과 함께.
4. [ ] **회귀 기준선**: `benchmarks/recognition_rate.py`로 조건별(조도/거리) 식별률 표 작성 → 개선 전후 비교 수치를 발표 자료로.
5. [ ] (아이디어) 카드 식별이 계속 한계면 **마커 하이브리드**: 카드 슬리브 모서리에 소형 ArUco → role은 슬리브 ID 매핑. "순수 비전" 어필은 줄지만 데모 안정성 100% 확보용 플랜 B.

---

### C. 조도별 주사위 인식률 — P1

**현황**
- `DotCounter`: CLAHE → HoughCircles(정/반전) → Blob 폴백. 원 검출 파라미터(canny_upper, accum_thresh)가 조도에 민감 — 어두우면 pip 경계 대비가 무너짐.

**작업 항목**
1. [ ] **카메라 제어 우선**: `CameraManager`에 수동 노출/화이트밸런스 고정 옵션(cv2 CAP_PROP_EXPOSURE 등). 자동노출이 손 출입마다 흔들리는 것 자체가 인식 불안정의 원인.
2. [ ] **조도 프리셋**: 주간/야간 DotCounterParams 프리셋 + 프레임 평균 휘도로 자동 선택.
3. [ ] **학습 기반 전환(중기)**: 주사위 crop → 6클래스 분류 CNN(수천 장이면 충분, `tools/frame_extractor.py`로 수집 용이). 또는 YOLO에 dice_1~dice_6 클래스로 직접 학습(파이프라인 변경 최소). DotCounter는 폴백으로 유지.
4. [ ] **D(조명)와 연동**: 게임 시작 시 휘도 체크 → 기준 미달이면 IoT 조명 밝기 자동 보정 → "인식을 위한 능동 조명 제어"로 발표 스토리화.
5. [ ] 조도별 인식률 벤치마크 시나리오 추가(개선 수치 확보).

---

### D. IoT 조명 연동 (분위기 조성) — P0 (시연 임팩트, 신규)

**현황**: 없음. 단, BGM/SFX가 phase 전환 훅에서 트리거되는 패턴이 이미 있어 같은 자리에 끼우면 됨.

**작업 항목**
1. [ ] **LightManager 신설**(`iot/light_manager.py`): AudioManager 대칭 설계 — `set_scene(name)`, 씬 프리셋: `lobby`(중성), `yacht_play`(밝음), `werewolf_night`(어둡고 붉은 톤), `werewolf_day`(주광), `vote`(긴장 펄스), `result`(축하 플래시).
2. [ ] **하드웨어 선택**: ① Philips Hue/스마트전구 로컬 API(빠름) ② ESP32+WS2812B 자작(WITHUS IoT 수상 연장선 어필, Wi-Fi/MQTT). 권장: ②를 메인 스토리 + ①을 백업.
3. [ ] 트리거 연결: 세션의 phase 전환(BGM 트리거와 동일 지점)에서 `set_scene`. 실패해도 게임 비차단(try/except + 로그).
4. [ ] **C와의 긴장 관계 설계**: 밤 씬으로 어두워지면 카드 인식 저하 → "연출 조도 vs 인식 최소 조도" 하한 클램프. 이 트레이드오프 해결 자체가 좋은 발표 포인트.

---

### E. TTS 목소리 조절 — P1

**현황**
- agent별 보이스 3종 하드코딩. `.env`의 TTS_* 변수는 **읽는 코드가 없음**(오늘 주석 정정). 사용자 노출 설정 없음. 캐시 키가 (text+voice+rate+pitch) 기반이라 보이스 변경 시 캐시 정합성은 이미 안전.

**작업 항목**
1. [ ] **VoiceSettings 런타임화**: `GET/PUT /settings/voice` API + `catalog.get_voice_for_agent()` 함수화(모듈 상수 직접 참조 제거). dotenv 로드 타이밍 문제(import 시점) 회피를 위해 lazy 조회로.
2. [ ] **프론트 설정 패널**: 진행자 보이스 선택(Neural2 남/여 등), 말속도·피치 슬라이더, 마스터 볼륨(프론트 gain). 미리듣기 버튼(`/debug/audio/tts` 재활용).
3. [ ] 보이스 변경 시 static 재prewarm 트리거(현재는 부팅 시 1회).
4. [ ] **A(페르소나)와 통합**: 페르소나 선택 = 보이스+말투 프리셋 세트로 노출하면 UI가 단순해짐.
5. [ ] `SESSION_TEMPLATES`/`EXCITED_LINES`가 빈 리스트라 session prewarm·EXCITED 보이스 인프라가 놀고 있음 → "{player}님 차례입니다" 류 등록, "요트!" 등 하이라이트 외침 등록.
6. [ ] **자연스러움 업그레이드**: Neural2 → **Chirp 3 / HD 계열 보이스** 교체 검토(현행 대비 운율이 크게 자연스러움; 가격·지원 파라미터 확인 필요). SSML 적용(문장 사이 `<break>`, 강조 `<emphasis>`)으로 기계적 낭독감 제거 — `_synthesize_sync`의 `SynthesisInput(text=)`를 `ssml=` 분기 지원으로 확장.
   - [ ] **요트 족보 완성 연출**: → **`game_experience_plan_2026-07.md` Y-1로 확장 이관**(티어별 차등 연출 + 라운드 마일스톤 + 시상식까지 게임 경험 계획에서 통합 관리).
7. [ ] **CRITICAL 멘트 prewarm 갭 해소**: 규칙 위반 경고("지금은 {player}님의 차례입니다")는 가장 반응성이 중요한데 현재 dynamic 캐시(첫 발화 시 합성 지연). SESSION_TEMPLATES에 넣되 **referee 보이스로도 prewarm**하도록 `prewarm_session` 확장(현재 narrator 고정 — 보이스 다르면 캐시 키가 달라 miss).

---

### F. 세션/파이프라인 안정화 (좀비 탭) — P1 (데모 리허설 필수)

**현황**
- `useWebSocket.js`: onclose → 자동 재연결. 닫지 않은 옛 탭(좀비)이 재접속하며:
  - 세션 생성자에서 무조건 `audio_manager.attach_broadcast` → 오디오 스트림 탈취
  - werewolf 접속 즉시 `pipeline_switcher("werewolf")` → 로비/요트 파이프라인 비활성화 (좌석 등록 깨짐 — 기존에 실제로 겪은 함정)
  - disconnect 시 무조건 `pipeline_switcher(None)` → 진행 중인 다른 게임 파이프라인까지 꺼버림
- `WerewolfFSM` 타이머(_timer_task/_passive/_active)와 세션 `_reg_transition_task`가 **세션 종료 시 취소되지 않음** → 죽은 웹소켓에 broadcast 시도하는 좀비 타이머 잔존.

**작업 항목**
1. [ ] **세대(generation) 토큰**: server가 연결마다 증가시키는 세대 번호를 세션에 부여. `pipeline_switcher`/`attach_broadcast`/`detach`는 "현재 세대와 일치할 때만" 동작 (detach_broadcast_if 패턴을 전면 확장).
2. [ ] **WerewolfSession.close() 신설**: FSM 타이머 3종 + `_reg_transition_task` 취소. 소켓 finally에서 호출.
3. [ ] 프론트: 게임 페이지 unmount 시 소켓 정리 확인 + 탭 visibilitychange 시 재연결 억제 검토.
4. [ ] 리허설 시나리오 테스트: "게임 중 새로고침", "로비로 이탈 후 재진입", "탭 2개" 각각 오디오/파이프라인 소유권 검증.

#### F-2. 2차 구조 점검에서 추가 발견 (2026-07-04)

1. [ ] **카메라 끊김 = 영구 정지**: `CameraManager._loop`는 `cap.read()` 실패 시 break — 재연결 시도가 없어 USB 접촉 불량 한 번이면 서버 재시작 전까지 모든 비전이 침묵(파이프라인은 queue.Empty만 반복, 에러 표면화 없음). → 백오프 재-open 루프 + `/health`에 camera 상태 노출 + 프론트 경고 배너. **시연 리스크 상위.**
2. [ ] **`_stabilize_hands` 3중 복제**: lobby/yacht/werewolf 파이프라인에 ~80줄 동일 로직이 복붙돼 있고 이미 분기 발생(lobby만 best_effort 폴백 없음). 한 곳의 버그픽스가 나머지에 전파 안 되는 구조 → `vision/tracking/hand_stabilizer.py`로 추출, `use_best_effort` 플래그로 차이 흡수.
3. [ ] **좌석 등록 SFX 이중 경로**: App.jsx가 `state.sound`를 보고 `new Audio('/sfx/hand_register.mp3')` 직접 재생 — AudioManager 큐/SFX_REGISTRY 경로와 별개 레거시(탭릿 핸들러 주석의 "M3 마이그레이션" 미완). 큐 경로로 통일.
4. [ ] **요트만 새로고침 복구 없음**: App.jsx는 werewolf phase일 때만 페이지 복구. 요트 게임 중 새로고침하면 로비로 떨어짐(백엔드 FSM은 세션 소멸로 어차피 초기화 — F-1 세대 가드와 함께 "진행 중 게임 복구" 정책을 정할 것).
4-1. [ ] **(버그) 늑대인간 투표 화면 레이아웃 어긋남**: VoteCountdown이 세로 중앙정렬 플렉스에 카운트다운 숫자(96px)를 조건부 삽입 → 등장 순간 타이틀·안내·플레이어 그리드 전체가 점프. 그리드도 인원수 무관 4열 고정 + `100vh overflow:hidden`이라 5~6인+카운트다운 조합에서 클리핑 가능. → 숫자 자리 고정 예약(또는 absolute 오버레이) + 인원수 기반 그리드. 상세: `game_experience_plan_2026-07.md` W-2.
5. [ ] (경미) `CameraManager.stop()`이 스레드 join 안 함 / `PlayerManager`는 자체 락 없이 orchestrator 락에 의존(비전 스레드는 라이브 Player 객체를 직접 읽음 — GIL 덕에 사실상 안전하나 스냅샷 전달이 더 깔끔).
6. (양호 확인) ByteTracker/DiceManager/HandTracker의 다수결·마진·miss 유예 설계, AudioManager ack 큐, useAudioPlayer의 unlock·fade-out·pendingNext 처리, tablet WS의 연속 오류 차단은 견고. frontend `useWebSocket`의 자동 재연결은 F-1 좀비 탭 가드와 함께 다뤄야 함.

---

### G. 품질 게이트·리포 위생 — P2 (꾸준히)

1. [ ] **CI 강화**: 전체 pytest 실행(무거운 ML deps는 requirements 설치 or mock 마커로 분리). ruff/black/mypy 범위를 vision/games/audio/backend/agents로 확대(이미 로컬 캐시는 있음).
2. [ ] **의존성 단일화**: `pyproject.toml` dependencies에 requirements.txt 내용 통합(현재 openai만 있음) → CI `pip install -e ".[dev]"`가 실제 환경과 일치하게.
3. [ ] `demos/` 정리: `players.json`(좌석 더미)은 커밋하고 `__pycache__` 제거, 아니면 `demos/`를 gitignore. 현재 untracked 상태로 방치.
4. [ ] `backend/server.py`의 `orchestrator._pm.state.players` 사적 접근 → `orchestrator.get_seat_positions()` 공개 메서드로.
5. [ ] 이름 충돌 해소 검토: `backend/Orchestrator` vs `agents/AgentOrchestrator`.
6. [ ] 요트 `turn_timeout=None`이라 TempoAgent가 요트에서 무동작 — 턴 제한(예: 90초) 도입 여부 팀 결정.
7. [ ] RulesAgent(CRITICAL TTS)와 FSM 경고(`last_message`→Progress TTS)가 같은 위반에 이중 발화하는지 실기기 확인, 중복이면 한쪽 억제.
8. [ ] `.secrets/` git 히스토리 무오염 확인 완료(안전). `.env.example` 파일 추가해 신규 팀원 온보딩 개선.

---

## 3. 우선순위 로드맵 제안

| 순위 | 항목 | 이유 |
|---|---|---|
| **P0** | A 페르소나+LLM / D IoT 조명 / B 카드 식별률 | 심사 임팩트(차별성·연출)와 데모 신뢰성 직결 |
| **P1** | F 세션 안정화 / C 조도 강건성 / E 보이스 설정 | 시연 중 사고 방지 + 완성도 |
| **P2** | G 품질 게이트·위생 | 재발 방지, 협업 속도 |

권장 진행 순서(방학 기준): ① F(1주, 데모 사고 원천 차단) → ② A(2주, LLM 검증→페르소나→콤비 데모) → ③ D(1~2주, 병렬 가능) → ④ B 데이터 수집·재학습(2~3주, 수집은 초반부터 병렬) → ⑤ C/E → ⑥ G 상시.

각 항목 착수 시 이 문서의 체크박스를 기준으로 세부 설계 세션을 따로 진행할 것.
