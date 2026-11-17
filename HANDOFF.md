# ASH-E 인수인계 문서

마지막 갱신: 2026-11-17 (P01 S3 촬영 직후)

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
| 브랜치 | `ash-e/stage-a-capture-priority`, HEAD `44dc254` (origin과 main도 같은 커밋) |
| 기본 담배 모델 | `models/cig_roi_v3.onnx` (사용자 결정 2026-11-13) |
| v4 모델 | `models/cig_roi_v4.onnx`. P02 dev 평가에서 v3보다 낫다고 보기 어려움 |
| 참가자 분할 | P01 = 학습, P02 = dev(조정용), P03 = hold-out(최종 시험). `data/splits/participants.json` (git 제외) |
| 평가 클립 | `data/raw_clips/P02/S1` 13개, `data/raw_clips/P03/S1` 12개. 라벨은 사용자가 2026-11-13에 모두 확인 |
| **P01 S3 촬영** | **완료 (2026-11-17)**. `data/raw/P01/S3/` holding 310, mouth 190, similar 331 = 831장 |
| **S3 박스 초안** | **완료**. 아래 3절 |
| **S3 사람 검수** | **아직 안 함 ← 다음 할 일** |
| v5 학습·P02 비교 | 검수 후 진행 |

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

### 진단에서 알게 된 것 (2026-11-13)

- holding_001(2 m): 사람 자세, 손 ROI, 거리 규칙은 278/278 프레임 모두 정상. 손 ROI에서 담배 점수가 낮을 뿐이다(순수 모델 재현율 문제).
- holding_002(4 m): v3의 "확정"은 담배가 아니라 후드티 가슴 로고와 휴대폰 모서리에 박스가 잡힌 것이다. 그래서 v3의 3~5 m 재현율은 우연한 오검출로 부풀려진 값이고, "v4가 원거리에서 나빠졌다"는 해석은 근거가 약하다.
- similar_001/003 오확정은 손에 든 볼펜·종이 막대를 담배로 본 것이다. gesture_002는 휴대폰 모서리와 로고.
- 평가 약점: `eval_clips.py`는 양성 구간에서 확정만 되면 정답으로 센다. 박스 위치는 확인하지 않는다.
- 학습 데이터는 P01 한 사람뿐이다. 참가자(P04 이상)를 늘리자는 제안은 v5 결과를 본 뒤 다시 논의하기로 했다. 그 전에는 README에 신규 참가자 절을 추가하지 않는다.

## 3. 오늘(2026-11-17) 한 일

1. S3 사진 831장 확인. 거리·각도 태그 분포:
   - holding: 2 m 정면 72 / 2 m 옆 58 / 3 m 옆 53 / 4 m 정면 38 / 4 m 좌45° 40 / 4 m 우45° 47 / 미지정 2
   - mouth: 2 m 옆 99 / 3 m 옆 91
   - similar: 2 m 100 / 3 m 127 / 4 m 104
2. v4 모델로 박스 초안 생성 (`--conf 0.25`):
   ```
   python prototype/prelabel.py --src data/raw/P01/S3 --model models/cig_roi_v4.onnx --conf 0.25
   ```
   - holding 310장 중 107장, mouth 190장 중 56장에만 박스가 잡혔다. **나머지 337장은 박스가 없어 사람이 직접 그려야 한다.**
   - similar 331장 중 167장(50 %)에서 모델이 담배라고 오검출했다. 이 사진들은 라벨이 비어 있는 "담배 없음" 학습 예시로 쓰이므로 검수할 필요는 없다.
   - 참고로 v3로도 초안을 만들어 비교했다(mouth 83장, holding 77장에 박스). 어느 쪽도 확실히 낫지 않아 오검출이 적은 v4 초안을 썼다.
   - 출력: `data/labeled/P01/S3/`, `data/labeled/review_queue_S3.csv`, `data/labeled/prelabel_report_S3.json`
3. 검수 대기열 병합: `data/labeled/review_queue_P01.csv` = S3 500장(앞) + 기존 S1·S2 1243장(뒤, 이미 검수 끝).
   병합 전 원본은 `data/labeled/review_queue_P01_S1S2_backup.csv`에 있다. `review_labels.py --selftest` 통과.

## 4. 다음 할 일 (순서대로)

### 4-1. 사용자: S3 박스 검수 (약 500장)

```
.venv\Scripts\python prototype\review_labels.py --pid P01
```
- 아직 검수 안 한 첫 사진(S3)부터 열린다. 박스 없는 337장이 먼저 나온다.
- 마우스 왼쪽 드래그 = 박스 그리기, 오른쪽 클릭 = 박스 지우기, SPACE/ENTER = 맞음·저장·다음,
  `i` = 담배가 30 % 미만 보임(학습 제외), `u` 되돌리기, `c` 전체 지우기, `z` 확대 전환, `q`/ESC 저장 후 종료.
- 중간에 꺼도 다음 실행 때 이어서 열린다. 결정은 `data/labeled/review_state_P01.json`에 저장된다.
- 끝나면 Claude에게 **"S3 검수 끝"**이라고 알린다.

### 4-2. Claude: v5 데이터셋·학습·내보내기 (v4와 같은 설정)

```
.venv\Scripts\python training\build_roi_own_reviewed.py --pid P01 --out data\roi_own_p01_reviewed_v5 --yaml data\roi_ds_v5.yaml --clean
.venv\Scripts\python training\train_cig_roi.py --data data\roi_ds_v5.yaml --epochs 30 --patience 10 --name cig_roi_v5
.venv\Scripts\python training\export_onnx.py --weights training\runs\cig_roi_v5\weights\best.pt --out models\cig_roi_v5.onnx
```
- `--clean`은 `--out` 폴더를 통째로 지운다. 반드시 새 이름(`_v5`)을 쓴다.
- 학습은 v4 기준 약 1시간 이상. 끊기면 `train_cig_roi.py ... --name cig_roi_v5 --resume`.
- 학습 전에 검수 통계(S3 ok / ignore 개수)를 확인해 보고한다.

### 4-3. Claude: P02 dev 클립 평가와 비교

```
.venv\Scripts\python prototype\eval_clips.py --clips-dir data\raw_clips\P02 --cig-model models\cig_roi_v5.onnx --tag dev_p02_v5
```
- v3(`clips_dev_p02_v3_distfix`), v4(`clips_dev_p02_v4`)와 표로 비교한다.
- 숫자만 보지 말고 holding_001, holding_002, side_001, similar_001/003에서 **박스가 실제로 담배 위에 있는지** 몇 프레임 확인한다(2절 진단 참고).
- 기본 모델 교체 여부는 사용자가 정한다.

### 4-4. 그 다음 (사용자 결정 필요)

- 참가자 추가(P04 이상) 여부.
- P03 클립을 `data/eval/holdout`으로 옮기고 `eval_clips.py --final` 실행할 시점.

## 5. 지켜야 할 규칙

- **P03(hold-out)은 사용자가 최종 평가를 요청하기 전에는 건드리지 않는다.** `--final` 실행 금지, P03 클립 이동 금지, P03 데이터로 학습·조정 금지.
- 사진·영상·모델 파일(`data/`, `models/`, `training/runs/`)은 git에 없다. **이 PC에만 있다.** 다른 PC에서 이어가려면 이 폴더들을 직접 복사해야 한다.
- 이 저장소에는 git 사용자 정보가 설정되어 있지 않다. 커밋할 때는 직전 커밋 작성자를 복사해 `git -c user.name=... -c user.email=... commit`으로 한다. 커밋·푸시는 사용자가 요청할 때만.
- `_workspace/사용자_할일.md`는 사용자가 직접 고친 파일이고 로컬 경로가 들어 있다. 묻지 않고 커밋하지 않는다.
- 계획 단계는 opus, 구현·검증 에이전트는 sonnet (CLAUDE.md).

## 6. 확인이 필요한 것 (2026-11-17 기준, 커밋 안 된 변경)

- `README.md`: 작업 폴더의 README가 커밋된 S3 촬영 안내(44dc254)가 아니라 **그 이전의 영상 촬영 안내와 비슷한 내용으로 바뀌어 있다**(약 600줄 차이). 사용자가 의도한 변경인지 확인 전까지 건드리지 않았다. 되돌리려면 `git checkout -- README.md`.
- `CLAUDE.md`: 사용자가 촬영 안내 문장을 추가했고, Claude가 HANDOFF.md 안내 한 줄을 추가했다.
- `HANDOFF.md`(이 파일): 새 파일, 아직 커밋 안 함.

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
