# ASH-E (Autonomous Smoker-approaching Helper for Eco)

로봇이 카메라로 **담배를 피우거나(smoking) 손에 든(holding) 사람**을 알아보고, 여러 명이면 우선순위를 정해 먼저 다가갈 사람을 고르는 프로그램입니다. 최종 목표는 라즈베리파이5(Ubuntu 24, ROS2 Jazzy) + 뎁스카메라이고, 지금은 **단계 A: Windows 노트북 웹캠으로 인식 정확도를 먼저 검증**하는 중입니다.

> 이 문서는 **지금 해야 할 일**과 **파일이 어디에 저장되는지**를 정리한 것입니다 (2026-11-11 기준).
> 사진·영상·참가자 정보·학습된 모델은 개인정보 및 용량 때문에 **git에 올라가지 않습니다** (`.gitignore`). 촬영한 PC에만 있습니다.

---

## 1. 지금 어디까지 왔나

| 항목 | 상태 |
| --- | --- |
| 촬영(사진) | P01(학습용) 1621장, P02(dev, 튜닝용) 731장, P03(hold-out, 최종 판정용) 636장 |
| 평가용 클립(영상) | **아직 없음 ← 지금 병목** |
| 라벨 검수 | P02 평가 라벨 366장, P03 평가 라벨 318장 완료. P01 학습 박스 721/733장 (12장 남음, 선택) |
| hold-out 잠금 | 완료 (`acceptance/holdout_manifest.sha256`, 637개 파일). P03 사진 라벨은 더 이상 수정 불가 |
| 기본 모델 | `models/cig_roi_v3.onnx` (검수한 P01 라벨로 2차 학습). dev(P02) 기준 precision 0.638 / recall 0.444 |
| 우선순위 로직 | `ash_e_core/priority.py` + 시뮬레이터 `prototype/sim_priority.py` 완료 (가짜 시나리오에서 현실적 장면 떨림 0회) |
| 테스트 | `pytest` 123개 통과 |
| 단계 B (ROS2 이식) | 단계 A 합격 판정 후 시작 |

참가자 역할: **P01 = 학습**, **P02 = dev(튜닝)**, **P03 = hold-out(최종 판정)**. 평가는 학습에 쓰지 않은 사람으로만 합니다.

---

## 2. 지금 해야 할 일 (사람이 직접, 중요한 순서)

합격선 지표(precision/recall, 확정까지 걸린 시간, 유사물 오확정 횟수)는 **클립(영상)으로만** 잴 수 있습니다. 그래서 클립 녹화가 가장 먼저입니다.

### 준비 (PowerShell, 매번 한 번)

```powershell
cd <저장소 폴더>   # 이 저장소를 받은 26PJT_ASH-E 폴더
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

### 할 일 1. P02 평가 클립 녹화 (가장 먼저)

시나리오마다 아래 명령을 한 번씩 실행합니다 (`mouth` 자리만 바꿉니다).

```powershell
python prototype\run_webcam.py --record --participant P02 --scenario mouth --consent-confirmed
```

창 조작:
- **r** → 녹화 시작, 정해진 시간 동작 후 다시 **r** → 정지
- 같은 시나리오를 여러 개 찍을 때는 거리를 바꿔 가며 r을 반복 (번호 `mouth_001`, `mouth_002`… 자동)
- **q** → 종료

| `--scenario` | 할 동작 | 분량 |
| --- | --- | --- |
| `mouth` | 불붙이지 않은 담배를 입에 대는 흡연 동작을 계속 | 30초 × 3개 (약 1.5 m / 3 m / 4.5 m) |
| `holding` | 담배를 손에 든 채로 있기 | 30초 × 2개 (2 m / 4 m) |
| `none` | 담배 없이 평소처럼 (담배는 화면 밖으로) | 60초 × 1개 |
| `similar` | 펜·빨대·막대사탕·젓가락 등을 손에 들고 입에도 대기 | 60초 × 2개 |
| `gesture` | 담배 없이 전화, 마시기, 입 가리기, 턱 괴기, 손가락 물기, 하품 | 60초 × 2개 |
| `s8_walk` | 걸으면서 흡연 동작 | 30초 × 1개 |
| `s9_side` | 옆모습·뒷모습으로 흡연 동작 | 30초 × 1개 |
| `ecig_liquid`, `ecig_heated` | 전원 끈 전자담배 (기기가 있을 때만) | 각 30초 × 1개 |

주의:
- **클립 하나에는 한 사람, 한 가지 동작만** 담습니다 (정답 라벨을 자동으로 채울 수 있게).
- **다른 사람이 화면에 들어오지 않게** 합니다 (동의하지 않은 사람은 쓸 수 없음).
- 조명을 2가지 이상으로 바꿔 찍으면 좋습니다. 전체 약 10분.
- 참가자는 서면 동의를 한 성인이어야 합니다 (`--consent-confirmed`는 그 확인입니다).

### 할 일 2. P03 평가 클립 녹화

할 일 1과 같고 `--participant P03`으로만 바꿉니다.

```powershell
python prototype\run_webcam.py --record --participant P03 --scenario mouth --consent-confirmed
```

- 녹화한 P03 클립은 일단 `data\raw_clips\P03\`에 **그대로 둡니다**. 라벨을 채우고 확인한 뒤 Claude가 `data\eval\holdout\` 아래로 옮깁니다.
- **중요:** 최종 평가(`eval_clips.py --final`)를 처음 돌리는 순간 hold-out 폴더의 파일 목록과 내용이 해시로 고정됩니다. 그 뒤에는 클립을 추가하거나 라벨을 고칠 수 없으므로, **P03 클립과 라벨을 전부 끝낸 뒤에만** 최종 평가를 돌립니다.
- 참가자가 2명뿐이라 S5(흡연자+비흡연자 동시 등장) 다인 클립은 찍지 않습니다. S5는 "미측정"으로 보고하고 시뮬레이터 결과를 참고로 냅니다.

### 할 일 3. 보충 촬영 (P01, 학습용 사진)

지금 모델은 **4 m를 넘으면 검출률이 크게 떨어집니다**. 아래 두 가지를 더 찍어 주세요.

```powershell
python prototype\capture.py --participant P01 --session S2 --consent-confirmed
```

- 키 **2**(mouth)로 **3~4 m**, 키 **1**(holding)로 **1~3 m**
- **SPACE**: 자동 촬영 시작/정지 (2장/초), **d**: 거리 태그 바꾸기(1m~5m), **c**: 각도 태그, **q**: 종료
- 담배 없는 장면(키 3·4·5)에서는 담배를 화면 밖으로 치웁니다.

### 할 일 4. (선택) P01 학습 박스 남은 12장 검수

```powershell
python prototype\review_labels.py --pid P01
```

이어서 하던 곳부터 다시 시작됩니다.

---

## 3. 클립을 찍은 뒤 진행 순서

| 순서 | 누가 | 무엇을 |
| --- | --- | --- |
| 1 | 사용자 | 클립 녹화 후 "녹화했어"라고 알림 (P02 `mouth` 1개만 먼저 찍어도 됨, 녹화·재생 정상 여부부터 확인) |
| 2 | Claude | 시나리오 이름으로 각 클립의 `labels.json` 정답을 자동으로 채우는 도구 준비 |
| 3 | 사용자 | 채워진 라벨 확인 (특히 사람 위치, 동작이 바뀐 구간) |
| 4 | Claude | P02(dev) 클립으로 확정 로직·임계값 튜닝: `python prototype\eval_clips.py --clips-dir data\raw_clips\P02` |
| 5 | Claude | P03 클립을 `data\eval\holdout\`로 옮기고 최종 평가: `python prototype\eval_clips.py --final` (실행 횟수가 기록됨) |
| 6 | 사용자 | 결과(클래스별 precision/recall, 혼동행렬, 오검출 사례)를 보고 **합격/불합격 판정** |
| 7 | — | 합격이면 단계 B(ROS2 이식), 불합격이면 원인(모델·데이터·안정화 파라미터)별로 단계 A 재작업 |

### 합격선 (`acceptance/acceptance.yaml`, 해시로 잠김, 변경 불가)

| 지표 | 합격선 |
| --- | --- |
| precision (4 m 이내) | 0.90 이상 |
| recall (3 m 이내) | 0.80 이상 |
| recall (3~5 m) | 0.60 이상 |
| smoking/holding 구분 정확도 | 0.75 이상 |
| 유사물 오확정 | 10분당 1회 이하 |
| 확정까지 걸린 시간 | 중앙값 2초 이하 |
| RPi5 처리 속도 | 5 Hz 이상 (단계 B에서 측정) |

hold-out 참가자가 1명이므로 합격이 나와도 **"예비 합격 (hold-out 1명, 클립 n개, 노출 n분)"** 으로 표기합니다.

---

## 4. 파일은 어디에 저장되나

경로는 모두 저장소 폴더 기준입니다. **git** 열은 GitHub에 올라가는지 여부입니다.

### 촬영·데이터 (`data/`, 전부 git 제외, 이 PC에만 있음)

| 경로 | 내용 | 만드는 것 | git |
| --- | --- | --- | --- |
| `data/raw/<PID>/<세션>/<시나리오>/<PID>_<세션>_<시나리오>_<번호>.jpg` | 촬영 사진 | `capture.py` | ✗ |
| `data/raw/<PID>/<세션>/meta.jsonl` | 사진별 참가자·시나리오·거리·각도 태그 | `capture.py` | ✗ |
| `data/raw_clips/<PID>/<세션>/<시나리오>_<번호>/clip.mp4` | **녹화 클립** (오버레이 없는 원본 영상) | `run_webcam.py --record` | ✗ |
| `data/raw_clips/.../events.jsonl` | 녹화 중 프레임별 인식 결과·이벤트 | `run_webcam.py --record` | ✗ |
| `data/raw_clips/.../labels.json` | 클립 정답 라벨 (빈 양식으로 생성 → 채워야 함) | `run_webcam.py --record` | ✗ |
| `data/labeled/P01/...` | P01 학습용 박스 라벨 (YOLO txt) | `prelabel.py`, `review_labels.py` | ✗ |
| `data/labeled/review_state_P01.json` | P01 박스 검수 진행 상태 | `review_labels.py` | ✗ |
| `data/eval/dev/images/` | P02 평가용 사진 + 라벨 (366장) | `make_eval_labels.py` | ✗ |
| `data/eval/holdout/images/` | P03 평가용 사진 + 라벨 (318장, **잠김**) | `make_eval_labels.py` | ✗ |
| `data/eval/holdout/` 아래 클립 | P03 평가 클립 (최종 평가용, 앞으로 옮길 곳) | Claude가 옮김 | ✗ |
| `data/splits/participants.json` | 참가자 → train/dev(`val`)/holdout 지정 | `make_splits.py` | ✗ |
| `data/public/`, `data/synth/` | 공개 데이터, 합성 데이터 (출처: `data/SOURCES.md`) | `training/` 스크립트 | ✗ (`SOURCES.md`만 ✓) |
| `data/roi_ds*`, `data/roi_own_*` | 학습용 ROI 데이터셋 | `training/build_roi_*.py` | ✗ |

### 모델 (`models/`, git 제외)

| 경로 | 내용 |
| --- | --- |
| `models/cig_roi_v3.onnx` | **현재 기본** 담배 검출 모델 (2차 학습) |
| `models/cig_roi.onnx` | 1차 모델 (사전 라벨링·의사 라벨 생성에 사용) |
| `models/cig_roi_v3exp.onnx` | 의사 라벨 실험 모델 (참고용) |
| `models/pose.onnx` | 사람 자세(키포인트) 모델 |
| `models/*.pt` | 원본 YOLO 가중치 |

새 PC에서 저장소를 받으면 모델 파일이 없으므로 기존 PC에서 `models/` 폴더를 따로 복사해야 합니다.

### 평가 결과·문서 (`_workspace/`, `acceptance/`)

| 경로 | 내용 | git |
| --- | --- | --- |
| `_workspace/eval_out/report_<dev\|holdout>.md` | 사진 평가 보고서 + 오검출 크롭 | ✗ (얼굴 포함) |
| `_workspace/eval_out/clips_<태그>/` | 클립 평가 결과, 재생 이벤트 | ✗ |
| `_workspace/01_planner_spec.md` | 설계서 (v2.1, 지표·시나리오·분량 정의) | ✓ |
| `_workspace/02a_perception_notes.md` | 인식 구현 노트, 촬영 방법 상세 | ✓ |
| `_workspace/02a_priority_notes.md` | 우선순위 구현 노트, 시뮬레이터 결과 | ✓ |
| `_workspace/03a_qa_report.md` | 단계 A 검증 보고서 | ✓ |
| `_workspace/사용자_할일.md` | 사용자 할 일 상세 (이 README의 원본) | ✓ |
| `_workspace/capture_qc_report.md` | 촬영 품질 점검 결과 | ✓ |
| `acceptance/acceptance.yaml` + `.sha256` | 합격선 (해시로 잠김) | ✓ |
| `acceptance/holdout_manifest.sha256` | hold-out 사진 637개 파일 해시 | ✓ |
| `acceptance/holdout_clips_manifest.json` | hold-out 클립 해시 (첫 `--final` 때 생성) | ✓ |
| `acceptance/holdout_runs.log` | `--final` 실행 기록 | ✓ |

### 코드

| 경로 | 내용 |
| --- | --- |
| `src/ash_e_core/` | 플랫폼 공통 핵심 로직 (검출, 추적, 안정화, 거리 추정, 우선순위). 단계 B에서 그대로 재사용 |
| `prototype/run_webcam.py` | 웹캠 실시간 실행·클립 녹화·재생 |
| `prototype/capture.py` | 사진 촬영 도구 |
| `prototype/eval_images.py`, `eval_clips.py` | 사진·클립 정확도 평가 |
| `prototype/sim_priority.py` | 카메라 없이 다수 인원 우선순위 시뮬레이션 (시나리오: `prototype/config/sim_scenarios.yaml`) |
| `prototype/review_labels.py`, `make_eval_labels.py`, `prelabel.py` | 라벨 만들기·검수 |
| `training/` | 데이터셋 구성, 학습, ONNX 변환, 분할·잠금 |

---

## 5. 자주 쓰는 명령

```powershell
# 웹캠으로 실시간 인식 보기 (녹화 없음)
python prototype\run_webcam.py

# 녹화한 클립을 다시 인식 (카메라 불필요)
python prototype\run_webcam.py --replay data\raw_clips\P02\S1\mouth_001\clip.mp4

# 우선순위 시뮬레이터
python prototype\sim_priority.py
python prototype\sim_priority.py --events --timeline --only s5_mixed

# 전체 테스트
python -m pytest -q prototype src/ash_e_core/test training
```

---

## 6. 개인정보·안전 원칙

- 참가자는 이름 대신 `P01` 같은 번호만 씁니다. 번호와 실명의 대응은 저장소 밖에 보관합니다.
- 얼굴이 찍힌 사진·영상·크롭은 git, 클라우드, 메신저에 올리지 않습니다.
- 동의하지 않은 사람이 찍힌 사진은 쓰지 않습니다 (이미 한 번 지움, 기록: `_workspace/scrub_third_party_log.json`).
- 담배는 **불을 붙이지 않습니다.**
