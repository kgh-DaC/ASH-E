# 02b 우선순위 구현 노트 (단계 B)

작성 2026-11-18. 표기: **[실행 확인]** = Windows에서 실행해 결과를 봤다. **[미검증]** = 코드만 있고 ROS가 없어 못 돌렸다.
core(`src/ash_e_core/`)는 수정하지 않았다(10.1).

## 구현 목록 (`src/ash_e_priority/`, ament_python)
| 파일 | 내용 | 상태 |
| --- | --- | --- |
| `ash_e_priority/priority_node.py` | 노드 `/ash_e/priority`(이름 `priority`, 네임스페이스 `ash_e`). 구독 `/ash_e/detections`(reliable, depth 5)·`/ash_e/target_feedback`(depth 10), 서비스 `~/set_lock`(= `/ash_e/priority/set_lock`, SetBool), 발행 `/ash_e/target`·`/ash_e/target_point`(has_target일 때만)·`/ash_e/priority/markers`(reliable, depth 1). 10 Hz 타이머는 `tick`만. | [미검증] (rclpy 없음) |
| `ash_e_priority/convert.py` | ROS 무관 순수 변환. msg(덕 타이핑)→core, core→msg(factory 주입). core dataclass 필드를 순회해 복사하므로 필드가 바뀌면 왕복 테스트가 깨진다. 시간 변환, `watchdog_now`. | [실행 확인] |
| `ash_e_priority/params.py` | 파라미터↔`PriorityConfig`: 형 강제(yaml `1`→float), 검증(near<far, release≥acquire 등), 래퍼 전용 키. | [실행 확인] |
| `ash_e_priority/markers.py` | RViz 마커 배치(순수, dict 스펙). 후보 라벨(거리·방위로 위치), 타깃 구, 좌상단 순위 범례. 프레임은 입력 det의 frame_id라 TF 불필요. | [실행 확인] |
| `ash_e_priority/tools/fake_detections_pub.py` | B7. `prototype/sim_priority.py`의 `load_scenarios`·`scenario_frames`와 `sim_scenarios.yaml` 재사용. stamp = 노드 시계 + 시나리오 시각. | [미검증] (변환 경로는 테스트됨) |
| `config/priority.yaml` | 8장 키 전부(`/**: ros__parameters:`). 값은 `prototype/config/priority.yaml`과 같고 테스트가 동치를 확인. | [실행 확인] |
| `launch/priority.launch.py` | 우선순위만, `fake:=true scenario:=...` 옵션. | [미검증] (구문만 확인) |
| `launch/ash_e_all.launch.py` | B8. 카메라 드라이버(`camera_launch`) 포함 옵션 + `perception_node` + `priority_node` + base_link→카메라 광학 프레임 정적 TF. | [미검증] |
| `test/` | 28개. 가짜 msg 객체(설계서 3장에서 직접 작성)로 왕복, `src/ash_e_msgs/msg/*.msg`와 core 필드 대조, 래퍼 경로 대 직접 호출 동일성, params·yaml. | [실행 확인] |

### 동작 결정 (설계서에 세부가 없어 정한 것)
- **tick 시각**: `last_stamp + (노드 시계 경과)`로 stamp 시간대에서 계산한다(`watchdog_now`). 카메라 드라이버가 노드 시계와 다른 시계로 stamp를 찍어도, `use_sim_time`/bag 재생(-r 0.2)에서도 `update(now=stamp)`와 같은 기준이라 입력 끊김 판정이 어긋나지 않는다. 피드백도 같은 방식으로 `now`를 만든다.
- **stamp 역행**: 입력 stamp가 직전보다 `time_jump_reset_s`(1.0 s) 넘게 과거로 가면(bag 반복 재생, 시계 리셋) 선택기를 새로 만든다. 로그 경고.
- **예외 처리**: 모든 콜백이 try/except. 예외가 나면 오류 로그(2 s 스로틀) 후 선택기를 새로 만들고 계속 돈다. 잘못된 yaml 값은 오류 로그 후 내장 기본값으로 기동한다(죽지 않음).
- **런타임 튜닝**: 파라미터 이름 = `PriorityConfig` 필드. `ros2 param set /ash_e/priority switch_margin 0.3`이 검증을 거쳐 `selector.cfg`에 바로 반영된다(현재 타깃 유지). 검증 실패는 거부. 가중치 합이 1이 아니면 core가 정규화하고 경고한다.
- `set_lock(true)`를 타깃 없을 때 부르면 core가 잠금을 적용하지 않으므로 `success=false, message="no target: lock not applied"`를 돌려준다. `locked` 플래그는 다음 `/ash_e/target`부터 보인다(잠금 변경만으로는 발행하지 않는다. core에 상태만 내는 공개 메서드가 없다).
- `/ash_e/target`은 `update`마다, 그리고 `tick`/`on_feedback`이 상태를 바꿀 때 발행한다(설계서 4.3). 빈 입력이 와도 update하므로 IDLE이 계속 나간다.
- 노드는 `threading.RLock`으로 콜백을 직렬화한다(MultiThreadedExecutor를 써도 안전).

## RPi5 실행법 (Ubuntu 24.04, ROS2 Jazzy) [미검증]
```bash
source /opt/ros/jazzy/setup.bash
cd ~/26PJT_ASH-E
python3 -m venv --system-site-packages .venv-ros && source .venv-ros/bin/activate   # numpy는 올리지 않는다(설계서 1.2)
pip install onnxruntime "numpy<2"          # perception용. core는 colcon이 설치하므로 pip install -e src/ash_e_core는 하지 않는다(중복 시 pip uninstall ash_e_core)
colcon build --symlink-install --packages-up-to ash_e_priority      # ash_e_msgs, ash_e_core를 의존으로 끌어옴. perception 포함: --packages-up-to ash_e_perception ash_e_priority
source install/setup.bash                  # venv를 켠 채 빌드해야 entry point 셔뱅이 venv 파이썬을 쓴다
python3 -c "import ash_e_core.priority"    # ROS 없이도 import 되어야 한다(10.1)
```
전체 기동:
```bash
ros2 launch ash_e_priority ash_e_all.launch.py camera_config:=$(ros2 pkg prefix ash_e_perception)/share/ash_e_perception/config/camera_astra_pro.yaml \n    extrinsics_file:=$HOME/ash_e/astra_pro_extrinsics.yaml model_dir:=$HOME/ash_e/models
ros2 launch ash_e_priority ash_e_all.launch.py color_topic:=/image_raw color_info_topic:=/camera_info use_depth:=false
ros2 launch ash_e_priority ash_e_all.launch.py equivalence_mode:=true use_sim_time:=true      # rosbag 동등성(10.2)
# perception 인자는 모두 기본값 ''(= perception.yaml/camera_config 유지), 비어 있지 않을 때만 덮어쓴다. 우선순위: perception.yaml < camera_config < 인자
ros2 launch ash_e_priority ash_e_all.launch.py camera_launch:=/path/to/driver.launch.py     # 드라이버까지 같이
```
**가짜 입력으로 우선순위만 단독 시험 (카메라·perception 불필요)**
```bash
# 터미널 1
ros2 launch ash_e_priority priority.launch.py
# 터미널 2: 시나리오 목록 / 재생
ros2 run ash_e_priority fake_detections_pub --ros-args -p list:=true
ros2 run ash_e_priority fake_detections_pub --ros-args -p scenario:=s5_mixed                # 설계서 12.2-1
ros2 run ash_e_priority fake_detections_pub --ros-args -p scenario:=target_departs_oor      # 12.2-5 (OUT_OF_RANGE, 즉시 다음 후보)
ros2 run ash_e_priority fake_detections_pub --ros-args -p scenario:=s5_mixed -p silence_from_s:=10.0 -p silence_for_s:=5.0   # 12.2-8 (입력 끊김)
ros2 run ash_e_priority fake_detections_pub --ros-args -p scenario:=target_dropout_reappear   # 12.2-6 (미관측 2 s)
# 한 번에: ros2 launch ash_e_priority priority.launch.py fake:=true scenario:=s5_mixed loop:=true
# 관찰
ros2 topic echo /ash_e/target --field last_event      # ACQUIRED=1 SWITCHED_BETTER=2 LOST_TIMEOUT=3 OUT_OF_RANGE=4 INPUT_TIMEOUT=6
ros2 topic echo /ash_e/target --field target_id
ros2 topic hz /ash_e/target
rviz2                                                  # Fixed Frame = sim_optical, MarkerArray /ash_e/priority/markers
# 서비스·피드백·튜닝
ros2 service call /ash_e/priority/set_lock std_srvs/srv/SetBool "{data: true}"
ros2 topic pub --once /ash_e/target_feedback ash_e_msgs/msg/TargetFeedback "{track_id: 1, result: 1}"   # DONE -> FEEDBACK_RELEASED (header.stamp는 0이어도 됨)
ros2 param set /ash_e/priority switch_margin 0.4
```
기대값은 `_workspace/02a_priority_notes.md`의 시나리오 표(ACQUIRED 시각, 전환 지연)와 같아야 한다. 시나리오 파일을 못 찾으면 `-p prototype_dir:=<repo>/prototype` 또는 `export ASH_E_REPO=<repo>`.
(fake 발행기는 레포 루트에서 `colcon build`한 경우 install/ 위쪽으로 올라가 `prototype/`을 자동으로 찾는다.)

## 알려진 한계
1. (해소) core에 `package.xml`·`resource/ash_e_core`가 추가되어 colcon이 core를 빌드한다. `ash_e_priority/package.xml`에 `exec_depend ash_e_core`를 넣었다. onnxruntime은 rosdep 키가 없어 pip로 따로 설치한다.
2. `ash_e_all.launch.py`는 perception 인자 목록을 `perception.launch.py`의 `OVERRIDES`와 같게 복사해 둔 것이다(`extrinsics_file`, `model_dir`, `equivalence_mode`, `camera_config` 포함). 한쪽에 인자를 추가하면 다른 쪽도 맞춰야 한다. perception 노드 이름은 `ash_e_perception`(perception.launch.py와 동일).
3. 정적 TF(`base_link`→`camera_color_optical_frame`, 높이 1.1 m·전방 0.1 m)는 H7 기본값이고 `publish_static_tf:=false`로 끈다. 카메라 드라이버가 같은 TF를 내면 끄지 않으면 충돌한다. 현장 확인 필요.
4. fake 발행기는 레포 `prototype/`(sim_priority.py → eval_clips.py → numpy)에 의존하므로 레포 바깥에 설치한 패키지만으로는 동작하지 않는다. 시험 도구라 허용했다.
5. 마커 후보 위치는 거리·방위로 다시 계산한 값이다(`TargetCandidate`에 위치가 없다). 거리 없는 후보는 범례 텍스트에만 나온다.
6. 우선순위 평가는 메시지 단위라 detections 지연이 곧 타깃 지연이다. 입력→`/ash_e/target` 300 ms(10.4)는 perception 쪽 지연이 지배한다.

## Windows에서 못 한 검증 (RPi5·ROS 필요)
- `colcon build` 성공, `ros2 interface show ash_e_msgs/msg/TargetStatus` 확인(12.4). 설계서 3장·`.msg` 파일과 core의 필드 대조는 pytest로 했다.
- `priority_node` 실제 기동, 실제 rclpy 메시지 setter의 형 검사(예: uint8·float32 범위) 통과 여부. 변환 함수는 IntEnum을 순수 int로 바꿔 넣게 해 두었다.
- `ParameterDescriptor(dynamic_typing=True)`와 `ros2 param set`의 콜백 경로, launch 파일 로딩(`ParameterValue`, `PythonExpression`, `tf2_ros` 인자 형식은 Jazzy 기준으로 작성, 구문만 컴파일 확인).
- 12.2 시나리오 1·5·7·8을 fake 발행기로 재현(12.4). 변환 경로(core→msg→core)를 거친 선택기 출력이 직접 호출과 같음은 시나리오 3종으로 확인했다.
- 10.2 동등성(target_id 타임라인 98%), bag 재생 `-r 0.2 --clock`에서 `watchdog_now`/역행 리셋 동작, 30분 연속 실행, RViz 마커 모양.

## Windows pytest
- `.venv\Scripts\python -m pytest` 전체: 178 passed (기존 core·prototype + perception-dev가 동시에 추가한 테스트 + 이 패키지 28개). 이 패키지만: `.venv\Scripts\python -m pytest src\ash_e_priority` 28 passed.
- core 금지 import grep(`rclpy` 등): `src/ash_e_core`에서 0건.
