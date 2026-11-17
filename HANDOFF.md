# ASH-E 인수인계 문서

마지막 갱신: 2026-11-18 03시 (v5 평가 끝, 제외 사진 재검수 끝, v6 학습 중)

> 다른 Claude 계정으로 로그인하면 이전 대화와 개인 메모리(`~/.claude-work/.../memory/`)가 따라오지 않습니다.
> 이 파일이 그 대신입니다. 새 세션에서 **"HANDOFF.md 읽고 이어서 진행해줘"**라고 말하면 됩니다.
> (CLAUDE.md에도 같은 안내를 적어 두었으므로 Claude는 이 파일을 먼저 읽습니다.)

---

## 1. 프로젝트 한 줄 요약

로봇(RPi5 + Ubuntu 24 + ROS2 Jazzy + 뎁스카메라)이 흡연자·담배 소지자를 알아보고, 여러 명이면 우선순위로 접근 대상을 정한다.
지금은 **단계 A(Windows 노트북 웹캠으로 인식 정확도 검증)**이다. 사용자가 "프로토타입 합격"이라고 말하기 전에는 단계 B(ROS2 이식)를 시작하지 않는다.

작업 흐름 규칙은 `CLAUDE.md`와 `.claude/skills/ash-e-orchestrator/SKILL.md`에 있다.

## 2. 지금 어디까지 왔나

| 항목 | 상태 |
| --- | --- |
| 브랜치 | `ash-e/stage-a-capture-priority`, HEAD는 `git log -1`로 확인 (2026-11-18 세션 종료 시 커밋함. README.md와 `_workspace/사용자_할일.md`는 커밋 안 함, 6절) |
| 기본 담배 모델 | `models/cig_roi_v3.onnx` (사용자 결정 2026-11-13) |
| v4 모델 | `models/cig_roi_v4.onnx`. P02 dev 평가에서 v3보다 낫다고 보기 어려움 |
| 참가자 분할 | P01 = 학습, P02 = dev(조정용), P03 = hold-out(최종 시험). `data/splits/participants.json` (git 제외) |
| 평가 클립 | `data/raw_clips/P02/S1` 13개, `data/raw_clips/P03/S1` 12개. 라벨은 사용자가 2026-11-13에 모두 확인 |
| **P01 S3 촬영** | **완료 (2026-11-17)**. `data/raw/P01/S3/` holding 310, mouth 190, similar 331 = 831장 |
| **S3 박스 초안** | **완료**. 아래 3절 |
| S3 사람 검수 | 완료 (2026-11-17 23:51). S3 500장 모두 ok. S1·S2도 다시 검수됨: S1 ok 688 / ignore 45, S2 ok 469 / ignore 41 |
| v5 데이터셋 | 완료 (2026-11-17 23:53). `data/roi_own_p01_reviewed_v5/build_report.json`: train pos 3359 / neg 15787, val pos 243 / neg 1048. 박스 없이 ok인 holding 1장은 빠짐 |
| v5 학습·내보내기 | 완료 (2026-11-18). 18 epoch에서 끊긴 것을 `--resume`로 30/30까지. best val P 0.798 / R 0.709 / mAP50 0.765. `models/cig_roi_v5.onnx` |
| v5 P02 비교 | 완료. 좋아진 점과 나빠진 점이 섞여 기본 모델로 쓰지 않음(사용자 결정 대기). 아래 "v5 결과", "기준값 실험" |
| 제외 사진 재검수 | 완료 (2026-11-18 02:57). 제외됐던 86장 중 75장 다시 포함, 11장 계속 제외 (8-6절) |
| v6 데이터셋 | 완료. `data/roi_own_p01_reviewed_v6`, train pos 3466 / neg 16034, val pos 267 / neg 1063 |
| **v6 학습** | **진행 중 ← 다음 할 일 (4절)**. 2026-11-18 03:03에 별도 cmd 창("ASH-E v6 training", 최소화)에서 시작. Claude 세션을 닫아도 계속 돈다. 로그 `training/runs/cig_roi_v6_train.log`, 결과 `training/runs/cig_roi_v6/` |

### P02 dev 결과 (2026-11-13, 판정 아님)

| 지표 | 합격선 | v3 | v4 |
| --- | --- | --- | --- |
| 정밀도 (4 m 이내) | ≥ 0.90 | 0.524 ❌ | 0.624 ❌ |
| 재현율 (3 m 이내) | ≥ 0.80 | 0.545 ❌ | 0.576 ❌ |
| 재현율 (3~5 m) | ≥ 0.60 | 0.539 ❌ | 0.320 ❌ |
| 흡연/소지 구분 | ≥ 0.75 | 0.967 ✅ | 0.973 ✅ |
| 유사물 오확정 (10분당) | ≤ 1 | 12.5 ❌ | 10.0 ❌ |
| 확정까지 시간 (중앙값) | ≤ 2 s | 0.53 s ✅ | 0.47 s ✅ |

리포트: `_workspace/eval_out/clips_dev_p02_v3_distfix/report.md`, `_workspace/eval_out/clips_dev_p02_v4/report.md`

### v5 결과 (2026-11-18, P02 dev, 판정 아님)

리포트 `_workspace/eval_out/clips_dev_p02_v5/report.md`.

| 지표 | 합격선 | v3 | v4 | v5 |
| --- | --- | --- | --- | --- |
| 정밀도 (4 m 이내) | ≥ 0.90 | 0.524 | 0.624 | 0.760 ❌ |
| 재현율 (3 m 이내) | ≥ 0.80 | 0.545 | 0.576 | 0.613 ❌ |
| 재현율 (3~5 m) | ≥ 0.60 | 0.539 | 0.320 | 0.049 ❌ |
| 흡연/소지 구분 | ≥ 0.75 | 0.967 | 0.973 | 1.000 ✅ |
| 유사물 오확정 (10분당) | ≤ 1 | 12.5 | 10.0 | 5.0 ❌ (2건) |

박스 위치를 장면으로 확인한 결과:
- 좋아진 점: side_001(옆모습)을 처음으로 확정했고 박스도 입 쪽에 있다. walking_001도 입의 담배를 잡는다. 유사물 오확정이 4건에서 2건으로 줄었다.
- 나빠진 점: mouth_002(3 m)·mouth_003(4.5 m)를 놓친다. v4는 이 두 클립에서 박스가 실제로 입의 담배 위에 있었다(진짜 정답). v5는 mouth_002에서 박스를 4프레임에만 잡았고, mouth_003에서는 무릎 위 휴대폰을 잡았다. 3~5 m 재현율 하락은 실제 성능 저하다.
- 그대로인 점: holding_001(2 m)은 박스가 0개다. holding_002(4 m)는 다시 가슴 로고를 잡는다(확정은 안 됨). similar_001/003은 손에 든 펜·흰 막대를 담배로 확정한다.
- 정밀도·오확정이 좋아진 것은 모델이 전반적으로 덜 반응하게 된 영향이 크다고 본다. S3에서 유사물 음성 사진 331장이 추가된 것이 원인일 수 있다(추정, 검증 안 함).
- 참고: `events.jsonl` 머리글의 `models.cigarette`는 실제 사용 모델과 상관없이 설정 기본값(v3)을 적는다. 실제 모델은 report.md의 `models:` 줄이 맞다. 결과에는 영향 없는 기록 버그.

### v5 판정 기준값 실험 (2026-11-18, 사용자 선택 "가")

`cig_conf_thresh`만 바꾸고 P02 dev를 다시 평가했다. 설정 파일은 세션 임시 폴더에 있었고, 리포트는 `_workspace/eval_out/clips_dev_p02_v5_t30`, `_t25`.

| 기준값 | 정밀도 ≤4 m | 재현율 ≤3 m | 재현율 3~5 m | 유사물 오확정 |
| --- | --- | --- | --- | --- |
| 0.35 (기본) | 0.760 | 0.613 | 0.049 | 2건 |
| 0.30 | 0.652 | 0.613 | 0.050 | 3건 |
| 0.25 | 0.673 | 0.613 | 0.241 | 4건 |

- 0.25에서 3~5 m 재현율이 오른 것은 전부 holding_002 확정 때문이다. 그런데 이때 박스는 **가슴 로고** 위에 있다(가짜 정답). mouth_002·003은 0.25에서도 확정되지 않는다.
- 결론: 기준값을 조정해도 v5가 놓친 먼 거리 입 담배는 되찾지 못한다. 오확정만 v4 수준으로 다시 늘어난다.

**유력한 원인 (데이터):** S1·S2를 다시 검수하면서 제외(ignore)한 사진이 86장으로 늘었다(v4 때 15장). mouth만 보면 58장이다(v4 때 8장). 이 사진들은 대부분 **4~5 m 이상 떨어져 앉아 손을 입에 댄 정면 장면**이다. 바로 v5가 놓친 mouth_002·003과 같은 장면이다. 86장 중 74장은 박스 파일(.txt)이 그대로 남아 있고 상태만 ignore다. v5의 학습용 양성은 2958 → 3359(+14 %)로, 음성은 11017 → 15787(+43 %)로 늘어 양성 비율도 낮아졌다.

### 진단에서 알게 된 것 (2026-11-13)

- holding_001(2 m): 사람 자세, 손 ROI, 거리 규칙은 278/278 프레임 모두 정상. 손 ROI에서 담배 점수가 낮을 뿐이다(순수 모델 재현율 문제).
- holding_002(4 m): v3의 "확정"은 담배가 아니라 후드티 가슴 로고와 휴대폰 모서리에 박스가 잡힌 것이다. 그래서 v3의 3~5 m 재현율은 우연한 오검출로 부풀려진 값이고, "v4가 원거리에서 나빠졌다"는 해석은 근거가 약하다.
- similar_001/003 오확정은 손에 든 볼펜·종이 막대를 담배로 본 것이다. gesture_002는 휴대폰 모서리와 로고.
- 평가 약점: `eval_clips.py`는 양성 구간에서 확정만 되면 정답으로 센다. 박스 위치는 확인하지 않는다.
- 학습 데이터는 P01 한 사람뿐이다. 참가자(P04 이상)를 늘리자는 제안은 v5 결과를 본 뒤 다시 논의하기로 했다. 그 전에는 README에 신규 참가자 절을 추가하지 않는다.

## 3. 최근에 한 일

### 2026-11-18
1. 사용자가 "S3 검수 끝". S3 500장 모두 ok. S1·S2도 사용자가 다시 검수해 제외 사진이 15장에서 86장으로 늘어 있었다.
2. v5는 11-17 밤에 이미 학습이 시작됐다가 18/30 epoch에서 끊겨 있었다. `--resume`로 30/30까지 마치고 `models/cig_roi_v5.onnx`로 내보냈다.
3. P02 dev 평가와 박스 위치 확인 → 2절 "v5 결과". 핵심: v5는 v4가 진짜로 잡던 먼 거리 입 담배(mouth_002 3 m, mouth_003 4.5 m)를 놓친다.
4. 판정 기준값을 0.30·0.25로 낮춰 다시 평가 → 해결되지 않음(2절 "기준값 실험").
5. 원인 추적: 다시 검수할 때 제외된 mouth 58장이 대부분 먼 거리 정면 입 담배 장면이었다.
6. `review_labels.py`에 `--only-ignored` 옵션 추가(8-6절). 종료 시 요약 줄의 분모 표시 오류도 고쳤다. 사용자가 86장을 다시 봐서 75장을 다시 포함했다. 시작 전 상태 백업: `data/labeled/review_state_P01_backup_20261118.json`, `data/labeled/ignore_backup_20261118.txt`.
7. 박스 위치 확인용 도구를 `prototype/box_sheet.py`로 저장했다(아래 4-2에서 사용).
8. v6 데이터셋을 만들고 학습을 시작했다(진행 중).

### 2026-11-17
- S3 사진 831장 확인(holding 310, mouth 190, similar 331). v4로 박스 초안을 만들었다(`prelabel.py --conf 0.25`): holding 107/310장, mouth 56/190장에 박스가 잡혔고, similar 167/331장은 오검출이었다.
- 검수 대기열 병합 `data/labeled/review_queue_P01.csv`(원본 백업 `review_queue_P01_S1S2_backup.csv`). `review_labels.py`에 `--session`, `--scenario` 추가. 인수문서 작성 → 커밋 `fdce68d`.

## 4. 다음 할 일 (순서대로)

### 4-1. v6 학습이 끝났는지 확인

```
Get-Content training\runs\cig_roi_v6_train.log -Tail 5
Get-Content training\runs\cig_roi_v6\results.csv | Select-Object -Last 3
```
- 끝났으면 로그 끝에 `TRAIN_WALL_SECONDS`와 `best weights: ...best.pt True`가 있다. 30번 반복에 약 2시간 20분 걸린다(03:03 시작 → 05:30 전후). 성능이 더 오르지 않으면 10번 만에 일찍 멈출 수 있다.
- **끊겼으면**(PC 재부팅·창 닫힘 등. 로그가 멈춰 있고 `tasklist | findstr python`에 아무것도 없을 때) 이어서 학습한다:
  ```
  .venv\Scripts\python training\train_cig_roi.py --data data\roi_ds_v6.yaml --epochs 30 --patience 10 --name cig_roi_v6 --resume
  ```
  `training\runs\cig_roi_v6\weights\last.pt`가 없으면(1번째 반복도 못 끝낸 경우) `--resume` 없이 처음부터 다시 돌린다.

### 4-2. Claude: 내보내기 → P02 평가 → 비교

```
.venv\Scripts\python training\export_onnx.py --weights training\runs\cig_roi_v6\weights\best.pt --out models\cig_roi_v6.onnx
.venv\Scripts\python prototype\eval_clips.py --clips-dir data\raw_clips\P02 --cig-model models\cig_roi_v6.onnx --tag dev_p02_v6
.venv\Scripts\python prototype\box_sheet.py _workspace\eval_out\clips_dev_p02_v6 data\raw_clips\P02\S1 _workspace\eval_out\box_v6 mouth_002 mouth_003 holding_001 holding_002 side_001 walking_001 similar_001 similar_003
```
- v4(`clips_dev_p02_v4`), v5(`clips_dev_p02_v5`)와 표로 비교한다.
- `box_v6\*.jpg`를 열어 박스가 실제로 담배 위에 있는지 확인한다. 가장 중요한 것은 **mouth_002·003을 진짜 담배로 다시 잡는지**, side_001·walking_001을 유지하는지, holding_002가 로고에 걸리지 않는지, similar 펜 오확정이 늘지 않는지다.
- 평가 리포트 머리글(`events.jsonl`)의 모델 이름은 항상 v3로 찍히는 기록 버그가 있다. 실제 사용 모델은 report.md의 `models:` 줄로 확인한다.

### 4-3. 사용자 결정

- 기본 모델(v3 유지 / v4 / v6) 교체 여부. 2026-11-18 기준 추천은 v3 유지였다(v6 결과 전).
- v6로도 먼 거리 입 담배나 펜 오확정이 해결되지 않으면 참가자 추가(P04 이상)를 다시 논의한다.
- P03 클립을 `data/eval/holdout`으로 옮기고 `eval_clips.py --final`을 실행할 시점.

## 5. 지켜야 할 규칙

- **P03(hold-out)은 사용자가 최종 평가를 요청하기 전에는 건드리지 않는다.** `--final` 실행 금지, P03 클립 이동 금지, P03 데이터로 학습·조정 금지.
- 사진·영상·모델 파일(`data/`, `models/`, `training/runs/`)은 git에 없다. **이 PC에만 있다.** 다른 PC에서 이어가려면 이 폴더들을 직접 복사해야 한다.
- 이 저장소에는 git 사용자 정보가 설정되어 있지 않다. 커밋할 때는 직전 커밋 작성자를 복사해 `git -c user.name=... -c user.email=... commit`으로 한다. 커밋·푸시는 사용자가 요청할 때만.
- `_workspace/사용자_할일.md`는 사용자가 직접 고친 파일이고 로컬 경로가 들어 있다. 묻지 않고 커밋하지 않는다.
- 계획 단계는 opus, 구현·검증 에이전트는 sonnet (CLAUDE.md).

## 6. 확인이 필요한 것 (2026-11-18 기준, 커밋 안 된 변경)

- `README.md`: 작업 폴더의 README가 커밋된 S3 촬영 안내(44dc254)가 아니라 **그 이전의 영상 촬영 안내와 비슷한 내용으로 바뀌어 있다**(약 600줄 차이). 사용자가 의도한 변경인지 확인 전까지 건드리지 않았다. 되돌리려면 `git checkout -- README.md`.
- `_workspace/사용자_할일.md`: 사용자 수정분, 커밋 안 함(5절).

## 7. 주요 파일 위치

| 용도 | 경로 |
| --- | --- |
| 설계서 | `_workspace/01_planner_spec.md` |
| 인식 구현 노트 (명령·결과 이력) | `_workspace/02a_perception_notes.md` |
| 우선순위 구현 노트 | `_workspace/02a_priority_notes.md` |
| QA 보고서 | `_workspace/03a_qa_report.md` |
| 공통 코어 | `src/ash_e_core/` |
| 웹캠 프로토타입·평가 도구 | `prototype/` |
| 학습 도구 | `training/` |
| 웹캠 실시간 데모 | `.venv\Scripts\python prototype\run_webcam.py` |
| 박스 검수 도구 | `prototype/review_labels.py` |
| 평가 클립 박스 위치 확인 | `prototype/box_sheet.py` |
| 검수 결과 | `data/labeled/review_state_P01.json` (ok/ignore), `data/labeled/ignore.txt`, 사진 옆 `.txt` 박스 파일 |

## 8. 검수하는 방법 (자세히)

### 8-1. 시작

저장소 폴더(`C:\Users\ghkim\Downloads\26PJT_ASH-E`)에서 PowerShell을 열고:
```
.venv\Scripts\python prototype\review_labels.py --pid P01
```
"ASH-E label review" 창에 사람 쪽으로 확대된 사진이 뜬다. 위쪽 글자는
`몇 번째/전체, 사진 이름, 박스 수, 상태(ok / ignore / -), 확대 모드`이다. `-`는 아직 검수 안 함.

### 8-2. 한 장마다 판단

| 화면 상태 | 할 일 |
| --- | --- |
| 박스가 담배에 딱 맞음 | **SPACE**(또는 ENTER) → 저장, 다음 사진 |
| 박스가 없는데 담배가 보임 | 담배를 **마우스 왼쪽 드래그**로 감싸고 → SPACE |
| 박스가 엉뚱한 곳(휴대폰, 로고, 펜, 손가락)에 있음 | 그 박스 위에서 **오른쪽 클릭**으로 지우고, 필요하면 새로 그린 뒤 → SPACE |
| 박스가 담배보다 너무 크거나 작음 | 오른쪽 클릭으로 지우고 다시 그린 뒤 → SPACE |
| 담배가 거의 안 보임(30 % 미만, 손에 가려짐, 너무 흐림) | **i** → 학습에서 빠짐, 다음 사진 |

박스 그리는 요령:
- 담배 개비만 꼭 맞게 감싼다. 불 붙는 끝부터 필터 끝까지 넣고, 손가락과 입술은 되도록 뺀다.
- 담배가 손가락에 일부 가려져도 보이는 부분이 30 % 이상이면 보이는 부분을 감싼다.
- 한 사진에 담배는 보통 하나다. 박스가 두 개 이상이면 틀린 쪽을 지운다.
- 4 m 사진은 담배가 작으므로 **z**를 눌러 "tight"(더 크게)로 보면 쉽다.

### 8-3. 그 밖의 키

| 키 | 기능 |
| --- | --- |
| u | 방금 그린 박스 취소 |
| c | 이 사진의 박스 전부 지우기 |
| z | 확대 전환: subject(사람) → tight(더 크게) → full(전체 사진) |
| n / b | 저장하지 않고 다음 / 이전 사진 (상태도 바뀌지 않음) |
| q / ESC | 저장하고 종료 |

### 8-4. 진행과 끝

- 한 장 5~10초면 S3 500장에 약 40분~1시간. 나눠서 해도 된다. 같은 명령으로 다시 열면 이어서 시작한다.
- S3 500장이 끝나면 "all ... frames already reviewed"가 나오며 종료된다(S1·S2는 이미 검수 끝).
- 검수 결과는 SPACE / i를 누를 때마다 바로 저장된다.

### 8-5. 이전에 검수한 사진 다시 검수하기

이미 검수한 사진도 다시 열어 고칠 수 있다. `--redo`는 처음부터 다시 보여 주고,
`--session`(S1, S2, S3)과 `--scenario`(holding, mouth)로 범위를 좁힐 수 있다(2026-11-17 추가).

```
.venv\Scripts\python prototype\review_labels.py --pid P01 --redo --session S1                    # S1 전체 다시
.venv\Scripts\python prototype\review_labels.py --pid P01 --redo --session S1,S2 --scenario holding  # S1·S2 holding만
.venv\Scripts\python prototype\review_labels.py --pid P01 --redo --session S3                    # S3 다시
.venv\Scripts\python prototype\review_labels.py --pid P01 --redo                                 # 전부 (1743장)
```

- 다시 검수할 때는 지금 저장된 박스가 그대로 보인다. 맞으면 SPACE, 고칠 게 있으면 고친 뒤 SPACE.
- **n**으로 넘기면 아무것도 바뀌지 않는다. 그래서 훑어보기만 하는 것도 안전하다.
- 예전에 `i`(제외)로 표시한 사진에서 SPACE를 누르면 다시 학습에 포함된다.
- 사진 수: S1 733장(holding·mouth), S2 510장, S3 500장. 기존 검수 결과는 S1 ok 729 / ignore 4, S2 ok 499 / ignore 11.
- 다시 검수하기 전에 백업해 두면 되돌릴 수 있다:
  ```
  Copy-Item data\labeled data\labeled_backup_20261117 -Recurse
  ```
- 다시 검수한 내용은 다음 학습(v5 이후)부터 반영된다.

### 8-6. 제외(ignore)한 사진만 다시 보기 (2026-11-18 추가)

```
.venv\Scripts\python prototype\review_labels.py --pid P01 --only-ignored                    # 제외한 86장 전부
.venv\Scripts\python prototype\review_labels.py --pid P01 --only-ignored --scenario mouth   # mouth 58장만
```
- 지금 제외로 표시된 사진만 처음부터 보여 준다. 저장된 박스가 그대로 보인다.
- 담배가 조금이라도(약 30 % 이상) 보이고 박스가 맞으면 **SPACE** → 다시 학습에 포함된다. 박스가 어긋나 있으면 고친 뒤 SPACE를 누른다.
- 정말 안 보이면 **i**(제외 유지)를 누르고, 판단이 어려우면 **n**(그대로 두고 넘김)을 누른다.
- 시작 전 상태는 `data/labeled/review_state_P01_backup_20261118.json`, `ignore_backup_20261118.txt`에 백업해 두었다. 이미 만든 v3·v4 모델은 바뀌지 않는다.
