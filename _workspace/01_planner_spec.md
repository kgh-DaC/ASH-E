# ASH-E 설계서 v2.1 — 흡연자/담배 소지자 인식 + 타깃 우선순위

- 문서 ID: `_workspace/01_planner_spec.md` (v1 원본 보존: `_workspace/01_planner_spec_v1.md`, v2 원본 보존: `_workspace/01_planner_spec_v2.md`)
- 작성: ash-e-planner (v1 2026-10-27, v2 2026-10-27, v2.1 2026-10-28)
- 상태: **v2.1. v2에서 데이터 방침만 부분 개정(사용자 승인 2026-10-28).** 사용자 답변 Q1~Q6 반영, Q7~Q13은 v1 기본값 채택(현장 확인 필요). 남은 미결 질문은 13장.
- 이 문서가 기준이다. 스킬 문서(`windows-prototype`, `smoker-perception`, `target-priority`)와 다르면 이 문서를 따른다. 다른 점은 14장 "스킬 문서와의 차이"에 모아 두었다.
- 표기: **[추정]** = 웹 조사로 확인하지 못해 추정한 값. **[현장 확인]** = 기본값을 채택했지만 실물·현장에서 확인해야 하는 값.

---

## v2.1 변경 요약 (v2 대비, 2026-10-28)

**사유:** 직접 촬영 부담(v2 기준 6명 이상 × 15분)을 줄이기 위해 학습 데이터를 공개·일반 사진·합성 위주로 바꾸고, 직접 촬영은 평가와 본인 1세션으로 한정한다.
**승인:** 사용자가 2026-10-28에 이 데이터 방침을 **명시적으로 승인**했다. 합격선 수치(9.4, Q3 승인값)는 바꾸지 않았다.
**인터페이스:** ROS 메시지·core 타입·설정 키·토픽 **변경 없음.** 바뀐 것은 데이터 구성·분할 인원·수량 목표·판정 보고 형식뿐이다.

| # | 바뀐 점 | 절 |
| --- | --- | --- |
| 1 | **학습 데이터** = CigDet(공개) + COCO val2017 부분집합(none 1000 / similar 164, 담배 라벨 없음) + copy-paste 합성 300장(train 전용) + **본인 1세션 직접 촬영**. Roboflow는 선택(API 키 있을 때) | 0, 1.3 H2, 5.7, 9A.2, 9A.3 |
| 2 | **평가 데이터(dev/holdout)** = 학습에 쓰지 않은 **직접 촬영 2~3명**. 권장 3명(dev 1 + holdout 2). 공개·COCO·합성 데이터는 평가에 **절대 쓰지 않는다**(유지) | 9.1, 9A.5 |
| 3 | 직접 촬영 총량 3~4명(각 약 15분). 9A.3 목표를 "참가자 6명 이상, 자체 ROI 양성·음성 각 3,000 이상"에서 **본인 세션 양성 ROI ≥ 500, 음성 ROI ≥ 1,500** + 병합 학습셋 목표(train 양성 ≥ 2,000 / 음성 ≥ 4,800)로 낮춤. `capture.py` 키 1~7 기준 본인 세션(표 A)·평가 참가자 1인당(표 B) 최소 수량 신설 | 9A.3, 9.1 |
| 4 | **판정 해석 규칙 신설(9.4.1):** holdout이 2~3명뿐이라 합격선을 넘어도 **"예비 합격"**으로 표기하고, 표본 수(참가자·클립·프레임·노출 시간)와 95% 신뢰구간, 참가자별 값을 함께 보고한다. 일반화 주장 금지 | 9.3, 9.4.1, 11 게이트 |
| 5 | 유지: 사람 단위 분할, holdout·합격선 SHA-256 잠금, 자동 튜닝 루프의 holdout·합격선·평가 스크립트 수정 금지, 합성은 train에만 | 9A.5 |
| 6 | 리스크 R11(공개·합성 데이터와 웹캠 도메인 차이로 인한 일반화 한계), R12(소규모 평가 신뢰도) 추가, R6·R7 갱신 | 16 |
| 7 | N1·Q2를 확정으로 이동, 신규 미결 질문 N7~N9 | 13 |

**신뢰도 한계(요약):** holdout 2명이면 참가자 간 분산을 추정할 수 없다. 프레임 수가 많아도 같은 사람·같은 장소의 프레임은 서로 독립이 아니어서 프레임 단위 신뢰구간은 실제보다 좁게 나온다. 그래서 단계 A 합격은 "이 2~3명·이 장소·이 웹캠 조건에서 합격선을 넘었다"는 뜻으로만 쓴다. 단계 B 실기 재평가(R8)가 사실상의 2차 검증이다.

---

## v2 변경 요약 (v1 대비)

| # | 바뀐 점 | 절 |
| --- | --- | --- |
| 1 | 뎁스카메라를 **Orbbec Astra Pro**(구조광, 뎁스 640×480, 컬러는 별도 UVC 모듈)로 확정. 6장을 후보 비교에서 "Astra Pro 특성·드라이버 계획"으로 교체 | 1.2, 1.3, 6 |
| 2 | 컬러-뎁스 정렬: 드라이버 정렬 토픽에 의존하지 않는다. **core에 순수 numpy 소프트웨어 정렬 `depth_align.py` 추가**(외부 보정 파일 사용). 좌표 기준은 v1과 같이 컬러 광학 프레임 유지. 하드웨어 D2C는 선택지로만 둔다 | 4.4, 5.4-7, 5.8, 8 |
| 3 | **[인터페이스 변경]** perception 노드 입력 토픽을 remap 대신 **파라미터**로 받는다(`color_topic`, `depth_topic`, `color_info_topic`, `depth_info_topic` 등). frame_id 덮어쓰기·동기화 허용오차 파라미터 추가. ROS 메시지 필드는 변경 없음 | 4.2, 4.3, 4.4, 8 |
| 4 | Astra Pro 유효 거리에 맞춰 수치 변경: `acquire_range_m` 6.0→**5.0**, `release_range_m` 7.0→**5.8**, `depth_min_m` 0.3→**0.6**, `depth_max_m` 8.0→**6.0**, `S_dist` 선형 구간 1.5~5.0 m, 실기 `hfov_deg`는 보정값 사용 | 0, 5.4, 7, 8, 12.2 |
| 5 | 단계 B에 **B0 "카메라 드라이버 확보"** 작업과 결정 순서(ros2_astra_camera 소스 빌드 → 자체 OpenNI2 래퍼 + UVC 컬러 → 컬러 전용 프록시 운용) 추가. 리스크 절(16장) 신설 | 6, 11, 16 |
| 6 | **담배 데이터 수집 계획 절(9A) 신설**: 공개 데이터셋 표, 자체 촬영 시나리오·수량, 라벨링, 사람 단위 분할, hold-out·합격선 보호 규칙, 개인정보 정책, 자동/사용자 작업 경계 | 9A, 11 |
| 7 | 전자담배·궐련형 전자담배는 **인식 대상 아님** 확정. 액상형 전자담배와 궐련형 기기 사용 장면은 **하드 네거티브**, 기기 밖 궐련형 스틱 단독 장면은 **학습 제외(무시)**. 평가 라벨에 `category` 필드 추가 | 1.3, 9.1, 9.2, 9A |
| 8 | 합격선(9.4) 사용자 **확정**, YOLO11(AGPL-3.0) 사용 **확정**(졸업작품 범위 밖 배포 시 재검토 주석) | 5.2, 9.4 |
| 9 | 이식 기준에 **프록시→Astra Pro 뎁스 교체 검증 절차(10.5)** 추가, 뎁스 정확도 기준을 Astra Pro 특성에 맞게 구간별로 변경 | 10.4, 10.5 |
| 10 | 미결 질문 정리: Q1~Q6 확정, Q7~Q13 기본값 채택(현장 확인), 신규 질문 N1~N6 추가 | 13 |

---

## 0. 한눈에 보기

| 항목 | 결정 |
| --- | --- |
| 인식 방식 | 2단계: **사람+포즈 검출(YOLO11n-pose, 320px)** → 입·손 ROI 크롭(원본 해상도) → **ROI 담배 검출기(YOLO11n 1클래스, 192px)** → 키포인트 거리로 상태 판정 |
| 런타임 | 기본 ONNX Runtime(Windows·RPi5 공통, 동등성 확보). RPi5에서는 NCNN 백엔드를 선택적으로 사용(별도 정합 검사 필수) |
| 클래스 | `none`(0) / `holding`(1) / `smoking`(2) |
| 안정화 | 시간창 1.5 s 투표(8 Hz 기준 N=12, M=7), 해제 히스테리시스, smoking 래치 20 s |
| 우선순위 | 가중합 점수(상태 0.35, 거리 0.30, 정지 0.15, 신뢰도 0.10, 중심 0.10), 전환 마진 0.15 + 최소 유지 3 s + 전환 확인 1 s |
| 이탈 | 미관측 2 s → LOST, 5.8 m 초과 1 s 지속 → OUT_OF_RANGE (획득은 5.0 m 이내), 상태 none 5 s → STATE_CLEARED. 해제 직후 남은 후보 중 최고점으로 재선택 |
| 카메라(단계 B) | Orbbec Astra Pro: 뎁스(OpenNI2, 640×480) + 컬러(별도 UVC). 뎁스는 core `depth_align.py`로 컬러에 소프트웨어 정렬. 실내·그늘 전용, 직사광에서는 자동으로 프록시 거리로 떨어짐 |
| 데이터 | (v2.1) 학습: CigDet(CC BY 4.0) + COCO val 부분집합(음성) + copy-paste 합성(train 전용) + 본인 1세션 촬영(미점화 소품). 평가: 학습에 쓰지 않은 직접 촬영 2~3명만. 사람 단위 분할, hold-out·합격선 잠금, 합격은 "예비 합격"으로 표기 |
| 구조 | `src/ash_e_core`(ROS 무관 로직 전부) / `prototype/`(Windows 웹캠) / `src/ash_e_msgs`, `src/ash_e_perception`, `src/ash_e_priority`(얇은 ROS 래퍼) |
| 개발 순서 | 단계 A Windows 웹캠 → **사용자 합격 선언** → 단계 B ROS2 Jazzy 이식(rosbag 동등성 검사) |

---

## 1. 목표 · 제약 · 가정

### 1.1 목표
1. 카메라 영상 속 여러 사람 가운데 **담배를 입에 문 사람(smoking)**과 **담배/꽁초를 손에 든 사람(holding)**을 사람 단위로 구분한다.
2. 그런 사람이 여럿이면 점수로 순위를 매겨 **현재 접근 타깃 1명**을 정한다. 타깃이 멀어지거나 사라지면 다음 후보로 넘어간다.
3. 주행/접근 제어와 넛지(인기투표) UI는 **범위 밖**이다. 이 둘과 연결될 인터페이스 훅(토픽·서비스)만 정의한다(4.5절).

### 1.2 하드웨어·소프트웨어 제약
| 항목 | 단계 A (프로토타입) | 단계 B (실기) |
| --- | --- | --- |
| 연산 | Windows 11 PC CPU (GPU 사용 금지 — RPi5와 결과가 달라짐) | Raspberry Pi 5 (Cortex-A76 4코어, GPU 추론 없음), 능동 쿨러 필수 |
| OS / 미들웨어 | Windows 11, Python 3.12 (ROS 없음) | Ubuntu 24.04, ROS2 Jazzy, Python 3.12 |
| 카메라 | 일반 USB 웹캠 (뎁스 없음), 1280×720 권장 | **Orbbec Astra Pro** (구조광 뎁스 640×480 + 별도 UVC 컬러, USB 2.0 [추정]). 6장 |
| 목표 처리율 | 측정만 함(PC 값), 단 처리율을 8 Hz로 제한해 RPi5 조건을 흉내 낸다 | 인식 출력 **≥ 5 Hz (목표 8 Hz)**, 사람 3명 기준 |
| 런타임 의존 | numpy, opencv-python, onnxruntime, pyyaml (core 공통) | 위 + rclpy, cv_bridge, message_filters (래퍼만) |

**RPi5 Python 주의:** Jazzy의 `cv_bridge`는 시스템 numpy(1.26.x)로 빌드되어 있다. RPi5에서 pip로 numpy 2.x를 설치하면 cv_bridge가 깨진다. `python3 -m venv --system-site-packages`로 venv를 만들고 `onnxruntime`(aarch64 wheel)만 추가 설치하며 numpy는 업그레이드하지 않는다. Windows 쪽도 `numpy<2`로 고정해 두 환경을 맞춘다.

### 1.3 확정 사항과 가정
| ID | 내용 | 상태 | 관련 질문 |
| --- | --- | --- | --- |
| H1 | 뎁스카메라 **Orbbec Astra Pro**. 정렬 뎁스 토픽이 없다고 보고 소프트웨어 정렬을 기본으로 설계(6장) | **확정**(사용자) | Q1 |
| H2 | 자체 학습 데이터 없음. (v2.1) 학습은 공개 데이터(CigDet) + COCO 부분집합 + 합성 + 본인 1세션 촬영, 평가는 학습에 안 쓴 직접 촬영 2~3명(9A장) | **확정**(사용자, v2.1 방침 2026-10-28 승인), 수집은 perception-dev | Q2 |
| H3 | 접근 대상 거리 0.6 ~ 5.0 m(v1 0.5~6 m에서 Astra Pro 유효 범위에 맞춰 축소). 운용 환경은 v1 기본값(흡연구역, 주간) 채택. **Astra Pro는 실내용이라 직사광 아래 뎁스가 거의 무효가 될 수 있다** → 그때는 프록시 거리로 동작 | 기본값 채택, **[현장 확인]** | Q7, N3 |
| H4 | `smoking`이 `holding`보다 우선(holding_value 0.7) | **확정**(사용자) | Q4 |
| H5 | 전자담배·궐련형 전자담배는 **인식 대상 아님**(`none`). 액상형·궐련형 기기 사용 장면은 하드 네거티브로 학습, 기기 밖 궐련형 스틱 단독은 학습 제외(9A.4) | **확정**(사용자), 처리 방식은 설계 판단 | Q5 |
| H6 | Ultralytics YOLO11 가중치(AGPL-3.0) 사용. **주석: 비공개·비상업 졸업작품 범위 전제. 졸업작품 범위 밖으로 배포(공개 저장소, 상업 이용, 외부 기관 납품 등)하면 라이선스 재검토 필요** | **확정**(사용자) | Q6 |
| H7 | 카메라는 지면에서 약 1.0~1.2 m 높이에 수평 장착 | 기본값 채택, **[현장 확인]** | Q8 |
| H8 | 한 화면에 사람 최대 8명, 담배 분석은 프레임당 최대 4명 | 기본값 채택, **[현장 확인]** | Q9 |
| H9 | 로봇은 운용 중 영상을 저장하지 않는다. 데이터셋 촬영만 동의를 받고 로컬 저장(9A.6) | 기본값 채택 | Q10 |

---

## 2. 아키텍처

### 2.1 단계 A (Windows 프로토타입) — 단일 프로세스
```
 [USB 웹캠 / 영상 파일]
        │ BGR frame, stamp(=frame_idx/fps 또는 monotonic)
        ▼
 prototype/run_webcam.py ── 처리율 제한(process_rate_hz=8)
        │
        ▼
 ash_e_core.pipeline.PerceptionPipeline.process(frame_bgr, stamp, frame_id, depth=None, intr)
        │   ├─ detector: PoseModel(YOLO11n-pose ONNX) → persons+keypoints
        │   ├─ roi: 입/손 ROI 계산 → CigaretteRoiModel(ONNX) 배치 추론
        │   ├─ state: 키포인트 거리로 raw_state
        │   ├─ tracker: track_id, stationary_s
        │   ├─ stabilizer: state(안정화)
        │   └─ distance: distance_proxy (박스 높이/어깨폭 → m)
        ▼
 DetectionArray ─────────────► ash_e_core.priority.PrioritySelector.update(det, now=det.stamp)
        │                                  │
        ▼                                  ▼
 viz.draw_detections()            TargetStatus → viz_priority.draw_ranking()
        └──────────── 화면 오버레이 + JSONL 로그(--log) ────────────┘
```

### 2.2 단계 B (RPi5 + ROS2 Jazzy)
```
 [Astra Pro 컬러: UVC 드라이버]        [Astra Pro 뎁스: OpenNI2 기반 드라이버]   (6.3절 B0에서 확정)
   color image, color camera_info        depth image(비정렬, 뎁스/IR 프레임), depth camera_info
          │   (토픽 이름은 파라미터 color_topic 등으로 받음, 4.2절)   │
          ▼                                                          ▼
 ash_e_perception_node (얇은 래퍼)
   - cv_bridge → BGR uint8 / depth float32[m]
   - ApproximateTimeSynchronizer(color, depth, slop=sync_slop_s), CameraInfo 2종 캐시
   - depth_alignment=software: core depth_align.DepthAligner.align(depth) → 컬러 크기 정렬 뎁스
     (=hardware: 드라이버가 이미 정렬한 뎁스를 그대로 / =none: 뎁스 미사용, 프록시)
   - PerceptionPipeline.process(frame, stamp, frame_id, depth_aligned, intr_color)  ← core 그대로
   - core DetectionArray → ash_e_msgs/SmokerDetectionArray 변환
        │  /ash_e/detections
        ▼
 ash_e_priority_node (얇은 래퍼)
   - msg → core DetectionArray 변환 → PrioritySelector.update()
   - 10 Hz 타이머 → PrioritySelector.tick(now) (입력 끊김 판정만)
        │  /ash_e/target (TargetStatus), /ash_e/target_point (PointStamped)
        │  /ash_e/priority/markers (MarkerArray)
        ▼
 [범위 밖] 주행/접근 제어 노드, 넛지 UI 노드
        └── /ash_e/target_feedback (TargetFeedback) ──► ash_e_priority_node
        └── ~/set_lock (std_srvs/SetBool) ─────────────► ash_e_priority_node
```

### 2.3 결정론 원칙 (동등성 검사의 전제)
- core의 모든 시간 판단(안정화 창, 정지 시간, 타임아웃, 쿨다운)은 **입력 프레임의 stamp**로 한다. 벽시계(`time.time()`)를 core 안에서 호출하지 않는다. 우선순위의 `now`도 호출자가 넣는다.
- 우선순위 평가는 **DetectionArray가 도착할 때마다** 한 번 한다(`update`). 타이머(`tick`)는 입력 끊김 판정만 한다. 그래야 프로토타입(프레임마다 호출)과 ROS(메시지마다 호출)의 결과가 같아진다.
- 트래커 ID는 프로세스 시작 시 1부터 단조 증가한다.

---

## 3. 데이터 타입 (core) — ROS 메시지와 1:1

**규칙:** `src/ash_e_core/ash_e_core/types.py`의 dataclass 필드 이름·순서·단위는 아래 표와 `.msg` 정의를 그대로 따른다. 유일한 차이는 헤더다. core는 `stamp: float`(초, float64)와 `frame_id: str`로 갖고, 래퍼가 `std_msgs/Header`로 바꾼다. 열거값은 `IntEnum`으로 두고 정수값을 메시지 상수와 같게 둔다.

### 3.1 열거형
| 이름 | 값 |
| --- | --- |
| `SmokerState` | `NONE=0`, `HOLDING=1`, `SMOKING=2` |
| `DistanceSource` | `NONE=0`(거리 없음), `PROXY=1`(박스 기반 근사), `DEPTH=2`(뎁스 중앙값) |
| `PriorityMode` | `IDLE=0`, `TRACKING=1` |
| `TargetEvent` | `NONE=0`, `ACQUIRED=1`, `SWITCHED_BETTER=2`, `LOST_TIMEOUT=3`, `OUT_OF_RANGE=4`, `STATE_CLEARED=5`, `INPUT_TIMEOUT=6`, `FEEDBACK_RELEASED=7` |
| `Ineligible` | `OK=0`, `NOT_CONFIRMED=1`, `LOW_CONFIDENCE=2`, `OUT_OF_RANGE=3`, `COOLDOWN=4` |
| `FeedbackResult` | `DONE=1`(꽁초 투입 완료), `REFUSED=2`, `ABORTED=3`, `UNREACHABLE=4` |

### 3.2 `ash_e_msgs/msg/SmokerDetection.msg` ↔ `types.Detection`
```
uint8 STATE_NONE=0
uint8 STATE_HOLDING=1
uint8 STATE_SMOKING=2
uint8 DIST_SRC_NONE=0
uint8 DIST_SRC_PROXY=1
uint8 DIST_SRC_DEPTH=2

uint32  track_id             # 트래커 ID (1부터)
uint8   state                # 안정화된 상태 (우선순위는 이것만 쓴다)
float32 state_confidence     # 0..1, 창 안 양성 관측의 raw_confidence 평균 (양성 없으면 0)
uint8   raw_state            # 이번 프레임 판정
float32 raw_confidence       # 이번 프레임 담배 박스 최대 신뢰도 (없으면 0)
bool    cigarette_checked    # 이번 프레임에 ROI 담배 검사를 했는지 (예산 초과·ROI 너무 작음이면 false)
float32 person_confidence    # 사람 검출 신뢰도
int32   bbox_x               # 사람 박스 좌상단 x [px, 원본 해상도]
int32   bbox_y
int32   bbox_w
int32   bbox_h
bool    has_cigarette_box
int32   cig_x                # 대표 담배 박스 [px, 원본 해상도], 없으면 0
int32   cig_y
int32   cig_w
int32   cig_h
geometry_msgs/Point position # [m], header.frame_id(카메라 컬러 광학 프레임) 기준. x 오른쪽, y 아래, z 전방
float32 distance_m           # 수평 거리 sqrt(x^2+z^2) [m], 거리 없으면 -1.0
uint8   distance_source
float32 bearing_rad          # 방위각, REP-103 규약(왼쪽 +). = -atan2(x, z). 거리 없을 때도 픽셀로 계산
float32 stationary_s         # 연속 정지 시간 [s]
uint32  frames_observed      # 이 트랙의 누적 관측 프레임 수
```
core에서 `position`은 `x: float, y: float, z: float` 세 필드 대신 `position: Point3`(dataclass `x,y,z`)로 둔다.

### 3.3 `SmokerDetectionArray.msg` ↔ `types.DetectionArray`
```
std_msgs/Header header        # core: stamp(float s), frame_id(str)
uint32  frame_seq             # 처리한 프레임 순번
uint32  image_width
uint32  image_height
float32 inference_ms          # 파이프라인 전체 처리 시간
SmokerDetection[] detections  # 발행 조건을 만족한 트랙만 (hits ≥ 2)
```

### 3.4 `TargetCandidate.msg` ↔ `types.TargetCandidate`
```
uint32  track_id
uint8   state
float32 score                 # 0..1 (자격 없으면 계산값을 그대로 두되 eligible=false)
float32 s_state
float32 s_dist
float32 s_conf
float32 s_center
float32 s_stay
float32 distance_m
float32 bearing_rad
bool    eligible
uint8   ineligible_reason     # Ineligible
float32 cooldown_remaining_s
```

### 3.5 `TargetStatus.msg` ↔ `types.TargetStatus`
```
std_msgs/Header header        # stamp = 평가 시각(입력 det stamp 또는 tick now), frame_id = 입력 det의 frame_id
uint8 MODE_IDLE=0
uint8 MODE_TRACKING=1
uint8 EVENT_NONE=0
uint8 EVENT_ACQUIRED=1
uint8 EVENT_SWITCHED_BETTER=2
uint8 EVENT_LOST_TIMEOUT=3
uint8 EVENT_OUT_OF_RANGE=4
uint8 EVENT_STATE_CLEARED=5
uint8 EVENT_INPUT_TIMEOUT=6
uint8 EVENT_FEEDBACK_RELEASED=7

uint8   mode
bool    has_target
uint32  target_id             # 없으면 0
bool    target_visible        # 이번 입력에 타깃이 보였는지 (LOST 대기 중이면 false)
uint8   target_state
float32 target_score
geometry_msgs/Point target_position   # 마지막 관측 위치
float32 target_distance_m
float32 target_bearing_rad
uint8   distance_source
float32 tracking_duration_s
bool    locked                # 넛지 진행 중 잠금 여부
uint8   last_event            # 이번 평가에서 발생한 이벤트 (없으면 NONE)
uint32  previous_target_id    # 직전 타깃 ID (없으면 0)
TargetCandidate[] ranking     # score 내림차순, 자격 없는 후보 포함
```

### 3.6 `TargetFeedback.msg` ↔ `types.TargetFeedback` (범위 밖 노드가 발행하는 훅)
```
std_msgs/Header header
uint32 track_id
uint8  RESULT_DONE=1
uint8  RESULT_REFUSED=2
uint8  RESULT_ABORTED=3
uint8  RESULT_UNREACHABLE=4
uint8  result
```

### 3.7 core 내부 전용 타입 (메시지 없음)
- `CameraIntrinsics(fx, fy, cx, cy, width, height)` — 프로토타입은 `hfov_deg`로 계산(fx=fy=(W/2)/tan(hfov/2), cx=W/2, cy=H/2), ROS는 CameraInfo의 K에서 가져온다.
- (v2 추가) `DepthExtrinsics(R: 3x3, t: 3 [m])` — 뎁스(IR) 광학 프레임 점을 컬러 광학 프레임으로 옮기는 변환 `p_c = R·p_d + t`. 보정 파일(yaml)에서 읽는다(5.8절).
- (v2 추가) `DepthAligner(intr_depth, intr_color, extr, decimate)` — 5.8절. 메시지 대응 없음.
- `PersonPose(bbox_xyxy, conf, keypoints[17,3])` — COCO 17 키포인트 (x, y, conf).
- `CigBox(xyxy, conf)` — 원본 이미지 좌표.

### 3.8 직렬화
`ash_e_core/serialize.py`: `DetectionArray`, `TargetStatus`를 dict/JSON으로 변환한다. JSONL 한 줄 = 한 프레임: `{"frame_seq", "stamp", "detections": DetectionArray, "target": TargetStatus}`. 프로토타입 로그와 ROS 덤프 도구가 같은 함수를 써서 동등성 비교를 단순하게 만든다. float은 소수 4자리로 반올림해 기록한다.

---

## 4. ROS2 노드 · 토픽 · QoS · 프레임

### 4.1 패키지
| 패키지 | 빌드 | 내용 |
| --- | --- | --- |
| `ash_e_msgs` | ament_cmake (rosidl) | 3장의 msg 4종. Python 패키지로는 메시지를 정의할 수 없어 별도 패키지가 필요하다 |
| `ash_e_core` | ament_python **겸** 일반 pip 패키지 | ROS import 금지. Windows에서는 `pip install -e src/ash_e_core` |
| `ash_e_perception` | ament_python | `perception_node`, 변환, 도구, launch, config |
| `ash_e_priority` | ament_python | `priority_node`, 변환, launch(전체 기동 포함), config |

### 4.2 노드
| 노드 | 실행 파일 | 구독 | 발행 | 서비스 |
| --- | --- | --- | --- | --- |
| `ash_e_perception` | `ros2 run ash_e_perception perception_node` | 파라미터 `color_topic`, `depth_topic`, `color_info_topic`, `depth_info_topic`이 가리키는 토픽 (v2: remap 대신 파라미터) | `/ash_e/detections`, `/ash_e/perception/debug_image`(옵션) | — |
| `ash_e_priority` | `ros2 run ash_e_priority priority_node` | `/ash_e/detections`, `/ash_e/target_feedback` | `/ash_e/target`, `/ash_e/target_point`, `/ash_e/priority/markers` | `/ash_e/priority/set_lock` (std_srvs/SetBool) |

**perception 노드 입력 파라미터 (v2 신설, 래퍼 전용 키).** Astra Pro는 드라이버(6.3절)에 따라 토픽 이름·QoS·frame_id가 달라지므로 코드에 박지 않는다. 드라이버가 정해지면 `config/camera_astra_pro.yaml`의 값만 바꾼다.
| 파라미터 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `color_topic` | string | `/camera/color/image_raw` | 컬러 이미지. ros2_astra_camera 기본 이름 [추정]. usb_cam·v4l2_camera를 쓰면 `/image_raw` 계열 |
| `color_info_topic` | string | `/camera/color/camera_info` | 컬러 CameraInfo. 드라이버가 보정값을 안 주면 `camera_info_url`로 보정 yaml을 넣어 발행하게 한다 |
| `depth_topic` | string | `/camera/depth/image_raw` | 뎁스 이미지(`16UC1` mm 또는 `32FC1` m) |
| `depth_info_topic` | string | `/camera/depth/camera_info` | 뎁스 CameraInfo. `depth_alignment=software`일 때 필수 |
| `use_depth` | bool | true | false면 뎁스 구독 안 함(프록시 모드, 동등성 검사용) |
| `depth_alignment` | string | `software` | `software`(core DepthAligner) / `hardware`(드라이버 D2C 결과를 컬러와 같은 크기로 받는다고 가정, 크기 다르면 오류 로그 후 프록시) / `none`(뎁스 미사용) |
| `extrinsics_file` | string | `config/astra_pro_extrinsics.yaml` | 뎁스→컬러 외부 파라미터(5.8절). `software`일 때 필수, 없으면 프록시로 동작하고 경고 |
| `color_frame_id_override` | string | `""` | 비어 있으면 컬러 이미지 `header.frame_id`를 그대로 쓴다. UVC 드라이버가 엉뚱한 frame_id(`default_cam` 등)를 주면 여기에 `camera_color_optical_frame`을 넣는다 |
| `sync_slop_s` | double | 0.05 | 컬러·뎁스 근사 동기화 허용 오차. 두 장치가 따로 시간 도장을 찍으므로 0.03~0.08 범위에서 조정 **[현장 확인]** |
| `input_qos` | string | `sensor_data` | `sensor_data`(best_effort) / `reliable`. best_effort 구독은 reliable 발행자와도 연결되므로 기본값으로 둔다 |
| `equivalence_mode` | bool | false | 10.2절 |
| `publish_debug_image` | bool | false | |

### 4.3 토픽 · QoS
| 토픽 | 타입 | QoS | 비고 |
| --- | --- | --- | --- |
| 컬러/뎁스 입력 (이름은 파라미터) | sensor_msgs/Image | `input_qos`(기본 SensorData: best_effort, keep_last 1, volatile). 동기화 큐는 keep_last 5 | 최신 프레임만 처리. 동등성 모드(`equivalence_mode:=true`)에서는 reliable, keep_last 100 |
| CameraInfo 2종 (이름은 파라미터) | sensor_msgs/CameraInfo | best_effort, keep_last 1. 드라이버가 transient_local로 발행해도 연결됨 | 첫 수신 후 캐시. 컬러 info가 5 s 안에 안 오면 `hfov_deg`로 만든 근사 내부 파라미터로 동작하고 경고 |
| `/ash_e/detections` | ash_e_msgs/SmokerDetectionArray | reliable, keep_last 5, volatile | 처리한 프레임마다 1회 (빈 배열도 발행) |
| `/ash_e/target` | ash_e_msgs/TargetStatus | reliable, keep_last 1, volatile | update마다 + tick에서 상태가 바뀌면. 소비자는 stamp가 0.5 s보다 오래됐으면 무시해야 한다 |
| `/ash_e/target_point` | geometry_msgs/PointStamped | reliable, keep_last 1 | `has_target`일 때만 |
| `/ash_e/priority/markers` | visualization_msgs/MarkerArray | reliable, keep_last 1 | 후보 순위 텍스트 + 타깃 강조 |
| `/ash_e/perception/debug_image` | sensor_msgs/Image (bgr8) | best_effort, keep_last 1 | `publish_debug_image` 기본 false (RPi5 부하) |
| `/ash_e/target_feedback` | ash_e_msgs/TargetFeedback | reliable, keep_last 10 | 범위 밖 노드 → priority |

### 4.4 좌표계 (frame_id)
- 인식 결과의 `position`은 **컬러 광학 프레임** 기준이다(v1 유지). frame_id는 `color_frame_id_override`가 비어 있으면 컬러 이미지 `header.frame_id`를 복사하고, 아니면 그 값을 쓴다. 사람 박스·키포인트가 컬러 픽셀에서 나오므로 뎁스를 컬러에 맞추는 쪽(5.8절)을 택했다. 뎁스 프레임 기준 좌표는 쓰지 않는다(박스를 뎁스 영상으로 옮기려면 어차피 같은 외부 보정이 필요하고, 프로토타입과 좌표 정의가 갈라진다).
- 프로토타입의 frame_id는 `webcam_optical`(설정값)이다.
- Astra Pro의 컬러와 뎁스는 별개 장치라 드라이버가 둘 사이 TF를 정확히 주지 않을 수 있다 [추정]. 그래서 **뎁스→컬러 변환은 TF가 아니라 `extrinsics_file`에서 읽는다.** 래퍼는 같은 값을 `camera_depth_optical_frame → camera_color_optical_frame` 정적 TF로도 발행할 수 있다(`publish_extrinsics_tf`, 기본 false, RViz 확인용).
- 우선순위 노드는 좌표 변환을 하지 않는다. `base_link`·`map` 변환은 범위 밖인 주행 노드가 tf2로 한다. `base_link → camera_color_optical_frame` 정적 TF는 단계 B launch 인자로 둔다. 기본값은 H7(높이 1.1 m, 수평, 로봇 중심 전방 0.1 m) **[현장 확인]**.
- `bearing_rad`는 REP-103 규약(왼쪽 +)으로 통일한다: `bearing = -atan2(x, z)`. 거리가 없을 때는 `-atan((u_c - cx)/fx)`(u_c = 박스 중심 x).

### 4.5 범위 밖 기능과 연결할 훅
| 훅 | 방향 | 용도 |
| --- | --- | --- |
| `/ash_e/target`, `/ash_e/target_point` | priority → 주행 | 접근 목표. `has_target=false`면 정지/배회 |
| `/ash_e/target_feedback` | 넛지 UI·주행 → priority | 상호작용 종료 통보. DONE/REFUSED면 그 대상을 길게 쿨다운 |
| `/ash_e/priority/set_lock` | 넛지 UI → priority | true면 "더 나은 후보로 전환"을 막는다(상호작용 중 타깃 고정). LOST/OUT_OF_RANGE 해제는 잠금과 관계없이 동작 |

---

## 5. 인식 파이프라인

### 5.1 왜 2단계인가
담배는 길이 약 8.5 cm, 굵기 약 0.8 cm다. HFOV 70°·폭 1280 px 카메라에서 3 m 거리의 담배는 길이 약 40 px, 굵기 약 4 px이고, 320 px로 줄이면 굵기가 1 px가 된다. 전체 화면 단일 검출기로는 재현율이 나오지 않는다. 사람·포즈로 입·손 위치를 먼저 찾고 **원본 해상도에서 ROI를 잘라** 담배만 보면 작은 객체 문제와 연산량을 함께 줄일 수 있다. 상태 구분(입/손)도 키포인트와의 거리로 바로 정해진다.

(v2) Astra Pro 컬러를 640×480으로 쓰면 HFOV 약 60~66° [추정]에서 fx ≈ 500 px이고, 3 m 담배 길이는 약 14 px, 굵기 약 1.3 px로 웹캠 1280×720의 절반 수준이 된다. 그래서 **컬러는 1280×720을 기본으로 요청**하고(5.5절), 그 해상도를 못 내면 담배 인식 유효 거리가 약 2.5 m로 줄어든다고 보고 합격선 거리 구간 해석을 사용자와 다시 정한다(N2).

### 5.2 모델 후보 비교
RPi5 수치는 공개 자료와 크기 비례로 추정한 값이다. 단계 A에서 `prototype/bench.py`를 RPi5에서 직접 돌려 확정한다(core가 ROS 무관이라 단계 A에서도 RPi5 측정이 가능하다).

참고 자료: Ultralytics 공식 RPi5 벤치마크에서 YOLO11n(640, FP32)은 NCNN 약 88 ms, ONNX 약 168 ms다. YOLO11n-pose는 NCNN 기본 설정에서 약 5~6 FPS이고, 입력 축소 등 최적화로 훨씬 빨라진다는 사례가 있다.

**1단계 — 사람 + 키포인트**
| 후보 | 라이선스 | RPi5 추정(320 입력) | 장점 | 단점 | 판정 |
| --- | --- | --- | --- | --- | --- |
| YOLO11n-pose | AGPL-3.0 | NCNN 35~50 ms / ORT 60~90 ms | 박스+17 키포인트를 한 번에, ONNX/NCNN 변환 공식 지원 | 라이선스, 원거리 키포인트 품질 저하 | **1순위** |
| YOLOv8n-pose | AGPL-3.0 | 비슷 | 자료 많음 | 11n보다 약간 느림 | 대안 |
| MoveNet MultiPose Lightning | Apache-2.0 | 30~50 ms (256 입력) | 라이선스 자유, 빠름 | 최대 6명, 작은 사람에 약함, TF→ONNX 변환 필요 | AGPL 불가 시 1순위 |
| RTMDet-nano + RTMPose-t | Apache-2.0 | 사람 수에 비례해 증가 | 키포인트 정확 | 사람마다 추가 추론, 의존성 큼 | 보류 |
| 사람 검출만(YOLO11n det) + 박스 비율 ROI | — | 30~45 ms | 가장 쌈 | 손 위치를 몰라 holding 재현율 낮음 | 키포인트 실패 시 폴백 로직으로만 사용 |

**2단계 — 담배**
| 후보 | 입력 | RPi5 추정 | 장점 | 단점 | 판정 |
| --- | --- | --- | --- | --- | --- |
| A. 전체 화면 단일 검출(person+cigarette) | 640 | 90~170 ms | 단순 | 담배 굵기 1~3 px, 재현율 낮음, 느림 | 기각 |
| B. ROI 담배 검출기 (YOLO11n det 1클래스) | 192 | 크롭당 6~10 ms, 배치 처리 | 위치를 알아 입/손 판정이 기하학적으로 됨. 학습 라벨이 담배 박스뿐 | ROI 수만큼 비용 | **1순위** |
| C. ROI 분류기 (MobileNetV3-small 또는 YOLO11n-cls) | 128 | 크롭당 2~4 ms | 가장 빠름, 라벨 쉬움 | 위치 없음, 손을 입에 대는 동작(먹기·통화)에 편향될 위험 | 단계 A 비교 실험용 |

**라이선스 (v2 확정):** 이 프로젝트는 학생 졸업작품용으로 비공개·비상업으로만 쓴다. 이 전제에서 YOLO11(AGPL-3.0) 사용을 확정한다. *주석: 졸업작품 범위 밖 배포(소스·가중치 공개, 상업 이용, 외부 납품) 시 AGPL 의무와 Ultralytics 라이선스를 재검토하고, 필요하면 MoveNet 등 Apache-2.0 모델로 교체한다.*

**결정:** 1단계 YOLO11n-pose(320) + 2단계 B(192). 단계 A 평가에서 B의 속도·정확도가 미달하면 C를 같은 평가 스크립트로 비교한다. 두 모델 모두 ONNX로 내보내고, core는 Ultralytics 패키지 없이 onnxruntime + 자체 전·후처리(letterbox, NMS)로 돌린다. 런타임 의존을 줄이고 Windows/RPi5의 동작을 같게 하기 위해서다.

### 5.3 백엔드
- `backend: onnxruntime`(기본). `intra_op_num_threads`: Windows 4, RPi5 4.
- `backend: ncnn`(RPi5 선택). pip `ncnn` 휠 사용. 켜기 전에 백엔드 정합 검사를 통과해야 한다(10.3절).
- 모델 파일은 `models/`(git 미추적)에 두고 `models/README.md`에 파일명·입출력 형태·내보내기 명령을 적는다. 파일이 없으면 스텁 모델이 동작한다(사람 0명 반환, 경고 로그). 이 경우 인터페이스는 살아 있고 QA 보고서에 "실추론 미검증"으로 표시한다.

### 5.4 단계별 처리 (core `PerceptionPipeline.process`)
입력: `frame_bgr`(uint8 HxWx3, BGR), `stamp`(float s), `frame_id`, `depth`(float32 HxW [m] 또는 None, **컬러와 같은 크기로 정렬된 것**. Astra Pro에서는 래퍼가 5.8절 `DepthAligner`로 만들어 넣는다), `intr`(컬러 CameraIntrinsics).

1. **사람·포즈 검출**: letterbox 320 → YOLO11n-pose → 원본 좌표로 복원. 사람 필터: `person_conf_thresh=0.40`, `min_person_h_px=60`, NMS IoU 0.5, 최대 `max_persons=8`(큰 박스 우선).
2. **트래킹** (`tracker.py`): 이전 트랙과 IoU ≥ `track_iou_thresh=0.3`로 탐욕 매칭, 남은 것은 중심 거리 ≤ `0.5 × bbox_h`로 2차 매칭. `track_max_age_s=1.0` 동안 미매칭이면 삭제. `hits ≥ 2`인 트랙만 발행.
   - 정지 시간: 정규화 속도 `v = |Δ박스중심| / bbox_h / Δt`를 EMA(α=0.5)로 거르고, `v < stationary_speed_thresh=0.25 [1/s]`이면 `stationary_s += Δt`, 아니면 0으로 리셋. 픽셀 기반이라 프록시/뎁스 모드에 관계없이 같은 값이 나온다.
3. **ROI 계산** (`roi.py`), COCO 키포인트 기준(0 코, 1·2 눈, 3·4 귀, 5·6 어깨, 7·8 팔꿈치, 9·10 손목), 키포인트 유효 조건 `kp_conf_thresh=0.30`:
   - 머리 크기 `h`: 우선순위대로 귀-귀 거리 → 2.0 × 눈-눈 거리 → 0.6 × 어깨폭 → 0.12 × bbox_h.
   - 입 위치 `m`: 코와 두 눈이 유효하면 `코 + 0.6 × (코 − 두눈중점)`, 코만 유효하면 `코 + (0, 0.25h)`. 얼굴 키포인트가 없으면(뒤돌아봄) 입 ROI 없음.
   - 손 위치: 손목 유효 시 `손목 + 0.3 × (손목 − 팔꿈치)`(팔꿈치 무효면 손목 그대로). 좌우 각각.
   - ROI는 정사각형. 입 ROI 한 변 `mouth_roi_scale=1.6 × h`, 손 ROI 한 변 `hand_roi_scale=1.4 × h`. 화면 밖은 잘라낸다.
   - 원본 해상도에서 ROI 한 변이 `min_roi_px=24` 미만이면 그 ROI는 건너뛴다(너무 멀다).
   - 키포인트가 모두 무효면 박스 비율 폴백: 박스 상단 25%를 입 ROI, 박스 세로 35~75% 구간 좌우 절반을 손 ROI로 쓴다.
4. **담배 검출**: ROI를 192로 리사이즈해 배치 추론. 프레임당 담배 분석 대상은 `max_roi_persons=4`명(박스가 큰 순, 즉 가까운 순). 나머지 사람은 라운드로빈으로 다음 프레임에 분석하고, 이번 프레임에는 `cigarette_checked=false`로 둔다. 담배 박스 `cig_conf_thresh=0.35`, 원본 좌표로 복원 후 전역 NMS(IoU 0.5).
5. **상태 판정** (`state.py`): 담배 박스마다 중심과 각 사람의 입·손 위치 사이 거리를 그 사람의 `h`로 나눈 값을 구하고, 가장 가까운 한 사람에게 배정한다(사람이 겹칠 때 엉뚱한 사람에게 붙는 것을 막는다).
   - 입까지 거리 ≤ `smoking_radius=0.7` → smoking 후보.
   - 아니고 손까지 거리 ≤ `holding_radius=0.9` → holding 후보.
   - 둘 다 아니면 무시(바닥·테이블 위 담배).
   - 사람별 `raw_state`: smoking 후보가 있으면 SMOKING, 아니면 holding 후보가 있으면 HOLDING, 아니면 NONE. `raw_confidence` = 채택한 상태의 후보 중 최대 신뢰도. 대표 담배 박스(`cig_*`)도 그것으로 한다.
6. **시간 안정화** (`stabilizer.py`, 트랙별):
   - 창: 최근 `stab_window_s=1.5` s의 관측 중 `cigarette_checked=true`인 것만 센다.
   - 양성 = raw_state ∈ {HOLDING, SMOKING}.
   - **확정(NONE → 양성)**: 관측 수 ≥ `stab_min_obs=4`이고 양성 비율 ≥ `confirm_ratio=0.6`. (8 Hz 기준 N=12 중 M=7 이상과 같다.)
   - **해제(양성 → NONE)**: 양성 비율 < `release_ratio=0.25`가 `release_hold_s=1.0` s 동안 이어질 때. 확정·해제 기준을 다르게 둬 상태가 깜빡이지 않게 한다.
   - 양성 상태에서 SMOKING/HOLDING 구분: 창 안 SMOKING 관측 수 ≥ `smoking_min_obs=2`이면 SMOKING.
   - **smoking 래치**: 흡연자는 대부분의 시간 동안 담배를 손에 들고 있다가 가끔 입에 문다. 그래서 한 번 SMOKING이 확정되면 양성이 이어지는 동안 `smoking_latch_s=20` s 동안 SMOKING을 유지한다.
   - `state_confidence` = 창 안 양성 관측의 raw_confidence 평균(양성이 없으면 0).
   - 처리율이 바뀌어도 동작이 같도록 창을 프레임 수가 아니라 시간으로 정의한다. 단계 A는 `process_rate_hz=8`로 제한해 RPi5와 같은 조건에서 파라미터를 정한다.
7. **거리·3D 위치** (`distance.py`, 순수 numpy):
   - **프록시(단계 A, 뎁스 없음)**: 박스가 화면 위·아래 가장자리에서 `edge_margin_px=8` 이상 떨어져 있으면(전신이 보임) `z = fy × person_height_m(1.65) / bbox_h`. 잘렸으면 어깨 키포인트가 유효할 때 `z = fx × shoulder_width_m(0.40) / 어깨폭px`, 아니면 머리 크기로 `z = fx × head_width_m(0.15) / h`. 이어서 `x = (u_c − cx) × z / fx`, `y = (v_c − cy) × z / fy`(u_c, v_c는 몸통 중심), `distance_source=PROXY`. 상수가 부정확하므로 우선순위 가중치를 이 값으로 최종 튜닝하지 않는다.
   - **뎁스(단계 B)**: 몸통 ROI(어깨와 엉덩이 키포인트가 이루는 사각형, 없으면 박스 가로 중앙 40% × 세로 20~60%)의 뎁스 중 0, NaN, 범위 밖(`depth_min_m=0.6` ~ `depth_max_m=6.0`, v2 변경) 값을 버리고 중앙값을 `z`로 쓴다. 유효 픽셀이 `depth_min_valid_px=30` 미만**이거나 ROI 안 유효 비율이 `depth_min_valid_ratio=0.15` 미만**(v2 추가)이면 프록시로 대체하고 `distance_source=PROXY`로 표시한다. x, y는 컬러 CameraInfo 내부 파라미터로 계산하고 `distance_source=DEPTH`.
   - (v2) Astra Pro 기준 근거: 구조광 뎁스는 0.6 m 미만이 사각(값 0)이고, 오차가 거리 제곱에 비례해 커진다. 1 m에서 ±3 mm(제조사 수치, Astra 계열)지만 5~6 m에서는 수 cm~10 cm 이상, 6 m를 넘으면 유효 픽셀이 급감한다 [원거리 수치는 추정]. 그래서 상한을 6.0 m로 낮추고 그 너머는 프록시로 넘긴다. 0.6 m 미만으로 다가온 사람도 뎁스가 0이라 자동으로 프록시(머리 크기 기반)로 떨어진다. 직사광에서는 IR 패턴이 묻혀 유효 비율이 떨어지므로 같은 규칙으로 프록시가 된다.
   - (v2) **중앙값 규칙의 유효성**: 소프트웨어 정렬 뒤에는 사람 윤곽 근처에서 배경 뎁스가 섞이고(시차·보정 오차), 구조광은 가장자리에 무효 띠가 생긴다. 몸통 ROI를 박스 안쪽으로 잡고 중앙값을 쓰는 v1 규칙은 이 두 문제에 강하므로 유지한다. 추가로 ROI를 사방 `depth_roi_shrink=0.1`(ROI 크기 비율)만큼 줄여 경계 섞임을 줄인다.
   - `distance_m = sqrt(x² + z²)`, `bearing_rad = -atan2(x, z)`.
   - **교체 지점**: `PerceptionPipeline.process`의 `depth` 인자다. None이면 프록시, 배열이면 뎁스를 쓴다. core 코드는 바뀌지 않고 래퍼가 depth를 넣는지만 다르다.
8. **출력**: `DetectionArray`(hits ≥ 2 트랙만, track_id 오름차순).

### 5.5 입력 해상도
- 웹캠: 1280×720 캡처(지원 안 되면 640×480; 해상도는 설정값). 포즈는 320 letterbox, ROI는 원본에서 자른다.
- RPi5 컬러(Astra Pro UVC): **1280×720 요청, MJPEG 우선** [추정: Astra Pro 컬러 모듈의 1280×720 지원과 포맷은 `v4l2-ctl --list-formats-ext`로 확인, N2]. 안 되면 640×480. 처리율이 8 Hz라 카메라는 15 fps 이상이면 충분하다.
- RPi5 뎁스(Astra Pro): 640×480 @30 fps(또는 15 fps), `16UC1` mm. Astra Pro는 USB 2.0 장치로 알려져 있어 [추정] 컬러 1280×720 비압축(YUYV)과 뎁스를 동시에 받으면 대역폭이 모자랄 수 있다 → 컬러는 MJPEG, 뎁스는 15 fps로 낮추는 것을 먼저 시도한다.
- 정렬은 래퍼가 core `DepthAligner`로 한다(5.8절). `depth_align_decimate=2`(뎁스 320×240 상당만 투영)로 RPi5 비용을 줄인다.

### 5.6 RPi5 처리 예산(추정, 사람 3명)
| 구간 | ONNX Runtime | NCNN |
| --- | --- | --- |
| 전처리 + letterbox | 5 ms | 5 ms |
| 포즈 320 | 60~90 ms | 35~50 ms |
| ROI 담배 192 × 최대 9 크롭(배치) | 50~80 ms | 30~50 ms |
| 후처리·트래킹·안정화·뎁스 | 5~10 ms | 5~10 ms |
| (v2) 뎁스 소프트웨어 정렬(decimate 2, 7.7만 점 투영) [추정] | 5~15 ms | 5~15 ms |
| (v2) MJPEG 디코드(드라이버 쪽, 1280×720) [추정] | 별도 프로세스 10~20 ms | 같음 |
| **합계 / 처리율** | 120~185 ms / **5.4~8 Hz** | 75~115 ms / **8.7~13 Hz** |
ONNX Runtime만으로 5 Hz 하한은 맞출 수 있다고 본다(v2 정렬 비용을 더하면 여유가 줄어 하한 근처). 못 맞추면 순서대로 조정한다: (1) NCNN 백엔드, (2) `roi_every_n=2`(ROI 분석을 격프레임으로), (3) `depth_align_decimate=4`, (4) 포즈 입력 256.

### 5.7 학습 데이터 확보
(v2) 수집·라벨링·분할·개인정보 규칙은 **9A장이 원본**이다. 이 절은 학습 방법만 다룬다. 아래 공개 데이터·자체 촬영 문단 중 9A와 다른 내용이 있으면 9A를 따른다.
- **라벨은 담배 박스 하나뿐이다.** 상태(smoking/holding)는 키포인트 거리로 정하므로 학습에 상태 라벨이 필요 없다. 상태 라벨은 평가 데이터에만 붙인다.
- **공개 데이터(라이선스 확인 필수)**: Roboflow Universe의 cigarette/smoking 데이터셋들(일부 MIT·CC BY 4.0, 라벨 정의가 제각각이니 확인할 것), Mendeley CigDet(YOLO 형식). `smoker` 클래스처럼 사람 전체에 박스를 친 데이터는 쓰지 않거나 담배 박스로 다시 라벨링한다.
- **ROI 데이터셋 변환** (`training/build_roi_dataset.py`): 원본 이미지에 포즈 모델을 돌려 5.4절과 같은 규칙으로 입·손 ROI를 자르고, 담배 박스를 ROI 좌표로 옮긴다. 담배가 없는 ROI는 음성 샘플이 된다. 학습 입력 분포가 실제 추론 입력과 같아지는 것이 이 단계의 목적이다.
- (v2.1) **일반 사람 사진(COCO val2017 부분집합)**: 담배 라벨 없는 음성 이미지(none 1,000장, 손·입 근처 가는 물체 similar 164장). 입·손 ROI 음성 샘플과 합성 배경으로만 쓴다. 이미지별 라이선스가 섞여 있어(NC 포함) 내부 학습 전용(`data/SOURCES.md`).
- (v2.1) **copy-paste 합성**: CigDet train 담배 크롭을 COCO train 분할 사람 이미지의 입·손목 근처에 붙인 300장. 실제 양성 대비 비율 상한 0.25, **train에만** 넣는다.
- **자체 촬영(동의 필수)**: (v2.1) 학습용은 **본인 1세션**, 평가용은 학습에 안 쓴 2~3명(9A.3). 불붙이지 않은 담배·꽁초 소품으로 1~5 m, 여러 각도·조명에서 촬영한다. 하드 네거티브(펜, 빨대, 젓가락, 막대사탕, 휴대폰 통화, 손가락 물기, 마스크 만지기)를 반드시 넣는다.
- **목표 규모**: (v2.1) 9A.3의 수량 표가 원본이다(v2의 "자체 ROI 각 3,000 이상"은 폐기). 학습과 평가는 **인물 단위로 나눈다**(같은 사람이 학습과 평가에 동시에 들어가면 정확도가 부풀려진다).
- **학습**: `training/`에서만 Ultralytics 사용. YOLO11n detect, imgsz 192, 1클래스 `cigarette`. 증강: 밝기, 블러, 회전 ±15°, 좌우 반전. ONNX(opset 17, 정적 배치 1 및 동적 배치) 내보내기. 학습 코드는 core·노드와 섞지 않는다.
- **초기 실험용**: 학습 전에는 공개된 사전학습 담배 검출 가중치(예: Hugging Face 공개 모델)를 ROI에 시험 적용해 파이프라인을 검증해 볼 수 있다. 라이선스와 ONNX 변환 가능 여부를 확인한 뒤 쓴다.

### 5.8 뎁스→컬러 소프트웨어 정렬 (v2 신설, core `depth_align.py`, 순수 numpy)
Astra Pro의 컬러는 OpenNI2 뎁스 장치와 별개인 UVC 모듈이라, 드라이버 정렬 토픽(`aligned_depth_to_color`)을 기대할 수 없다. OpenNI2 쪽 하드웨어 D2C는 OpenNI2가 다루는 컬러 스트림 기준이라 UVC 1280×720 컬러와 맞는다는 보장이 없다 [추정]. 그래서 정렬을 core에서 직접 한다.
- 입력: 뎁스 float32 [m] (Hd×Wd), `intr_depth`, `intr_color`, `DepthExtrinsics(R, t)`, `decimate`.
- 처리: (1) 뎁스 픽셀을 `decimate` 간격으로 골라 유효값(0·NaN 아님)만 뎁스 내부 파라미터로 3D 역투영, (2) `p_c = R·p_d + t`, (3) 컬러 내부 파라미터로 투영해 반올림, (4) 컬러 크기(Hc×Wc) 배열에 **z-버퍼(가까운 값 우선)**로 기록, (5) `decimate`만큼 생긴 빈 칸을 `fill_radius=decimate` 정사각 최소값 필터로 메운다(0은 무효로 유지). 왜곡 계수는 쓰지 않는다(Astra 계열 렌즈 왜곡이 작다고 보고 단순화 [추정]. 10.5 검증에서 오차가 크면 컬러 영상을 미리 undistort하는 옵션 추가).
- 출력: 컬러와 같은 크기의 float32 [m], 무효는 0.
- `DepthAligner`는 생성 시 역투영 격자를 미리 계산해 두고 `align(depth)`만 프레임마다 호출한다. 결정론: 같은 입력 → 같은 출력(z-버퍼 동률은 인덱스 순).
- 보정 파일 `astra_pro_extrinsics.yaml` 형식: `{depth_K: [9], depth_size: [W,H], color_K: [9], color_size: [W,H], R: [9], t: [3](m), rms_px: float, date: str, note: str}`. 내부 파라미터는 CameraInfo가 오면 그것을 우선하되, 크기가 다르면 파일 값을 쓰고 경고한다.
- **보정 절차(B0-4)**: 체커보드(예: 9×6, 25 mm)를 IR 영상과 컬러 영상에서 동시에 찍는다. IR 영상은 OpenNI2 IR 스트림으로 받고 **프로젝터 패턴을 가리거나 끄고**(구조광 점 때문에 코너 검출이 깨짐) 할로겐/햇빛 간접광을 쓴다. OpenCV `stereoCalibrate`(내부 파라미터 고정 또는 동시 추정)로 R, t를 구한다. 합격: 재투영 RMS ≤ 0.5 px [제안], 10.5절 정렬 검증 통과. 보정 스크립트는 `src/ash_e_perception/ash_e_perception/tools/calib_astra_extrinsics.py`(ROS 불필요, OpenCV만).
- **IR과 뎁스 좌표 주의**: 일부 구조광 카메라는 뎁스 영상이 IR 영상보다 몇 픽셀 어긋나 있다 [추정]. 보정 후 평평한 벽·사람 실루엣으로 컬러-뎁스 가장자리를 겹쳐 보고 어긋나면 `depth_pixel_offset_uv: [du, dv]` 보정값(기본 [0,0])을 yaml에 넣는다.

---

## 6. 뎁스카메라: Orbbec Astra Pro (v2, Q1 확정)

### 6.1 특성 (조사 결과, 실물로 재확인 필요)
| 항목 | 값 | 출처·신뢰도 |
| --- | --- | --- |
| 방식 | 구조광(IR 패턴 프로젝터 + IR 카메라) | Orbbec 제품군 설명 |
| 뎁스 해상도/FPS | 640×480 @30 fps (320×240 모드도 있음) | Astra 계열 사양. Astra Pro 단독 사양서는 못 찾음 [추정 일부] |
| 유효 거리 | 0.6 ~ 8 m (제조사 표기). 최소 거리 0.6 m 미만은 사각(값 0) | Orbbec Astra 시리즈 페이지·Pro Plus 사양 |
| 정확도 | ±3 mm @1 m (제조사). 원거리는 거리 제곱에 비례해 악화, 5 m 이상은 수 cm~10 cm 이상 | 1 m 값은 제조사, 원거리 값은 구조광 일반 특성에 따른 **[추정]** |
| 뎁스 FOV | 약 H58.4° × V45.5° | Astra 시리즈 페이지 |
| 컬러 | **뎁스와 별개인 UVC(V4L2) 웹캠 모듈.** OpenNI2로는 컬러가 안 나오고 usb_cam·libuvc 같은 UVC 드라이버로 받는다. 해상도는 1280×720 지원으로 알려져 있으나 [추정], FOV 약 60~66° [추정] | ROS Answers·Orbbec 포럼(오래된 자료) |
| 정렬(registration) | 컬러가 별도 UVC라 드라이버가 정렬 뎁스를 보장하지 않음. ros2_astra_camera에 `depth_registration`(하드웨어 D2C) 파라미터가 있으나 Astra Pro+UVC 컬러 조합에서 동작은 확인 못 함 | ros2_astra_camera README. **결론: 소프트웨어 정렬(5.8) 기본** |
| 실외·직사광 | 실내용(운용 환경 Indoor로 표기되는 계열). 햇빛의 IR이 패턴을 덮어 뎁스가 대부분 무효가 될 수 있음 | Orbbec 제품 페이지의 Indoor 표기. 실외 동작 정도는 **[추정]** |
| 인터페이스 | USB 2.0 [추정] | — |
| 다른 Astra Pro 센서와의 간섭 | 같은 공간에 구조광 카메라 여러 대면 패턴 간섭 | 일반 특성 |

### 6.2 설계에 반영한 것
| v1 | v2 | 이유 |
| --- | --- | --- |
| 정렬 뎁스 토픽(`aligned_depth_to_color`) 구독 | 비정렬 뎁스 + 뎁스 CameraInfo 구독, core `DepthAligner`로 정렬 | 컬러가 별도 UVC |
| `acquire_range_m=6.0`, `release_range_m=7.0` | **5.0 / 5.8** | 5 m 이상에서 뎁스 품질 급락, 담배 인식 자체도 5 m 이상 기대하기 어려움(합격선 recall 구간도 ≤5 m). 히스테리시스 간격 0.8 m(5 m에서 뎁스 노이즈 + 걸음 한두 번) |
| `depth_min_m=0.3`, `depth_max_m=8.0` | **0.6 / 6.0** | 사각 0.6 m, 6 m 이상 신뢰 불가 |
| `S_dist` 1.5~6.0 m 선형 | 1.5~5.0 m 선형 (`far_m=5.0` 키 신설, 기본은 `acquire_range_m`와 같게) | 획득 범위와 맞춤 |
| 실기 `hfov_deg` = 카메라 값 | 컬러 보정 후 `hfov = 2·atan(W / (2·fx))`로 계산해 priority.yaml에 기록 | 공식 FOV가 불명확 |
| 실외 주간 가정 | 유지(Q7 기본값)하되 **직사광 시 뎁스 무효 → 프록시 자동 전환**을 정상 동작으로 정의. 래퍼는 10 s마다 뎁스 유효 비율을 로그로 남긴다 | Astra Pro 실내용 |

### 6.3 ROS2 Jazzy + Ubuntu 24.04 + arm64 드라이버 후보 (B0에서 결정)
| ID | 후보 | 현황(조사) | 설치 리스크 | 판정 |
| --- | --- | --- | --- | --- |
| D1 | `orbbec/ros2_astra_camera` (OpenNI2 기반, 컬러는 `use_uvc_camera`로 UVC 사용, `astrapro` 런치 존재) | README가 Galactic 기준, 2023년 이후 활발한 유지보수 흔적 적음. **Jazzy·arm64 공식 지원 표기 없음** | 높음: 소스 빌드 시 Jazzy API 변경으로 컴파일 수정이 필요할 수 있음, 동봉 OpenNI2 arm64 라이브러리·udev 규칙 확인 필요 | **1순위 시도** (시간 상자 2일) |
| D2 | OrbbecSDK_ROS2 (v1 main / v2) | v2는 OpenNI 프로토콜 구형 장치를 지원하지 않음. v1 main의 지원 목록에 Astra Pro Plus·Astra Mini Pro는 있으나 **원조 Astra Pro는 없음** | 매우 높음 | 원칙적으로 제외. 실물이 사실 Astra Pro **Plus**로 확인되면(N2) v1 main을 1순위로 재검토 |
| D3 | **자체 얇은 드라이버 노드** `ash_e_camera`: 뎁스 = Orbbec OpenNI2 SDK(arm64 Linux 배포본) + Python 바인딩(`openni` pip 패키지), 컬러 = Jazzy apt의 `usb_cam` 또는 `v4l2_camera` 노드 | OpenNI2 + 별도 UVC 조합은 ROS1 시절부터 쓰인 방식. 바인딩·SDK arm64 동작은 미확인 [추정] | 중간: OpenNI2 SDK arm64 배포본 확보가 관건. ROS 쪽은 단순 | **2순위** (D1 실패 시) |
| D4 | 컬러 전용 운용: UVC 컬러만 쓰고 `use_depth:=false` | 항상 가능 | 낮음 | 최후 대안. 거리는 프록시. 데모 가능하나 거리 정확도 저하를 보고서에 명시 |
- 어느 후보든 perception 노드는 4.2절 파라미터로 토픽 이름만 바꿔 붙는다. D3의 노드 이름·토픽은 `/camera/depth/image_raw`, `/camera/depth/camera_info`(frame_id `camera_depth_optical_frame`), 컬러 `/camera/color/image_raw`, `/camera/color/camera_info`(frame_id `camera_color_optical_frame`)로 맞춰 기본값이 그대로 통하게 한다.
- **조기 위험 감소(선택)**: 단계 A 중에 Windows PC에서 Orbbec OpenNI2 SDK로 Astra Pro 뎁스를 열어 보고(A12, 선택), 컬러 UVC가 일반 웹캠처럼 잡히는지 확인한다. 잡히면 단계 A 평가 영상 일부를 **Astra Pro 컬러로** 찍어 웹캠과의 영상 차이(도메인 차이)를 미리 본다.

launch 인자 기본값(`config/camera_astra_pro.yaml`, D1/D3 공통 가정 [추정], B0 결과로 갱신):
| 인자 | 기본값 |
| --- | --- |
| `color_topic` | `/camera/color/image_raw` |
| `color_info_topic` | `/camera/color/camera_info` |
| `depth_topic` | `/camera/depth/image_raw` |
| `depth_info_topic` | `/camera/depth/camera_info` |
| `depth_alignment` | `software` |
| `extrinsics_file` | `config/astra_pro_extrinsics.yaml` |

---

## 7. 우선순위 정책 (`ash_e_core/priority.py`)

### 7.1 후보 자격 (eligible)
아래를 모두 만족해야 타깃 후보가 된다. 자격이 없는 후보도 `ranking`에 사유와 함께 넣는다.
1. `state ≠ NONE` (아니면 NOT_CONFIRMED)
2. `state_confidence ≥ min_state_conf=0.40` (아니면 LOW_CONFIDENCE)
3. 거리가 있으면 `distance_m ≤ acquire_range_m=5.0` (v2: 6.0→5.0) (아니면 OUT_OF_RANGE). `distance_source=NONE`이면 거리 조건은 통과시키고 `S_dist=0`
4. 쿨다운이 아님 (아니면 COOLDOWN)

### 7.2 점수식
```
score = w_state·S_state + w_dist·S_dist + w_conf·S_conf + w_center·S_center + w_stay·S_stay     (0..1)
```
| 항 | 정의 | 가중치 기본값 |
| --- | --- | --- |
| `S_state` | SMOKING 1.0, HOLDING `holding_value=0.7` | `w_state=0.35` |
| `S_dist` | d ≤ `near_m=1.5` → 1.0, `near_m`~`far_m=5.0` 선형으로 1→0, `far_m` 초과 0 (v2: 6.0→5.0) | `w_dist=0.30` |
| `S_conf` | `state_confidence` | `w_conf=0.10` |
| `S_center` | `1 − |bearing_rad| / (hfov_rad/2)`, 0..1로 자름 (`hfov_deg` 파라미터: 웹캠 70 [현장 확인], 실기는 Astra Pro 컬러 보정값으로 계산, 6.2절) | `w_center=0.10` |
| `S_stay` | `min(stationary_s / stay_full_s(10 s), 1)` | `w_stay=0.15` |
가중치 합은 1.0이다. 로드할 때 합이 1이 아니면 정규화하고 경고를 남긴다. 동점이면 `distance_m`이 작은 쪽, 그다음 `track_id`가 작은 쪽을 고른다(결정론).

### 7.3 상태 머신
```
          후보 있음(최고점)                    더 나은 후보: 마진·유지·확인 조건 충족, 잠금 아님
 IDLE ─────────────────────► TRACKING(t) ─────────────────────────────► TRACKING(t')  [SWITCHED_BETTER]
  ▲   [ACQUIRED]               │  │  │  │
  │                            │  │  │  └ 피드백 수신(DONE/REFUSED/ABORTED/UNREACHABLE) → 해제 [FEEDBACK_RELEASED]
  │                            │  │  └ 타깃 state NONE이 5 s 지속 → 해제 [STATE_CLEARED]
  │                            │  └ distance_m > release_range_m(5.8)이 1.0 s 지속 → 해제 [OUT_OF_RANGE]
  │                            └ 타깃 미관측 2.0 s → 해제 [LOST_TIMEOUT]
  │                    해제 시: 해당 ID 쿨다운 등록 → 같은 평가에서 즉시 재선택(남은 자격 후보 최고점)
  └──────────── 후보 없음 / 입력이 input_timeout(1.0 s) 이상 끊김 [INPUT_TIMEOUT, 쿨다운 없음]
```
- 해제 뒤 **같은 평가 안에서** 다음 후보를 고른다. 이벤트는 해제 사유를 기록하고 `previous_target_id`에 이전 ID를 둔다. 새 타깃의 ACQUIRED는 별도 이벤트로 남기지 않고 `target_id` 변화로 알 수 있게 한다(한 평가에 이벤트는 하나).
- 거리 히스테리시스: 획득은 5.0 m 이내, 해제는 5.8 m 초과(v2). 경계에서 타깃이 붙었다 떨어졌다 하는 것을 막는다. 뎁스가 무효라 프록시로 바뀐 프레임에서도 같은 규칙을 쓴다(프록시는 오차가 커서 경계 떨림이 늘 수 있으나 1.0 s 지속 조건이 막는다).
- 미관측 중(`target_visible=false`)에는 마지막 위치·점수를 유지하고, 다른 후보로 전환하지 않는다(잠깐 가려진 경우를 고려).

### 7.4 히스테리시스 (타깃 떨림 방지) — 세 조건을 모두 만족해야 전환
1. `score(new) ≥ score(current) + switch_margin` (`switch_margin=0.15`)
2. 현재 타깃을 잡은 지 `min_hold_s=3.0` s 이상
3. 조건 1이 `switch_confirm_s=1.0` s 연속 유지(같은 후보 기준)
4. `locked=false`

### 7.5 쿨다운
| 해제 사유 | 쿨다운 [s] |
| --- | --- |
| LOST_TIMEOUT | `cooldown_lost_s=10` |
| OUT_OF_RANGE | `cooldown_out_of_range_s=30` |
| STATE_CLEARED | `cooldown_state_cleared_s=30` |
| FEEDBACK DONE | `cooldown_done_s=600` |
| FEEDBACK REFUSED | `cooldown_refused_s=300` |
| FEEDBACK ABORTED / UNREACHABLE | `cooldown_aborted_s=60` |
| INPUT_TIMEOUT | 0 |

**한계와 보완:** 트래커 ID는 사람이 가려졌다 다시 나타나면 새로 붙는다. 그래서 ID 기준 쿨다운만으로는 같은 사람에게 다시 갈 수 있다. FEEDBACK DONE·REFUSED에는 **공간 쿨다운**을 함께 건다: 해제 위치에서 `spatial_cooldown_radius_m=1.0` 이내(거리 없으면 방위각 5° 이내)의 새 후보도 같은 시간 동안 자격을 막는다(`spatial_cooldown_enable=true`). 사람 재식별(Re-ID)은 차기 과제다.

### 7.6 API (core, ROS 무관)
- `PrioritySelector(config: PriorityConfig)`
- `update(dets: DetectionArray, now: float) -> TargetStatus` — 입력마다 호출, `now = dets.stamp`
- `tick(now: float) -> TargetStatus | None` — 입력 끊김만 판정, 상태가 바뀌면 반환
- `on_feedback(fb: TargetFeedback, now: float) -> TargetStatus | None`
- `set_lock(locked: bool) -> None`
- 모든 가중치·임계값은 `PriorityConfig` dataclass에 있고 yaml 키 이름과 같다.

---

## 8. 패키지 · 디렉터리 구조

```
26PJT_ASH-E/
├─ models/                         # git 미추적. README.md만 추적
│   └─ README.md                   # pose.onnx, cig_roi.onnx (+ *.ncnn.param/bin) 명세와 내보내기 방법
├─ src/
│   ├─ ash_e_core/                 # ROS·Windows 전용 import 금지 (cv2, numpy, onnxruntime, yaml만)
│   │   ├─ package.xml, setup.py, resource/ash_e_core   # colcon과 pip 양쪽에서 설치 가능
│   │   ├─ ash_e_core/
│   │   │   ├─ types.py            # 3장 (계약). 소유: perception-dev
│   │   │   ├─ config.py           # PerceptionConfig, PriorityConfig + yaml 로더 (평면 dict)
│   │   │   ├─ serialize.py        # JSONL 직렬화 (3.8)
│   │   │   ├─ backends.py         # OnnxModel / NcnnModel / StubModel
│   │   │   ├─ detector.py         # PoseModel, CigaretteRoiModel (전·후처리, NMS)
│   │   │   ├─ roi.py              # 입·손 ROI, 머리 크기
│   │   │   ├─ state.py            # 담배 박스 배정 → raw_state
│   │   │   ├─ tracker.py          # IoU 트래커, stationary_s
│   │   │   ├─ stabilizer.py       # 시간창 투표, 래치
│   │   │   ├─ distance.py         # 프록시 거리, 뎁스 중앙값, 3D 투영
│   │   │   ├─ depth_align.py      # (v2) DepthExtrinsics 로더, DepthAligner (5.8). 소유: perception-dev
│   │   │   ├─ pipeline.py         # PerceptionPipeline.process (프로토타입·ROS 공용 진입점)
│   │   │   ├─ priority.py         # 7장. 소유: priority-dev
│   │   │   ├─ viz.py              # 검출 오버레이 (perception-dev)
│   │   │   └─ viz_priority.py     # 순위·타깃 오버레이 (priority-dev)
│   │   └─ test/                   # pytest (Windows에서 실행)
│   ├─ ash_e_msgs/                 # 단계 B. ament_cmake, msg 4종
│   ├─ ash_e_perception/           # 단계 B
│   │   ├─ ash_e_perception/perception_node.py, convert.py
│   │   ├─ ash_e_perception/tools/video_to_bag.py, dump_jsonl.py
│   │   ├─ ash_e_perception/tools/calib_astra_extrinsics.py, depth_check.py   # (v2) 5.8, 10.5
│   │   ├─ launch/perception.launch.py (카메라 토픽 파라미터 인자, v2)
│   │   └─ config/perception.yaml  # ros__parameters 아래 core 키 그대로 + 래퍼 전용 키
│   │       config/camera_astra_pro.yaml, astra_pro_extrinsics.yaml       # (v2) 6.3, 5.8
│   ├─ ash_e_camera/               # (v2, 조건부) D3 자체 OpenNI2 뎁스 드라이버. B0에서 D1 실패 시에만 생성
│   └─ ash_e_priority/             # 단계 B
│       ├─ ash_e_priority/priority_node.py, convert.py
│       ├─ launch/priority.launch.py, ash_e_all.launch.py (perception 포함 전체 기동)
│       └─ config/priority.yaml
├─ prototype/                      # 단계 A, Windows
│   ├─ run_webcam.py               # --camera N | --video path, --config-dir, --log out.jsonl, --record out.mp4, --no-throttle
│   ├─ eval_images.py              # 프레임 단위 평가 (raw)
│   ├─ eval_clips.py               # 클립 단위 평가 (안정화 포함)
│   ├─ bench.py                    # 속도 측정 (Windows·RPi5 모두 실행 가능, ROS 불필요)
│   ├─ sim_priority.py             # 가짜 다수 인원 시나리오로 우선순위 시각화 (카메라 불필요)
│   ├─ config/perception.yaml, priority.yaml   # 평면 키
│   └─ requirements.txt            # numpy<2, opencv-python, onnxruntime, pyyaml
├─ training/                       # 학습 전용 (Ultralytics는 여기에서만)
│   ├─ fetch_public_datasets.py    # (v2) 9A.2 자동 다운로드·라이선스 기록
│   ├─ merge_dedup.py, make_splits.py   # (v2) 중복 제거, 참가자 단위 분할 (9A.5)
│   ├─ build_roi_dataset.py, train_cig_roi.py, export_onnx.py
│   └─ README.md
├─ acceptance/                     # (v2) 잠금 대상. 합격선·hold-out 해시 (9A.5)
│   ├─ acceptance.yaml             # 9.4 합격선 그대로
│   └─ holdout_manifest.sha256
└─ data/                           # git 미추적. 9A.5 디렉터리 규칙
    ├─ public/<dataset>/           # 공개 데이터 원본 + LICENSE.txt
    ├─ raw/<participant_id>/<session>/   # 자체 촬영 원본 영상
    ├─ labeled/                    # 프레임 + YOLO 라벨
    ├─ splits/                     # train.txt, val.txt (참가자 목록 포함)
    ├─ eval/dev/                   # 튜닝용 평가 클립(9.2 형식)
    ├─ eval/holdout/               # 최종 보고 전용 (읽기 전용)
    └─ consent/                    # 동의서 스캔(데이터와 분리, 접근 제한)
```

**설정 키 규칙:** core 설정의 키 이름이 원본이다. `prototype/config/*.yaml`은 평면 키, ROS `config/*.yaml`은 `<node_name>: ros__parameters:` 아래에 같은 키를 둔다. 래퍼 전용 키(4.2절 표의 `color_topic`, `color_info_topic`, `depth_topic`, `depth_info_topic`, `use_depth`, `depth_alignment`, `extrinsics_file`, `color_frame_id_override`, `sync_slop_s`, `input_qos`, `equivalence_mode`, `publish_debug_image`, 그리고 `publish_extrinsics_tf`=false)는 `ros.` 접두어 없이 별도로 두되 core 키와 겹치지 않게 한다. QA는 두 파일의 core 키 집합이 같은지 검사한다.

**인식 설정 키(기본값):** `pose_model_path=models/pose.onnx`, `cig_model_path=models/cig_roi.onnx`, `backend=onnxruntime`, `num_threads=4`, `pose_input=320`, `roi_input=192`, `person_conf_thresh=0.40`, `min_person_h_px=60`, `max_persons=8`, `max_roi_persons=4`, `roi_every_n=1`, `kp_conf_thresh=0.30`, `mouth_roi_scale=1.6`, `hand_roi_scale=1.4`, `min_roi_px=24`, `cig_conf_thresh=0.35`, `smoking_radius=0.7`, `holding_radius=0.9`, `track_iou_thresh=0.3`, `track_max_age_s=1.0`, `stationary_speed_thresh=0.25`, `stab_window_s=1.5`, `stab_min_obs=4`, `confirm_ratio=0.6`, `release_ratio=0.25`, `release_hold_s=1.0`, `smoking_min_obs=2`, `smoking_latch_s=20`, `person_height_m=1.65`, `shoulder_width_m=0.40`, `head_width_m=0.15`, `edge_margin_px=8`, `hfov_deg=70`, `depth_min_m=0.6`, `depth_max_m=6.0`, `depth_min_valid_px=30`, `depth_min_valid_ratio=0.15`, `depth_roi_shrink=0.1`, `depth_align_decimate=2`, `process_rate_hz=8`, `frame_id=webcam_optical`. (v2: `depth_min_m`·`depth_max_m` 변경, 뒤의 세 키 추가. `depth_align_decimate`는 core `DepthAligner` 생성 인자라 core 키로 둔다.)

**우선순위 설정 키(기본값):** `w_state=0.35`, `w_dist=0.30`, `w_conf=0.10`, `w_center=0.10`, `w_stay=0.15`, `holding_value=0.7`, `near_m=1.5`, `far_m=5.0`(v2 신설), `acquire_range_m=5.0`(v2), `release_range_m=5.8`(v2), `out_of_range_hold_s=1.0`, `min_state_conf=0.40`, `hfov_deg=70`, `stay_full_s=10`, `switch_margin=0.15`, `min_hold_s=3.0`, `switch_confirm_s=1.0`, `lost_timeout_s=2.0`, `state_cleared_s=5.0`, `input_timeout_s=1.0`, `cooldown_lost_s=10`, `cooldown_out_of_range_s=30`, `cooldown_state_cleared_s=30`, `cooldown_done_s=600`, `cooldown_refused_s=300`, `cooldown_aborted_s=60`, `spatial_cooldown_enable=true`, `spatial_cooldown_radius_m=1.0`, `spatial_cooldown_bearing_deg=5`.

**색 순서·단위 규약:** core는 BGR uint8 컬러, float32 미터 뎁스만 받는다. ROS 래퍼는 `cv_bridge.imgmsg_to_cv2(msg, 'bgr8')`, 뎁스 `16UC1`(mm)은 ×0.001, `32FC1`은 그대로 쓴다.

---

## 9. 프로토타입(단계 A) 평가 계획

### 9.1 촬영 시나리오 (동의를 받은 배우, 불붙이지 않은 소품 허용)
| ID | 시나리오 | 기대 라벨 | 목적 |
| --- | --- | --- | --- |
| S1 | 서서 흡연 동작 반복 (입 ↔ 손) | smoking | 기본 재현율, 래치 |
| S2 | 담배·꽁초를 손에 쥠 (내린 손, 가슴 높이) | holding | holding 재현율 |
| S3 | 펜·빨대·젓가락·막대사탕을 입에 묾 / 손에 쥠 | none | 유사물 오검출 |
| S4 | 휴대폰 통화, 손으로 입 가리기, 음료 마시기 | none | 동작 편향 오검출 |
| S5 | 2~4명 혼재 (흡연자 1~2명 + 비흡연자) | 사람별 | 사람 배정, 우선순위 |
| S6 | 거리 1 / 2 / 3 / 4 / 5 m 고정 촬영 | 사람별 | 거리별 재현율 |
| S7 | 실내 형광등 / 실외 주간 / 역광 / 저녁 | 사람별 | 조명 강건성 |
| S8 | 걷기 + 흡연, 정지 + 흡연 | smoking | 정지 시간·트래킹 |
| S9 | 측면·뒷모습 흡연 | smoking/holding | 키포인트 결손 폴백 |
| S10 | 흡연자가 멀어짐 / 화면 밖으로 나감 | — | 타깃 전환 데모 |
| S11 (v2) | 액상형 전자담배(pod·모드형) 흡입 동작, 손에 쥠 | none (`category: ecig_liquid`) | 비대상 오검출. 9.4 "유사물 오확정"에 포함 |
| S12 (v2) | 궐련형 전자담배 기기(스틱 꽂은 상태) 흡입 동작, 손에 쥠 | none (`category: ecig_heated`) | 비대상 오검출. **별도 집계·보고만, 합격 판정에서 제외**(기기 끝에 나온 스틱 필터가 담배와 시각적으로 거의 같아 현 방식의 한계를 보는 용도) |
최소 분량: (v2.1) 평가 참가자 1인당 분량과 `capture.py` 키 대응은 **9A.3 표 B**를 따른다(v2의 "배우 3명 이상, 합계 30분 이상"은 폐기). 평가용 프레임·클립은 학습에 쓰지 않는다. 클립은 `dev`(튜닝용, **dev 평가 참가자**로 촬영)와 `holdout`(최종 보고용, holdout 참가자로만 촬영)로 나눈다(9A.5). 두 그룹 모두 **학습에 쓰지 않은 사람**이다. 공개·COCO·합성 데이터는 dev·holdout 어디에도 넣지 않는다. 9.4 합격 판정은 **holdout 결과로만** 한다. S11·S12 소품(전자담배 기기)이 없으면 그 시나리오는 "미촬영"으로 보고하고 판정에 넣지 않는다. S5·S10(다인)은 등장 인물이 모두 같은 그룹일 때만 쓰므로, holdout 참가자 2명이 함께 찍어야 한다(N8).

(v2.1) `capture.py` 키와 시나리오 ID 대응: 키 `1` holding = S2, `2` mouth = S1, `3` none = 담배 없는 평상 동작(`category: plain`), `4` similar = S3, `5` gesture = S4, `6` ecig_liquid = S11, `7` ecig_heated = S12. S6(거리)·S9(각도)는 `capture.py`의 거리 태그(`d`)·각도 태그(`c`)로, S7(조명)은 세션 메모로 기록한다. S5·S8·S10은 키가 없으므로 `run_webcam.py --record`로 클립을 녹화한다. `capture.py`는 프레임(jpg, 기본 2 fps)만 저장하므로 프레임 단위 지표(9.3-1·2)에 쓰고, 안정화가 필요한 클립 지표(9.3-3·6)는 녹화 클립(9.2 형식)으로 잰다.

### 9.2 라벨 형식
- `data/eval/{dev|holdout}/clips/<clip_id>.mp4` (v2: dev/holdout 분리)
- `data/eval/{dev|holdout}/labels/<clip_id>.json`: `{"fps": float, "camera": "webcam|astra_pro_color", "participants": ["P03", ...], "persons": [{"person_ref": "p1", "segments": [{"t0": s, "t1": s, "label": "smoking|holding|none", "category": "cigarette|similar_object|gesture|ecig_liquid|ecig_heated|plain"}], "anchor": {"t": s, "bbox_xyxy": [...]}}]}` (v2: `camera`, `participants`, `category` 추가. `category` 생략 시 label이 smoking/holding이면 `cigarette`, none이면 `plain`) — `anchor`는 그 사람의 한 시점 박스다. 평가 스크립트는 anchor와 IoU가 가장 큰 트랙을 그 사람으로 매칭하고 이후 트랙 ID를 따라간다(ID가 바뀌면 그 구간에서 다시 IoU 매칭).
- 프레임 단위 평가용: 클립에서 0.5 s 간격으로 프레임을 뽑아 세그먼트 라벨을 상속한다(`eval_images.py --from-clips`). 이미지 폴더 평가도 지원한다: `data/eval/images/*.jpg` + 같은 이름의 `.json`(`[{bbox_xyxy, label}]`).
- 라벨 기준: smoking = 담배가 입에 닿아 있음, holding = 담배·꽁초가 손에 있음, 그 외 none. 담배가 화면상 보이지 않으면(손에 가려짐) none으로 하고 `"occluded": true`를 붙여 별도로 집계한다.

### 9.3 지표
1. **프레임 단위(raw_state)**: 3×3 혼동행렬, 클래스별 precision/recall/F1. 거리 구간별(≤2, 2~4, 4~6 m, 프록시 기준) 재현율.
2. **이진 지표(담배 사람 vs 아님)**: positive = smoking ∪ holding. precision/recall. 우선순위에서 가장 중요한 지표다.
3. **안정화 상태(state) 클립 단위**: 양성 구간 중 확정된 시간 비율, **확정까지 걸린 시간**(중앙값, 95% 분위), none 전용 클립(S3·S4)의 **분당 오확정 횟수**.
4. **오검출 상위 사례**: 신뢰도가 높은 FP 20건과 FN 20건의 크롭 이미지를 `_workspace/eval_out/`에 저장한다.
5. **속도**: PC 측정값과 **RPi5 실측값**(bench.py를 RPi5에서 ONNX Runtime·NCNN으로 실행)을 따로 기록한다. RPi5 실측이 불가능하면 PC × 5~10 추정치를 쓰고 "추정"으로 표시한다.
6. **우선순위 데모**: S5·S10 클립의 타깃 ID 타임라인과 이벤트 로그, 떨림 횟수(10 s 안에 전환 2회 이상).
7. (v2.1) **표본 수와 불확실성**: 모든 지표 옆에 분모(참가자 수, 클립 수, 프레임 수, 노출 시간[분])와 95% 신뢰구간을 적는다. 비율 지표는 Wilson 구간(프레임 기준, 낙관적)과 **클립 단위 부트스트랩** 구간(클립을 재표집, 2,000회, 시드 고정)을 함께 낸다. 참가자별 값도 따로 표로 낸다. 오확정 횟수는 관측 0회일 때 rule of three(95% 상한 ≈ 3 / 노출 시간)로 상한을 적는다.
8. (v2.1) **오확정·누락 사례 목록**: holdout·dev의 오확정(none 클립에서 양성 확정) 전 건과 놓친 양성 구간 전 건을 클립 ID·시각·시나리오·거리 태그·조명과 함께 목록으로 낸다(9.3-4의 상위 20건과 별개, 전수).

### 9.4 합격선 (v2: 사용자 **확정**, 2026-10-27. 값은 v1 제안 그대로)
판정은 holdout 클립으로만 한다. 이 표는 `acceptance/acceptance.yaml`에 그대로 옮기고 잠근다(9A.5). 거리 구간은 단계 A에서는 프록시 거리 기준이다.
| 지표 | 확정값 |
| --- | --- |
| 이진 precision (state, ≤4 m) | ≥ 0.90 |
| 이진 recall (state, ≤3 m) | ≥ 0.80 |
| 이진 recall (state, 3~5 m) | ≥ 0.60 |
| smoking/holding 구분 정확도 (참 양성 중) | ≥ 0.75 |
| 유사물·동작 클립 오확정 | ≤ 1회 / 10분 |
| 확정 시간 중앙값 | ≤ 2.0 s |
| RPi5 처리율 (사람 3명, ONNX Runtime 또는 NCNN) | ≥ 5 Hz |
| 우선순위 떨림 (S5) | 0회 |

### 9.4.1 판정 해석 (v2.1 신설, 합격선 수치는 그대로)
holdout이 2~3명이라 합격선을 넘었다는 사실이 다른 사람·장소·카메라로 일반화된다고 볼 수 없다. 그래서 판정 표기와 보고 형식을 다음과 같이 정한다. 이 규칙은 합격선 값을 바꾸지 않으므로 `acceptance.yaml` 해시에 영향이 없다. 보고 형식만 `eval_clips.py --final` 출력에 반영한다.
- **판정 기준**: 9.4 표의 각 지표를 holdout **점추정값**으로 비교한다(v2와 같음).
- **표기**: 모든 지표가 통과하면 **"예비 합격 (holdout n=2명, 클립 k개, 양성 노출 t분)"**처럼 표본 수를 붙여 쓴다. "합격"이라는 단어만 단독으로 쓰지 않는다. 하나라도 미달이면 "불합격"이다.
- **함께 낼 것**: 9.3-7의 95% 신뢰구간(프레임 Wilson + 클립 부트스트랩), 참가자별 값, 9.3-8 사례 목록, holdout 실행 횟수(9A.5).
- **주의 표시**: (1) 신뢰구간 하한이 합격선보다 낮은 지표, (2) 참가자 한 명이라도 합격선에 못 미치는 지표, (3) 오확정 지표의 노출 시간이 10분 미만이라 "≤ 1회/10분"을 판정할 힘이 없는 경우(0회여도 rule of three 상한을 함께 적는다)는 표에 "불확실"로 표시한다. "불확실" 표시가 있어도 점추정이 통과하면 예비 합격이지만, 사용자가 게이트(11장)에서 이 표시를 보고 판단한다.
- **금지 표현**: "일반 사용자에게서 precision 0.9", "실환경 검증 완료" 같은 일반화 주장. 보고서에는 "참가자 2~3명, 실내/실외 어느 조건, 웹캠 모델 X에서 측정"이라고 조건을 적는다.
- **dev와의 비교**: dev 값과 holdout 값의 차이가 0.10을 넘는 지표가 있으면 과적합 가능성으로 적는다.

### 9.5 튜닝 순서
(v2) 튜닝은 `data/eval/dev`와 학습 val로만 한다. holdout은 튜닝 반복 중에 보지 않는다(9A.5). (v2.1) dev는 평가 참가자 1명뿐이라 dev에 맞춘 임계값이 그 사람에게 치우칠 수 있다. 임계값을 고를 때는 dev 값과 학습 val(공개·COCO·본인 세션 val 블록) 값을 함께 보고, dev 하나에서만 좋아지는 변경은 채택하지 않는다.
`cig_conf_thresh` → `smoking_radius`/`holding_radius` → `confirm_ratio`/`stab_window_s` → 데이터 보강(오검출 사례 기반 하드 네거티브) → 모델 교체(5.2의 C안 비교). 우선순위 가중치는 프록시 거리를 쓰므로 S5 데모가 상식적으로 동작하는 수준까지만 맞추고 최종 튜닝은 단계 B 실기에서 한다.

---

## 9A. 담배 데이터 수집 계획 (v2 신설, Q2 답변 반영, v2.1 개정)

사용자 보유 데이터는 없다. 수집 실행은 perception-dev(단계 A 작업 A0)가, 촬영·동의는 사용자가 맡는다. 학습 라벨은 **담배 박스 1클래스(`cigarette`, class id 0)**다(v1 방침 유지, 꽁초 포함).

(v2.1) **데이터 방침(사용자 승인 2026-10-28):**
| 용도 | 구성 | 금지 |
| --- | --- | --- |
| 학습(train/val) | CigDet + COCO val2017 부분집합(음성) + copy-paste 합성(train만) + 본인 1세션 직접 촬영 (+ Roboflow, API 키가 있을 때) | — |
| 평가(dev/holdout) | 학습에 쓰지 않은 직접 촬영 2~3명 | 공개·COCO·합성 데이터, 본인 세션 데이터 |

현재 확보 상태(사실, 2026-10-28 기준 `data/SOURCES.md`·`_workspace/02a_perception_notes.md`): `data/roi_ds_v2` train 양성 ROI 1,625 / 음성 3,641, val 양성 186 / 음성 320. COCO 부분집합 1,164장, 합성 300장. 직접 촬영분은 아직 없음.

### 9A.1 전체 흐름과 자동/사용자 경계
| 순서 | 작업 | 자동화 가능(perception-dev가 바로 실행) | 사용자가 해야 하는 것 |
| --- | --- | --- | --- |
| 1 | 공개 데이터 다운로드 | Mendeley CigDet 직접 다운로드, Roboflow는 API 스크립트로 다운로드·라이선스 기록 | **Roboflow 계정·API 키 발급**(무료)과 환경변수 `ROBOFLOW_API_KEY` 설정. 키가 없으면 Roboflow 분은 건너뛰고 notes에 남김 |
| 2 | 형식 통일·중복 제거·클래스 재매핑 | 전부 자동 | 재매핑 규칙에 애매한 클래스가 있으면 확인 |
| 3 | 공개 데이터만으로 1차 모델 학습 | 자동 | — |
| 4 | 자체 촬영 | 촬영 체크리스트·파일명 규칙·동의서 양식 초안 작성, `capture.py` | (v2.1) **본인 1세션(학습용) 촬영, 평가 참가자 2~3명 모집·동의·촬영, 소품 준비** |
| 5 | 자체 영상 프레임 추출·사전 라벨 | 자동(1차 모델로 사전 라벨) | — |
| 6 | 라벨 검수 | 검수 대상 목록·도구 설정 | **사람이 박스를 검수·수정**(자동 라벨을 그대로 쓰지 않는다) |
| 7 | 참가자 단위 분할·hold-out 지정 | 분할 스크립트 | **dev/hold-out 참가자 지정 승인**(v2.1: 평가 참가자 중 누구를 dev로 둘지) |
| 8 | 평가 클립 라벨(9.2) | 라벨 도구·형식 검사 스크립트 | **구간 라벨 작성/검수** |

### 9A.2 공개 데이터셋 후보 (2026-10-27 조사)
판정 기준: 졸업작품(비공개·비상업) 사용. CC BY 4.0·MIT은 출처 표기 조건으로 **사용 가능**. 라이선스가 확인되지 않거나 페이지 표기와 실제 출처가 의심되면 **사용 보류**. Roboflow 페이지는 이번 조사에서 직접 열람이 막혀(403) 규모를 확인하지 못한 곳이 많다 → 다운로드 시 perception-dev가 규모·라벨 정의를 확인해 notes에 기록한다.
| 데이터셋 | 규모 | 라벨 형식 | 라이선스 | 품질 우려 | 판정 |
| --- | --- | --- | --- | --- | --- |
| CigDet (Mendeley Data, 2024) | 557장 (train 446 / test 111) | YOLO txt, 담배 1클래스(LabelImg) | CC BY 4.0 | 작음. 기존 Kaggle 흡연자 분류 데이터에서 파생된 인터넷 이미지라 근접·고해상도 위주일 가능성 [추정] | **사용 가능** (1순위) |
| Roboflow `mi-privado/cigarette-detection` | 미확인 | 박스(YOLO 내보내기 가능) | MIT (검색 결과 표기) | 규모·라벨 정의 미확인 | **사용 가능(조건부)**: 다운로드 후 라벨이 담배 박스인지 확인 |
| Roboflow `sda-vfqmd/smoking36` | 미확인 | 박스 | CC BY 4.0 (검색 결과 표기) | 클래스가 사람 전체(`smoking`)일 수 있음 | **사용 가능(조건부)**: 담배 박스 클래스만 사용, 사람 박스 데이터면 제외 |
| Roboflow `deyan-markov/cigarette-finder` | 미확인 | 박스 | CC BY 4.0 (검색 결과 표기) | 미확인 | **사용 가능(조건부)** |
| Roboflow `smoking-bycpp/smoking-detection` (v1 참고) | 미확인 | 박스 | 미확인 | — | **사용 보류** |
| Roboflow `itmo-dl/cig`, `aie223objdetection…/cigarette_detection` | 미확인 | 박스 | 미확인 | — | **사용 보류** |
| Roboflow `jeet-work/cigarette_butt_detection` | 미확인 | 박스 | 미확인 | 바닥에 버려진 꽁초 위주로 보여 도메인이 다름 [추정] | **사용 보류** |
| Roboflow `amoura/cigar-detection` | 미확인 | 박스 | 미확인 | 시가(대상 아님) | **사용 보류** |
| Roboflow Smoking-CCTV (9,712장) | 9,712장 | 박스 | — | 비공개·접근 불가로 보고됨 | **사용 불가** |
| Kaggle "Smoker Detection" 분류 데이터 (gts.ai 미러) | 1,120장 (smoking 560 / not 560), 250×250 | 분류(박스 없음) | 미확인 | 박스 없음, 저해상도 | **사용 보류** (CigDet이 이 데이터의 담배 박스판이므로 CigDet으로 대신) |
| Hugging Face `basant18/Smoking-detection-YOLO26s` (가중치) | — | — | 미확인 | 학습 데이터·라이선스 불명 | **사용 보류**(v1의 "초기 실험용" 후보에서 내림. 라이선스 확인되면 파이프라인 동작 확인용으로만) |
| (v2.1) COCO 2017 val 부분집합 (사람 포함) | 1,164장: none 1,000 / similar 164(휴대폰·칼·야구방망이·숟가락·포크·칫솔) | 담배 라벨 없음(빈 라벨). 원본 instances json | annotations CC BY 4.0 [추정, 약관 미확인], 이미지는 Flickr 원본별로 혼재(NC 계열 약 62%, ND 제외하고 받음) | 담배 없는 음성만. 근접 사진 비중, 손·입 근처 가는 물체는 164장뿐(요청 500) | **사용(학습 음성·합성 배경 전용, 내부 학습만, 재배포·평가 사용 금지)**. 이미지 ID % 10 == 0 → val, 나머지 train |
| (v2.1) copy-paste 합성 (`data/synth/`) | 300장 (hand 209 / mouth 91) | YOLO txt, 담배 1클래스 | 파생물: CigDet CC BY 4.0 + COCO 이미지별 조건 | 붙인 경계·조명 불일치, 원거리 크기 분포가 실제와 다를 수 있음 | **train 전용**(val·평가 금지), 실제 양성 대비 비율 상한 0.25 |
- 사용 가능 판정 데이터는 `data/public/<name>/LICENSE.txt`와 `training/README.md`의 출처 표에 이름·URL·라이선스·다운로드 날짜를 남긴다(CC BY 출처 표기 의무). 졸업작품 발표 자료에도 출처를 적는다.
- **재매핑 규칙**: `cigarette`, `cig`, `cigarette_butt`(손에 든 것) → 0. 사람 전체·얼굴 박스(`smoker`, `smoking`, `person`) → 버림. 시가·전자담배 클래스 → 박스를 지우고 이미지는 하드 네거티브 후보로만 둔다.
- **중복 제거**: 지각 해시(pHash, 해밍 거리 ≤ 6)로 데이터셋 간·내부 중복을 지운다. Roboflow 데이터끼리 같은 원본을 공유하는 경우가 많다 [추정].
- **기대 규모**: 공개 데이터는 합쳐 담배 박스 수백~수천 장 수준으로 본다 [추정]. 대부분 근접·정면이라 로봇 시점(1~5 m, 비스듬한 위치)과 다르다. 그래서 **공개 데이터는 1차 모델·사전 라벨용**이고, 합격선 달성은 자체 촬영 데이터에 달려 있다.
- (v2.1) **실제 규모**: Roboflow는 API 키가 없어 받지 않았고, CigDet은 557장(전부 250×250 근접, 음성 이미지 없음)이다. 음성은 COCO 부분집합, 양성 보강은 합성과 본인 세션이 맡는다. 웹캠 시점(1~5 m) 양성은 **본인 세션이 유일한 실사진 출처**이므로, 본인 세션의 거리·각도·조명 다양화가 원거리 재현율을 좌우한다(R11).

### 9A.3 자체 촬영 계획
**안전·윤리 원칙**
- 참가자는 **성인, 서면 동의**를 받은 사람만. 동의서에 목적(졸업작품 인식 모델 학습·평가), 보관 장소·기간(9A.6), 공개 금지, 철회 시 삭제를 적는다.
- **불을 붙이지 않는다.** 미점화 담배(구입이 곤란하면 모형: 흰 종이를 말고 주황 필터 테이프로 만든 길이 8~8.5 cm·지름 0.8 cm 모형) 또는 꽁초 모형을 쓴다. 실제 흡연 촬영은 하지 않는다. 미점화 실물 담배와 모형의 비율은 실물 ≥ 50%를 권장(모형만 쓰면 질감 차이가 생김).
- 학교 금연 구역에서 촬영하면 오해가 없도록 "촬영 중, 미점화 소품" 안내판을 둔다. 지나가는 사람이 찍히지 않게 배경을 정리하고, 찍혔으면 해당 구간을 버린다.

**참가자와 규모 (v2.1 개정, 사용자 승인 2026-10-28)**
- 직접 촬영 총 **3~4명, 각 약 15분**:
  - **본인(예: `P01`) 1세션 → 학습 전용.** 평가에는 쓰지 않는다.
  - **평가 참가자 2~3명 → 학습에 쓰지 않음.** 권장 3명: dev 1명 + holdout 2명. 2명뿐이면 9A.5의 대안 규칙(N7)을 따른다.
- 평가 참가자는 본인과 다른 사람으로, 가능한 한 성별·키·안경·마스크·복장(밝은/어두운 소매)이 본인과 다르게 고른다.
- v2의 "최소 6명, 자체 ROI 양성·음성 각 3,000 이상"은 **폐기**한다. 대신 아래 표 A·B를 최소 수량으로 쓴다.

**표 A. 본인 학습 세션 최소 수량** (`capture.py --participant P01 --session S1`, 자동 저장 2 fps 기준. 15분 = 약 1,800프레임)
| 키 | 시나리오(capture.py) | 대응 S-ID | 최소 프레임 | 시간(2 fps) | 다양화 조건 |
| --- | --- | --- | --- | --- | --- |
| 1 | holding (손에 듦) | S2 | 420 | 3.5분 | 거리 태그 1/2/3/4/5 m 각 ≥ 70, 각도 front/left45/right45/side 모두, 왼손·오른손 각 ≥ 150, 꽁초 ≥ 60, 내린 손·가슴 높이·손가락 사이 |
| 2 | mouth (입에 묾 ↔ 내림 반복) | S1 | 420 | 3.5분 | 거리 1~4 m 각 ≥ 80, 5 m ≥ 40, 각도 front/45°/side, 양손 |
| 3 | none (담배 없음, 평상 동작) | — | 180 | 1.5분 | 손이 보이게, 걷기·서기·앉기 섞기 |
| 4 | similar (유사물, 입·손) | S3 | 330 | 2.75분 | 볼펜·빨대·젓가락·막대사탕·분필·이쑤시개·립밤 중 ≥ 5종, 종류별 ≥ 40, 입과 손 모두 |
| 5 | gesture (담배 없는 손-입 동작) | S4 | 330 | 2.75분 | 통화·마시기·입 가리기·턱 괴기·손가락 물기·하품 중 ≥ 5종, 종류별 ≥ 40 |
| 6 | ecig_liquid | S11 | 60 | 0.5분 | 기기 있을 때만(전원 끔). 없으면 이 수량을 키 4·5에 반씩 더함 |
| 7 | ecig_heated | S12 | 60 | 0.5분 | 기기 있을 때만. 노출 필터가 크게 보이는 프레임은 9A.4대로 제외. 없으면 키 4·5에 더함 |
| | **합계** | | **1,800** | **15분** | 음성 시나리오(키 3~7) 비중 53%. **부정 예시를 줄이지 않는다** |
- 조명은 한 세션 안에서 **최소 2가지**(실내 형광등 + 창가 역광 또는 실외 그늘)로 바꾼다. 각 키의 프레임이 두 조명에 모두 걸치게 한다. 가능하면 장소도 2곳.
- 카메라 높이 1.0~1.2 m(H7). Astra Pro 컬러를 쓸 수 있으면(N5) 세션의 30% 이상을 그것으로 찍는다.
- **ROI 기대치와 최소 기준**: 프레임마다 입 1 + 손 2 ROI가 나오고 포즈 실패·`ignore`·pHash 중복 제거로 일부 빠진다. 본인 세션에서 **양성 ROI ≥ 500, 음성 ROI ≥ 1,500(그중 키 4~7 유래 ≥ 800)**을 최소 기준으로 둔다 [기대 수율은 추정]. 미달이면 같은 방식으로 짧은 보충 세션(`S2`)을 찍는다(여전히 본인, 학습 전용).
- **병합 학습셋 목표**: 기존 `roi_ds_v2`(train 양성 1,625 / 음성 3,641)에 본인 세션을 더해 train **양성 ≥ 2,000, 음성 ≥ 4,800**. 합성 비율은 실제 양성 대비 0.25 상한을 유지한다.

**표 B. 평가 참가자 1인당 최소 수량** (dev·holdout 공통, 약 15분)
| 구분 | 키 / 시나리오 | 수량 | 비고 |
| --- | --- | --- | --- |
| 프레임(`capture.py`, 2 fps, 약 5분) | 1 holding (S2) | 120 | 거리 태그 1/2/3/4/5 m 각 ≥ 20 |
| | 2 mouth (S1) | 120 | 거리 태그 1~5 m 각 ≥ 20 |
| | 3 none | 60 | |
| | 4 similar (S3) | 120 | ≥ 4종 |
| | 5 gesture (S4) | 120 | ≥ 4종 |
| | 6 ecig_liquid (S11) / 7 ecig_heated (S12) | 각 30 | 기기 있을 때만 |
| 클립(`run_webcam.py --record`, 1280×720, ≥ 15 fps, 약 9.5분) | S1 흡연 동작(키 2 동작을 연속으로) | 30 s × 3 (약 1.5 / 3 / 4.5 m) | 3~5 m recall 지표용 |
| | S2 손에 듦(키 1) | 30 s × 2 (2 / 4 m) | |
| | none 평상(키 3) | 60 s × 1 | |
| | S3 유사물(키 4) | 60 s × 2 | 오확정 노출 시간 확보 |
| | S4 동작(키 5) | 60 s × 2 | 오확정 노출 시간 확보 |
| | S11 / S12(키 6 / 7) | 30 s × 1씩 | 기기 있을 때만 |
| | S8 걷기+흡연, S9 측면·뒷모습 | 30 s × 1씩 | |
| 다인 클립(같은 그룹 2명이 함께) | S5 혼재(흡연 1 + 비흡연 1, 역할 교대) | 45 s × 2 | holdout 2명이 함께 찍음(N8). dev 참가자는 다인 클립 없음(같은 그룹 상대가 없음) |
| | S10 멀어짐·화면 이탈 | 30 s × 1 | |
- 1인당 음성 클립(키 3·4·5·6, S12 제외) 노출 시간 ≥ 5.5분 → holdout 2명 합계 ≥ 11분이 되어 "오확정 ≤ 1회/10분" 지표를 최소한으로 잴 수 있다. 그래도 0회 관측의 95% 상한은 약 2.7회/10분이므로 9.4.1의 "불확실" 표시 대상이다.
- 조명은 1인당 최소 2가지(본인 세션과 다른 장소면 더 좋다). 평가 촬영 장소가 본인 세션 장소와 같으면 보고서에 적는다(배경 누수 가능성, N9).

**다양성 매트릭스 (본인 학습 세션 기준. 평가 참가자는 표 B 범위에서 가능한 만큼)**
| 축 | 수준 | 비고 |
| --- | --- | --- |
| 거리 | 1 / 2 / 3 / 4 / 5 m (바닥 테이프 표시) | 거리별 수량은 표 A·B (v2의 "거리별 최소 1분"을 대체) |
| 각도 | 정면 / 좌·우 45° / 측면 90° / 뒷모습 | 뒷모습은 holding만 의미 |
| 동작 | 입에 묾(smoking) / 입↔손 반복 / 손에 듦(내린 손, 가슴 높이, 손가락 사이) / 꽁초 쥠 | 왼손·오른손 모두 |
| 조명 | 실내 형광등 / 실외 그늘 / 실외 직사광 / 역광 / 해질녘 | (v2.1) 한 세션에서 다 못 하므로 최소 2가지(표 A). 직사광은 Astra Pro 뎁스 한계 확인도 겸함 |
| 카메라 | 프로토타입 웹캠 / **Astra Pro 컬러(가능하면, 세션의 30% 이상)** | 실기 카메라와의 도메인 차이 축소 |
| 카메라 높이 | 1.0~1.2 m (H7) | 로봇 시점 |

**하드 네거티브(유사물·동작) — 같은 세션에서 촬영, 담배는 화면에 없음**
- 유사물: 볼펜, 빨대, 젓가락, 막대사탕, 하얀 분필, 이쑤시개, 립밤.
- 동작: 휴대폰 통화, 음료 마시기, 손으로 입 가리기·턱 괴기, 손가락 물기, 마스크 만지기, 하품.
- **전자담배(Q5: 대상 아님)** — 9A.4 규칙대로 처리.

### 9A.4 전자담배 처리 (Q5 판단)
| 대상 | 학습 처리 | 평가 처리 | 근거 |
| --- | --- | --- | --- |
| 액상형 전자담배(pod·모드·일회용) | **하드 네거티브**(박스 없음, 이미지는 음성 ROI로 학습) | S11, `none`, 9.4 "유사물 오확정"에 포함 | 모양·색이 담배와 달라 구분 학습이 가능하고, 오검출 시 로봇이 비대상에게 가는 비용이 크다 |
| 궐련형 전자담배 기기 + 꽂힌 스틱(IQOS 등) 사용 장면 | **하드 네거티브**. 단 기기 밖으로 나온 스틱 필터 부분이 크게 보이는 프레임(필터 길이 > 기기 폭)은 학습에서 제외 | S12, `none`, **별도 집계만**(합격 판정 제외) | 기기에 꽂힌 상태는 기기 몸체로 구분 가능하지만, 노출된 필터는 담배 필터와 같아 억지로 음성으로 가르치면 진짜 담배 재현율이 떨어질 위험 |
| 궐련형 스틱 단독(기기 밖) | **학습 제외**(양성도 음성도 아님, 라벨 도구에서 `ignore` 태그) | 촬영하지 않음 | 일반 담배와 시각적으로 사실상 같음. 이번 범위에서 구분 불가로 정의 |
- 소품(전자담배 기기)은 참가자 본인 소유 기기를 전원 끈 상태로 쓰거나, 없으면 S11·S12를 생략한다. 구입은 요구하지 않는다.

### 9A.5 라벨링 · 분할 · 보호 규칙
**라벨링**
- 도구: **X-AnyLabeling 또는 labelImg(로컬 실행)** 권장. ONNX 모델로 사전 라벨을 띄울 수 있는 X-AnyLabeling이 1순위. CVAT를 쓸 경우 **로컬 Docker 설치만** 허용. 자체 촬영 데이터는 Roboflow 등 **클라우드 라벨링 서비스에 올리지 않는다**(9A.6).
- 포맷: YOLO txt(`class cx cy w h`, 0~1 정규화), 원본 프레임 단위. 이미지와 같은 이름의 `.txt`. 담배 없는 프레임은 빈 `.txt`. `ignore` 프레임은 `data/labeled/ignore.txt` 목록으로 관리.
- 박스 기준: 보이는 담배 전체(필터·재 포함)를 꼭 맞게. 길이의 30% 미만만 보이면 박스를 치지 않고 프레임을 `ignore`(가려진 담배를 음성으로 가르치지 않기 위해). 꽁초도 같은 클래스.
- 검수: 사전 라벨을 사람이 전수 확인. 무작위 5%를 다른 사람이 재검수해 불일치율을 notes에 기록(목표 ≤ 5% [제안]).
- 평가 클립 구간 라벨(9.2)은 별도 JSON. 클립 단위 라벨은 프레임 박스 라벨과 독립적으로 작성한다.
- (v2.1) 출처별 라벨 작업:
  | 출처 | 라벨 | 사람 검수 |
  | --- | --- | --- |
  | CigDet | 원본 YOLO 박스 그대로 | 불필요(원본 신뢰) |
  | COCO 부분집합 | 빈 라벨(담배 없음). 단 이미지에 실제 담배가 보이면 학습에서 뺀다 | similar 164장 전수 + none 무작위 10% 육안 확인(담배 섞임 여부) |
  | 합성 | 생성 스크립트가 박스 자동 생성 | 몽타주 육안 점검(`_workspace/eval_out/synth_montage.jpg`) |
  | 본인 세션(학습) | 1차 모델 사전 라벨 → 박스 수정 | **전수 검수**(v2와 같음). 재검수자가 없으면 무작위 5%를 하루 뒤 본인이 재검수하고 그렇게 했다고 적는다 |
  | 평가 참가자 프레임 | `capture.py` meta의 `expected_label`을 사람 단위 상태 라벨 초안으로 쓰고(`make_eval_labels.py`) 사람이 검수. 담배가 가려진 프레임은 `occluded` | **전수 검수** |
  | 평가 클립 | 9.2 형식 구간 라벨 직접 작성 | **전수** |

**분할 (사람 단위, 누수 방지)**
- 모든 자체 촬영 파일은 `P01`~`Pnn` 참가자 ID와 세션 ID를 파일명에 갖는다. 여러 명이 함께 나온 영상은 **등장 참가자 집합**을 메타데이터로 둔다.
- (v2.1) 참가자를 세 그룹으로 나눈다. 한 참가자는 한 그룹에만 속한다.
  | 그룹 | 참가자 | 데이터 |
  | --- | --- | --- |
  | **학습(train/val)** | 본인 1명(예: `P01`) | 본인 세션 + CigDet + COCO 부분집합 + 합성(train만) |
  | **dev** | 평가 참가자 1명 | 튜닝용 프레임·클립(`data/eval/dev/`) |
  | **holdout** | 평가 참가자 2명 | 최종 판정용 프레임·클립(`data/eval/holdout/`) |
- (v2.1) 평가 참가자가 **2명뿐**이면 기본은 **dev 1명 + holdout 1명**이다(사용자 문구 "평가는 학습에 쓰지 않은 사람"을 그대로 지킴). 이때 9.4.1 표기는 "예비 합격 (holdout n=1명)"이고 S5 다인 판정은 holdout 1명만으로는 불가하므로 "미측정"으로 보고한다. 대안(두 명 모두 holdout, dev는 본인 세션 val 블록으로 대체)은 사용자 승인이 있어야 쓴다(N7).
- (v2.1) **본인 세션의 train/val 나눔**: 학습 그룹이 1명뿐이라 사람 단위로 train/val을 나눌 수 없다. 본인 세션은 (키 × 거리 태그) 블록마다 **시간순 마지막 20%를 val**로, 나머지를 train으로 둔다(인접 프레임 누수를 줄이려 무작위 분할 금지). 이 val은 같은 사람이라 낙관적이며 **모델 선택·조기 종료에만** 쓰고 성능 보고에는 쓰지 않는다. 사람 단위 분할 원칙은 {학습} ↔ {dev} ↔ {holdout} 사이에 그대로 적용된다.
- 여러 명 영상은 등장 참가자가 모두 같은 그룹일 때만 그 그룹에 쓴다. 섞여 있으면 학습에도 평가에도 쓰지 않는다(S5 다인 영상은 처음부터 그룹별로 따로 찍는다. 본인과 평가 참가자가 함께 나온 영상은 쓰지 않는다).
- 공개·COCO 데이터는 train/val에만, **합성 데이터는 train에만** 넣는다(dev·holdout에 넣지 않는다). 공개·COCO·합성과 자체 데이터 사이 pHash 중복 검사도 한다.
- `make_splits.py`는 참가자 목록과 시드로 결정론적 분할을 만들고, 그룹 간 참가자 교집합이 0인지·pHash 교차 중복이 0인지·**dev/holdout에 공개·COCO·합성 출처 파일이 0개인지**(v2.1) 검사해 실패하면 멈춘다.

**hold-out과 합격선 보호**
- `data/eval/holdout/`과 holdout 참가자의 모든 촬영 파일(v2.1: holdout 참가자는 학습 프레임이 없으므로 `capture.py` 프레임과 녹화 클립 전부)은 분할 직후 `acceptance/holdout_manifest.sha256`에 파일별 SHA-256을 기록하고, 폴더를 읽기 전용으로 바꾼다.
- 9.4 합격선은 `acceptance/acceptance.yaml`에 기록하고 같은 매니페스트에 해시를 넣는다.
- **자동 튜닝 루프(스크립트·에이전트 모두)는 `acceptance/`와 `data/eval/holdout/`을 수정할 수 없다.** 튜닝 스크립트는 holdout 경로를 입력으로 받으면 오류로 멈춘다. holdout 평가는 `eval_clips.py --final` 모드에서만 하고, 실행 전에 매니페스트 해시를 검증해 불일치면 결과를 내지 않는다.
- holdout 평가 실행 횟수와 일시를 `acceptance/holdout_runs.log`에 남긴다. 단계 A 게이트 보고에는 마지막 실행 결과와 총 실행 횟수를 함께 낸다(여러 번 보고 고르는 것 방지).
- 합격선이나 holdout 구성을 바꾸려면 **사용자 승인**이 필요하고, 바꾸면 설계서 변경 내역에 적는다.

### 9A.6 개인정보 · 영상 보관 정책 (기본값)
- **보관 위치**: 촬영 PC의 로컬 `data/` 폴더(git 미추적, `.gitignore`에 등록). 가능하면 BitLocker 등 디스크 암호화 [제안]. 백업은 팀이 관리하는 오프라인 외장 디스크 1개까지.
- **외부 반출·공개 금지**: 클라우드 드라이브·메신저·공개 저장소·Roboflow 업로드 금지. 학습을 외부 GPU 서비스에서 해야 한다면 사용자 승인 후 ROI 크롭만 올리고 끝나면 삭제.
- **얼굴 노출 최소화**: 학습 데이터는 입 주변이 필요해 얼굴을 가릴 수 없다. 대신 (1) 장기 보관은 학습에 쓰는 ROI 크롭과 평가 클립으로 한정하고, 원본 영상은 ROI 데이터셋 생성·라벨 검수가 끝나면 삭제 [제안], (2) 보고서·발표·notes에 들어가는 이미지는 눈 부분을 모자이크, (3) `_workspace/eval_out/`의 오검출 사례 크롭은 ROI만 저장(전신 이미지 저장 안 함).
- **보관 기간**: 졸업작품 최종 평가 종료 후 삭제(기본값) **[사용자 확인, N6]**. 참가자가 철회하면 그 참가자 ID의 모든 파일과 파생 ROI를 지우고 모델을 다시 학습할지는 팀이 판단(최소한 holdout이면 평가에서 제외).
- **동의서 보관**: `data/consent/`에 데이터와 분리, 이름과 참가자 ID 대응표는 동의서 폴더에만 둔다(데이터 쪽에는 ID만).
- **로봇 운용(단계 B)**: 영상 저장 안 함(H9). `publish_debug_image` 기본 false, rosbag 녹화는 동의받은 테스트 촬영에서만.

---

## 10. 이식(단계 B) 완료 기준

### 10.1 core 무수정 원칙
- 단계 A 합격 시점 `src/ash_e_core`의 해시를 `_workspace/02a_perception_notes.md`에 기록한다. 단계 B에서 core가 바뀌면 사유를 보고하고, 오케스트레이터가 단계 A 평가를 다시 돌릴지 판단한다.
- RPi5에서 `python3 -c "import ash_e_core.pipeline, ash_e_core.priority"`가 ROS 없이도 성공해야 한다.

### 10.2 rosbag 동등성 검사 (프록시 모드, 같은 백엔드)
1. 평가 클립 3개 이상(S5, S8, S10 포함)을 `video_to_bag.py`로 rosbag2로 바꾼다. 프레임 stamp = `frame_idx / fps`, frame_id = `webcam_optical`, CameraInfo는 `hfov_deg`로 만든 것과 같게 넣는다. 뎁스 토픽은 넣지 않는다.
2. 프로토타입: `run_webcam.py --video clip.mp4 --no-throttle --log proto.jsonl` (stamp = frame_idx / fps, 모든 프레임 처리).
3. ROS: `use_depth:=false equivalence_mode:=true use_sim_time:=true`로 노드를 띄우고 `ros2 bag play -r 0.2 --clock`, `dump_jsonl.py`로 `ros.jsonl`을 기록한다. 동등성 모드에서는 입력 QoS가 reliable·keep_last 100이고 `process_rate_hz`·`roi_every_n` 스로틀이 꺼져 모든 프레임을 처리한다.
4. 비교(`frame_seq` 기준, 같은 백엔드·같은 스레드 수):
| 항목 | 기준 |
| --- | --- |
| 처리 프레임 수 | 일치 |
| 프레임별 사람 수, track_id 집합 | ≥ 99% 프레임 일치 |
| bbox IoU (같은 track_id) | 평균 ≥ 0.98 |
| state 일치 | ≥ 99% |
| raw_confidence 차이 | 평균 ≤ 0.02 |
| target_id 타임라인 | ≥ 98% 프레임 일치, 이벤트 순서 동일 |
x86(Windows)과 arm64(RPi5)의 부동소수점 차이 때문에 완전 일치는 요구하지 않는다. 불일치가 나면 래퍼(색 순서, 해상도, stamp 변환, QoS 프레임 누락)를 먼저 의심하고 core는 마지막에 의심한다.

### 10.3 백엔드 정합 (NCNN을 쓸 때만)
같은 입력 200프레임에서 ONNX Runtime 대비 사람 박스 IoU 평균 ≥ 0.95, 담배 신뢰도 차이 평균 ≤ 0.05, 그리고 단계 A 평가셋의 이진 F1 차이 ≤ 0.02.

### 10.4 실기(뎁스) 확인
- 뎁스 거리 정확도(v2, Astra Pro 기준, 실내): 사람 몸통 중앙값 거리 vs 줄자. 1 / 2 / 3 m에서 오차 ≤ 5%, 4 / 5 m에서 ≤ 10%, 0.5 m(사각)에서는 `distance_source=PROXY`로 떨어지는지 확인. 실외 그늘에서도 같은 측정을 하고 결과만 기록(합격 판정은 실내 기준).
- 처리율 ≥ 5 Hz (3명, 뎁스 정렬 포함), 입력→`/ash_e/target` 지연 ≤ 300 ms.
- 30분 연속 실행에서 노드가 죽지 않고 메모리 증가 ≤ 50 MB, CPU 온도 스로틀링 없음. 카메라 USB 재연결 1회 후 드라이버·노드가 자동 복구되는지(안 되면 알려진 한계로 기록).

### 10.5 프록시 → Astra Pro 뎁스 교체 검증 (v2 신설)
도구: `tools/depth_check.py`(ROS 불필요, 녹화된 컬러·뎁스·CameraInfo 또는 rosbag을 읽어 core를 두 번 돌림: `depth=None`과 `depth=정렬 뎁스`). 결과는 `_workspace/02b_perception_notes.md`에 표로 남긴다.
1. **외부 보정 검증**: 5.8절 보정 RMS ≤ 0.5 px. 평평한 벽 앞 사람 실루엣에서 정렬 뎁스의 사람 경계와 컬러 사람 경계의 어긋남을 1 / 3 / 5 m에서 측정해 **≤ 8 px(1280×720 기준)** [제안]. 넘으면 `depth_pixel_offset_uv`·보정 재실시.
2. **정렬 정합 간이 검사**: 바닥 테이프로 1~5 m 1 m 간격 지점에 사람을 세우고 각 지점 10 s 녹화. 정렬 뎁스 몸통 중앙값과 **정렬 없이 뎁스 영상 중앙 ROI**의 값 차이 ≤ 3% (정렬이 엉뚱한 곳을 보지 않는지).
3. **프록시 오차 측정**: 같은 녹화에서 프록시 거리(5.4-7)와 뎁스 거리를 지점별로 비교해 평균 오차·표준편차·부호(과대/과소)를 표로 남긴다. 사람 키·자세(앉음 포함) 2명 이상. 이 표로 단계 A의 프록시 기반 판단(합격선 거리 구간, 우선순위 거리 점수)이 얼마나 어긋났는지 해석한다. 프록시 평균 오차가 25%를 넘으면 단계 A 거리 구간별 재현율을 **뎁스 거리로 다시 집계**해 보고한다(합격선 자체는 바꾸지 않는다).
4. **경계 동작**: 5.0 m 획득 / 5.8 m 해제 경계를 걸어서 왕복(각 5회)했을 때 획득·해제 떨림 0회. 0.6 m 이내 접근 시 PROXY 전환 후 타깃 유지.
5. **유효 비율 로그**: 실내·실외 그늘·실외 직사광에서 사람 몸통 ROI 유효 뎁스 비율을 기록. 직사광에서 `depth_min_valid_ratio` 미만이면 PROXY로 떨어지고 노드가 정상 동작하는지 확인(실패가 아니라 정상 동작).
6. **동기화**: 컬러·뎁스 stamp 차이 분포(중앙값, 95%)를 기록. 95% 분위가 `sync_slop_s`를 넘으면 값을 조정하거나 걷는 사람 거리 오차를 따로 측정.
7. **결정론 유지**: 같은 bag 두 번 재생 시 `distance_m` 일치(정렬 포함).

---

## 11. 담당별 작업 분해

### 계약 소유권 (병렬 작업 충돌 방지)
- `ash_e_core/types.py`, `config.py`, `serialize.py`: **perception-dev 소유.** 3장과 8장대로 작성한다. priority-dev는 읽기만 한다. priority-dev가 시작할 때 파일이 없으면 3장 표대로 같은 내용을 만들고 notes에 적는다. QA가 3장과 대조한다.
- `PriorityConfig`는 `config.py`에 두되 필드 목록은 8장 우선순위 키가 원본이다.
- `ash_e_msgs`: **perception-dev 소유**(단계 B). priority-dev도 같은 규칙.
- 인터페이스를 바꿔야 하면 임의로 고치지 않고 오케스트레이터에 보고한다.

### 단계 A (Windows 프로토타입)
| 담당 | 작업 | 산출물 |
| --- | --- | --- |
| perception-dev | **A0. 데이터 확보 (v2, v2.1 개정, 9A장)** — 완료(2026-10-28 기준): CigDet 다운로드·라이선스 기록, COCO 부분집합 1,164장, 합성 300장, `roi_ds_v2`, `capture.py`, `SOURCES.md`. 남은 자동 부분: (a) 본인 세션이 들어오면 프레임 → 사전 라벨 → (사용자 검수 후) ROI 변환, 9A.3 표 A 최소 기준(양성 ROI ≥ 500, 음성 ≥ 1,500) 충족 여부를 notes에 표로 보고, 미달이면 보충 세션 요청 (b) 본인 세션 (키 × 거리) 블록 시간순 80/20 train/val 분할과 `roi_ds_v3` 병합(합성은 train만, 비율 상한 0.25) (c) 평가 참가자 촬영분 들어오면 `make_eval_labels.py` 초안·`make_splits.py`(dev/holdout, 출처 검사 포함)·holdout 매니페스트 생성 (d) 표 B 대비 수량 점검표 (e) Roboflow는 API 키가 생기면 추가(선택). **사용자 대기 지점**: 본인 세션 촬영, 평가 참가자 2~3명 동의·촬영, 라벨 검수, dev/holdout 지정 승인 — 대기 중에는 현 `roi_ds_v2` 모델로 A2~A3를 진행하고 notes에 대기 항목을 적는다 | `training/`, `data/README.md`, `acceptance/`, notes |
| | A1. types/config/serialize (계약) | `src/ash_e_core/ash_e_core/*.py` |
| | A2. backends(ORT·NCNN·Stub), detector, roi, state, tracker, stabilizer, distance, **depth_align(v2, 5.8 — 단위 테스트는 합성 데이터로)**, pipeline, viz | 위 + `test/` (roi·state·stabilizer·tracker·distance·depth_align 단위 테스트) |
| | A3. run_webcam(우선순위·viz_priority 연동 포함, import 실패 시 우선순위 없이 동작), eval_images, eval_clips, bench | `prototype/` |
| | A4. 학습 도구: ROI 데이터셋 변환, 학습, ONNX 내보내기, 모델 README | `training/`, `models/README.md` |
| | A5. 실행법·평가 결과·오검출 사례·core 해시 | `_workspace/02a_perception_notes.md` |
| priority-dev | A6. PrioritySelector (7장 전부) | `src/ash_e_core/ash_e_core/priority.py` |
| | A7. 순위 오버레이 `draw_ranking(img, status, dets)` | `viz_priority.py` |
| | A8. pytest: 12장 테스트 기준의 우선순위 항목 전부 (v2: v1의 "11장" 오기 수정) | `src/ash_e_core/test/test_priority*.py` |
| | A9. 가짜 시나리오 시뮬레이터 (카메라 없이 다수 인원·이탈 재생) | `prototype/sim_priority.py`, `prototype/config/priority.yaml` |
| | A10. notes | `_workspace/02a_priority_notes.md` |
| ash-e-qa | A11. pytest 실행, core 금지 import grep(`rclpy`, `rospy`, `sensor_msgs`, `cv_bridge`, `win32`, `msvcrt`, `ultralytics`, **`openni`**), types 대 3장 대조, 설정 키 대조, 평가 실행(데이터 있을 때), bench, 5대 시나리오. **(v2) 분할 누수 검사(참가자 교집합 0, pHash 교차 중복 0), holdout 매니페스트 해시 검증, `acceptance/` 무수정 확인, 공개 데이터 라이선스 기록 존재 확인** **(v2.1) dev/holdout에 공개·COCO·합성·본인(학습 참가자) 파일 0개, 합성이 val에 0개, 최종 평가 보고에 9.3-7 표본 수·신뢰구간·참가자별 값과 "예비 합격" 표기가 있는지 확인** | `_workspace/03a_qa_report.md` |
| perception-dev | **A12. (선택, v2) Astra Pro 조기 확인** — 사용자가 Astra Pro를 Windows PC에 연결할 수 있을 때만. 컬러 UVC가 일반 웹캠처럼 열리는지·지원 해상도, Orbbec OpenNI2 SDK(Windows)로 뎁스가 열리는지 확인하고, 되면 `prototype/astra_record.py`(OpenNI2 뎁스 + OpenCV 컬러 동시 녹화, core 밖)로 10.5 검증용 데이터를 미리 녹화. core는 바꾸지 않는다 | notes에 결과 표 |
**게이트:** 사용자가 9.4절 합격선 대비 결과(holdout)를 보고 "프로토타입 합격"을 선언해야 단계 B로 간다. (v2.1) 보고는 9.4.1 형식("예비 합격", 표본 수, 신뢰구간, 참가자별 값, "불확실" 표시, 오확정·누락 사례 목록)으로 한다. 사용자의 합격 선언은 "예비 합격 결과를 받아들이고 단계 B로 간다"는 뜻이며, 일반화 검증은 단계 B 실기 재평가(R8, R12)로 넘긴다.

### 단계 B (ROS2 이식)
| 담당 | 작업 | 산출물 |
| --- | --- | --- |
| perception-dev | **B0. 카메라 드라이버 확보 (v2, 6.3절)** — 순서와 시간 상자: (1) 실물 확인: `lsusb`로 모델·PID 확인(Astra Pro vs Pro Plus), `v4l2-ctl --list-formats-ext`로 컬러 해상도·포맷 확인 (2) D1 `ros2_astra_camera` Jazzy 소스 빌드·udev 규칙·`astrapro` 런치로 뎁스+UVC 컬러 발행 시도, **최대 2일** (3) 실패 시 D3: Orbbec OpenNI2 SDK arm64 + Python 바인딩 뎁스 노드(`ash_e_camera`) + apt `usb_cam`/`v4l2_camera` 컬러, **최대 3일** (4) 둘 다 실패 시 D4(컬러 전용, `use_depth:=false`)로 진행하고 사용자에게 보고 (5) 성공한 드라이버의 실제 토픽·QoS·frame_id·인코딩을 `ros2 topic info -v`로 기록해 `config/camera_astra_pro.yaml` 갱신 (6) 5.8절 외부 보정, `astra_pro_extrinsics.yaml` 생성 | `config/`, `ash_e_camera/`(조건부), `_workspace/02b_camera_notes.md` |
| | B1. `ash_e_msgs` (3장 msg 4종) | `src/ash_e_msgs/` |
| | B2. perception_node: **토픽 이름·QoS·정렬 방식 파라미터(4.2절)**, 구독(동기화 `sync_slop_s`, use_depth), cv_bridge, depth 단위 변환, CameraInfo 2종→CameraIntrinsics, **DepthAligner 호출(software 모드)**, frame_id 덮어쓰기, pipeline 호출, msg 변환·발행, 디버그 이미지, 추론 시간·뎁스 유효 비율 주기 로그, 모델·보정 파일 없어도 기동 | `src/ash_e_perception/` |
| | B3. 도구: video_to_bag, dump_jsonl (serialize 사용), **calib_astra_extrinsics, depth_check(10.5)** | `tools/` |
| | B4. launch(카메라 토픽 **파라미터** 인자, 정적 TF 인자), config(`perception.yaml`, `camera_astra_pro.yaml`) | `launch/`, `config/` |
| | B5. notes (실행법, RPi5 설치 절차, 알려진 한계) | `_workspace/02b_perception_notes.md` |
| priority-dev | B6. priority_node: detections 구독 → update, 10 Hz tick, feedback 구독, set_lock 서비스, target·target_point·markers 발행, 예외로 죽지 않음 | `src/ash_e_priority/` |
| | B7. 가짜 입력 발행기 (`fake_detections_pub`, sim_priority 시나리오 재사용) | `ash_e_priority/tools/` |
| | B8. 전체 기동 launch `ash_e_all.launch.py` | `launch/` |
| | B9. notes | `_workspace/02b_priority_notes.md` |
| ash-e-qa | B10. msg 필드 대 core 타입 1:1 대조(이름·타입·상수값), 변환 함수 왕복 테스트, 동등성 절차·비교 스크립트 작성 및 실행(ROS 없으면 "미실행" + RPi5 명령 안내), **(v2) 토픽 이름 하드코딩 grep(래퍼 코드에 `/camera/` 문자열이 파라미터 기본값 외에 없을 것), 10.5 검증 결과 확인** | `_workspace/03b_qa_report.md` |

---

## 12. 테스트 기준

### 12.1 core 단위 테스트 (Windows pytest, 모델 불필요)
| 모듈 | 필수 케이스 |
| --- | --- |
| roi | 키포인트 완비·코만·얼굴 없음·전부 무효(폴백), 화면 밖 자르기, `min_roi_px` 미만 건너뜀 |
| state | 입 근처 → SMOKING, 손 근처 → HOLDING, 둘 다 먼 박스 무시, 두 사람 겹침 시 가까운 사람 배정, 신뢰도 임계 |
| stabilizer | 단발 오검출 1프레임 → 확정 안 됨, 1.5 s 중 60% 양성 → 확정, 해제 히스테리시스, smoking 래치 20 s, `cigarette_checked=false` 관측 제외, 처리율 4/8/15 Hz에서 같은 시나리오 같은 결과 |
| tracker | 교차 보행에서 ID 유지, max_age 후 삭제, hits ≥ 2 발행, stationary_s 누적·리셋 |
| distance | 프록시(전신·잘림·머리 폴백), 뎁스 중앙값에서 0·NaN·범위 밖(0.6~6.0 m) 제거, 유효 픽셀 부족·유효 비율 < 0.15 시 PROXY 폴백, ROI 축소(`depth_roi_shrink`), bearing 부호(왼쪽 +) |
| depth_align (v2) | 항등 외부 파라미터 + 같은 내부 파라미터 → 입력과 같은 출력, 알려진 평행 이동(t=[0.025,0,0])의 합성 평면에서 예상 픽셀 이동, z-버퍼(가까운 값 우선), 0·NaN 무시, decimate 빈칸 채움, 출력 크기 = 컬러 크기, 결정론 |
| pipeline | 스텁 모델로 빈 결과·형식, 같은 입력 두 번 → 같은 출력(결정론) |
| serialize | 왕복 일치 |

### 12.2 우선순위 테스트 (QA 필수 시나리오 포함)
1. 흡연자 3명 동시 → 최고 점수 선택, ranking 내림차순·동점 규칙
2. 거리·상태 가중치 효과 (가까운 holding vs 먼 smoking 사례 수치 검증)
3. 점수 근접(차이 < 0.15) 두 후보 → 30 s 동안 전환 0회(히스테리시스)
4. 마진 초과 후보가 1 s 미만만 유지 → 전환 안 함 / 1 s 이상 + min_hold 경과 → SWITCHED_BETTER
5. 타깃이 5.8 m 초과 1 s → OUT_OF_RANGE, 즉시 다음 후보 선택, 이전 ID 쿨다운 30 s (v2: 7→5.8 m)
6. 타깃 미관측 2 s → LOST_TIMEOUT, 1.9 s 재등장 시 유지
7. 대상 0명 → IDLE, `has_target=false`
8. 입력 1 s 끊김 → tick이 INPUT_TIMEOUT·IDLE 반환
9. 피드백 DONE → 해제·600 s 쿨다운·공간 쿨다운(새 ID가 같은 자리면 자격 없음)
10. 잠금 중 더 나은 후보 → 전환 없음, 잠금 중 LOST → 해제됨
11. 가중치 합 ≠ 1 → 정규화·경고
12. 5.0~5.8 m 경계 왕복 → 획득·해제 떨림 없음 (v2)
13. (v2) 같은 타깃의 `distance_source`가 DEPTH↔PROXY로 바뀌며 거리 값이 튀어도(예: 4.8 m ↔ 6.0 m가 0.5 s마다 교대) 1.0 s 지속 조건 때문에 해제되지 않음

### 12.3 단계 A 통합
- `run_webcam.py --video` 로 S5 클립 처리 → JSONL 생성, 오버레이 녹화 확인.
- `eval_images.py`, `eval_clips.py`가 9.3 지표 표·혼동행렬·사례 이미지를 낸다.
- `bench.py`가 PC·RPi5 각각 구간별 ms를 출력한다.

### 12.4 단계 B 통합 (RPi5)
- `colcon build` 경고 없이 성공, `ros2 interface show ash_e_msgs/msg/TargetStatus`가 3.5절과 같다.
- 모델 파일 없이 perception_node가 기동해 빈 배열을 발행한다.
- 가짜 입력 발행기로 priority_node 12.2 시나리오 1·5·7·8 재현.
- (v2) 토픽 이름을 launch 인자로 바꿔(예: `color_topic:=/image_raw`) 노드가 그 토픽을 구독하는지 `ros2 node info`로 확인. 보정 파일 없이 `depth_alignment:=software`로 띄우면 경고 후 PROXY로 동작.
- 10.2 동등성, 10.4 실기, 10.5 뎁스 교체 검증.

---

## 13. 질문 현황

### 13.1 확정 (v2·v2.1에서 답변 반영)
| ID | 질문 | 확정 내용 | 반영 절 |
| --- | --- | --- | --- |
| Q1 | 뎁스카메라 기종 | **Orbbec Astra Pro** | 1.3, 5.8, 6, 10.5 |
| Q2 | 학습 데이터 보유 | 없음 → (v2.1, 2026-10-28 승인) 학습 = CigDet + COCO 부분집합 + 합성 + 본인 1세션, 평가 = 학습에 안 쓴 직접 촬영 2~3명 | 9A, A0 |
| N1 (v2.1 확정, 일부) | 자체 촬영 인원 | 직접 촬영 **총 3~4명, 각 약 15분**(본인 1 학습 + 평가 2~3). 미점화 실물 담배 사용 가능 여부와 촬영 장소·일정은 아직 미정 → N1b로 남김 | 9A.3, 9A.5 |
| Q3 | 합격선 | v1 제안값 그대로 **승인** | 9.4 |
| Q4 | smoking vs holding 우선 | smoking 우선(holding_value 0.7) | 7.2 |
| Q5 | 전자담배·궐련형 | **대상 아님**. 액상형·궐련형 기기 사용 장면은 하드 네거티브, 기기 밖 스틱 단독은 학습 제외 | 1.3, 9.1, 9A.4 |
| Q6 | YOLO11 AGPL-3.0 | 졸업작품(비공개·비상업) 범위에서 **사용 확정**. 범위 밖 배포 시 재검토 | 1.3, 5.2 |

### 13.2 기본값 채택 · 현장 확인 필요 (Q7~Q13, 사용자 별도 답변 없음)
| ID | 질문 | 채택한 기본값 | 현장 확인 항목 |
| --- | --- | --- | --- |
| Q7 | 운용 환경·최대 접근 거리 | 흡연구역, 주간. 접근 거리는 Astra Pro에 맞춰 **5.0 m(해제 5.8 m)로 변경** | 실외 직사광이면 뎁스 무효 → 프록시 운용이 되는데 이를 받아들일지(N3), 흡연구역 크기 |
| Q8 | 장착 높이·HFOV | 1.0~1.2 m 수평, 웹캠 `hfov_deg=70` | 웹캠 모델명·실제 HFOV, Astra Pro 컬러 보정값, 로봇 위 장착 위치(정적 TF) |
| Q9 | 최대 인원 | 8명, 담배 분석 4명/프레임 | 실제 흡연구역 동시 인원 |
| Q10 | 영상 저장 | 로봇은 저장 안 함, 데이터셋만 동의 후 로컬 저장(9A.6) | 학교 규정(연구 윤리·개인정보) 추가 요구 여부 |
| Q11 | Re-ID 없음 | 받아들임 + 공간 쿨다운 | 시연에서 같은 사람 재접근 빈도 |
| Q12 | 잠금·쿨다운 값 | 7.5절 값 | 넛지 UI 팀과 시간 값 합의 |
| Q13 | RPi5 사전 벤치 | 가능하면 실측, 아니면 추정 | Ubuntu 24.04 설치 여부 |

### 13.3 남은 미결 질문 (v2 신규, v2.1 갱신)
| ID | 질문 | 현재 가정 | 영향 |
| --- | --- | --- | --- |
| N1b | (N1에서 인원은 확정, 나머지만 남김) 촬영 장소·일정은? 미점화 실물 담배를 소품으로 써도 되나(학교 규정), 아니면 모형만? | 실물 ≥ 50% | 질감 도메인 차이, 촬영 일정 |
| N2 | 가진 카메라가 원조 **Astra Pro**가 맞나(Pro Plus·Mini Pro가 아닌지)? 컬러 모듈이 UVC로 1280×720을 내나? (`lsusb`, `v4l2-ctl --list-formats-ext` 결과 또는 제품 라벨 사진) | 원조 Astra Pro, 컬러 UVC 1280×720 [추정] | 드라이버 경로(Pro Plus면 OrbbecSDK v1 main), 담배 인식 유효 거리 |
| N3 | 실제 운용이 **실외 직사광**인가? Astra Pro는 실내용이라 직사광에서는 뎁스가 대부분 무효가 되고 거리 추정이 프록시로 떨어진다. 이를 받아들이나, 아니면 실내·그늘 시연으로 한정하나? | 받아들임(프록시 자동 전환) | 10.4 판정 환경, 접근 정확도 |
| N4 | Roboflow 계정·API 키를 만들어 줄 수 있나? | 없으면 CigDet만 자동 다운로드 | 공개 데이터 규모 |
| N5 | 단계 A 기간에 Astra Pro를 Windows PC에 연결해 조기 확인(A12)을 할 수 있나? | 가능하면 진행 | 단계 B 위험 조기 발견, 도메인 차이 측정 |
| N6 | 촬영 원본 영상 보관 기간: "졸업작품 최종 평가 후 삭제"로 해도 되나? 원본을 ROI 생성 후 바로 지우는 안(9A.6)에 동의하나? | 최종 평가 후 삭제, 원본은 ROI 생성 후 삭제 | 개인정보, 재학습 가능성 |
| N7 (v2.1) | 평가 참가자가 **2명뿐**이면 어떻게 나누나? (a) dev 1 + holdout 1(기본, "평가는 학습에 안 쓴 사람" 문구를 지킴. holdout 1명이라 신뢰도 가장 낮고 S5 판정 불가) (b) 2명 모두 holdout, dev는 본인 세션 val 블록으로 대체(holdout은 2명이 되지만 튜닝이 본인에게 치우침) | (a) | holdout 신뢰도, S5 우선순위 떨림 판정 가능 여부 |
| N8 (v2.1) | 평가 참가자 3명을 모을 수 있나? 그 가운데 holdout 2명이 **같은 시간에 함께** 촬영할 수 있나(S5·S10 다인 클립은 같은 그룹끼리만 써야 함)? | 3명 모집, holdout 2명 동시 촬영 가능 | S5 "떨림 0회" 판정 가능 여부. 불가하면 S5는 "미측정"이고 sim_priority 결과만 참고로 냄 |
| N9 (v2.1) | 평가 촬영 장소를 본인 학습 세션과 **다른 장소**로 할 수 있나? | 가능하면 다른 장소 | 같은 배경이면 배경 누수로 holdout 값이 부풀 수 있음(보고서에 명시) |

---

## 14. 스킬 문서와의 차이 (구현자 주의)
| 항목 | 스킬 문서 | 이 설계서 | 사유 |
| --- | --- | --- | --- |
| 우선순위 순수 로직 위치 | target-priority: `ash_e_priority/core.py` | `src/ash_e_core/ash_e_core/priority.py` (래퍼는 `ash_e_priority/priority_node.py`) | windows-prototype 구조와 사용자 지시(로직은 core)에 맞춤 |
| core 디렉터리 | `src/ash_e_core/detector.py` 평면 | `src/ash_e_core/ash_e_core/*.py` (+ setup.py, package.xml) | colcon과 pip 양쪽에서 설치하기 위한 표준 레이아웃 |
| 뎁스 중앙값 계산 | smoker-perception: 래퍼에서 구현 | core `distance.py`(순수 numpy)에 두고 래퍼는 depth 배열만 전달 | Windows에서 단위 테스트 가능, 동등성 단순화 |
| 안정화 N/M | N프레임 중 M프레임 | 시간창(1.5 s) + 비율(0.6), 8 Hz 기준 N=12/M=7과 같음 | PC와 RPi5 처리율 차이에도 같은 동작 |
| 메시지 패키지 | 언급 없음 | `ash_e_msgs` 추가 | rclpy 패키지로는 msg 정의 불가 |
| (v2) 뎁스 입력 | smoker-perception: 정렬된 뎁스(`aligned_depth_to_color`) 토픽 입력 | 비정렬 뎁스 + 뎁스 CameraInfo를 받아 core `depth_align.py`로 소프트웨어 정렬(하드웨어 D2C는 선택지) | Astra Pro 컬러가 별도 UVC 장치 |
| (v2) 카메라 토픽 지정 | (스킬 문서에 방식 언급 없음, v1은 remap) | 노드 파라미터(`color_topic` 등) | 드라이버가 B0에서 정해지며 토픽·QoS·frame_id가 달라짐 |
| (v2) 3D 위치 frame_id | smoker-perception: "설계서가 정한 frame_id" | 컬러 광학 프레임, `color_frame_id_override`로 덮어쓰기 가능 | UVC 드라이버 frame_id가 부정확할 수 있음 |
| (v2) 평가 데이터 | windows-prototype: 직접 촬영 영상에 3클래스 라벨 | 위에 더해 dev/holdout 사람 단위 분리, holdout·합격선 잠금. (v2.1) 평가는 학습에 안 쓴 직접 촬영 2~3명만, 공개·COCO·합성 데이터는 평가 금지 | 누수 방지, 자동 튜닝 루프의 합격선 훼손 방지 |
| (v2.1) 학습 데이터 | windows-prototype: "직접 촬영한 영상/이미지에 라벨"(학습·평가 구분 없이 직접 촬영 전제) | 학습은 CigDet + COCO 부분집합 + copy-paste 합성 + 본인 1세션만 직접 촬영. 직접 촬영 총 3~4명 | 촬영 부담 축소(사용자 승인 2026-10-28). 일반화 한계는 R11·9.4.1로 관리 |
| (v2.1) 합격 표기 | orchestrator: 사용자가 "프로토타입 합격"을 명시 | 결과 보고는 "예비 합격" + 표본 수·신뢰구간. 사용자 선언 문구는 그대로 "프로토타입 합격" | holdout 2~3명의 통계적 한계 |

---

## 15. 변경 내역
| 버전 | 날짜 | 내용 |
| --- | --- | --- |
| v1 | 2026-10-27 | 최초 작성 |
| v2 | 2026-10-27 | 맨 위 "v2 변경 요약" 참조. **인터페이스 변경 상세**는 아래 |
| v2.1 | 2026-10-28 | 데이터 방침 부분 개정(사용자 승인). 맨 위 "v2.1 변경 요약" 참조. **ROS 메시지·core 타입·설정 키·토픽 변경 없음.** 바뀐 데이터 계약: `make_splits.py` 출처 검사 추가, 평가 보고 형식(9.3-7·8, 9.4.1) 추가. 합격선 값과 `acceptance.yaml` 내용은 그대로. v2 원본은 `_workspace/01_planner_spec_v2.md` |

### 15.1 v2 인터페이스 변경 상세 (구현자 필독)
| 구분 | v1 | v2 | 영향 받는 담당 |
| --- | --- | --- | --- |
| ROS 메시지(`ash_e_msgs` 4종) | — | **변경 없음** | — |
| core 타입 | — | `DepthExtrinsics`, `DepthAligner` 추가(메시지 대응 없음). `PerceptionPipeline.process` 시그니처 변경 없음 | perception-dev |
| perception 입력 토픽 | `~/color/image_raw` 등 + launch remap | 파라미터 `color_topic`, `color_info_topic`, `depth_topic`, `depth_info_topic` | perception-dev, qa |
| perception 래퍼 키 신설 | — | `depth_alignment`, `extrinsics_file`, `color_frame_id_override`, `sync_slop_s`, `input_qos`, `publish_extrinsics_tf` | perception-dev, qa |
| 인식 core 키 | `depth_min_m=0.3`, `depth_max_m=8.0` | `0.6`, `6.0` + 신설 `depth_min_valid_ratio=0.15`, `depth_roi_shrink=0.1`, `depth_align_decimate=2` | perception-dev, qa |
| 우선순위 키 | `acquire_range_m=6.0`, `release_range_m=7.0` | `5.0`, `5.8` + 신설 `far_m=5.0` | priority-dev, qa |
| 평가 라벨 JSON | `data/eval/clips`, `labels` | `data/eval/{dev,holdout}/...`, 필드 `camera`, `participants`, `segments[].category` 추가 | perception-dev, qa |
| 디렉터리 | — | `acceptance/`, `training/fetch_public_datasets.py`, `merge_dedup.py`, `make_splits.py`, 조건부 `src/ash_e_camera/` | perception-dev, qa |

---

## 16. 리스크 (v2 신설)
| ID | 리스크 | 가능성 | 영향 | 대응 |
| --- | --- | --- | --- | --- |
| R1 | Astra Pro용 ROS2 Jazzy·arm64 드라이버가 빌드·동작하지 않음 | 높음 | 단계 B 지연 | B0 시간 상자(D1 2일 → D3 3일 → D4). 단계 A 중 A12로 조기 확인 |
| R2 | 실외 직사광에서 뎁스 무효 | 높음(실외 운용 시) | 거리 정확도 저하 | 프록시 자동 전환을 정상 동작으로 정의, N3로 운용 환경 확인 |
| R3 | 컬러(UVC)·뎁스(OpenNI2) 시간 도장 불일치 | 중간 | 걷는 사람 거리 오차 | `sync_slop_s` 조정, 10.5-6 측정, 몸통 중앙값으로 완화 |
| R4 | 외부 보정 품질 부족(IR 코너 검출 실패 등) | 중간 | 정렬 뎁스가 배경을 봄 | 프로젝터 가림·간접광, ROI 축소, `depth_pixel_offset_uv`, 10.5-1·2 검증 |
| R5 | USB 2.0 대역폭으로 컬러 1280×720 + 뎁스 동시 불가 | 중간 [추정] | 컬러 해상도 저하 → 담배 인식 거리 단축 | MJPEG, 뎁스 15 fps, 최후 640×480 + 합격선 거리 해석 재협의 |
| R6 | 공개 데이터가 작고 근접 위주 | 높음(확인됨: CigDet 전부 250×250 근접) | 원거리 재현율 부족 | 본인 세션 1~5 m 거리별 최소 수량(9A.3 표 A), ROI 데이터셋 변환. (v2.1) R11 참조 |
| R7 | 촬영 참가자 부족 | (v2.1) 해소 방향: 총 3~4명으로 확정 | holdout 신뢰도 저하 | R12로 이관 |
| R8 | 웹캠과 Astra Pro 컬러의 화질 차이(도메인 차이) | 중간 | 단계 B에서 정확도 하락 | 자체 촬영 30% 이상 Astra Pro 컬러, 단계 B에서 holdout 일부를 Astra Pro로 재평가 |
| R9 | 뎁스 정렬 비용으로 RPi5 5 Hz 미달 | 낮음~중간 | 처리율 | `depth_align_decimate=4`, NCNN, `roi_every_n=2` |
| R10 | 라이선스 오판(Roboflow 표기와 실제 원본 저작권 불일치) | 중간 | 졸업작품 범위에서는 낮은 영향 | 표기 라이선스 기록, 불명확은 보류, 범위 밖 배포 시 재검토. (v2.1) COCO 이미지는 NC 계열 약 62%, annotations 라이선스는 미확인 [추정] → 내부 학습 전용, 발표 자료에 COCO 이미지 싣지 않음 |
| R11 (v2.1) | **일반화 한계**: 학습 양성 대부분이 CigDet 근접 사진·합성(경계·조명 불일치)이고, 웹캠 시점 실사진 양성은 본인 1명뿐 → 다른 사람(피부색·손 크기·안경·복장), 다른 장소·조명, 원거리에서 재현율이 떨어지고, 본인 특유의 배경·옷에 과적합할 수 있음 | 높음 | holdout recall 미달 또는 dev-holdout 격차, 단계 B 실기 하락 | (1) 본인 세션에서 **거리 1~5 m·각도·조명(최소 2종)·양손·꽁초**를 표 A 수량대로 다양화 (2) **부정 예시 촬영 강조**: 키 3~7이 세션의 53%, 유사물·동작 각 ≥ 5종 (3) 평가 결과에 **오확정·누락 사례 전수 목록**(9.3-8)을 내고 반복 패턴(특정 소품·조명·거리)을 다음 보충 세션의 촬영 항목으로 되먹임(보충은 본인 세션만, holdout은 건드리지 않음) (4) 합성 비율 상한 0.25 유지, 합성 on/off 학습을 dev에서 비교 (5) 평가 장소를 학습 장소와 다르게(N9) |
| R12 (v2.1) | **소규모 평가 신뢰도**: holdout 2명(최악 1명)이라 참가자 간 분산 추정 불가, 프레임 간 상관으로 프레임 단위 신뢰구간이 지나치게 좁음. 오확정 지표는 노출 시간이 짧아 판정력이 약함. dev 1명에 맞춘 튜닝이 치우칠 수 있음 | 높음(확실) | 합격 판정이 우연에 좌우될 수 있음, 일반화 주장 불가 | 9.4.1 규칙: "예비 합격" 표기, 클립 부트스트랩 신뢰구간·참가자별 값·rule of three 상한 보고, "불확실" 표시, 일반화 주장 금지. holdout 실행 횟수 기록(9A.5). 단계 B에서 Astra Pro 컬러로 holdout 참가자 재촬영·재평가(R8)를 2차 검증으로 둠. 가능하면 평가 참가자 3명 확보(N8) |

## 참고 자료
- Ultralytics Raspberry Pi 가이드(RPi5 YOLO11n/s 벤치마크): https://docs.ultralytics.com/guides/raspberry-pi
- Core Electronics, RPi5 YOLO 포즈 추정 가이드: https://core-electronics.com.au/guides/getting-started-with-yolo-pose-estimation-on-the-raspberry-pi/
- RPi5 YOLO11n NCNN 사용자 보고: https://community.ultralytics.com/t/raspberry-pi-5-crash-when-running-yolov11n-ncnn/1525
- Roboflow cigarette-detection 데이터셋: https://universe.roboflow.com/mi-privado/cigarette-detection-iggcm
- Roboflow smoking-detection 데이터셋: https://universe.roboflow.com/smoking-bycpp/smoking-detection-8fgr8
- CigDet (Mendeley): https://data.mendeley.com/datasets/6hyrr8typ7
- Hugging Face 흡연 검출 모델 예: https://huggingface.co/basant18/Smoking-detection-YOLO26s
- OrbbecSDK ROS2 Wrapper v2 (Jazzy): https://index.ros.org/r/orbbec_camera_v2/
- ROS2 3D 카메라 사용 토론: https://discourse.openrobotics.org/t/what-3d-cameras-are-you-using-with-ros2/36775
- Clearpath 지원 부품(RealSense D435 Jazzy arm64): https://docs.clearpathrobotics.com/docs/ros/supported-components
- (v2) Orbbec Astra 시리즈(거리 0.6~8 m, ±3 mm@1 m, 뎁스 FOV): https://www.orbbec.com/products/structured-light-camera/astra-series/
- (v2) Astra Pro Plus 사양(뎁스 640×480@30, 0.6~8 m): https://shop.orbbec3d.com/Astra-Pro-Plus
- (v2) Astra 원조 데이터시트(뎁스 640×480@30, 0.4~8 m): https://static.chipdip.ru/lib/020/DOC024020204.pdf
- (v2) orbbec/ros2_astra_camera (OpenNI2, `use_uvc_camera`, `depth_registration`): https://github.com/orbbec/ros2_astra_camera
- (v2) OrbbecSDK_ROS2 (v1 main 지원 목록, v2는 OpenNI 장치 미지원): https://github.com/orbbec/OrbbecSDK_ROS2
- (v2) astra_camera ROS 인덱스(구 패키지, Jazzy 없음): https://index.ros.org/p/astra_camera/
- (v2) Astra Pro 컬러가 별도 UVC라는 설명: https://answers.ros.org/question/246595/astra_launch-and-astra_camera-packages-problems-with-rgb , https://3dclub.orbbec3d.com/t/cant-view-rgb-d-with-astra-pro/1966
- (v2) ROS2에서 OpenNI2 포크로 구형 Astra 구동 사례: https://answers.ros.org/question/399944/ros2-original-astra-camera-driver/
- (v2) CigDet (Mendeley, 557장, YOLO, CC BY 4.0): https://data.mendeley.com/datasets/6hyrr8typ7
- (v2) Roboflow 데이터셋: https://universe.roboflow.com/sda-vfqmd/smoking36 , https://universe.roboflow.com/deyan-markov/cigarette-finder/dataset/ , https://universe.roboflow.com/itmo-dl/cig-ue4ls , https://universe.roboflow.com/jeet-work/cigarette_butt_detection-ha7he , https://universe.roboflow.com/amoura/cigar-detection-gmctu
- (v2) Smoking-CCTV 접근 불가 보고: https://discuss.roboflow.com/t/request-access-to-smoking-cctv-dataset-for-yolov8-based-smoking-detection/10661
- (v2) Smoker Detection 분류 데이터(Kaggle 출처 미러): https://gts.ai/dataset-download/smoker-detection-image-dataset/
