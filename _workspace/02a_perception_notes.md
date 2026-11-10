# 02a 인식 구현 노트 (단계 A, Windows 프로토타입)

최종 갱신 2026-10-28 (공개·합성 데이터 보충 반영). 표기: **[실행 확인]** = 이번에 실제로 실행해 결과를 봤다. **[미검증]** = 코드만 있고 실행해 보지 않았다.
모든 명령은 프로젝트 루트(`<프로젝트 루트>`)에서, `.venv`의 파이썬으로 실행한다 (`.venv\Scripts\python`). 전역 설치는 하지 않는다.

---

## 사용자 작업 (당신이 할 일)

지금 상태 (2026-10-28): 공개 CigDet + COCO none/유사물 + 합성으로 만든 학습 세트 `data/roi_ds_v2`(train 5266 / val 506 ROI)가 있다. 기존 `data/roi_ds`(v1)는 그대로 보존했다. **자체 촬영 데이터는 여전히 0장**이다. 공개·합성 데이터는 "담배 없는 사람/유사물" 음성을 채워 주지만 로봇 시점(1~5 m, 웹캠)의 양성은 못 채운다. 따라서 **합격 판단은 직접 촬영한 평가 데이터로만** 한다.

### 새 촬영 계획 (공개·합성 보충 후 변경안)
| 용도 | 사람 | 분량 | 비고 |
| --- | --- | --- | --- |
| 학습 (공개+합성+본인) | 본인 1세션 (P01) | 아래 시나리오 1~5를 1회, 약 15분 | 로봇 시점 양성(holding/mouth, 거리 1~5 m)을 만드는 유일한 자체 학습 데이터 |
| 평가 (dev + hold-out) | 학습에 안 쓴 사람 2~3명 (P02~P04) | 1인 약 15분. hold-out은 `make_splits.py`에서 사용자가 승인해 정함 | 평가는 직접 촬영분만. 공개·합성 데이터는 평가에 절대 안 씀 |

- 기존 안(6명 이상, 담배 ROI 3000개 이상)보다 대폭 줄였다. 대신 아래 **신뢰도 한계**를 보고서에 명시해야 한다.
- **hold-out 신뢰도가 낮다는 점을 보고서에 반드시 적는다. 근거:** (1) hold-out이 1~2명이면 사람 간 차이(손 모양, 담배 쥐는 법, 얼굴 각도)를 표본으로 보지 못한다. 한 사람의 연속 프레임은 서로 독립이 아니어서 프레임 수가 많아도 유효 표본은 사람 수(2~3)에 가깝다. (2) 신뢰구간은 프레임 수가 아닌 사람/클립 수 기준으로 매우 넓다. 예를 들어 독립 시도 20번 중 20번 성공해도 95% 하한(Wilson)은 약 0.84다 [계산값]. (3) 학습에 본인 1명만 들어가므로 일반화(다른 사람)는 평가 2~3명으로만 확인된다. 합격 선언 문구는 "소수 인원 hold-out 기준 합격, 일반화는 미검증"으로 한다.
- 구분 가능 여부를 빨리 보려면: 본인 1세션만 찍어도 3단계의 `prelabel_report`로 none/similar/gesture 오검출을 바로 볼 수 있다.

### 0. 촬영 전 동의 확인 (필수)
- 참가자는 성인, **서면 동의**. 동의서에 목적(졸업작품 인식 모델 학습·평가), 보관 장소·기간(로컬 `data/`, 최종 평가 종료 후 삭제), 공개 금지, 철회 시 삭제를 적는다. 동의서는 `data/consent/`에 별도 보관하고 이름-ID 대응표는 거기에만 둔다.
- **불을 붙이지 않는다.** 미점화 담배 또는 모형(흰 종이 말이 + 주황 필터 테이프, 길이 약 8.5 cm, 지름 0.8 cm). 실물이 절반 이상이면 좋다.
- 참가자는 이름이 아닌 ID(`P01`, `P02`...)로만 기록한다. 새 계획은 학습용 본인 1명 + 평가용 2~3명(위 표). 6명 미만이므로 hold-out 신뢰도가 낮다고 보고서에 적어야 한다.
- 동의를 받았다는 확인은 사람이 하는 것이다. `capture.py`는 `--consent-confirmed`가 없으면 기록을 거부한다 [실행 확인: 플래그 없이 실행하면 거부됨, 이름 형태 ID(`Kim`)도 거부됨].

### 1. 촬영 (`prototype/capture.py`)
```
.venv\Scripts\python prototype\capture.py --participant P01 --session S1 --consent-confirmed
```
- 키: `1`~`7` 시나리오 선택 / `SPACE` 자동 촬영 시작·정지(기본 2장/초) / `s` 한 장 / `d` 거리 태그 순환 / `c` 각도 태그 순환 / `q` 종료.
- 저장 위치: `data/raw/<참가자>/<세션>/<시나리오>/*.jpg` + `meta.jsonl`. 모두 로컬.
- 웹캠 1280x720을 명시 요청한다 (이 PC에서 1280x720 수신 확인됨).
- **참가자 1명당 약 15분, 아래 순서로.** 거리는 바닥에 1/2/3/4/5 m 테이프를 붙이고 `d`로 태그를 맞춘다. 노트북 웹캠 높이가 낮으면 로봇 시점(1.0~1.2 m)과 다르므로 노트북을 책상 위 등으로 올려 두는 것을 권장.

| 순서 | 키 | 시나리오 | 무엇을 하나 | 1인당 최소 분량 |
| --- | --- | --- | --- | --- |
| 1 | `1` holding | 손에 든 담배 | 내린 손/가슴 높이/손가락 사이, 왼손·오른손. 거리 1~5 m 각각 | 거리당 1분 = 5분 |
| 2 | `2` mouth | 입에 문/입에 댄 담배 | 입에 물기 ↔ 내리기 반복, 정면/좌우 45°/측면, 거리 1~4 m | 거리당 1분 = 4분 |
| 3 | `3` none | 아무것도 없음 | 서 있기, 걷기, 손 움직이기. 담배 화면에 없음 | 1.5분 |
| 4 | `4` similar | 유사물 | 볼펜, 빨대, 젓가락, 막대사탕, 립밤을 손에/입에 | 2분 |
| 5 | `5` gesture | 동작 | 통화, 음료 마시기, 입 가리기, 턱 괴기, 손가락 물기, 하품 | 2분 |
| 6 | `6` ecig_liquid | 액상 전자담배 (전원 끔) | 손/입. **없으면 생략** | 1분 |
| 7 | `7` ecig_heated | 궐련형 기기 (전원 끔) | 손/입. **없으면 생략** (합격 판정에서 제외, 참고용) | 1분 |

- 조명: 가능하면 실내 형광등 + 창가(역광) 둘 다 한 세션씩. 지나가는 사람이 찍히면 그 프레임은 지운다.
- **최소 촬영 분량 (변경안)**: 설계서 9A.3의 "자체 담배 ROI 3000개 이상, 음성 3000개 이상"은 공개 양성 1297+합성 328, COCO 음성 2475로 일부 대체한다고 보고 자체 목표를 낮췄다. 본인 1세션 + 평가 2~3명, 각 약 15분(2 fps로 약 1800프레임, 담배 ROI 약 1000개 [추정]). 설계서 기준 미달이므로 설계서 수정 승인 대상이다 [미승인].
- **구분 가능 여부를 빨리 보고 싶으면**: 참가자 1~2명으로 위 순서를 한 번만 찍어도 2·3단계(사전 라벨 → 평가)에서 "none/similar/gesture에서 오검출이 얼마나 나는가"를 `prelabel_report_*.json`으로 즉시 볼 수 있다.

### 2. 사전 라벨링 후 사람이 검수 (`prototype/prelabel.py`)
```
.venv\Scripts\python prototype\prelabel.py --src data\raw\P01 --model models\cig_roi.onnx
```
- 먼저 `models\cig_roi.onnx`가 있어야 한다 (5번 "본 학습" 참조). 없으면 빈 초안 라벨이 만들어지고 전부 손으로 그려야 한다.
- 결과: `data/labeled/P01/<세션>/<시나리오>/`에 이미지, YOLO txt 초안(클래스 0=cigarette), `classes.txt`. holding/mouth는 모델 박스가 초안이고, none/similar/gesture/ecig_*는 **빈 라벨(하드 네거티브)**이며 거기서 모델이 낸 박스는 오검출 통계(`data/labeled/prelabel_report_P01.json`)로만 센다.
- 검수 순서표: `data/labeled/review_queue_P01.csv` (박스를 못 찾은 프레임 → 신뢰도 낮은 순). **초안을 그대로 쓰지 말고 holding/mouth 프레임은 전부 확인**한다. 담배가 길이의 30% 미만만 보이면 박스를 치지 않고 그 프레임을 `data/labeled/ignore.txt`에 적는다 (설계서 9A.5).
- 라벨링 도구 (로컬 실행만, 클라우드 업로드 금지): **X-AnyLabeling** (GitHub 릴리스의 Windows 실행 파일 또는 pip 패키지를 별도 가상환경에 설치) 또는 **labelImg**. 둘 다 `data/labeled/<...>` 폴더를 열고 YOLO 형식, 클래스 `cigarette`로 저장. **[미검증]** 이 PC에 설치해 보지 않았다. 정확한 패키지명·설치 명령은 설치 시점의 공식 README를 확인할 것 (설치는 `.venv`가 아닌 별도 폴더/가상환경에).
- 이 단계에서 `prelabel.py`는 [실행 확인]됨 (공개 이미지 6장을 임시 폴더에 넣어 실행, 라벨/큐/리포트 생성 확인 후 임시 데이터는 삭제함).

### 3. 평가용 프레임 만들기 + 평가 (`make_eval_labels.py`, `eval_images.py`)
평가는 학습에 쓰지 않는 사람으로 한다. **hold-out 참가자(2명 이상)는 지금 정하지 말고 `make_splits.py` 단계에서 사용자가 승인해 정한다.** 튜닝은 dev로만 한다.
```
# dev (튜닝용, train/val 참가자의 프레임 일부) -- 학습에 쓴 프레임과 겹치지 않게 별도 촬영분을 권장
.venv\Scripts\python prototype\make_eval_labels.py --participants P01,P02 --split dev --every 2 --review
.venv\Scripts\python prototype\eval_images.py --cig-model models\cig_roi.onnx
# hold-out (최종 보고용): 한 번만 만들고 바로 잠근다
.venv\Scripts\python prototype\make_eval_labels.py --participants P05,P06 --split holdout --review
.venv\Scripts\python training\lock_acceptance.py --create
.venv\Scripts\python prototype\eval_images.py --final --cig-model models\cig_roi.onnx
```
- `--review` 창에서 `s`=smoking, `h`=holding, `n`=none, `d`=버림, `SPACE`=유지, `q`=중단. mouth 시나리오에서 손을 내린 순간은 실제로 holding이므로 반드시 고친다.
- 평가 결과: `_workspace/eval_out/report_<dev|holdout>.md`와 오검출 상위 20건(FP/FN)의 **ROI 크롭**.
- 영상 클립 단위 평가(확정 시간, 오확정 횟수)는 `data/eval/<split>/clips/<id>.mp4` + `labels/<id>.json`(설계서 9.2)이 있어야 하며, `capture.py`는 jpg만 저장하므로 클립은 별도 녹화가 필요하다 (`eval_images.py --clips`). 현재 이 입력을 만드는 도구는 없다.
- 합격 판정은 hold-out으로만 하고, `--final` 실행 횟수가 `acceptance/holdout_runs.log`에 기록된다. 보고할 때 횟수를 같이 적는다.

### 4. 학습/분할 순서 (자체 데이터가 모인 뒤)
```
.venv\Scripts\python training\make_splits.py --holdout P05,P06 --val P04 --approve-holdout
.venv\Scripts\python training\build_roi_dataset.py --source own --out data\roi_ds_own   # 자체 라벨 -> ROI 데이터셋. 기본 --out(data\roi_ds, 공개 데이터)에 겹쳐 쓰거나 --clean 하지 말 것 (--clean은 --out 폴더를 통째로 지운다). 공개+자체를 합쳐 학습하는 방법(data.yaml에 두 폴더 나열)은 미검증
oi_ds, 공개 데이터 포함)를 통째로 지운다. 합칠지 따로 둘지(--out) 먼저 정할 것
```
**[미검증]** `make_splits.py`, `build_roi_dataset.py --source own`은 자체 데이터가 없어 실행하지 못했다 (`--help` 기동만 확인). `--source public`은 이전 실행에서 `data/roi_ds`를 만든 것으로 보이나 이번에 재실행하지 않았다.

### 5. 본 학습 시작 명령 (이번에는 시작하지 않았다)
공개+합성 세트는 이미 `data\roi_ds_v2`에 있다. 재생성이 필요하면 `build_roi_dataset_v2.py --out data\roi_ds_v2` (**`--clean`은 `--out`을 통째로 지운다**). `train_cig_roi.py`가 `data\roi_ds_v2\data.yaml`을 받는 인자는 `--help`로 확인할 것 (v2_small 실행은 이 data.yaml로 돌았다).
```
.venv\Scripts\python training\train_cig_roi.py --epochs 80 --batch 32 --workers 2 --name cig_roi
.venv\Scripts\python training\export_onnx.py        # training\runs\cig_roi\weights\best.pt -> models\cig_roi.onnx
```
예상 시간은 아래 "본 학습 예상 시간" 절. 학습 중에는 PC 부하가 높다. 공개 데이터만으로 먼저 돌려 `models\cig_roi.onnx`를 만들면 2번의 사전 라벨링에 쓸 수 있다.

### 6. 지금 바로 해 볼 수 있는 것
- 웹캠 데모: `.venv\Scripts\python prototype\run_webcam.py` (`q` 종료). 담배 모델이 없으면 화면에 `NO MODEL`이 뜨고 상태는 none으로 유지된다. 스모크 모델로 기동만 보려면 `--cig-model training\runs\smoke\weights\best.onnx` (1 에폭짜리라 정확도 없음).

---

## 이번 실행에서 확인한 결과 (기존 코드 검증 포함)

### 환경
- Python 3.12.10 (`.venv`), Windows 11, CUDA 없음 → CPU 전용 (AMD Ryzen AI Max+ 395, 32 스레드). numpy 1.26.4, opencv 4.11.0.86, onnxruntime 1.31.1, torch 2.14.1+cpu, ultralytics 8.4.190, pytest 9.1.1. 목록은 `requirements.txt`.
- 웹캠: `cv2.VideoCapture(0, CAP_DSHOW)`로 열림, 1280x720 요청 시 1280x720 수신 [실행 확인, run_webcam 실행에서 재확인].

### pytest [실행 확인]
`cd src\ash_e_core; ..\..\.venv\Scripts\python -m pytest test -q` → **31 passed, 0 failed** (0.21 s). 모델 파일이 필요 없는 단위 테스트다 (추론 경로는 아래 기능 실행으로 확인).

### 컴파일 / --help [실행 확인]
`python -m py_compile`이 `prototype/*.py`, `training/*.py` 전부 성공. `--help`로 기동 확인: capture, prelabel, build_roi_dataset, lock_acceptance, make_splits, train_cig_roi, export_onnx.

### 스모크 학습 결과 (`training/runs/smoke/`) [실행 확인]
- 파이프라인이 끝까지 돌았다: `results.csv` 1행(1 에폭), `weights/best.pt`, `last.pt`, `best.onnx`(입력 1x3x192x192, 출력 1x5x756) 존재. 120장 학습/40장 검증, 에폭 소요 2.1 s.
- 정확도는 의미 없음 (1 에폭, mAP50 0.0005). 파이프라인 동작 확인용이다.
- 설계서와 어긋난 코드: 찾지 못했다. 안정화(창 1.5 s, 확정 0.6/최소 4관측, 해제 0.25/1 s, 래치 20 s), ROI 규칙, 상태 판정 반경이 설계서 5.4와 일치. 백엔드는 설계대로 onnxruntime만 구현 (NCNN은 단계 B).

### 파이프라인 end-to-end [실행 확인]
`models/pose.onnx`(YOLO11n-pose 320) + 스모크 `best.onnx`로 웹캠과 CigDet 이미지를 처리해 사람/키포인트/ROI/담배 박스/상태가 나오는 것을 확인했다.

### `prototype/eval_images.py` (신규)
- 기능: 프레임 단위 3x3 혼동행렬, 클래스별 precision/recall/F1, 이진(담배 vs 아님) 지표, smoking/holding 구분 정확도, 거리 구간별(프록시) 재현율·정밀도, 유사물 카테고리별 FP, 추론 시간, FP/FN 상위 20건의 **ROI 크롭** 저장, 합격선 비교표. `--clips`는 안정화 상태 기준 확정 시간(중앙값/95%), 양성 구간 확정 비율, none 구간 10분당 오확정 횟수.
- 보호: `acceptance.yaml`을 `acceptance/acceptance.sha256`으로 잠갔고(`lock_acceptance.py --lock-thresholds`, 읽기 전용 속성 설정) 매 실행마다 해시를 검증한다. hold-out 경로는 `--final` 없이는 거부, `--final`은 매니페스트를 검증하고 불일치/없음이면 결과를 내지 않으며 실행을 `acceptance/holdout_runs.log`에 남긴다. 이 스크립트는 `acceptance/`에 그 로그 외에는 쓰지 않는다.
- [실행 확인]: (a) 데이터가 없으면 "평가 데이터 없음, 촬영 필요" 안내 후 정상 종료. (b) 해시 OK 출력. (c) `data/eval/holdout/...` 입력을 `--final` 없이 주면 REFUSED. (d) `--final`인데 매니페스트가 없으면 REFUSED. (e) 공개 데이터로 만든 데모 세트(`data/eval/demo_cigdet`, 40장, `--make-demo-cigdet 40`)로 이미지 모드 전체 실행, 리포트와 크롭 생성. (f) 같은 이미지 1장을 8초 영상으로 만든 합성 클립으로 클립 모드 실행(확정 0.40 s, 임시 클립은 삭제함).
- **[미검증]**: 해시 불일치 경로(acceptance.yaml을 일부러 바꿔 보지 않음), `--final` 성공 경로(hold-out 데이터가 없음), none 클립의 오확정 계산(실제 none 클립 없음), 다인 클립의 트랙 추적.
- 데모 세트 결과(스모크 1 에폭 모델): 40장 중 TP 11 / FN 29, 재현율 0.275. 이 숫자는 **정확도가 아니다**: 라벨이 "positive"(담배 있음)뿐이고 사람 박스는 포즈 모델이 만든 것이며 음성이 없어 정밀도는 정의되지 않는다. 도구가 돌아가는지 보는 용도다.
- 한계: 이미지 모드는 raw_state 기준이다 (안정화 상태 기준 합격선과는 다름). 라벨이 없는 검출 사람은 혼동행렬에 넣지 않고 "unlabeled detections"로 따로 센다.

### `prototype/run_webcam.py` (신규)
- 1280x720을 명시 요청하고 수신 해상도를 출력한다. 처리율은 `process_rate_hz=8`로 제한, 화면에는 카메라 FPS, 추론 Hz/ms, 사람별 상태(none/holding/smoking, 안정화), raw 상태, 담배 박스, 키포인트, ROI, 프록시 거리를 표시한다. `q`로 종료. `--no-gui --max-seconds N`으로 헤드리스 점검, `--video 파일`도 지원.
- 모델이 없으면 콘솔에 "모델 없음: ..."을 출력하고 화면에 ASCII 배너 `NO MODEL: cigarette`를 표시하며 기동한다 (cv2는 한글을 그릴 수 없다).
- [실행 확인] (이 PC 웹캠, 사람 1명 앞에서):
  - 담배 모델 없이 8 s 헤드리스: 1280x720 수신, 235프레임(28.2 fps), 59회 처리(7.1 Hz; 카메라 28 fps에서 4프레임마다 처리해 8 Hz에 못 미침), 평균 추론 8.2 ms, 사람 1명 검출, "모델 없음" 메시지 출력.
  - 스모크 담배 모델 8 s: 평균 추론 12.1 ms.
  - GUI 창 모드 5 s(`imshow` 포함) 크래시 없이 종료. **`q` 키 입력 종료는 직접 눌러 보지 못했다 [미검증]**, 화면 오버레이의 모양도 이미지로 확인하지 못했다 (얼굴 저장을 피함).
- **다운로드 기록**: 이번 실행에서 ultralytics 자동 다운로드는 **일어나지 않았다** (`models/pose.onnx`, `models/yolo11n-pose.pt`가 이미 있음). `models/pose.onnx`가 없을 때 `.pt`를 받아 ONNX로 내보내는 코드 경로는 **[미검증]**.
- 추론 시간은 이 PC(고성능) 기준이다. RPi5 값은 별도 측정 필요 (설계서 9.3 5항, 추정은 PC x 5~10).

### `prototype/make_eval_labels.py` (신규, 설계서에 없던 보조 도구)
촬영 프레임에서 평가용 이미지+json을 만든다 (가장 큰 사람을 대상으로 시나리오에서 유추한 라벨 초안, `--review`로 수정). [실행 확인]: 합성 raw 폴더(공개 이미지 4장)로 dev 세트 생성 → `eval_images.py`가 읽는 것까지 확인, 임시 데이터 삭제. `--review` 화면 조작은 [미검증].

### `prototype/prelabel.py` 수정
리뷰 큐/리포트 파일명을 `--src`별로 분리 (`review_queue_<src>.csv`) — 참가자를 여러 명 처리해도 서로 덮어쓰지 않는다.

---

## 공개·합성 데이터 보충 (v2) 검증 결과

수치는 이번 실행에서 직접 읽거나 측정했다. 출처·라이선스는 `data/SOURCES.md`.

### 받은 것과 용량
- COCO annotations zip 242 MB + val2017 부분집합 이미지 1164장(none 1000, similar 164) 181 MB. CigDet 76 MB(이전). `du` 기준 `data/public` 516 MiB, 상한 3 GB의 약 17%. 합성 `data/synth` 29 MB(생성물), `data/roi_ds_v2` 60 MB, `data/roi_ds` 35 MB(보존 확인).
- similar는 500장을 요청했으나 조건(사람 키 30% 이상 + 손/입 근처 가는 물체, ND 라이선스 제외)을 만족한 것이 164장뿐이었다. 더 받으려면 train2017(약 18GB)이 필요해 받지 않았다.

### `roi_ds_v2/build_report.json` (ROI 샘플 수; 양성 = 담배 라벨 있음)
| 분할 | 양성 | public_pos | synth_pos | 음성 | coco_none | coco_similar | public_neg | 음성/양성 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 1625 | 1297 | 328 | 3641 | 2087 | 388 | 1166 | 2.24 |
| val | 186 | 186 | 0 | 320 | 194 | 43 | 83 | 1.72 |
- 합성은 train 양성의 20%(328/1625). val에는 합성이 없고 양성은 CigDet 실사진뿐이다. 클래스는 `cigarette` 1개, 양성:음성 약 1:2.2.
- pHash 중복 제거: val에서 2장 제거 (train은 기록 없음).
- 합성 몽타주 `_workspace/eval_out/synth_montage.jpg`(24장) 육안 점검: 대부분 손/입 근처에 담배가 붙었고 박스가 맞는다. 일부는 담배가 너무 작아 거의 안 보이고 조명이 배경과 어색하다. 현실감은 낮다.

### none 이미지에 담배가 섞였는지 점검
- 방법 1: `fetch_coco_subset.py`가 COCO 카테고리로 선별. COCO에는 담배 카테고리가 없어 **이 선별은 담배를 걸러 주지 않는다**.
- 방법 2: `build_roi_dataset_v2.py`가 calib 모델(2 에폭짜리)로 conf 0.5 이상 검출된 ROI를 제외하는 스크린. 걸러 낸 수는 빌드 로그에 없다. `coco_neg_flagged_by_screen.jpg`가 생성되지 않았으므로 0으로 추정한다 [추정]. 이 모델 재현율이 낮아 약한 필터다.
- 방법 3 (이번 실행): 최종 `roi_ds_v2`의 COCO 음성 ROI(train 2475, val 237)에 calib와 v2_small 모델을 conf 0.25로 돌림. calib는 24장(train 17+6, val 1+0), v2_small은 2장 검출. conf 0.5에서는 둘 다 0장. 검출된 장을 사람이 하나씩 보지는 않았다 [미검증].
- 방법 4: 무작위 48 ROI 몽타주(`_workspace/eval_out/coco_neg_random_sample.jpg`) 육안 점검에서 명확한 담배는 없었고 1장(철망 앞 손, 가는 갈색 물체)이 애매했다. 전수 검수는 하지 않았다.
- 결론: 우연히 섞였을 가능성은 낮지만 0이라고 보장하지 못한다.

### 평가 경로에 공개/합성이 섞였는지 (grep과 코드 확인)
- `training/build_roi_dataset_v2.py`는 `data/public`, `data/synth`만 읽고 입력마다 `refuse_holdout()`를 호출한다 (`data/eval/holdout`, `acceptance/` 거부).
- `prototype/eval_images.py` 입력 기본값은 `data/eval/dev/images` 또는 hold-out이고 COCO·synth 경로를 참조하지 않는다. `make_eval_labels.py`는 `data/raw`(자체 촬영)에서만 만든다. `training/make_splits.py`는 `data/labeled`(자체)를 나누고, CigDet은 hold-out과의 pHash 누출 검사에만 쓴다. COCO·합성은 평가 경로 어디에도 없다.
- 현재 `data/eval/`에는 `demo_cigdet`(CigDet test 40장, 도구 기동 확인용, 정확도 시험 아님)뿐이다. 공개 데이터이므로 dev/hold-out과 섞지 말 것. v2 val의 CigDet test와 겹친다.
- 한계: 코드 확인이며 hold-out 데이터가 아직 없어 실제 실행으로 방어를 검증하지는 못했다.

### 실행 확인
- [실행 확인] `synth_copy_paste.py`, `build_roi_dataset_v2.py`, `fetch_coco_subset.py` `--help` 기동. pytest `src/ash_e_core` **31 passed** (0.21 s).
- [이전 실행 기록과 가중치를 읽고 재사용] `training/runs/v2_small` (yolo11n, `roi_ds_v2`, 3 에폭, batch 32, imgsz 192, CPU): 3 에폭 완료, 총 195 s(에폭당 약 60~70 s). val mAP50 0.032 -> 0.140 -> **0.326**, P 0.437, R 0.338. 이번에 재실행하지는 않고 `results.csv`와 `best.pt`를 읽었다. 3 에폭이라 **의미 있는 성능이 아니다.** v1 보정(mAP50 0.31)과 val 구성이 달라 비교는 무의미하다.
- [실행 확인] 오검출률 참고 수치 (이번 측정, v2_small best.pt, "검출 1개 이상인 ROI 비율", 공개 데이터 기준):
  | 대상 | n | conf 0.25 | conf 0.5 |
  | --- | --- | --- | --- |
  | val coco_none | 194 | 0 | 0 |
  | val coco_similar | 43 | 0 | 0 |
  | val public_neg | 83 | 0 | 0 |
  | train coco_none / similar (학습에 쓴 것, 낙관적) | 2087 / 388 | 2 / 0 | 0 / 0 |
  | val public_pos (재현율 대용) | 186 | 32 (17.2%) | 9 (4.8%) |
  오검출이 0에 가까운 것은 모델이 거의 아무것도 검출하지 못해서이기도 하다(재현율 17%). **구분 능력의 증거가 아니다.**

## 본 학습 예상 시간 (시작하지 않음, roi_ds_v2 기준으로 갱신)

실측 (이 PC, CPU 32스레드, imgsz 192, batch 32, workers 2):
| 측정 | 데이터 | 시간 |
| --- | --- | --- |
| v1 보정 2 에폭 | `roi_ds` train 2463 + val 269 | 62.9 s, 에폭당 약 29 s |
| v2_small 3 에폭 | `roi_ds_v2` train 5266 + val 506 | 총 195 s, 에폭당 약 60~70 s (약 11~12 ms/장) |
- 외삽 (선형 가정):
  - 공개+합성만(5772장), 80 에폭: 약 **80~95분** (patience 20 조기 종료 시 더 짧음. v2_small은 patience 5였음).
  - 공개+합성+본인 1세션(자체 ROI 약 1000 추가 가정, 약 6800장), 80 에폭: 에폭당 약 75~80 s, 약 **100~110분**.
  - 코어가 적은 PC면 2~4배.
- 권장 순서: (1) 공개+합성만 약 1.5시간 학습 -> `models/cig_roi.onnx` -> 본인 세션 사전 라벨링, (2) 검수한 본인 데이터를 합쳐 재학습. 20 에폭 후 val mAP50이 0.3 미만이면 80 에폭을 다 돌리지 말고 데이터를 먼저 본다. 합성 비율(train 양성의 20%)이 과하면 도메인이 어긋나므로 자체 데이터가 들어오면 줄이는 것을 검토.

---

## 진행 체크리스트 (실제 상태)
- [x] 1. 환경 기록 + requirements.txt
- [x] 2. 데이터 출처 기록 (`data/SOURCES.md`)
- [x] 3. core (detector/roi/state/tracker/stabilizer/distance/pipeline/viz/serialize + 테스트): pytest 31 passed. `priority.py`는 범위 밖
- [x] 4. capture.py: 컴파일/--help/동의·ID 거부 확인. **실제 촬영 저장은 미검증** (동의 확인은 사람이 해야 하므로 실행하지 않음. 카메라 열기 코드는 run_webcam과 같은 방식으로 확인됨)
- [x] 5. prelabel.py: 실행 확인 (임시 데이터)
- [x] 6. training/: 스모크 학습 + 2 에폭 보정 학습 실행 확인, ONNX 변환 결과 존재. make_splits / build_roi_dataset(own)은 미검증
- [x] 7. eval_images.py + acceptance 잠금 (`acceptance.sha256` 생성, 읽기 전용). hold-out 매니페스트는 자체 데이터 분할 후 `lock_acceptance.py --create`
- [x] 8. run_webcam.py: 웹캠 실제 기동 확인 (q 키, 오버레이 모양은 미검증)
- [x] 8b. 공개+합성 보충: COCO 부분집합 1164장, 합성 300장, `roi_ds_v2` 생성, `data/SOURCES.md` 기록, 3 에폭 학습 기록 확인, 오검출 참고 수치 측정 (위 절). **코드만 있고 실행하지 않은 것**: `build_roi_dataset_v2.py --include-own`(자체 데이터 합치기)
- [ ] 9. 자체 촬영(본인 1세션 + 평가 2~3명), 라벨 검수, 본 학습, hold-out 평가 -- 사용자 작업. 합격 게이트(단계 A 합격 선언)는 아직 열리지 않음
- 보류/받지 못한 것: Roboflow 계열(계정·키 필요), COCO train2017(용량 18GB), similar 500장 목표(164장만 조건 충족), 본 학습(지시상 시작 안 함), none ROI 전수 사람 검수(미실시), COCO annotations CC BY 4.0 확인(약관 페이지 추출 실패, 추정).

## 알려진 한계 / 막힌 점
- 자체 촬영 데이터 0장. CigDet은 250 px 근접 사진이고 음성이 없다. v2에서 COCO 음성이 추가돼 오검출을 참고 수치로는 잴 수 있지만 도메인이 달라 합격 판단에는 쓸 수 없다.
- v1 `data/roi_ds`의 음성에는 유사물이 없었다. v2는 COCO 유사물(휴대폰/칼/숟가락/포크/칫솔/방망이) 431 ROI를 넣었지만 펜·빨대·막대사탕·전자담배는 없다. 이 구분은 자체 촬영 시나리오 4~7이 만든다.
- 클립(mp4) 녹화 도구 없음. 클립 단위 합격선(확정 시간, 오확정/10분)은 클립이 있어야 측정된다.
- 라벨링 도구는 설치하지 못했다 (미검증).
- 단계 B용 `ash_e_core` 해시 기록은 합격 선언 시점에 한다 (설계서 10.1).

## 녹화 기능 (`run_webcam.py --record` / `--replay`)
평가 클립(설계서 표 B, 9.2)을 만들고, 안정화 지표(time-to-confirm, 10분당 오확정)를 클립 단위로 잴 수 있게 하는 기능. 새 파일 `prototype/clip_io.py`(녹화·재생·events 기록, GUI 없음), 테스트 `prototype/test_clip_io.py`. `run_webcam.py`는 옵션과 루프의 녹화 분기만 추가했고 기존 동작(옵션 없을 때)은 그대로다. **core는 수정하지 않았다.**

### 사용법
```
python prototype/run_webcam.py --record --participant P01 --session S1 --scenario mouth --consent-confirmed
python prototype/run_webcam.py --replay data/raw_clips/P01/S1/mouth_001/clip.mp4        # 카메라 없이 events 재생성
python prototype/run_webcam.py --record --record-auto 30 --no-gui --participant P01 --scenario mouth --consent-confirmed  # 헤드리스 30 s 1클립
```
- 키: `r` 클립 시작/정지(여러 번 가능, 클립마다 `<scenario>_001, _002 ...`), `q` 종료(열려 있는 클립은 정상 마감). 녹화 중 화면에 빨간 `REC`와 경과 시간이 보이지만 **저장 영상에는 오버레이가 없다**(저장은 오버레이 그리기 전 원본 프레임).
- 거부 규칙은 `capture.py`와 같다: `--consent-confirmed` 없으면 종료, 참가자 ID는 `P01`~`P999`만(이름 거부). 추가로 세션 `S1`~`S99`, 시나리오 `[a-z0-9_]`만 허용(경로 오염 방지). `--record`는 `--video/--replay`와 같이 못 쓴다. `--no-gui`에서는 키가 없으므로 `--record-auto N` 필수.
- 옵션: `--record-fps`(기본 15, 설계서 >= 15), `--record-out`(기본 `data/raw_clips`), `--rate`(처리율, 기본 8 Hz), 재생 `--replay-out`, `--no-throttle`(모든 프레임 처리, 설계서 이식 절차 892행과 같은 방식).
- 시나리오 이름 권장: 표 B 키 대응 `holding`(S2) `mouth`(S1) `none` `similar`(S3) `gesture`(S4) `ecig_liquid`(S11) `ecig_heated`(S12), 키 없는 것은 `s5_mixed` `s8_walk` `s9_angle` `s10_leave` 등.

### 출력 구조
```
data/raw_clips/<PID>/<SESSION>/<scenario>_<NNN>/
    clip.mp4      원본 프레임, 오버레이 없음, mp4v, 일정 프레임률(--record-fps)
    events.jsonl  header 1줄 + frame 줄(영상 프레임마다 1줄) + event 줄 + footer 1줄
    labels.json   설계서 9.2 형식의 빈 템플릿(사람이 채움. 이미 있으면 덮어쓰지 않음)
    (재생 시) events.replay.jsonl   live events.jsonl을 덮어쓰지 않고 옆에 생성
```
- **시간축**: 영상 프레임 k의 시각 t = k / fps. 처리 루프가 느려 한 프레임을 놓칠 상황이면 직전 카메라 프레임을 되풀이해 쓰고(`dup: true`) 영상 시계를 실제 시계와 맞춘다. 그래서 플레이어에서 읽은 라벨 시각과 events의 t가 같다. 파이프라인에는 stamp = k/fps를 넣고 처리율 제한도 같은 시계로 하므로 live와 replay가 같은 프레임에서 같은 결정을 한다.
- **header**: schema, fps, 해상도, participant/session/scenario, process_rate_hz, throttle, 모델 경로+sha256(앞 16자), models_ready, 전체 config(stab_window_s, confirm_ratio 등 튜닝 값 포함), source(record|replay).
- **frame 줄**: `frame_idx, t, processed, dup, frame_seq, inference_ms, detections[]`. detections는 `serialize.to_dict(Detection)` 그대로(track_id, state, state_confidence, raw_state, raw_confidence, cigarette_checked, person_confidence, bbox_*, cig 박스, position, distance_m, distance_source(1=PROXY), bearing_rad, stationary_s, frames_observed)에 `confirmed`(= state != none)를 더한 것. `processed=false` 프레임은 직전 처리 결과를 그대로 싣는다(`inference_ms: null`).
- **event 줄**(처리된 프레임에서만, 트랙별): `track_new`, `confirm`(none -> holding/smoking), `state_change`(holding <-> smoking), `release`(-> none), `track_lost`. 필드: frame_idx, t, track_id, from_state, to_state, state_confidence, distance_m.
- **footer**: n_frames, n_processed, n_dup, duration_s, mean_inference_ms, n_events.

### 설계서 지표와 events 필드 대조
| 지표 | 필요한 것 | events에 있는 필드 |
| --- | --- | --- |
| time-to-confirm (9.3-3, 중앙값/95% 분위) | 양성 구간 시작(labels.json segments.t0), 그 사람의 트랙, 첫 confirm 시각 | `confirm` 이벤트 t, track_id. 사람-트랙 매칭은 labels의 `anchor`(t, bbox)와 frame 줄의 bbox_*(IoU)로 평가 스크립트가 한다 |
| 확정된 시간 비율 | 프레임별 state | frame 줄 `confirmed`, `state` |
| 10분당 오확정 (none/유사물/동작 클립) | confirm 횟수, 노출 시간 | `confirm` 이벤트 수 / footer `duration_s`. 클립 시나리오는 header.scenario + labels category |
| 거리 구간별 recall | 프록시 거리 | `distance_m`, `distance_source` |
| raw 프레임 지표(9.3-1, 2) | raw_state, 신뢰도 | `raw_state`, `raw_confidence`, `cigarette_checked` |
| 오확정·누락 사례 목록(9.3-8) | 클립 ID, 시각, 시나리오, 거리/조명 태그 | 클립 경로(PID/SESSION/scenario_NNN), t, header.scenario, labels.json의 `distance_tag`/`lighting`(사람이 채움) |
| 속도 | 추론 시간 | `inference_ms`, footer `mean_inference_ms` |
| 재현성 | 모델·설정 | header models(sha), config |
설계서에 없어서 **추가한 것**: `dup`, `processed`, footer(노출 시간 계산용), header의 모델 해시와 config 스냅샷, `track_new/track_lost/state_change` 이벤트, labels.json의 `split/lighting/distance_tag/angle_tag/notes`. 우선순위(9.3-6 타깃 ID 타임라인)는 이 단계 범위가 아니라 넣지 않았다(priority 모듈이 생기면 같은 frame 줄에 target을 붙이면 된다. `serialize.frame_to_jsonl`이 이미 target 필드를 가진다).

### 데이터 보호 점검 (코드와 grep 확인, 보호 코드는 수정하지 않음)
- 클립은 `data/raw_clips/`에 두며 `data/raw/`(프레임), `data/labeled/`, `data/eval/`와 별개다. `make_splits.py`는 `data/labeled`만 읽고, `make_eval_labels.py`/`prelabel.py`는 `data/raw`로 제한되며, `build_roi_dataset.py`는 `--source public|own`으로 고정 경로만 쓴다. `data/raw_clips`를 참조하는 학습·분할 코드는 없다 -> 자동으로 학습/평가에 섞일 경로는 없다. `.gitignore`의 `data/`로 git 미추적.
- **충돌 가능성(보고만)**: (1) 설계서 9.2는 평가 클립을 `data/eval/{dev|holdout}/clips/`에 두라고 한다. 지금 클립은 `data/raw_clips/`에 있으므로, 사람이 그룹(dev/holdout)을 정한 뒤 옮겨야 하고, holdout 참가자 클립의 해시 매니페스트 등록과 읽기 전용 잠금(9A.5)은 아직 이 도구가 하지 않는다. (2) `data/raw_clips`의 holdout 참가자 클립에 `--replay`를 돌리는 것은 아직 holdout 실행 횟수 로그(`holdout_runs.log`)를 거치지 않는다. 튜닝 중에는 dev 참가자 클립에만 replay를 쓰고, holdout 판정은 이후 `eval_clips.py --final`로만 해야 한다(이 스크립트는 아직 없음). (3) 참가자 ID는 경로에 들어가므로 참가자 단위 분할이 가능하다. 여러 명이 나오는 S5/S10 클립은 `labels.json`의 `participants`에 모두 적어야 한다(템플릿은 녹화 참가자 1명만 미리 넣음).
- `build_roi_dataset.py --clean`은 쓰지 않았고 `data/roi_ds`는 건드리지 않았다.

### 시험 결과
- **pytest [실행 확인]**: 기존 `cd src\ash_e_core; ..\..\.venv\Scripts\python -m pytest test -q` -> 31 passed. 신규 `.venv\Scripts\python -m pytest prototype\test_clip_io.py -q` -> 7 passed. 신규 테스트: 동의/ID/세션/시나리오 거부, 합성 프레임+가짜 모델로 녹화 레이아웃·events 스키마·필수 필드·오버레이 없는 영상·dup, 클립 번호 증가·labels 비덮어쓰기, 빈 클립 삭제, `--replay`가 live events와 같은 결과(inference_ms/dup 제외 전부 일치), 임의 mp4 재생과 `--no-throttle`, none 클립에 confirm 이벤트 없음.
- **거부 경로 [실행 확인]**: 이름(`Alice`) 거부, `--consent-confirmed` 없음 거부, `--no-gui`에서 `--record-auto` 없음 거부 메시지.
- **실제 웹캠 [실행 확인, 1회]**: `--record --record-auto 4 --no-gui --participant P99 --scenario trial --consent-confirmed`. 1280x720 수신, 60프레임(4.0 s, 15 fps) 기록, dup 0, 30프레임 처리, 클립 폴더에 3파일 생성. 이어서 같은 클립에 `--replay`(와 스모크 담배 모델 `--cig-model`) 실행 성공. 이 PC에서 `models/cig_roi.onnx`가 없어 담배 모델은 stub 상태로 녹화했다(state는 none 고정). **시험 파일은 얼굴이 담겨 있어 전부 삭제했고 `data/raw_clips`는 남아 있지 않다.**
- **live vs replay (실제 웹캠 클립)**: 처리된 프레임 수·시점·트랙 수는 동일하고 state 전부 동일했다. 단 mp4 손실 압축 때문에 사람 박스가 1~2 px, distance_m이 약 0.01 m, person_confidence가 약 0.003 달라졌다(합성 프레임 테스트에서는 완전 일치). 임계값 근처의 경계 검출은 live와 replay가 갈릴 수 있다. 평가는 항상 replay(또는 clip.mp4에서 낸 events)로 하면 일관된다.
- **[미검증]**: `r` 키로 시작/정지하는 GUI 경로와 화면 REC 표시(헤드리스 `--record-auto`로만 실행함), 느린 PC에서 dup가 실제로 생기는 경우(합성 정체로만 확인), 담배 모델이 있는 상태의 실제 confirm 이벤트(합성 모델로만 확인), 30 s 이상 긴 녹화의 디스크/성능, labels.json을 평가 스크립트가 읽는 부분(평가 스크립트가 아직 없음).
- 알려진 한계: 코덱은 mp4v(Windows 플레이어/OpenCV는 재생, 웹 브라우저는 못 열 수 있음). replay는 `dup`를 알 수 없어 항상 false로 쓴다. 클립마다 파이프라인(트래커·안정화)을 새로 리셋하므로 클립 사이에 트랙 ID는 이어지지 않는다.


## 클립 평가 (`prototype/eval_clips.py`)
녹화 클립(`clip.mp4` + 사람이 채운 `labels.json`)으로 안정화 상태 지표를 재고 9.4.1 형식으로 보고한다. 파일: `prototype/eval_clips.py`, 테스트 `prototype/test_eval_clips.py`(24개). **core는 수정하지 않았다.** `training/dataset_utils.py`의 `refuse_holdout()`/`is_under()`는 보강했다(아래 보호 규칙).

### 사용법
```
python prototype/eval_clips.py                              # dev: data/eval/dev 아래 모든 클립 (판정 아님, DEV 표시)
python prototype/eval_clips.py --clips-dir data/raw_clips   # 보호 대상이 아닌 폴더. 참가자 그룹이 확인돼야 함
python prototype/eval_clips.py --final                      # hold-out 판정. data/eval/holdout 만 읽음
```
- 클립 찾기: `<폴더>/clip.mp4` + 같은 폴더 `labels.json`(녹화 레이아웃) 또는 `<x>/clips/<id>.mp4` + `<x>/labels/<id>.json`(설계서 9.2). 평가는 **항상 clip.mp4를 replay**(`clip_io.replay_clip`)한 events로 하며 live `events.jsonl`은 읽지 않는다. replay 결과는 `_workspace/eval_out/clips_<tag>/replay/`에 저장하고 클립 폴더에는 쓰지 않는다(hold-out 폴더는 잠겨 있음).
- 옵션: `--config`, `--pose`, `--cig-model`, `--rate`(replay 처리율, 기본 cfg), `--no-throttle`, `--tag`, `--allow-train`, `--allow-unknown-split`.
- 출력: dev는 `_workspace/eval_out/clips_dev/{report.md,metrics.json}`(덮어씀), `--final`은 `clips_holdout/run_NNN/`(실행마다 새 폴더, 이전 결과를 지우지 않음). 같은 폴더의 `replay/*.events.jsonl`은 박스/상태 기록뿐이고 영상·이미지는 저장하지 않는다.
- 담배 모델이 없으면(stub) dev는 경고 후 진행(결과 무의미), `--final`은 holdout 실행 횟수를 소모하지 않도록 거부한다.

### labels.json 채우는 법 (설계서 9.2, `run_webcam.py --record`가 만든 템플릿을 채운다)
1. 플레이어로 `clip.mp4`를 보며 시각(초, 영상 시작 0)을 읽는다. events의 t와 같은 시계다.
2. 사람마다 `persons[]` 항목: `person_ref`("p1"...), `anchor`(`t`, `bbox_xyxy` 픽셀: 그 사람이 또렷이 보이는 한 시점과 박스), `segments[]`(`t0`,`t1`,`label` smoking|holding|none, `category` cigarette|similar_object|gesture|ecig_liquid|ecig_heated|plain). category를 생략하면 양성은 cigarette, none은 plain. 담배가 손에 가려 안 보이면 `label: none` + `"occluded": true`(별도 집계, 오확정 판정에서 제외).
3. 구간은 이어 붙여도 되고 비워도 된다. 라벨이 없는 시간은 평가에서 제외된다. 사람이 화면에 있는데 라벨하지 않으면 그 사람의 확정은 "라벨 없는 확정 트랙"으로 클립별 표에 경고만 뜬다(정밀도에는 안 들어감). **화면의 모든 사람을 라벨하라.**
4. 여러 명(S5/S10)이면 `participants`에 모두 적고 `persons[].participant`를 각 사람에 적는다(없으면 그 클립은 건너뜀, `--final`에서는 거부). 참가자별 표가 이 값을 쓴다.
5. `distance_tag`, `lighting`, `angle_tag`는 오확정·누락 목록에 그대로 실린다. 템플릿 그대로(anchor/segments 비어 있음)인 클립은 "건너뜀"으로 보고하고, `--final`에서는 하나라도 있으면 거부한다(고르기 방지).

### 지표 정의
| 지표 | 정의 | 합격선 키 |
| --- | --- | --- |
| time-to-confirm | 양성 구간 t0 이후 첫 state != none 시각 - t0. 앞 구간이 이어진 양성이고 이미 확정 중이면 제외(이어짐) | confirm_time_median_s (중앙값) |
| precision (<=4 m) | 예측 양성 프레임(state != none, 프록시 거리 <= 4) 중 라벨 양성 비율. 라벨 없는 트랙·occluded none 제외 | binary_precision_max4m |
| recall (<=3 m, 3-5 m) | 양성 구간 프레임 중 state != none 비율. 거리는 매칭된 트랙의 distance_m(미검출 프레임은 마지막 거리) | binary_recall_max3m, binary_recall_3to5m |
| smoking/holding 정확도 | 확정된 양성 프레임 중 state == 라벨 | smoking_holding_accuracy |
| 오확정 / 10분 | none 구간(category similar_object, gesture, ecig_liquid)에서 none -> 양성 상승 횟수 / 노출(라벨된 사람-구간 길이 합) x 10분. 직전 양성 구간에서 이어진 state가 풀리는 동안은 센 안 함. 0건이면 rule of three 상한(30 / 노출분) 병기 | lookalike_false_confirm_per_10min |
| S5 떨림 | S5 클립(시나리오 s5*)의 타깃 전환 중 앞 전환 후 10 s 이내 전환 횟수. events에 `target_id`(또는 `target.track_id`)가 있고 참가자 2명 이상일 때만 | priority_flicker_s5 |
- plain none, ecig_heated(S12), occluded none의 오확정은 **별도 집계만** 하고 판정에 넣지 않는다. 합격선 수치는 `acceptance/acceptance.yaml`에서만 읽는다(코드에 숫자 없음). 방향(>=, <=)만 코드에 있다.
- 신뢰구간: 비율은 프레임 Wilson(낙관적) + 클립 단위 부트스트랩(2,000회, 시드 고정, 클립 2개 미만이면 n/a), 중앙값·비율도 부트스트랩. 참가자별 값 표, 오확정·누락 사례 전수 표(클립 ID, t, 시나리오, 거리/조명 태그), 양성 구간별 확정 시간 표 포함.
- 판정 문구(9.4.1): `--final`에서 모든 지표 통과 시 "예비 합격 (holdout n=N명, 클립 k개, 양성 노출 t분)", 하나라도 미달이면 "불합격", 합격선 지표 중 데이터가 없으면 "판정 불가". 불확실 표시: CI가 합격선을 가로지름 / 참가자 1명이 미달 / 오확정 노출 10분 미만. dev 결과가 `clips_dev/metrics.json`에 있으면 dev-holdout 차이 0.10 초과 지표를 적는다. dev 실행은 "DEV 참고 (판정 아님)"만 쓴다. RPi5 처리율은 이 스크립트 범위 밖.
- **S5 떨림은 현재 측정 불가**: priority 모듈이 없어 events에 타깃 필드가 없다. 그래서 "미측정"으로 출력되고 판정을 막지 않는다(acceptance.yaml도 범위 밖 표기). priority가 생기면 frame 줄에 `target_id`만 붙이면 같은 코드가 계산한다.

### 보호 규칙 (eval_images.py와 같은 방식, 완화하지 않음)
- 모든 모드: `acceptance.yaml`이 `acceptance.sha256`과 다르면 거부. sha 파일이 없으면 dev는 경고, `--final`은 거부(eval_images보다 엄격).
- hold-out 클립(`data/eval/holdout` 안, 또는 참가자가 hold-out인 클립, 또는 labels `split: holdout`)은 `--final` 없이 거부. `data/eval`처럼 hold-out을 품은 상위 폴더도 거부.
- `--final`: `acceptance/holdout_manifest.sha256` 검증 -> 라벨 사용 가능 여부(하나라도 불가면 거부) -> 클립 폴더 매니페스트. 매니페스트 `acceptance/holdout_clips_manifest.json`은 **첫 `--final` 실행에서 `data/eval/holdout/` 전 파일의 SHA-256으로 기록**(읽기 전용 속성), 이후 실행은 파일이 바뀌거나 추가·삭제되면 거부. 성공한 `--final`마다 `acceptance/holdout_runs.log`에 한 줄 추가하고 보고서에 실행 횟수를 적는다. (acceptance/에 쓰는 것은 이 두 파일뿐.)
- 참가자 교차 오염: 그룹은 `data/splits/participants.json`(holdout / val=dev / train)과 폴더(`data/eval/holdout`, `data/eval/dev` 아래 PID)에서 알아낸다. 한 클립의 참가자가 서로 다른 그룹이면 거부, json과 폴더가 다르게 말하면(conflict) 거부, dev 평가에서 train 참가자는 `--allow-train` 없으면 거부, 그룹을 모르는 참가자(`data/raw_clips`의 아직 분할 안 된 PID)는 `--allow-unknown-split` 없으면 거부(hold-out 참가자는 그 플래그로도 불가). `--final`은 모두 hold-out 참가자인 클립만 허용.
- **학습 코드 보강** (`training/dataset_utils.py`): `refuse_holdout()`이 이전에는 `data/eval/holdout`, `acceptance`만 막았다. 이제 `data/raw_clips` 전체(학습 코드가 읽을 일이 없음), 보호 폴더를 품은 상위 경로(`data`, `data/eval`), `data/` 아래에서 hold-out 참가자 PID(`data/splits/participants.json`)가 경로 요소인 모든 경로를 막는다. `is_under()`는 realpath+대소문자 정규화로 `..`, 대소문자, 정션 우회를 막는다(eval_images.py도 이 함수를 쓴다). `build_roi_dataset*.py`, `train_cig_roi.py`, `eval_images.py`는 컴파일 확인, `data/roi_ds`와 `data/labeled`는 여전히 허용됨을 확인했다.
- 알려진 빈틈: `data/splits/participants.json`이 없고 hold-out 폴더도 비어 있으면 hold-out 참가자를 알 수 없다. 이때 `data/raw_clips` 평가는 `--allow-unknown-split` 없이는 거부되지만, 그 플래그를 쓰면 hold-out 참가자의 클립을 가려내지 못한다. 분할을 먼저 확정하고 hold-out 클립을 `data/eval/holdout/<PID>/...`로 옮긴 뒤 `lock_acceptance.py --create`를 실행해야 한다.

### 시험 결과
- pytest [실행 확인]: core 31 passed, `prototype/test_clip_io.py` 7 passed, 신규 `prototype/test_eval_clips.py` 24 passed. 합성 events/labels로 지표(ttc, recall/precision 거리 구간, smoking/holding, 오확정 10분당, rule of three, lingering 제외, occluded/ecig_heated 제외, Wilson 값, 부트스트랩 결정성, 떨림 계산), --final 게이트(없이 거부, 상위 폴더 거부, raw_clips의 hold-out 참가자 거부, acceptance 해시 불일치/sha 없음, 전역 매니페스트 없음/불일치, 클립 매니페스트 생성·검증·변경·추가·삭제 거부, 실행 로그와 run_NNN 보존, 라벨 미작성 클립 거부, 그룹 혼합/충돌 거부), `refuse_holdout` 보강, 녹화 클립을 실제 replay 경로로 평가하는 end-to-end를 임시 폴더에서 검증했다.
- 실제 저장소에서 `eval_clips.py`(dev)는 "평가 데이터 없음", `--final`은 "hold-out manifest missing"으로 거부되고 `acceptance/`·`data/`에는 아무것도 생기지 않았다.
- [미검증] 실제 담배 모델·실제 사람 클립으로 돌린 적 없음(데이터와 `models/cig_roi.onnx` 없음). 긴 클립 replay 시간, 다인 클립의 트랙 ID 교체 시 매칭 품질, 실제 hold-out 파일 수에서의 해시 시간은 확인하지 못했다. 매니페스트 파일의 읽기 전용 속성(chmod)은 코드로 설정하지만 걸렸는지는 따로 확인하지 않았다(실제 `acceptance/`의 매니페스트는 첫 `--final` 때 처음 생성됨).


## 논문용 지표·그래프 (`prototype/paper_report.py`, `prototype/bench_latency.py`)
기존 평가 출력(`eval_clips.py` metrics.json, ultralytics `results.csv`, `build_report.json`)을 읽어 그림·표를 만든다. 평가 로직은 다시 짜지 않았고 `eval_clips`의 통계·라벨 규칙을 import해 쓴다. **core는 수정하지 않았다.** `eval_images.py`에는 기존 출력은 그대로 두고 `_workspace/eval_out/metrics_<tag>.json`(혼동행렬·이진 카운트·거리 구간) 기록만 추가했다(혼동행렬 그림의 입력).

### 사용법
```
python prototype/eval_clips.py                       # dev metrics.json
python prototype/eval_images.py --cig-model models/cig_roi.onnx   # metrics_dev.json
python prototype/paper_report.py --collect-dev-scores  # dev replay events+labels -> dev_scores.json (모델 실행 없음)
python prototype/paper_report.py --run-ablation        # dev 클립을 안정화 켬/끔으로 replay (eval_clips.main, --final 없음)
python prototype/bench_latency.py                      # 지연시간/FPS/모델 크기 -> _workspace/paper/latency.json
python prototype/paper_report.py [--lang ko]           # -> _workspace/paper/
python prototype/paper_report.py --demo                # 합성 입력 -> _workspace/paper_demo/ (워터마크)
```
옵션: `--gallery-dir D --gallery-source public|synthetic|own`, `--allow-own-faces`, `--no-blur`. ko는 Malgun Gothic이 없으면 경고 후 en.

### 출력 구조
`_workspace/paper/{figures/*.png(300dpi)+pdf, tables/*.csv+tex(booktabs), reproducibility.json, README.md}`. 그림: 학습 곡선, PR+AP, 임계값 스윕, 혼동행렬, 거리 구간별 recall, time-to-confirm, 10분당 오확정, 참가자별, 안정화 ablation, 데이터셋, 지연시간/FPS/모델 크기, (옵션) 사례 갤러리. dev/hold-out은 파일명 접미사로 구분(`_dev`, `_holdout`). 표: 지표 요약, 데이터셋, 하이퍼파라미터, 지연시간, ablation. README에 그림→입력 파일 매핑과 영문 캡션 초안.

### 보호 규칙
- hold-out 그림은 `eval_*.py --final`이 이미 쓴 metrics.json(`final: true`)만 읽는다. 파일이 없으면 "SKIPPED" 경고 후 건너뜀. 이 도구는 hold-out에 모델을 돌리지 않고 `--final`을 실행하지 않는다.
- 스윕/PR은 `assert_dev_scores()`가 dev/val 점수만 허용하고 hold-out 경로·split·final은 `HoldoutRefusedError`. 임계값을 hold-out으로 정하는 기능 없음. `acceptance/`는 읽기만(해시·임계값).
- 합성 데이터는 `_workspace/paper_demo/`에만 쓰고(`--demo` 외 경로 거부), 모든 그림에 "SYNTHETIC DEMO - NOT RESULTS", 표에 같은 표기. 실제 모드는 `synthetic_demo` 입력을 거부.
- 사례 갤러리는 기본 비활성. 참가자 크롭은 `--allow-own-faces` + pose 키포인트 얼굴 블러(모델 없으면 거부). 논문 게재에는 참가자 동의서에 게재 동의가 포함돼야 한다(README에 경고).

### 한계
- 참가자별 신뢰구간은 metrics.json에 없어 점과 전체 CI만 그린다. 범주별 오확정 노출은 구간 길이로 근사.
- PR/스윕은 dev 프레임 단위이며 설정된 담배 임계값 아래는 기록이 없어 평탄. 안정화 "끔"은 config로 만든 통과 설정(1프레임 해제 지연, smoking 래치 없음).
- 지연시간은 Windows 값(RPi5 아님). 실제 데이터(담배 모델, 평가 클립)가 없어 실제 `_workspace/paper/`는 아직 생성하지 않았다. [실행 확인]은 합성 데모와 pytest뿐.
- 시험: `prototype/test_paper_report.py` 12개. 전체 prototype 43 passed(기존 31 + 12), core 31 passed.

---

## 2026-11-10 1차 본 학습 (공개+합성만) 및 P01 사전 라벨 [실행 확인]

- 학습: `train_cig_roi.py --data data/roi_ds_v2/data.yaml --epochs 80 --name cig_roi_v2`. 84분(5068 s), 80 에폭 완주.
  - best = 49 에폭: val mAP50 0.750, P 0.764, R 0.696. val은 CigDet test + COCO라서 로봇 시점이 아님.
  - 결과물: `models/cig_roi.onnx` (2026-11-10 23:37).
- 그 전에 제3자 처리를 했다: `own_subject` 필터를 넣었고, 원본 프레임에서 제3자를 가리거나 프레임을 삭제했다. 상세는 `_workspace/capture_qc_report.md`.
- 사전 라벨: `prelabel.py --src data/raw/P01`.
  - 결과: `data/labeled/P01/`, `data/labeled/review_queue_P01.csv` (박스 없음 248 → 확인 485), `prelabel_report_P01.json`.
- **참고 수치.** 1차 모델, P01 프레임, 운영 임계값 0.35, 프레임 단위로 담배 박스가 1개 이상 나온 비율이다. 합격 판정 지표가 아니고 안정화 전 값이다. holding·mouth는 담배가 안 보이는 프레임도 포함한다.

| 시나리오 | 전체 | 1 m | 2 m | 3 m | 4 m | 5 m |
| --- | --- | --- | --- | --- | --- | --- |
| holding (검출률) | 0.49 | 태그 없음 62/75 | 35/47 | 43/55 | 16/62 | 9/98 |
| mouth (검출률) | 0.72 | 95/95 | 146/163 | 38/40 | 6/18 | 2/80 |
| none (오검출) | 0.07 | 1/36 | 2/26 | 5/45 | 0/41 | 4/36 |
| similar (오검출) | 0.22 | 16/28 | 40/95 | 10/75 | 6/85 | 6/74 |
| gesture (오검출) | 0.28 | 31/42 | 42/71 | 22/82 | 1/88 | 0/64 |

- 해석:
  - 공개 데이터는 근접 사진 위주라서 1~3 m는 잡히지만, 4~5 m는 거의 못 잡는다(R6).
  - 1~2 m의 유사물·동작 오검출이 50~70%로 높다. 공개 음성 데이터에 펜·빨대·손-입 동작이 없기 때문이다.
  - 둘 다 P01 자체 데이터(특히 원거리 양성, 유사물·동작 음성)가 들어가야 고칠 수 있는 부분이다.
- 다음: 사용자가 P01 holding·mouth 박스를 검수한다 → `make_splits.py` → `build_roi_dataset_v2.py --include-own`으로 `roi_ds_v3` → 2차 학습.

## 2026-11-11 실험용 2차 학습 (검수 없는 의사 라벨, 사용자 결정) [실행 확인]

- 데이터: `training/build_roi_own_pseudo.py` → `data/roi_own_p01_pseudo`. 병합 설정은 `data/roi_ds_v3exp.yaml`.
  - 구성: roi_ds_v2 + P01 ROI (train 양성 1461 / 음성 6328, val 88 / 398).
  - 양성 = 1차 모델 신뢰도 0.5 이상 박스가 든 ROI만. 박스 없는 holding·mouth ROI와 프레임은 버렸다.
- 학습: 1차 best.pt에서 이어서 30 에폭(74분). 결과물은 `models/cig_roi_v3exp.onnx`. 기본 모델 `cig_roi.onnx`는 바꾸지 않았다.
- **dev(P02) 비교.** 프레임 단위, 장면 라벨 기준이다. 오검출 = none·similar·gesture 장면에서 박스가 나온 프레임 비율.

| 임계값 | 1차: 검출률 / 오검출 | 실험: 검출률 / 오검출 |
| --- | --- | --- |
| 0.25 | 0.58 / 0.47 | 0.52 / 0.35 |
| 0.35 | 0.53 / 0.38 | 0.49 / 0.29 |
| 0.45 | 0.45 / 0.30 | 0.44 / 0.24 |
| 0.55 | 0.39 / 0.20 | 0.38 / 0.17 |
| 0.65 | 0.22 / 0.08 | 0.26 / 0.10 |

  같은 검출률에서 오검출이 4~6%p 낮다. 개선은 작다. 4~5 m 검출은 두 모델 모두 거의 0이다(의사 라벨은 1차 모델이 이미 잡는 것만 양성으로 넣기 때문이다).

- **발견 1: P02 음성 장면에 진짜 담배가 있다.** gesture 2 m(32/33 검출), none 1 m 등에서 검출된 ROI를 눈으로 확인했다. 입에 대거나 손에 든 담배가 분명히 보이는 프레임이 여럿이었다. 참가자가 음성 장면에서도 담배를 들고 있었던 것으로 보인다.
  - 따라서 위 표의 "오검출"은 실제보다 부풀려져 있다.
  - P02 평가에는 **프레임별 라벨 검수**가 필요하다: `make_eval_labels.py --participants P02 --split dev --review`.
  - hold-out(P03)에도 같은 문제가 있을 수 있다. P03는 보지 않았다(보호 규칙). P03 라벨 검수는 사용자가 해야 한다.
- **발견 2: P01 음성 장면의 오검출은 대부분 진짜 오검출이다.** 1차 모델, 신뢰도 0.5 이상을 확인했다.
  - 주원인은 **휴대폰 모서리**(P01이 거의 모든 장면에서 휴대폰을 듦)와 펜·막대류다.
  - 즉 학습 음성 데이터는 대체로 맞다. 휴대폰이 가장 큰 혼동 요인이다.
- 결정 보류: 기본 모델을 바꿀지는 검수한 dev 라벨이 생긴 뒤에 정한다. 실험 모델을 웹캠에서 보려면 `run_webcam.py --cig-model models\cig_roi_v3exp.onnx`.
