# ASH-E 인수인계 문서

마지막 갱신: 2026-11-18 12시 30분 (v6 최종, P03 최종 시험 불합격, README 보고서)

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
| 브랜치 | `ash-e/stage-a-capture-priority` (main도 같은 커밋으로 fast-forward, 2026-11-18). `_workspace/사용자_할일.md`는 커밋 안 함 |
| **기본(최종) 담배 모델** | **`models/cig_roi_v6.onnx`** (사용자 결정 2026-11-18 "최종결과 v6"). config.py와 prototype 도구 기본값 모두 v6 |
| **P03 최종 시험** | **2026-11-18 12:08 v6로 1회 실행 → 불합격** (6개 중 2개 통과). `acceptance/holdout_runs.log` run #1, 리포트 `_workspace/eval_out/clips_holdout_p03_v6/run_001/`. P03 영상은 `data/eval/holdout/clips/P03/S1/`에 복사했고 영상 매니페스트 `acceptance/holdout_clips_manifest.json`이 생김 |
| 보고서 | README 5절(모델 개발 보고서 v1~v6), 참고 절(val mAP50 설명). 그래프 `docs/figures/` (`prototype/report_figures.py`로 재생성) |
| 예전 README | `docs/README_v1~v3_촬영안내_*.md` (v3 = 11-13 S3 촬영 안내, GitHub main에 있던 것) |
| ROS2 이식(단계 B) | **시작 안 함.** 사용자가 이식 준비를 요청했으나 합격선 미달이라 확인을 받았고, 사용자는 "P03 최종 시험 먼저"를 골랐다. 결과가 불합격이므로 다음 방향은 사용자 결정 대기(4절) |

### v6 핵심 수치 (자세한 표는 README 5절)

| 지표 | 합격선 | P02 dev | **P03 hold-out** |
| --- | --- | --- | --- |
| 정밀도 (≤4 m) | ≥ 0.90 | 0.804 | **0.471** ❌ |
| 재현율 (≤3 m) | ≥ 0.80 | 0.573 | **0.420** ❌ |
| 재현율 (3~5 m) | ≥ 0.60 | 0.153 | **0.166** ❌ |
| 흡연/소지 구분 | ≥ 0.75 | 1.000 | **0.993** ✅ |
| 유사물 오확정 (10분당) | ≤ 1 | 2.5 (1건) | **24.9 (10건)** ❌ |
| 확정 시간 중앙값 | ≤ 2 s | 7.8 s | **1.6 s** ✅ |

- P03 오확정 10건: gesture_002 4건(얼굴 앞 휴대폰 모서리), similar_001·002 각 3건(입에 댄 펜·막대). P03 결과는 모델 조정에 쓰지 않는다.
- v5부터 학습 시작점(v1 가중치 → COCO yolo11n)과 최적화기(AdamW → MuSGD 자동 선택)도 바뀌었다(README 5-3). 원거리 하락 원인을 데이터와 분리하지 못했다.

## 3. 최근에 한 일

### 2026-11-18 (오후)
1. v6 학습: 03:03 첫 시도는 Claude 세션 종료와 함께 끊김(1 epoch도 못 끝냄). 08:41 WMI(`Win32_Process.Create`)로 분리 실행해 처음부터 다시 → 30/30 완료(8,940 s), best epoch 26. `models/cig_roi_v6.onnx`.
2. P02 평가: 영상(v1·v3exp·v6 추가), 사진(v4·v5·v6 추가), 기준값 스윕(6개 버전), 박스 위치 확인(`_workspace/eval_out/box_v6`). v6가 영상 정밀도·오확정 최고, mouth_002(3 m) 회복, mouth_003(4.5 m)은 못 잡음.
3. 공통 val 비교 도구 `prototype/report_val_common.py` 추가(모든 버전을 v6 val로 평가, PR·F1 곡선). 그래프 도구 `prototype/report_figures.py` 추가.
4. 사용자 결정: v6 최종 → 기본 모델 v6로 변경, P03 `--final` 1회 실행(불합격).
5. README를 보고서 형태로 재구성(GitHub main의 11-13 README는 `docs/README_v3_촬영안내_2026-11-13.md`로 보관). Claude Docs 문서 "YOLO 학습 지표 쉽게 이해하기"를 참고 절로 옮김.
6. 커밋·푸시(브랜치 + main fast-forward).

## 4. 다음 할 일 (사용자 결정 필요)

1. **방향 결정:** (가) 정확도 개선 후 이식 — 학습 참가자 추가(P04 이상; 펜·막대를 입에 대기, 휴대폰을 얼굴 앞에 들기 장면), 원거리 ROI 확대, v7 실험(v6 데이터 + v1 가중치 + AdamW). 이 경우 P03는 이미 한 번 썼으므로 **새 hold-out 참가자**가 필요. (나) 사용자가 v6를 "현재 수준으로 프로토타입 합격"이라고 명시하면 단계 B(ROS2 이식) 시작 — `ash-e-orchestrator` 스킬 3B단계.
2. v7 실험을 하면: `.venv\Scripts\python training\train_cig_roi.py --data data\roi_ds_v6.yaml --weights training\runs\cig_roi_v2\weights\best.pt --epochs 30 --patience 10 --name cig_roi_v7` (`optimizer=auto`라 AdamW를 강제하려면 train_cig_roi.py에 옵션 추가 필요). 평가는 P02로만.
3. 긴 학습은 WMI로 분리 실행해야 Claude 세션이 끝나도 계속 돈다 (PowerShell):
   ```
   $cmd = "cmd.exe /c cd /d <repo> && .venv\Scripts\python training\train_cig_roi.py ... > training\runs\<name>_train.log 2>&1"
   Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=$cmd; CurrentDirectory=(Get-Location).Path}
   ```

## 5. 지켜야 할 규칙

- **P03(hold-out)은 2026-11-18 v6로 한 번 사용했다(run #1).** 다시 `--final`을 돌리거나 P03 결과로 모델·기준값을 조정하지 않는다. P03 데이터로 학습 금지. 다음 판정은 새 hold-out 참가자로 한다.
- 사진·영상·모델 파일(`data/`, `models/`, `training/runs/`)은 git에 없다. **이 PC에만 있다.** 다른 PC에서 이어가려면 이 폴더들을 직접 복사해야 한다.
- 이 저장소에는 git 사용자 정보가 설정되어 있지 않다. 커밋할 때는 직전 커밋 작성자를 복사해 `git -c user.name=... -c user.email=... commit`으로 한다. 커밋·푸시는 사용자가 요청할 때만.
- `_workspace/사용자_할일.md`는 사용자가 직접 고친 파일이고 로컬 경로가 들어 있다. 묻지 않고 커밋하지 않는다.
- 계획 단계는 opus, 구현·검증 에이전트는 sonnet (CLAUDE.md).

## 6. 확인이 필요한 것

- `_workspace/사용자_할일.md`: 사용자 수정분, 커밋 안 함(5절).
- (해결) 작업 폴더 README가 옛 영상 안내로 바뀌어 있던 문제: 2026-11-18 README를 보고서로 재구성하며 정리. 이전 작업 폴더본은 v2와 거의 같았다.

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
