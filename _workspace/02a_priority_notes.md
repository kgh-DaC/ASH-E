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
