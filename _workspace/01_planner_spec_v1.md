# ASH-E 설계서 v1 — 흡연자/담배 소지자 인식 + 타깃 우선순위

- 문서 ID: `_workspace/01_planner_spec.md`
- 작성: ash-e-planner (2026-10-27)
- 상태: **초안, 사용자 확인 대기.** 미결 질문(13장)에 답을 받기 전까지 가정(1.3절)으로 진행한다.
- 이 문서가 기준이다. 스킬 문서(`windows-prototype`, `smoker-perception`, `target-priority`)와 다르면 이 문서를 따른다. 다른 점은 12장 "스킬 문서와의 차이"에 모아 두었다.

---

## 0. 한눈에 보기

| 항목 | 결정 |
| --- | --- |
| 인식 방식 | 2단계: **사람+포즈 검출(YOLO11n-pose, 320px)** → 입·손 ROI 크롭(원본 해상도) → **ROI 담배 검출기(YOLO11n 1클래스, 192px)** → 키포인트 거리로 상태 판정 |
| 런타임 | 기본 ONNX Runtime(Windows·RPi5 공통, 동등성 확보). RPi5에서는 NCNN 백엔드를 선택적으로 사용(별도 정합 검사 필수) |
| 클래스 | `none`(0) / `holding`(1) / `smoking`(2) |
| 안정화 | 시간창 1.5 s 투표(8 Hz 기준 N=12, M=7), 해제 히스테리시스, smoking 래치 20 s |
| 우선순위 | 가중합 점수(상태 0.35, 거리 0.30, 정지 0.15, 신뢰도 0.10, 중심 0.10), 전환 마진 0.15 + 최소 유지 3 s + 전환 확인 1 s |
| 이탈 | 미관측 2 s → LOST, 7 m 초과 1 s 지속 → OUT_OF_RANGE, 상태 none 5 s → STATE_CLEARED. 해제 직후 남은 후보 중 최고점으로 재선택 |
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
| 카메라 | 일반 USB 웹캠 (뎁스 없음), 1280×720 권장 | 뎁스카메라 (기종 미정, 6장 비교) |
| 목표 처리율 | 측정만 함(PC 값), 단 처리율을 8 Hz로 제한해 RPi5 조건을 흉내 낸다 | 인식 출력 **≥ 5 Hz (목표 8 Hz)**, 사람 3명 기준 |
| 런타임 의존 | numpy, opencv-python, onnxruntime, pyyaml (core 공통) | 위 + rclpy, cv_bridge, message_filters (래퍼만) |

**RPi5 Python 주의:** Jazzy의 `cv_bridge`는 시스템 numpy(1.26.x)로 빌드되어 있다. RPi5에서 pip로 numpy 2.x를 설치하면 cv_bridge가 깨진다. `python3 -m venv --system-site-packages`로 venv를 만들고 `onnxruntime`(aarch64 wheel)만 추가 설치하며 numpy는 업그레이드하지 않는다. Windows 쪽도 `numpy<2`로 고정해 두 환경을 맞춘다.

### 1.3 가정 (미결 질문에 답을 받으면 갱신)
| ID | 가정 | 관련 질문 |
| --- | --- | --- |
| H1 | 뎁스카메라는 미정. 정렬된 뎁스(`aligned depth to color`)를 내는 USB 스테레오 카메라(RealSense D435i / Orbbec Gemini 335급)를 기준으로 설계 | Q1 |
| H2 | 자체 학습 데이터 없음. 공개 데이터셋 + 동의를 받은 배우를 직접 촬영해 확보 | Q2 |
| H3 | 우선 대상 거리: 0.5 ~ 6 m. 실외 흡연구역, 주간 기준 | Q7 |
| H4 | `smoking`이 `holding`보다 우선(곧 꽁초가 생길 사람). 사용자 의도에 따라 뒤집을 수 있게 가중치를 파라미터로 둠 | Q4 |
| H5 | 전자담배·궐련형(IQOS 등)은 이번 범위에서 제외(`none` 취급) | Q5 |
| H6 | Ultralytics YOLO11 가중치(AGPL-3.0) 사용 가능. 불가하면 대안 모델(5.2절)로 교체 | Q6 |
| H7 | 카메라는 지면에서 약 1.0~1.2 m 높이에 수평으로 장착 | Q8 |
| H8 | 한 화면에 사람 최대 8명, 담배 분석은 프레임당 최대 4명 | Q9 |
| H9 | 로봇은 얼굴 이미지를 저장하지 않는다. 데이터셋 촬영만 동의를 받고 저장 | Q10 |

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
 [뎁스카메라 드라이버 노드]
   color image ─┐  aligned depth ─┐  camera_info ─┐
                ▼                 ▼               ▼
 ash_e_perception_node (얇은 래퍼)
   - cv_bridge → BGR uint8 / depth float32[m]
   - ApproximateTimeSynchronizer(color, depth), CameraInfo 캐시
   - PerceptionPipeline.process(frame, stamp, frame_id, depth, intr)  ← core 그대로
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
| `ash_e_perception` | `ros2 run ash_e_perception perception_node` | `~/color/image_raw`, `~/depth/image_raw`, `~/color/camera_info` (launch에서 카메라 토픽으로 remap) | `/ash_e/detections`, `/ash_e/perception/debug_image`(옵션) | — |
| `ash_e_priority` | `ros2 run ash_e_priority priority_node` | `/ash_e/detections`, `/ash_e/target_feedback` | `/ash_e/target`, `/ash_e/target_point`, `/ash_e/priority/markers` | `/ash_e/priority/set_lock` (std_srvs/SetBool) |

### 4.3 토픽 · QoS
| 토픽 | 타입 | QoS | 비고 |
| --- | --- | --- | --- |
| 컬러/뎁스 입력 | sensor_msgs/Image | SensorData (best_effort, keep_last 1, volatile) | 최신 프레임만 처리. 동등성 모드(`equivalence_mode:=true`)에서는 reliable, keep_last 100 |
| CameraInfo | sensor_msgs/CameraInfo | SensorData | 첫 수신 후 캐시 |
| `/ash_e/detections` | ash_e_msgs/SmokerDetectionArray | reliable, keep_last 5, volatile | 처리한 프레임마다 1회 (빈 배열도 발행) |
| `/ash_e/target` | ash_e_msgs/TargetStatus | reliable, keep_last 1, volatile | update마다 + tick에서 상태가 바뀌면. 소비자는 stamp가 0.5 s보다 오래됐으면 무시해야 한다 |
| `/ash_e/target_point` | geometry_msgs/PointStamped | reliable, keep_last 1 | `has_target`일 때만 |
| `/ash_e/priority/markers` | visualization_msgs/MarkerArray | reliable, keep_last 1 | 후보 순위 텍스트 + 타깃 강조 |
| `/ash_e/perception/debug_image` | sensor_msgs/Image (bgr8) | best_effort, keep_last 1 | `publish_debug_image` 기본 false (RPi5 부하) |
| `/ash_e/target_feedback` | ash_e_msgs/TargetFeedback | reliable, keep_last 10 | 범위 밖 노드 → priority |

### 4.4 좌표계 (frame_id)
- 인식 결과의 `position`은 **컬러 이미지 메시지의 `header.frame_id`(카메라 컬러 광학 프레임, 예: `camera_color_optical_frame`)** 기준이다. 래퍼가 하드코딩하지 않고 입력 이미지에서 복사한다.
- 프로토타입의 frame_id는 `webcam_optical`(설정값)이다.
- 우선순위 노드는 좌표 변환을 하지 않는다. `base_link`·`map` 변환은 범위 밖인 주행 노드가 tf2로 한다. 카메라→base_link 정적 TF는 단계 B launch에 파라미터로 둔다(값은 Q8 답변 후 확정).
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

**결정:** 1단계 YOLO11n-pose(320) + 2단계 B(192). 단계 A 평가에서 B의 속도·정확도가 미달하면 C를 같은 평가 스크립트로 비교한다. 두 모델 모두 ONNX로 내보내고, core는 Ultralytics 패키지 없이 onnxruntime + 자체 전·후처리(letterbox, NMS)로 돌린다. 런타임 의존을 줄이고 Windows/RPi5의 동작을 같게 하기 위해서다.

### 5.3 백엔드
- `backend: onnxruntime`(기본). `intra_op_num_threads`: Windows 4, RPi5 4.
- `backend: ncnn`(RPi5 선택). pip `ncnn` 휠 사용. 켜기 전에 백엔드 정합 검사를 통과해야 한다(10.3절).
- 모델 파일은 `models/`(git 미추적)에 두고 `models/README.md`에 파일명·입출력 형태·내보내기 명령을 적는다. 파일이 없으면 스텁 모델이 동작한다(사람 0명 반환, 경고 로그). 이 경우 인터페이스는 살아 있고 QA 보고서에 "실추론 미검증"으로 표시한다.

### 5.4 단계별 처리 (core `PerceptionPipeline.process`)
입력: `frame_bgr`(uint8 HxWx3, BGR), `stamp`(float s), `frame_id`, `depth`(float32 HxW [m] 또는 None, 컬러와 정렬됨), `intr`(CameraIntrinsics).

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
   - **뎁스(단계 B)**: 몸통 ROI(어깨와 엉덩이 키포인트가 이루는 사각형, 없으면 박스 가로 중앙 40% × 세로 20~60%)의 뎁스 중 0, NaN, 범위 밖(`depth_min_m=0.3` ~ `depth_max_m=8.0`) 값을 버리고 중앙값을 `z`로 쓴다. 유효 픽셀이 `depth_min_valid_px=30` 미만이면 프록시로 대체하고 `distance_source=PROXY`로 표시한다. x, y는 CameraInfo 내부 파라미터로 계산하고 `distance_source=DEPTH`.
   - `distance_m = sqrt(x² + z²)`, `bearing_rad = -atan2(x, z)`.
   - **교체 지점**: `PerceptionPipeline.process`의 `depth` 인자다. None이면 프록시, 배열이면 뎁스를 쓴다. core 코드는 바뀌지 않고 래퍼가 depth를 넣는지만 다르다.
8. **출력**: `DetectionArray`(hits ≥ 2 트랙만, track_id 오름차순).

### 5.5 입력 해상도
- 웹캠: 1280×720 캡처(지원 안 되면 640×480; 해상도는 설정값). 포즈는 320 letterbox, ROI는 원본에서 자른다.
- RPi5 컬러: 1280×720 @15 fps 또는 848×480 @15 fps(USB 대역폭과 기종에 따라 결정). 뎁스는 컬러에 정렬된 토픽을 쓴다.

### 5.6 RPi5 처리 예산(추정, 사람 3명)
| 구간 | ONNX Runtime | NCNN |
| --- | --- | --- |
| 전처리 + letterbox | 5 ms | 5 ms |
| 포즈 320 | 60~90 ms | 35~50 ms |
| ROI 담배 192 × 최대 9 크롭(배치) | 50~80 ms | 30~50 ms |
| 후처리·트래킹·안정화·뎁스 | 5~10 ms | 5~10 ms |
| **합계 / 처리율** | 120~185 ms / **5.4~8 Hz** | 75~115 ms / **8.7~13 Hz** |
ONNX Runtime만으로 5 Hz 하한은 맞출 수 있다고 본다. 못 맞추면 순서대로 조정한다: (1) NCNN 백엔드, (2) `roi_every_n=2`(ROI 분석을 격프레임으로), (3) 포즈 입력 256.

### 5.7 학습 데이터 확보
- **라벨은 담배 박스 하나뿐이다.** 상태(smoking/holding)는 키포인트 거리로 정하므로 학습에 상태 라벨이 필요 없다. 상태 라벨은 평가 데이터에만 붙인다.
- **공개 데이터(라이선스 확인 필수)**: Roboflow Universe의 cigarette/smoking 데이터셋들(일부 MIT·CC BY 4.0, 라벨 정의가 제각각이니 확인할 것), Mendeley CigDet(YOLO 형식). `smoker` 클래스처럼 사람 전체에 박스를 친 데이터는 쓰지 않거나 담배 박스로 다시 라벨링한다.
- **ROI 데이터셋 변환** (`training/build_roi_dataset.py`): 원본 이미지에 포즈 모델을 돌려 5.4절과 같은 규칙으로 입·손 ROI를 자르고, 담배 박스를 ROI 좌표로 옮긴다. 담배가 없는 ROI는 음성 샘플이 된다. 학습 입력 분포가 실제 추론 입력과 같아지는 것이 이 단계의 목적이다.
- **자체 촬영(동의 필수)**: 불붙이지 않은 담배·꽁초 소품으로 배우 3명 이상을 1~6 m, 여러 각도·조명에서 촬영한다. 하드 네거티브(펜, 빨대, 젓가락, 막대사탕, 휴대폰 통화, 손가락 물기, 마스크 만지기)를 반드시 넣는다.
- **목표 규모(제안)**: 담배가 있는 ROI 3,000장 이상, 하드 네거티브 ROI 3,000장 이상. 학습/검증/평가는 **촬영 세션·인물 단위로 나눈다**(같은 사람이 학습과 평가에 동시에 들어가면 정확도가 부풀려진다).
- **학습**: `training/`에서만 Ultralytics 사용. YOLO11n detect, imgsz 192, 1클래스 `cigarette`. 증강: 밝기, 블러, 회전 ±15°, 좌우 반전. ONNX(opset 17, 정적 배치 1 및 동적 배치) 내보내기. 학습 코드는 core·노드와 섞지 않는다.
- **초기 실험용**: 학습 전에는 공개된 사전학습 담배 검출 가중치(예: Hugging Face 공개 모델)를 ROI에 시험 적용해 파이프라인을 검증해 볼 수 있다. 라이선스와 ONNX 변환 가능 여부를 확인한 뒤 쓴다.

---

## 6. 뎁스카메라 후보 비교 (Q1 답변 전 참고)

| 기종 | ROS2 Jazzy | RPi5(arm64) | 장점 | 단점 |
| --- | --- | --- | --- | --- |
| Intel RealSense D435i | realsense-ros, Jazzy apt 패키지 있음 | librealsense를 RSUSB 백엔드로 소스 빌드하는 경우가 많음 | 가장 성숙한 드라이버, 자료 많음, 정렬 뎁스 기본 제공 | 비쌈, RPi5 설치 번거로움, 실외 장거리 뎁스 노이즈 |
| Orbbec Gemini 335/335L | OrbbecSDK ROS2 Wrapper v2가 Jazzy 공식 지원 | arm64 지원(RPi5 실사례는 확인 필요) | 가격 대비 성능, 실외용 스테레오, USB3 | 커뮤니티 자료가 적음 |
| Luxonis OAK-D / OAK-D Lite | depthai-ros | 지원 | 내장 VPU로 사람 검출을 카메라 안에서 돌려 RPi5 CPU를 덜 수 있음 | 온디바이스 모델은 blob 형식이라 core의 ONNX 경로와 갈라짐. 이번 설계는 CPU 경로를 기준으로 하고, OAK 오프로드는 차기 과제로 둔다 |

**권장:** 아직 구매 전이면 정렬 뎁스 토픽을 기본으로 주고 Jazzy 지원이 확인된 RealSense D435i 또는 Orbbec Gemini 335. 기종이 정해지면 launch의 remap 표만 채우면 된다.

launch 인자(기본값은 RealSense 예시, 기종 확정 후 `ros2 topic list`로 확인해 수정):
| 인자 | 기본값 |
| --- | --- |
| `color_topic` | `/camera/camera/color/image_raw` |
| `depth_topic` | `/camera/camera/aligned_depth_to_color/image_raw` |
| `info_topic` | `/camera/camera/color/camera_info` |

---

## 7. 우선순위 정책 (`ash_e_core/priority.py`)

### 7.1 후보 자격 (eligible)
아래를 모두 만족해야 타깃 후보가 된다. 자격이 없는 후보도 `ranking`에 사유와 함께 넣는다.
1. `state ≠ NONE` (아니면 NOT_CONFIRMED)
2. `state_confidence ≥ min_state_conf=0.40` (아니면 LOW_CONFIDENCE)
3. 거리가 있으면 `distance_m ≤ acquire_range_m=6.0` (아니면 OUT_OF_RANGE). `distance_source=NONE`이면 거리 조건은 통과시키고 `S_dist=0`
4. 쿨다운이 아님 (아니면 COOLDOWN)

### 7.2 점수식
```
score = w_state·S_state + w_dist·S_dist + w_conf·S_conf + w_center·S_center + w_stay·S_stay     (0..1)
```
| 항 | 정의 | 가중치 기본값 |
| --- | --- | --- |
| `S_state` | SMOKING 1.0, HOLDING `holding_value=0.7` | `w_state=0.35` |
| `S_dist` | d ≤ `near_m=1.5` → 1.0, 1.5~6.0 m 선형으로 1→0, 6.0 초과 0 | `w_dist=0.30` |
| `S_conf` | `state_confidence` | `w_conf=0.10` |
| `S_center` | `1 − |bearing_rad| / (hfov_rad/2)`, 0..1로 자름 (`hfov_deg` 파라미터: 웹캠 70, 실기는 카메라 값) | `w_center=0.10` |
| `S_stay` | `min(stationary_s / stay_full_s(10 s), 1)` | `w_stay=0.15` |
가중치 합은 1.0이다. 로드할 때 합이 1이 아니면 정규화하고 경고를 남긴다. 동점이면 `distance_m`이 작은 쪽, 그다음 `track_id`가 작은 쪽을 고른다(결정론).

### 7.3 상태 머신
```
          후보 있음(최고점)                    더 나은 후보: 마진·유지·확인 조건 충족, 잠금 아님
 IDLE ─────────────────────► TRACKING(t) ─────────────────────────────► TRACKING(t')  [SWITCHED_BETTER]
  ▲   [ACQUIRED]               │  │  │  │
  │                            │  │  │  └ 피드백 수신(DONE/REFUSED/ABORTED/UNREACHABLE) → 해제 [FEEDBACK_RELEASED]
  │                            │  │  └ 타깃 state NONE이 5 s 지속 → 해제 [STATE_CLEARED]
  │                            │  └ distance_m > release_range_m(7.0)이 1.0 s 지속 → 해제 [OUT_OF_RANGE]
  │                            └ 타깃 미관측 2.0 s → 해제 [LOST_TIMEOUT]
  │                    해제 시: 해당 ID 쿨다운 등록 → 같은 평가에서 즉시 재선택(남은 자격 후보 최고점)
  └──────────── 후보 없음 / 입력이 input_timeout(1.0 s) 이상 끊김 [INPUT_TIMEOUT, 쿨다운 없음]
```
- 해제 뒤 **같은 평가 안에서** 다음 후보를 고른다. 이벤트는 해제 사유를 기록하고 `previous_target_id`에 이전 ID를 둔다. 새 타깃의 ACQUIRED는 별도 이벤트로 남기지 않고 `target_id` 변화로 알 수 있게 한다(한 평가에 이벤트는 하나).
- 거리 히스테리시스: 획득은 6.0 m 이내, 해제는 7.0 m 초과. 경계에서 타깃이 붙었다 떨어졌다 하는 것을 막는다.
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
│   │   │   ├─ pipeline.py         # PerceptionPipeline.process (프로토타입·ROS 공용 진입점)
│   │   │   ├─ priority.py         # 7장. 소유: priority-dev
│   │   │   ├─ viz.py              # 검출 오버레이 (perception-dev)
│   │   │   └─ viz_priority.py     # 순위·타깃 오버레이 (priority-dev)
│   │   └─ test/                   # pytest (Windows에서 실행)
│   ├─ ash_e_msgs/                 # 단계 B. ament_cmake, msg 4종
│   ├─ ash_e_perception/           # 단계 B
│   │   ├─ ash_e_perception/perception_node.py, convert.py
│   │   ├─ ash_e_perception/tools/video_to_bag.py, dump_jsonl.py
│   │   ├─ launch/perception.launch.py (카메라 토픽 remap 인자)
│   │   └─ config/perception.yaml  # ros__parameters 아래 core 키 그대로 + 래퍼 전용 키
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
│   ├─ build_roi_dataset.py, train_cig_roi.py, export_onnx.py
│   └─ README.md
└─ data/                           # git 미추적. eval/ 라벨 데이터 (9.2)
```

**설정 키 규칙:** core 설정의 키 이름이 원본이다. `prototype/config/*.yaml`은 평면 키, ROS `config/*.yaml`은 `<node_name>: ros__parameters:` 아래에 같은 키를 둔다. 래퍼 전용 키(`publish_debug_image`, `equivalence_mode`, 토픽 이름)는 `ros.` 접두어 없이 별도로 두되 core 키와 겹치지 않게 한다. QA는 두 파일의 core 키 집합이 같은지 검사한다.

**인식 설정 키(기본값):** `pose_model_path=models/pose.onnx`, `cig_model_path=models/cig_roi.onnx`, `backend=onnxruntime`, `num_threads=4`, `pose_input=320`, `roi_input=192`, `person_conf_thresh=0.40`, `min_person_h_px=60`, `max_persons=8`, `max_roi_persons=4`, `roi_every_n=1`, `kp_conf_thresh=0.30`, `mouth_roi_scale=1.6`, `hand_roi_scale=1.4`, `min_roi_px=24`, `cig_conf_thresh=0.35`, `smoking_radius=0.7`, `holding_radius=0.9`, `track_iou_thresh=0.3`, `track_max_age_s=1.0`, `stationary_speed_thresh=0.25`, `stab_window_s=1.5`, `stab_min_obs=4`, `confirm_ratio=0.6`, `release_ratio=0.25`, `release_hold_s=1.0`, `smoking_min_obs=2`, `smoking_latch_s=20`, `person_height_m=1.65`, `shoulder_width_m=0.40`, `head_width_m=0.15`, `edge_margin_px=8`, `hfov_deg=70`, `depth_min_m=0.3`, `depth_max_m=8.0`, `depth_min_valid_px=30`, `process_rate_hz=8`, `frame_id=webcam_optical`.

**우선순위 설정 키(기본값):** `w_state=0.35`, `w_dist=0.30`, `w_conf=0.10`, `w_center=0.10`, `w_stay=0.15`, `holding_value=0.7`, `near_m=1.5`, `acquire_range_m=6.0`, `release_range_m=7.0`, `out_of_range_hold_s=1.0`, `min_state_conf=0.40`, `hfov_deg=70`, `stay_full_s=10`, `switch_margin=0.15`, `min_hold_s=3.0`, `switch_confirm_s=1.0`, `lost_timeout_s=2.0`, `state_cleared_s=5.0`, `input_timeout_s=1.0`, `cooldown_lost_s=10`, `cooldown_out_of_range_s=30`, `cooldown_state_cleared_s=30`, `cooldown_done_s=600`, `cooldown_refused_s=300`, `cooldown_aborted_s=60`, `spatial_cooldown_enable=true`, `spatial_cooldown_radius_m=1.0`, `spatial_cooldown_bearing_deg=5`.

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
최소 분량(제안): 시나리오마다 클립 3개 이상(10~30 s), 배우 3명 이상, 합계 30분 이상. 평가용 클립은 학습에 쓰지 않는다.

### 9.2 라벨 형식
- `data/eval/clips/<clip_id>.mp4`
- `data/eval/labels/<clip_id>.json`: `{"fps": float, "persons": [{"person_ref": "p1", "segments": [{"t0": s, "t1": s, "label": "smoking|holding|none"}], "anchor": {"t": s, "bbox_xyxy": [...]}}]}` — `anchor`는 그 사람의 한 시점 박스다. 평가 스크립트는 anchor와 IoU가 가장 큰 트랙을 그 사람으로 매칭하고 이후 트랙 ID를 따라간다(ID가 바뀌면 그 구간에서 다시 IoU 매칭).
- 프레임 단위 평가용: 클립에서 0.5 s 간격으로 프레임을 뽑아 세그먼트 라벨을 상속한다(`eval_images.py --from-clips`). 이미지 폴더 평가도 지원한다: `data/eval/images/*.jpg` + 같은 이름의 `.json`(`[{bbox_xyxy, label}]`).
- 라벨 기준: smoking = 담배가 입에 닿아 있음, holding = 담배·꽁초가 손에 있음, 그 외 none. 담배가 화면상 보이지 않으면(손에 가려짐) none으로 하고 `"occluded": true`를 붙여 별도로 집계한다.

### 9.3 지표
1. **프레임 단위(raw_state)**: 3×3 혼동행렬, 클래스별 precision/recall/F1. 거리 구간별(≤2, 2~4, 4~6 m, 프록시 기준) 재현율.
2. **이진 지표(담배 사람 vs 아님)**: positive = smoking ∪ holding. precision/recall. 우선순위에서 가장 중요한 지표다.
3. **안정화 상태(state) 클립 단위**: 양성 구간 중 확정된 시간 비율, **확정까지 걸린 시간**(중앙값, 95% 분위), none 전용 클립(S3·S4)의 **분당 오확정 횟수**.
4. **오검출 상위 사례**: 신뢰도가 높은 FP 20건과 FN 20건의 크롭 이미지를 `_workspace/eval_out/`에 저장한다.
5. **속도**: PC 측정값과 **RPi5 실측값**(bench.py를 RPi5에서 ONNX Runtime·NCNN으로 실행)을 따로 기록한다. RPi5 실측이 불가능하면 PC × 5~10 추정치를 쓰고 "추정"으로 표시한다.
6. **우선순위 데모**: S5·S10 클립의 타깃 ID 타임라인과 이벤트 로그, 떨림 횟수(10 s 안에 전환 2회 이상).

### 9.4 합격선 (제안 — 사용자가 확정해야 하며 확정 전에는 "통과"라고 선언하지 않는다)
| 지표 | 제안값 |
| --- | --- |
| 이진 precision (state, ≤4 m) | ≥ 0.90 |
| 이진 recall (state, ≤3 m) | ≥ 0.80 |
| 이진 recall (state, 3~5 m) | ≥ 0.60 |
| smoking/holding 구분 정확도 (참 양성 중) | ≥ 0.75 |
| 유사물·동작 클립 오확정 | ≤ 1회 / 10분 |
| 확정 시간 중앙값 | ≤ 2.0 s |
| RPi5 처리율 (사람 3명, ONNX Runtime 또는 NCNN) | ≥ 5 Hz |
| 우선순위 떨림 (S5) | 0회 |

### 9.5 튜닝 순서
`cig_conf_thresh` → `smoking_radius`/`holding_radius` → `confirm_ratio`/`stab_window_s` → 데이터 보강(오검출 사례 기반 하드 네거티브) → 모델 교체(5.2의 C안 비교). 우선순위 가중치는 프록시 거리를 쓰므로 S5 데모가 상식적으로 동작하는 수준까지만 맞추고 최종 튜닝은 단계 B 실기에서 한다.

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
- 뎁스 거리 정확도: 1 / 2 / 3 / 5 m에 사람을 세워 줄자 대비 오차 ≤ 10%.
- 처리율 ≥ 5 Hz (3명), 입력→`/ash_e/target` 지연 ≤ 300 ms.
- 30분 연속 실행에서 노드가 죽지 않고 메모리 증가 ≤ 50 MB, CPU 온도 스로틀링 없음.

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
| perception-dev | A1. types/config/serialize (계약) | `src/ash_e_core/ash_e_core/*.py` |
| | A2. backends(ORT·NCNN·Stub), detector, roi, state, tracker, stabilizer, distance, pipeline, viz | 위 + `test/` (roi·state·stabilizer·tracker·distance 단위 테스트) |
| | A3. run_webcam(우선순위·viz_priority 연동 포함, import 실패 시 우선순위 없이 동작), eval_images, eval_clips, bench | `prototype/` |
| | A4. 학습 도구: ROI 데이터셋 변환, 학습, ONNX 내보내기, 모델 README | `training/`, `models/README.md` |
| | A5. 실행법·평가 결과·오검출 사례·core 해시 | `_workspace/02a_perception_notes.md` |
| priority-dev | A6. PrioritySelector (7장 전부) | `src/ash_e_core/ash_e_core/priority.py` |
| | A7. 순위 오버레이 `draw_ranking(img, status, dets)` | `viz_priority.py` |
| | A8. pytest: 11장 테스트 기준의 우선순위 항목 전부 | `src/ash_e_core/test/test_priority*.py` |
| | A9. 가짜 시나리오 시뮬레이터 (카메라 없이 다수 인원·이탈 재생) | `prototype/sim_priority.py`, `prototype/config/priority.yaml` |
| | A10. notes | `_workspace/02a_priority_notes.md` |
| ash-e-qa | A11. pytest 실행, core 금지 import grep(`rclpy`, `rospy`, `sensor_msgs`, `cv_bridge`, `win32`, `msvcrt`, `ultralytics`), types 대 3장 대조, 설정 키 대조, 평가 실행(데이터 있을 때), bench, 5대 시나리오 | `_workspace/03a_qa_report.md` |
**게이트:** 사용자가 9.4절 합격선 대비 결과를 보고 "프로토타입 합격"을 선언해야 단계 B로 간다.

### 단계 B (ROS2 이식)
| 담당 | 작업 | 산출물 |
| --- | --- | --- |
| perception-dev | B1. `ash_e_msgs` (3장 msg 4종) | `src/ash_e_msgs/` |
| | B2. perception_node: 구독(동기화, use_depth 파라미터), cv_bridge, depth 단위 변환, CameraInfo→CameraIntrinsics, pipeline 호출, msg 변환·발행, 디버그 이미지, 추론 시간 주기 로그, 모델 없어도 기동 | `src/ash_e_perception/` |
| | B3. 도구: video_to_bag, dump_jsonl (serialize 사용) | `tools/` |
| | B4. launch(카메라 토픽 remap 인자, 정적 TF 인자), config | `launch/`, `config/` |
| | B5. notes (실행법, RPi5 설치 절차, 알려진 한계) | `_workspace/02b_perception_notes.md` |
| priority-dev | B6. priority_node: detections 구독 → update, 10 Hz tick, feedback 구독, set_lock 서비스, target·target_point·markers 발행, 예외로 죽지 않음 | `src/ash_e_priority/` |
| | B7. 가짜 입력 발행기 (`fake_detections_pub`, sim_priority 시나리오 재사용) | `ash_e_priority/tools/` |
| | B8. 전체 기동 launch `ash_e_all.launch.py` | `launch/` |
| | B9. notes | `_workspace/02b_priority_notes.md` |
| ash-e-qa | B10. msg 필드 대 core 타입 1:1 대조(이름·타입·상수값), 변환 함수 왕복 테스트, 동등성 절차·비교 스크립트 작성 및 실행(ROS 없으면 "미실행" + RPi5 명령 안내) | `_workspace/03b_qa_report.md` |

---

## 12. 테스트 기준

### 12.1 core 단위 테스트 (Windows pytest, 모델 불필요)
| 모듈 | 필수 케이스 |
| --- | --- |
| roi | 키포인트 완비·코만·얼굴 없음·전부 무효(폴백), 화면 밖 자르기, `min_roi_px` 미만 건너뜀 |
| state | 입 근처 → SMOKING, 손 근처 → HOLDING, 둘 다 먼 박스 무시, 두 사람 겹침 시 가까운 사람 배정, 신뢰도 임계 |
| stabilizer | 단발 오검출 1프레임 → 확정 안 됨, 1.5 s 중 60% 양성 → 확정, 해제 히스테리시스, smoking 래치 20 s, `cigarette_checked=false` 관측 제외, 처리율 4/8/15 Hz에서 같은 시나리오 같은 결과 |
| tracker | 교차 보행에서 ID 유지, max_age 후 삭제, hits ≥ 2 발행, stationary_s 누적·리셋 |
| distance | 프록시(전신·잘림·머리 폴백), 뎁스 중앙값에서 0·NaN·범위 밖 제거, 유효 픽셀 부족 시 PROXY 폴백, bearing 부호(왼쪽 +) |
| pipeline | 스텁 모델로 빈 결과·형식, 같은 입력 두 번 → 같은 출력(결정론) |
| serialize | 왕복 일치 |

### 12.2 우선순위 테스트 (QA 필수 시나리오 포함)
1. 흡연자 3명 동시 → 최고 점수 선택, ranking 내림차순·동점 규칙
2. 거리·상태 가중치 효과 (가까운 holding vs 먼 smoking 사례 수치 검증)
3. 점수 근접(차이 < 0.15) 두 후보 → 30 s 동안 전환 0회(히스테리시스)
4. 마진 초과 후보가 1 s 미만만 유지 → 전환 안 함 / 1 s 이상 + min_hold 경과 → SWITCHED_BETTER
5. 타깃이 7 m 초과 1 s → OUT_OF_RANGE, 즉시 다음 후보 선택, 이전 ID 쿨다운 30 s
6. 타깃 미관측 2 s → LOST_TIMEOUT, 1.9 s 재등장 시 유지
7. 대상 0명 → IDLE, `has_target=false`
8. 입력 1 s 끊김 → tick이 INPUT_TIMEOUT·IDLE 반환
9. 피드백 DONE → 해제·600 s 쿨다운·공간 쿨다운(새 ID가 같은 자리면 자격 없음)
10. 잠금 중 더 나은 후보 → 전환 없음, 잠금 중 LOST → 해제됨
11. 가중치 합 ≠ 1 → 정규화·경고
12. 6.0~7.0 m 경계 왕복 → 획득·해제 떨림 없음

### 12.3 단계 A 통합
- `run_webcam.py --video` 로 S5 클립 처리 → JSONL 생성, 오버레이 녹화 확인.
- `eval_images.py`, `eval_clips.py`가 9.3 지표 표·혼동행렬·사례 이미지를 낸다.
- `bench.py`가 PC·RPi5 각각 구간별 ms를 출력한다.

### 12.4 단계 B 통합 (RPi5)
- `colcon build` 경고 없이 성공, `ros2 interface show ash_e_msgs/msg/TargetStatus`가 3.5절과 같다.
- 모델 파일 없이 perception_node가 기동해 빈 배열을 발행한다.
- 가짜 입력 발행기로 priority_node 12.2 시나리오 1·5·7·8 재현.
- 10.2 동등성, 10.4 실기 기준.

---

## 13. 미결 질문 (사용자 답변 필요)

| ID | 질문 | 현재 가정 | 영향 |
| --- | --- | --- | --- |
| Q1 | 뎁스카메라 기종이 정해졌나? 아직이면 RealSense D435i / Orbbec Gemini 335 / OAK-D 중 선호가 있나? | H1 (정렬 뎁스를 주는 USB 스테레오) | 단계 B launch remap, 해상도, RPi5 설치 절차 |
| Q2 | 담배 학습 데이터를 가지고 있나? 배우(동의)를 섭외해 소품으로 촬영할 수 있나? 공개 데이터셋(Roboflow, CigDet) 사용에 라이선스 제약이 있나? | H2 (없음, 공개 + 자체 촬영) | 단계 A 일정 대부분 |
| Q3 | 프로토타입 합격선을 9.4절 제안값으로 해도 되나? | 제안값 | 게이트 판정 |
| Q4 | `smoking`과 `holding` 중 누구를 먼저 가야 하나? 꽁초를 막 들고 있는 사람(곧 버릴 사람)이 넛지 목적상 더 중요할 수도 있다 | H4 (smoking 우선, holding 0.7) | `S_state` 값 |
| Q5 | 전자담배·궐련형 전자담배도 인식 대상인가? | H5 (제외) | 데이터·클래스 |
| Q6 | YOLO11(AGPL-3.0) 사용이 괜찮나? 공개·상업 배포 계획이 있으면 Apache 계열 모델(MoveNet 등)로 바꿔야 한다 | H6 (사용 가능) | 1단계 모델 선택 |
| Q7 | 운용 환경: 실내/실외, 주간/야간, 흡연구역 크기, 최대 접근 거리 6 m가 적절한가? | H3 | 거리 상수, 카메라 선택 |
| Q8 | 카메라 장착 높이·기울기, 로봇 기준 위치는? 프로토타입 웹캠 모델명과 화각(HFOV)은? | H7, `hfov_deg=70` | 정적 TF, 프록시 거리, S_center |
| Q9 | 한 화면에 동시에 있을 최대 인원은? | H8 (8명, 담배 분석 4명/프레임) | 처리 예산 |
| Q10 | 개인정보: 로봇이 영상을 저장해도 되나? 데이터 수집·보관 정책은? | H9 (로봇은 저장 안 함) | 로그·디버그 이미지 정책 |
| Q11 | 사람이 가려졌다 다시 나타나면 ID가 바뀌는 한계(Re-ID 없음)를 이번 범위에서 받아들여도 되나? | 받아들임 + 공간 쿨다운 | 같은 사람 재접근 |
| Q12 | 넛지 진행 중 타깃 잠금, 완료 후 600 s 재접근 금지 같은 쿨다운 값이 운영 의도와 맞나? | 7.5절 값 | 훅 동작 |
| Q13 | RPi5에서 단계 A 벤치(bench.py)를 미리 돌릴 수 있나(Ubuntu 24 설치 완료 여부)? | 가능하면 실측, 아니면 추정 | 모델·백엔드 결정 시점 |

---

## 14. 스킬 문서와의 차이 (구현자 주의)
| 항목 | 스킬 문서 | 이 설계서 | 사유 |
| --- | --- | --- | --- |
| 우선순위 순수 로직 위치 | target-priority: `ash_e_priority/core.py` | `src/ash_e_core/ash_e_core/priority.py` (래퍼는 `ash_e_priority/priority_node.py`) | windows-prototype 구조와 사용자 지시(로직은 core)에 맞춤 |
| core 디렉터리 | `src/ash_e_core/detector.py` 평면 | `src/ash_e_core/ash_e_core/*.py` (+ setup.py, package.xml) | colcon과 pip 양쪽에서 설치하기 위한 표준 레이아웃 |
| 뎁스 중앙값 계산 | smoker-perception: 래퍼에서 구현 | core `distance.py`(순수 numpy)에 두고 래퍼는 depth 배열만 전달 | Windows에서 단위 테스트 가능, 동등성 단순화 |
| 안정화 N/M | N프레임 중 M프레임 | 시간창(1.5 s) + 비율(0.6), 8 Hz 기준 N=12/M=7과 같음 | PC와 RPi5 처리율 차이에도 같은 동작 |
| 메시지 패키지 | 언급 없음 | `ash_e_msgs` 추가 | rclpy 패키지로는 msg 정의 불가 |

---

## 15. 변경 내역
| 버전 | 날짜 | 내용 |
| --- | --- | --- |
| v1 | 2026-10-27 | 최초 작성 |

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
