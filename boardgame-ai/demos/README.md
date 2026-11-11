# 최종 발표용 비전 시각화 데모

화면 녹화 → 움짤(PPT) 제작용 독립 실행 스크립트 모음.
모든 명령은 **`boardgame-ai/` 디렉터리에서** 실행한다.

## 파일 한눈에 보기

| 파일 | 용도 | 등록 필요 |
|---|---|---|
| [`register.py`](register.py) | **0단계** 플레이어 좌석 등록 (2·3·5의 선행) | — |
| [`demo1_detection.py`](demo1_detection.py) | ① 객체+손 인식 3분할 (YOLO / MediaPipe / 혼합) | ✕ |
| [`demo2_matching.py`](demo2_matching.py) | ② 손 → 가장 가까운 좌석 매칭 선 | ✓ |
| [`demo3_violation.py`](demo3_violation.py) | ③ 차례 아닌 사람 굴림 → 규칙 위반 배너 | ✓ (2명+) |
| [`demo4_rolecard.py`](demo4_rolecard.py) | ④ 늑대인간 역할 카드 인식 | ✕ |
| [`demo5_vote.py`](demo5_vote.py) | ⑤ 손가락 지목 벡터 + 투표 대상 강조 | ✓ (2명+) |
| [`demo6_roll_gate.py`](demo6_roll_gate.py) | ⑥ 진짜로 굴렸을 때만 처리 — 카메라 뷰만 (가림·킵존 이동은 무시) | 선택 |
| [`live_view.py`](live_view.py) | 시연 플레이 중 카메라 장면 출력(녹화용) | 선택 |
| [`common.py`](common.py) | 공용 유틸(카메라 루프·한글 텍스트·손 그리기·매칭) | — |

> 실행 순서 권장: `register` → 각 데모. 데모 1·4는 등록 없이 바로 가능.

## 공통 옵션 (모든 데모)

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--source` | 카메라 인덱스(정수) 또는 동영상 경로 | `0` |
| `--width` / `--height` | 카메라 해상도 | `1920` / `1080` (기본 1080p) |
| `--mirror` | 좌우 반전(셀카 모드). **등록과 데모는 같은 값으로** | off |
| `--record PATH` | mp4 녹화 (예: `--record /tmp/d1.mp4`) | off |
| `--players PATH` | 플레이어 JSON 경로 | `demos/players.json` |

종료: 영상 창에서 **`q` 또는 ESC**.

> 💡 녹화는 `--record` 로도 되지만, 화질·움짤 편집을 위해 **macOS 화면 녹화(⌘⇧5)** 로
> 창을 잡는 것을 권장. 녹화 후 [ezgif](https://ezgif.com) 등에서 gif 변환.

### 화질 관련

- 기본이 **1080p**. 실행 시 콘솔에 `요청 1920x1080 → 실제 캡처 WxH` 가 찍히니 카메라가
  진짜 1080p를 주는지 확인. `⚠` 가 뜨면 그 카메라가 1080p 미지원이거나 다른 해상도로 잡힌 것.
- **창을 화면보다 크게 늘리면 업스케일돼 뭉개진다.** 녹화할 땐 창을 네이티브 크기 근처로 두고
  ⌘⇧5 로 그 창 영역만 잡기.
- 데모1(3분할)은 각 칸이 960×540(합쳐서 1920×1080). 원본 한 칸만 크게 보고 싶으면 데모2·4 처럼
  단일 화면 데모를 쓰면 풀해상도로 보인다.
- 1080p라 손/카드 인식(MediaPipe·YOLO)이 무거워 FPS가 낮으면 → `--width 1280 --height 720` 로
  낮추면 부드러워진다(화질↔속도 트레이드오프).

---

## 0단계 — 플레이어 등록 (데모 2·3·5의 선행 조건)

데모 2/3/5는 "누구의 손인지" 매칭이 필요하므로 좌석 등록이 먼저다.
(데모 1·4는 등록 없이 바로 실행 가능)

```bash
python3 -m demos.register --mirror
```

- 한 명씩 **오른손 + 왼손을 둘 다 카메라에 보이게**(자기 자리 방향으로 뻗기) 한 뒤
  `SPACE` → 그 순간 양손을 동시 캡처해 그 사람 한 명 등록
- 4명이면 4번 반복 (다음 사람 손 → SPACE → 다음 사람 → SPACE …)
- `u` 취소 · `s` 저장 · **`q`/ESC 종료(자동 저장)** ← 종료는 `q` 권장(Ctrl+C 말고)
- 결과: `demos/players.json` (이후 데모들이 자동으로 읽음, 매 데모마다 재사용)

> **제스처는 안 봄** — V/OK 사인 안 해도 된다. 손목 위치 + 팔 방향만 저장하므로 양손만
> 보이면 충분(실제 시스템과 동일한 SeatZone 구조 생성).
>
> **재실행하면 기본은 새로 시작**(저장 시 기존 `players.json` 덮어씀). 이전 등록에 이어서
> 추가하려면 `--keep` 을 붙인다.

---

## 1 — 객체 인식 + 손 인식 (3분할)

```bash
python3 -m demos.demo1_detection --record /tmp/demo1.mp4
# YOLO 가중치 바꾸려면: --weights weights/yacht_v4.pt
```

위 두 칸 / 아래 한 칸:
- **좌상**: YOLO 객체 추적 — 박스 + `track_id` + 이동 궤적(trail)
- **우상**: MediaPipe 손 — 21 관절 골격
- **아래**: 두 결과 혼합

주사위를 굴리거나 손을 움직이면 궤적과 관절이 프레임 따라 변하는 게 보인다.

## 2 — 플레이어 매칭

```bash
python3 -m demos.demo2_matching --mirror --record /tmp/demo2.mp4
```

각 손에서 **가장 가까운 좌석까지 선**을 그어 어느 플레이어인지 시각화.
좌석 앵커(○)와 몸 위치(✛)도 함께 표시. (등록 필요)

## 3 — 상황 판단 (규칙 위반)

```bash
python3 -m demos.demo3_violation --active p_1 --mirror --record /tmp/demo3.mp4
```

- `--active` 가 **현재 차례** 플레이어. (등록 시 첫 사람이 `p_1`, 둘째가 `p_2` …)
- **차례가 아닌 사람**(예: `p_2`)이 트레이에서 주사위를 굴리면
  → 화면 중앙에 빨간 **"⚠ 규칙 위반!"** 배너 발화
- 실제 요트 파이프라인(굴림 인식 + Fusion)을 그대로 사용. 2명 이상 등록 필요.

## 4 — 늑대인간 역할 카드 인식

```bash
python3 -m demos.demo4_rolecard --record /tmp/demo4.mp4
```

카드를 카메라에 비추면 역할명(앞면)·`Card_Back`(뒷면)·`track_id`를 표시,
안정적으로 인식되면 **"✓ 인식 완료"** 강조. (등록 불필요. 등록돼 있으면 카드 소유자도 표시)

## 5 — 손가락 지목 / 투표

```bash
python3 -m demos.demo5_vote --mirror --record /tmp/demo5.mp4
```

손목→검지끝 **방향 벡터를 연장**해 지목 대상 좌석을 판정.
지목 선 + 대상 강조 원 + **누적 득표 수**를 표시. (2명 이상 등록 필요)

---

## 라이브 카메라 출력 (시연 플레이 녹화용)

태블릿에서 UI를 화면녹화하는 동안, 컴퓨터에서 **카메라가 보는 장면**을 큰 창으로 띄워
같이 화면녹화하기 위한 뷰어.

```bash
python3 -m demos.live_view --mirror --fullscreen                 # 깨끗한 카메라 패스스루
python3 -m demos.live_view --overlay all --mirror                # 손+객체+카드 인식 오버레이
python3 -m demos.live_view --overlay objects --record /tmp/play.mp4
```

| 옵션 | 설명 |
|---|---|
| `--overlay none/hands/objects/cards/all` | 표시할 인식 오버레이 (기본 `none` = 깨끗한 영상) |
| `--http [URL]` | 카메라 대신 백엔드 프레임 엔드포인트 폴링 (아래 참고). 값 생략 시 기본 URL |
| `--fullscreen` | 전체화면 |
| `--fps-hud` | FPS 표시 (기본 숨김 — 깨끗한 녹화를 위해) |
| `--clock` | 좌상단 경과시간 |
| `--record PATH` | mp4 동시 저장 |

### 카메라 1대 + 실제 백엔드 동시 (시연 본 영상) → `--http`

macOS에서 카메라는 **한 프로세스만** 연다. 실제 백엔드가 카메라를 쥐고 게임을 돌리는 중에는
뷰어가 같은 카메라를 직접 못 연다. 대신 **백엔드가 이미 노출하는 프레임 엔드포인트**
(`GET /debug/vision/frame.jpg`)를 폴링하면 충돌 없이 같은 장면을 맥에 띄울 수 있다.

```bash
# 백엔드 실행 중인 상태에서 (uvicorn backend.server:app --host 127.0.0.1 --port 8000)
python3 -m demos.live_view --http --fullscreen
# 다른 host/port면: python -m demos.live_view --http http://127.0.0.1:8000/debug/vision/frame.jpg
```

- `--http` 는 카메라를 직접 열지 않고 백엔드 프레임을 받아 그대로 띄운다 → **장면만 그대로 출력**.
- 백엔드가 아직 프레임을 안 올렸으면 잠깐 대기 후 자동 재시도.
- 이 모드에서도 `--overlay` 를 켜면 받은 프레임에 추가 인식을 그릴 수 있지만(로컬에서 한 번 더
  추론), "장면만" 필요하면 `--overlay none`(기본) 으로 두면 된다.

### 카메라를 직접 열 때 (백엔드 미실행 / 카메라 2대)

```bash
python3 -m demos.live_view --mirror --fullscreen          # 백엔드 없이 장면만
python3 -m demos.live_view --overlay all --mirror         # 뷰어가 곧 AI 인식 화면
python3 -m demos.live_view --source 1 --overlay all       # 둘째 카메라(2대 세팅)
```

---

## 촬영 팁

- 오버헤드(머리 위) 카메라 환경이 실제 세팅. 데모도 가능하면 위에서 내려보는 각도로.
- `--mirror` 는 **등록과 모든 데모에서 동일하게** 쓸 것 (좌우 일관성).
- 손이 잘 안 잡히면 조명을 밝게, 배경을 단순하게.
- 규칙 위반(데모 3)은 비차례 플레이어가 실제로 트레이에 주사위를 넣고 굴려야 발화한다.


---

## 6 — 진짜로 굴렸을 때만 처리된다 (카메라 뷰만)

```bash
python3 -m demos.demo6_roll_gate --mirror
python3 -m demos.demo6_roll_gate --mirror --record /tmp/demo6.mp4
```

실제 요트 비전 파이프라인(YOLO + ByteTrack + RollAttributor + Fusion)을 그대로 돌리고,
카메라 화면 위에 인식 결과만 그린다. 판정은 게임 서버와 같다.

- **트레이**: 평소 하늘색 → 손이 들어오면 노랑 "판정 중" → 실제 굴림이면 초록
  "굴림 확정 3 5 5 2 6", 손으로 가림·킵존 옮김이면 주황 "무시됨"
- **굴림통** 자홍 · **주사위** 눈 숫자(멈추면 초록, 움직이면 주황) · **손** 골격 + 이름

촬영 순서: 주사위 5개가 초록이 될 때까지 대기 → 손으로 가렸다 치움(무시됨) →
킵존으로 옮김(무시됨) → 굴림통으로 굴림(굴림 확정).

> 백엔드가 같은 카메라를 쓰는 중이면 이 데모는 카메라를 못 연다. 백엔드를 끄고 찍는다.
