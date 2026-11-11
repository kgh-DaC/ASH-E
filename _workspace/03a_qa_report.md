# ASH-E 단계 A QA 보고서

## A9 sim_priority QA (2026-11-11)
대상: prototype/sim_priority.py, prototype/config/{sim_scenarios,priority}.yaml, prototype/test_sim_priority.py, 02a_priority_notes.md "A9" 절. 소스 수정 없음, 커밋 없음.

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| S5 떨림 = eval_clips.flicker_count | 통과 | `from eval_clips import flicker_count`로 동일 객체 import, 테스트도 `is` 확인. switch_times 로직은 flicker_count 내부와 동일 정의 |
| ash_e_core 무수정·공개 인터페이스만 | 통과 | git status에 src/ 변경 없음. 쓰는 것: PrioritySelector.update, config, types, viz.draw_priority. ROS/Windows 전용 import grep 0건 |
| priority.yaml == PriorityConfig 기본값 | 통과 | test_priority_yaml_equals_defaults 통과(dataclass 동등) |
| B7 재사용 분리 | 통과 | 시나리오는 yaml, load_scenarios/scenario_frames는 순수 함수(ROS·cv2 없음). cv2는 --show 안에서만 import |
| 결정론 | 통과 | --json 두 번 실행 결과 바이트 동일. 시드는 시나리오별 random.Random |
| 노트 결과 표 vs 실제 실행 | 통과 | 6개 시나리오 전환/떨림/이벤트/지연(1.00, 4.88, 1.00, 1.88 s, 21.0/14.9/18.0/21.9/33.75 s) 모두 일치 |
| 이탈 후 전환 지연 계산 | 통과(주의 1) | departure 시각 이후 첫 다른 id 타깃까지. cur==tid일 때만 값 산출 |
| 원인 분석 vs priority.py | 대체로 통과(주의 2) | 거리점수 0.30*Δd/3.5, 마진 0.15 -> Δd 1.75 m는 코드와 일치. 전환 조건 margin+confirm 1 s+min_hold 3 s도 priority.py 206-209행과 일치 |
| pytest 전체 | 통과 | 115 passed (8.55 s) |
| 테스트 의미 | 통과 | stress가 전환>=2·떨림>=1을 요구하고 margin 0.40이면 0이 되는지 확인(공허 방지). 단 아래 결함 3 참고 |
| --show | 부분 | 이 머신에서 `--show --speed 100` 오류 없이 종료(cv2 4.11). 창 내용 시각 확인은 불가 -> 화면 렌더링은 미검증 |

### 결함·주의 (심각도 순, 담당 priority-dev)
1. [낮음] 잘못된 입력 처리: 사용자 입력 오류가 traceback으로 나옴. 재현:
   - 상태값 오타: state에 `bogus` -> `KeyError: 'bogus'` (sim_priority.py 97행 STATES[...]).
   - `tracks: []` -> 의도된 ValueError지만 traceback, argparse 오류가 아님. 없는 --scenarios/--config 파일도 FileNotFoundError traceback.
   - 빈 시나리오 파일(`scenarios: {}` 또는 빈 파일): 아무 시나리오도 없이 종료코드 0, 요약 한 줄만 출력. "시나리오 없음" 오류로 처리하는 게 안전.
   - 알 수 없는 --only는 정상(argparse error, 종료 2, 목록 안내).
2. [낮음] 노트 정확성: two_smokers_stress 설명 "약 7.5 s 간격으로 전환"은 일부만 맞음. 실제 타임라인은 7.4~7.5 s와 약 2.9~3.0 s 구간이 섞임(34.0-36.9 s, 43.9-46.8 s). 짧은 구간은 min_hold_s 3 s가 걸림돌이 되는 경우라 "7.5 s 또는 3 s(min_hold)"로 적는 게 정확. 결론(margin 상향으로 완화)은 영향 없음. 또 dropout 노트의 "쿨다운 종료 31.9 s 후 33.75 s 복귀"는 확인 1 s 대기 + 잡음 때문에 약 1.8 s 차이로 설명하는 것이 정확.
3. [낮음] 경계: 프레임 수가 duration*rate+1이라 idle_s가 duration을 약간 넘을 수 있음(재현: 5 s, 8 Hz, 항상 비존재 트랙 -> idle 5.12 s). 영향 미미.
4. [참고] 테스트가 CLI 오류 경로(빈 시나리오, 잘못된 state)는 커버하지 않음. departures 지연 계산은 시나리오 결과 단언으로만 간접 검증되고 단위 테스트가 없음(cur != tid인 경우 delay None).

### 미실행
- --show 화면 렌더링 시각 확인(창 출력은 실행됐으나 내용 미확인).
- 단계 B(ROS2, fake_detections_pub 재사용 B7) 동등성: 미실행(ROS 환경 없음).
- 합격 여부 판단은 사용자 몫. 이 시뮬레이터 결과는 참고값(N8)이며 합격 근거가 아님.
