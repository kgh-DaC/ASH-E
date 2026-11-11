# 02a 우선순위 구현 노트 (단계 A)

최종 갱신 2026-11-11. 표기: **[실행 확인]** = 실제로 실행해 결과를 봤다. **[미검증]** = 코드만 있다.

## 구현한 것
- `src/ash_e_core/ash_e_core/priority.py`: `PrioritySelector`. 설계서 7장 그대로 구현했다.
  - 후보 자격(7.1), 점수식(7.2), 상태 머신(7.3), 전환 히스테리시스(7.4), ID·공간 쿨다운(7.5).
  - API는 7.6과 같다: `update`, `tick`, `on_feedback`, `set_lock`. ROS에 의존하지 않고, 시각은 호출자가 넘긴다(결정론).
  - 정렬 순서: 점수 내림차순 → 거리 오름차순(거리 없으면 맨 뒤) → `track_id` 오름차순.
- `src/ash_e_core/ash_e_core/viz.py`: `draw_priority` 추가.
  - 타깃은 흰 굵은 테두리와 `TARGET #id 점수`로 표시한다.
  - 오른쪽 위에 순위 상위 5명(자격이 없으면 사유)과 마지막 이벤트를 표시한다.
- `prototype/run_webcam.py`: 기본으로 우선순위 오버레이를 켠다.
  - `--priority-config`로 yaml을 지정하고, `--no-priority`로 끈다.
  - 녹화 클립을 시작하거나 멈추면 선택기를 새로 만든다. 클립 시계가 0부터 다시 시작해 시간이 거꾸로 가는 것을 막기 위해서다.

## 설계서에 명시가 없어 정한 것
- `set_lock`은 타깃이 있을 때만 켜진다. 타깃이 해제되면(LOST 등) 잠금도 풀린다. 잠금은 "지금 타깃에 대한 넛지 진행 중"이라는 뜻으로 해석했다.
- `on_feedback`
  - 현재 타깃이 아닌 ID에 대한 피드백은 그 ID의 쿨다운만 등록하고 상태는 바꾸지 않는다.
  - 현재 타깃이면 해제한다. 마지막 입력이 1초 이내면 그 입력으로 바로 다시 고른다.
- 해제 사유 판정 순서: 미관측(LOST)을 먼저 보고, 관측 중이면 OUT_OF_RANGE를 STATE_CLEARED보다 먼저 본다.
- 자격이 없는 현재 타깃(예: 5.0~5.8 m)도 점수는 계산한다. 전환 마진 비교에 그 점수를 쓴다.

## 시험 [실행 확인]
- `src/ash_e_core/test/test_priority.py` 20개: 설계서 12.2의 시나리오 1~13 전부, STATE_CLEARED, 거리 없음, 결정론 재생.
- 전체 pytest 결과: 100 passed (2026-11-11).
- `run_webcam.py --video`(dev 참가자 P02 프레임으로 만든 임시 영상, `--no-gui --rate 1000`): ACQUIRED가 나오고 타깃 테두리·순위 표시가 정상이었다. 임시 영상과 캡처는 삭제했다.

## 클립 평가 연결 (2026-11-11) [실행 확인: 가짜 모델 테스트]
- `prototype/clip_io.ClipRunner`: 처리한 프레임마다 `PrioritySelector.update`를 호출한다. 녹화(`run_webcam --record`)와 재생(`--replay`, `eval_clips.py`)이 모두 이 경로를 쓴다.
  - frame 줄에 `target_id`(타깃 없으면 null, 처리하지 않은 프레임은 직전 값을 그대로 씀)와 `target_event`를 기록한다.
  - 선택기는 클립마다 새로 만든다.
- `eval_clips.py`의 기존 S5 떨림 계산(`target_ids`, `flicker_count`)이 이 필드를 그대로 읽는다. `prototype/test_clip_io.py`에 테스트를 1개 추가했다.
- 지표가 실제 값을 갖는 조건: S5 클립에 같은 그룹 참가자 2명 이상이 등장해야 한다. hold-out이 P03 1명뿐이라 hold-out에서는 S5를 판정할 수 없다(N7, 설계서대로).

## 아직 안 한 것
- **실제 웹캠 GUI에서 여러 명이 있을 때의 동작 [미검증]**: S5 다인 클립이 없다.
- 단계 B ROS 노드(`ash_e_priority`)는 합격 게이트 이후에 한다.

## A9 sim_priority (2026-11-11)
카메라 없이 가짜 다수 인원 시나리오를 `PrioritySelector`에 재생한다. `ash_e_core`는 수정하지 않았다.

### 파일
- `prototype/sim_priority.py`: 시나리오 로더(`load_scenarios`), 프레임 생성기(`scenario_frames`, 시드 고정이라 결정론), 실행·요약, CLI. B7의 `fake_detections_pub`는 앞의 두 함수와 yaml을 그대로 재사용한다.
- `prototype/config/sim_scenarios.yaml`: 시나리오 데이터(트랙별 presence/state/distance/bearing/conf/wobble, 잡음, 이탈 시각). 파일 머리에 필드 설명이 있다.
- `prototype/config/priority.yaml`: `PriorityConfig` 기본값과 같은 값(테스트로 동치 확인). 튜닝용 사본이고 `--config`, `run_webcam.py --priority-config`에 쓴다.
- `prototype/test_sim_priority.py`: 13개.
- S5 떨림은 `eval_clips.flicker_count`를 그대로 import해 쓴다(전환 후 10 s 안에 또 전환이면 1회로 센다. 테스트로 동일 객체임을 확인).

### 실행
```
.venv\Scripts\python prototype\sim_priority.py                       # 텍스트 요약(전 시나리오)
.venv\Scripts\python prototype\sim_priority.py --events --timeline   # 이벤트 로그, 타깃 ID 타임라인
.venv\Scripts\python prototype\sim_priority.py --json --out _workspace\sim_priority.json
.venv\Scripts\python prototype\sim_priority.py --only target_departs_oor --show   # [미검증] OpenCV 창, q로 종료
```
`--show`는 디스플레이가 없는 환경이라 실행해 보지 못했다. 헤드리스 경로만 [실행 확인].

### 결과 [실행 확인] (기본 가중치, 8 Hz, 시드 고정)
| 시나리오 | 길이 | 전환 | S5 떨림 | 이벤트 | 이탈 후 전환 지연 |
| --- | --- | --- | --- | --- | --- |
| s5_mixed (흡연 1 + 비흡연 1, 20 s에 역할 교대) | 45 s | 1 | 0 | ACQUIRED 1, SWITCHED_BETTER 1 (21.0 s) | #1 흡연 중단(20 s) -> #2로 1.00 s |
| two_smokers_close (두 명 비슷한 거리, 반대 위상 흔들림 ±0.4 m) | 60 s | 0 | 0 | ACQUIRED 1 | 해당 없음 |
| two_smokers_stress (흔들림 ±1.5 m, 5 s 주기, 잡음 큼) | 60 s | 9 | 8 | ACQUIRED 1, SWITCHED_BETTER 9 | 해당 없음 |
| target_departs (3 -> 7 m로 이동, 흡연자·소지자 잔류) | 40 s | 1 | 0 | ACQUIRED 1, SWITCHED_BETTER 1 (14.9 s) | 이동 시작(10 s) -> #2로 4.88 s |
| target_departs_oor (이동 + 약한 후보 4.9 m 1명) | 40 s | 1 | 0 | ACQUIRED 1, OUT_OF_RANGE 1 (18.0 s) | 5.8 m 통과(17 s) -> #2로 1.00 s (= out_of_range_hold_s) |
| target_dropout_reappear (1.2 s 소실, 4 s 소실 후 재등장) | 50 s | 2 | 0 | ACQUIRED 1, LOST_TIMEOUT 1 (21.9 s), SWITCHED_BETTER 1 (33.75 s) | 소실(20 s) -> #2로 1.88 s (= lost_timeout_s 2 s 이내 마지막 관측 기준) |

실제 흡연 현장에 가까운 시나리오(s5_mixed, two_smokers_close)의 떨림은 0회이고 합격선(S5 0회)과 일치한다. 단, 가짜 입력이라 **합격 판정 근거가 아니라 참고값**이다(N8).

### 해석·원인 분석 (가중치는 바꾸지 않았다)
- **two_smokers_stress 떨림 8회**: 이 시나리오는 두 사람의 거리가 ±1.5 m(최대 3 m 차이)로 서로 반대로 오가게 만든 일부러 가혹한 입력이다. 거리 점수 차이는 `w_dist * Δd / (far_m - near_m) = 0.30 * Δd / 3.5`라서 Δd가 약 1.75 m를 넘으면 `switch_margin 0.15`를 넘는다. 이 상태가 주기마다 약 2 s 이상 유지되면 `switch_confirm_s 1 s`와 `min_hold_s 3 s`를 둘 다 통과해 전환 간격은 약 7.4~7.5 s와 약 2.9~3.0 s(예: 34.0→36.9 s, 43.9→46.8 s)가 섞여 나온다. 짧은 쪽은 `min_hold_s` 3 s가 하한이다. 간격이 모두 10 s 미만이라 떨림으로 센다. 즉 히스테리시스는 "마진 이하 + 1 s 미만"의 흔들림만 막고, 마진을 넘는 지속적 진동은 막지 못한다. 사람이 두 명 모두 3 m 안팎에서 ±1.5 m씩 반대로 움직이는 것은 현실적이지 않으니 큰 문제는 아니다. 그래도 현장에서 두 흡연자가 번갈아 접근·후퇴하면 일어날 수 있다. 완화 수단은 `switch_margin` 상향(0.40이면 이 시나리오는 0회, 테스트로 확인) 또는 `min_hold_s`/`switch_confirm_s` 상향이다. 값 결정은 현장 튜닝으로 한다.
- **target_departs**: 이동하는 타깃은 OUT_OF_RANGE에 도달하기 전에, 더 나은 후보가 마진을 넘는 즉시 SWITCHED_BETTER로 교체된다(약 4.9 s). OUT_OF_RANGE 경로는 약한 후보만 있는 `target_departs_oor`에서 확인했다. 의도한 동작이다.
- **target_dropout_reappear**: 1.2 s 소실은 아무 일도 없었다(`lost_timeout_s` 2 s 미만). 4 s 소실은 LOST_TIMEOUT 후 #2가 된다. #1이 24 s에 재등장하면 ID 쿨다운(10 s)이 끝난 뒤(약 31.9 s)에 #1이 더 가깝다는 이유로, `switch_confirm_s` 1 s 대기와 잡음 때문에 약 1.9 s 늦은 33.75 s에 #2에서 #1로 되돌아간다. 전환 간격이 11.9 s라 S5 떨림 정의(10 s)로는 0회지만, 소실이 반복되면 같은 핑퐁이 생길 수 있다. 정의상 떨림이 아니라는 점만 적어 둔다.
- 거리 대체값(프록시)은 시나리오에서 잡음(σ 0.03~0.15 m)을 넣어 흉내 냈다. 실제 프록시의 오차(박스 높이 기반, 수십 cm 이상)는 더 크므로 `two_smokers_close`의 0회가 실측에서도 유지된다는 보장은 없다.

### 남은 문제
- `--show` 시각화 미검증(디스플레이 없음).
- 시나리오는 가짜 입력이다. 트랙 ID 교환·분할 같은 트래커 오류는 모델링하지 않았다.
- 전체 pytest: QA 수정 라운드 1 이후 기록은 아래 참조.
- QA 수정 1: 잘못된 입력(알 수 없는 state, `tracks: []`, 빈 시나리오 파일, 없는 `--scenarios`/`--config` 파일)은 stderr 메시지와 종료 코드 2로 끝난다. `idle_s`는 duration 이하로 제한한다.
