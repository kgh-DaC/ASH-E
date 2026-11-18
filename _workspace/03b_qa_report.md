# 03b QA 보고서 (단계 B, B10) — 2026-11-18

환경: Windows 11, `.venv`, ROS2/rclpy/colcon/rosbag2 없음. **rclpy 노드·launch·rosbag 도구는 한 번도 실행되지 않았다.** 아래 "미실행" 항목은 RPi5에서 사용자가 실행해야 한다. P03/holdout 데이터는 읽지 않았다.

## 1. 요약 판정

- Windows에서 가능한 검증은 모두 통과. **ROS 쪽 결함 후보 3건(중간 1, 낮음 2)과 문서 불일치 몇 건**을 찾았다(5절). 코드는 고치지 않았다.
- 가장 중요한 발견: **동등성 검사(10.2)에서 첫 프레임이 버려질 가능성이 높다**(D1). 비교 스크립트는 stamp 기준 짝짓기와 프레임 수 불일치 보고를 하므로 발생하면 바로 드러난다.
- 최종 합격 판단은 RPi5 실행 결과와 사용자 몫이다.

## 2. 검증 결과 표

| # | 항목 | 결과 | 근거 |
| --- | --- | --- | --- |
| 1 | `.venv\Scripts\python -m pytest` 전체 | **통과** 217 passed (보고값과 일치). QA가 `prototype/test_compare_jsonl.py` 5개를 추가해 **222 passed** | 실행 2회, 21 s |
| 2a | msg 필드 대 core 타입 (이름·순서) 5종 | **통과** | QA 독립 스크립트로 `.msg`를 직접 파싱해 dataclass 필드와 대조(Header는 stamp+frame_id로 전개). 5종 모두 순서까지 일치 |
| 2b | msg 상수 대 core IntEnum 값 | **통과** | STATE_*, DIST_SRC_*, MODE_*, EVENT_*(0~7), RESULT_*(1~4) 양방향(msg에 있는 상수, enum에 있는 멤버) 일치. `Ineligible`은 3.4절대로 msg 상수가 없고 core에만 있다(설계서와 같음) |
| 2c | 타입 (uint8/uint32/int32/float32/bool, Point, 배열) | **통과(정적)** | 타입 힌트 대조 이상 없음. 단 rosidl이 만드는 실제 setter의 범위 검사는 미실행(10절) |
| 2d | 변환 왕복 테스트 | **통과** | `test_convert.py::test_array_roundtrip`, `test_every_core_field_is_copied`, priority `test_detections_roundtrip_core_msg_core`, `test_real_msg_files_match_core`, `test_target_status_to_msg_fields`, `test_wrapper_path_equals_direct_selector`(시나리오 3종, 래퍼 경로 = 직접 호출). 실제 rosidl 클래스가 아니라 `.msg`에서 만든 가짜 클래스를 쓴다는 한계는 노트와 같다 |
| 2e | `ash_e_msgs` 패키징 | **통과(정적)** | CMakeLists가 msg 5개를 모두 등록, std_msgs/geometry_msgs 의존, package.xml에 rosidl_interface_packages 그룹. `colcon build`는 미실행 |
| 3a | core 금지 import (rclpy, rospy, sensor_msgs, cv_bridge, openni, ultralytics, win32, msvcrt) | **통과** | `src/ash_e_core` 전체 grep 0건(`ament`, `ash_e_msgs` import도 0건). 신규 `depth_align.py` 포함 |
| 3b | 래퍼의 `/camera/` 문자열 | **조건부 통과** | `params.py`(기본값 한 곳), `config/camera_astra_pro.yaml`(설정값)에만 있음. **예외 1건**: `ash_e_priority/launch/ash_e_all.launch.py`에 launch 인자 기본값 4개로 중복(D3, 낮음). `perception.launch.py`·노드 코드에는 없음 |
| 4 | core 무수정 | **통과** | `git diff dfaf7e2 --name-status -- src/ash_e_core` = `M setup.py` 하나(data_files 6줄, 패키징만). 기존 core .py는 diff 없음. 신규: `depth_align.py`, `package.xml`, `resource/ash_e_core`(빈 파일), `test/test_depth_align.py` — 허용 목록과 정확히 일치 |
| 5a | 프로토타입 JSONL 스크립트 | **작성·실행 통과** | `prototype/log_replay_jsonl.py` (영상 → core v6 기본 설정, 스로틀 끔 → `frame_to_jsonl`). P02 `data/raw_clips/P02/S1/mouth_001/clip.mp4` 120프레임 2.4 s, 120줄 생성, holdout/P03 경로는 거부함(시험) |
| 5b | 비교 스크립트 | **작성·자체 시험 통과** | `prototype/compare_jsonl.py` (설계서 10.2 허용 오차 그대로). 아래 표 참고. pytest 5개 |
| 5c | ROS 대 프로토 실제 비교 | **미실행** | RPi5(또는 ROS PC)에서 7절 절차로 |
| 6a | perception.yaml 키 대 `PerceptionConfig` | **통과** | 누락 0, 알 수 없는 키 0, 값 차이 0 (래퍼 키는 `WRAPPER_DEFAULTS`에 있음). `camera_astra_pro.yaml` 키도 모두 래퍼 파라미터 |
| 6b | priority.yaml 대 `PriorityConfig`·`prototype/config/priority.yaml` | **통과** | 누락 0, 값 차이 0. 추가 키 5개(`marker_*`, `publish_markers`, `tick_rate_hz`, `time_jump_reset_s`)는 래퍼 전용 |
| 7 | launch 정적 점검 | **통과(정적)** | 3개 파일 모두 파싱 OK. Node의 package/executable이 setup.py entry_points와 일치(`perception_node`, `priority_node`, `fake_detections_pub`). setup.py data_files가 launch/config를 share에 설치, setup.cfg가 lib/<pkg>로 스크립트 설치(ros2 run 요건). 노드 이름 `ash_e_perception` / `priority`+namespace `ash_e`, yaml 키 `/**` 와일드카드라 이름과 무관하게 적용됨. 모든 launch 인자(OVERRIDES, ash_e_all의 파라미터)가 노드가 선언한 파라미터이고 형(b/f/i/s)이 기본값과 일치. 실제 launch 로딩은 미실행 |
| 8 | pyflakes | 통과 | 미정의 이름 0. 미사용 import 5건(무해, 아래 D6) |

### 비교 스크립트 자체 시험 (같은 영상 120프레임 proto.jsonl 기준)
| 시험 | 기대 | 결과 |
| --- | --- | --- |
| proto 대 proto | 통과, 종료 코드 0 | 전 항목 PASS, IoU 1.0, exit 0 |
| bbox +1 px, raw_conf +0.01 | 통과 | PASS |
| 첫 프레임 삭제(D1 재현) | 프레임 수 불일치 FAIL, stamp 짝짓기로 나머지는 비교 | `frames_equal` FAIL, `only_proto=1`, 나머지 PASS, `frame_seq_offsets` 보고 |
| state 변경, bbox +80 px, target_id +1 | FAIL, exit 1 | state·IoU·target_id·events FAIL, exit 1 |

(이 영상에서는 사람 1명, 이벤트 ACQUIRED 1건이라 target 비교의 변별력은 약하다. S5·S8·S10 같은 다수 인원 클립으로 RPi5에서 다시 돌려야 한다.)

## 3. 단계 A 필수 시나리오 재확인 (순수 파이썬)
이번 변경은 core를 바꾸지 않았으므로 기존 `prototype/test_sim_priority.py`와 core 우선순위 테스트가 그대로 통과(217/222 안에 포함). 래퍼 변환 경로(core→msg→core)를 거친 선택기 출력이 직접 호출과 같음은 priority 테스트가 3종 시나리오로 확인. fake 발행기를 통한 실제 토픽 재현은 미실행.

## 4. 미실행 목록 (ROS/RPi5 필요)
`colcon build` 경고 유무, `ros2 interface show ash_e_msgs/msg/TargetStatus`, 노드 기동·모델 없이 빈 배열 발행, `ros2 node info`로 토픽 파라미터 반영, 보정 파일 없는 software 모드의 PROXY 폴백, launch 실제 로딩, cv_bridge 변환, QoS 연결, CameraInfo 수신, `video_to_bag`·`dump_jsonl`·`calib_astra_extrinsics capture`·`depth_check --bag` ROS 입출력, 12.2 시나리오 1·5·7·8의 토픽 재현, 10.2 동등성 실측, 10.4 실기(처리율, 지연, 30분, USB 재연결), 10.5 뎁스 교체 검증, B0 드라이버, `DepthAligner.align` RPi5 실측(Windows 18 ms, RPi5 40~60 ms 예상으로 예산 초과 가능).
**10.5 검증 결과 확인**: 도구(`depth_check`)의 순수 부분(요약표, 최근접 매칭, 스텁 모델 end-to-end)과 정렬 단위 테스트 13개는 통과했으나, 실제 Astra Pro 데이터가 없어 10.5 항목 1~7은 전부 미실행이다.

## 5. 결함 목록 (수정하지 않음. 담당별)

### perception-dev
| ID | 심각도 | 내용 | 재현 | 제안 |
| --- | --- | --- | --- | --- |
| D1 | **중간** (10.2 동등성에 영향 가능) | `perception_node._process`는 컬러 CameraInfo가 아직 없고 `info_wait_s`(5 s) 이내면 `_WAIT`을 돌려주고 **그 프레임을 버린다**(`matcher.pop_ready`가 이미 꺼낸 뒤). `video_to_bag`은 같은 stamp로 Image를 먼저, CameraInfo를 나중에 쓰므로 bag 재생 시 프레임 0이 CameraInfo보다 먼저 도착해 버려질 가능성이 높다. 그러면 프로토타입(frame_seq 1부터 120)과 ROS(2부터)의 frame_seq가 1 어긋나고 트래커 hits가 한 프레임 늦게 시작해 초반 검출·ACQUIRED 시각이 달라진다. (use_sim_time이면 `_t_start`가 시계 수신 전 0이라 5 s 대기도 시뮬레이션 시간 기준) | 7절 동등성 절차 후 `proto.jsonl`과 `ros.jsonl`의 `compare_jsonl.py` 결과에서 `only_proto=1`/`frames_equal FAIL`이면 확정 | `_WAIT`이면 프레임을 버리지 말고 매처에 되돌리거나(equivalence_mode에서는 info를 기다린 뒤 처리), `video_to_bag`이 CameraInfo를 Image보다 먼저 쓰게 하고 노드가 info를 받을 때까지 구독을 시작하지 않게. 비교 스크립트는 stamp 기준이라 이 어긋남이 있어도 나머지는 비교 가능 |
| D2 | 낮음 | `ash_e_all.launch.py`(priority-dev 소유)가 perception의 `extrinsics_file`, `model_dir`, `equivalence_mode`, `camera_config`를 인자로 노출하지 않는다. 그래서 전체 기동에서는 보정 파일 경로를 줄 수 없어 PROXY로만 동작하고, `camera_astra_pro.yaml`도 로드되지 않는다(launch 기본 인자가 값을 덮음). 인식만 `perception.launch.py`로 띄우면 해결 | `ros2 launch ash_e_priority ash_e_all.launch.py extrinsics_file:=...` 가 "unknown argument"로 실패 | 인자 추가 또는 전체 기동 대신 `perception.launch.py` + `priority.launch.py` 두 개 사용을 문서화 |
| D6 | 정보 | 미사용 import: `depth_check.py`(Dict, CameraIntrinsics), `dump_jsonl.py`(Optional), `test_tools.py`(os). 기능 무관 | pyflakes | 정리 |

### priority-dev
| ID | 심각도 | 내용 | 제안 |
| --- | --- | --- | --- |
| D3 | 낮음 | `ash_e_all.launch.py`에 `/camera/...` 토픽 문자열 4개가 launch 인자 기본값으로 들어 있다(설계서 B10 grep 규칙은 "파라미터 기본값 외 없음"이므로 엄밀히는 위반, 실질적으로는 perception.launch처럼 빈 문자열 기본값이 맞다). 또 기본값이 `camera_astra_pro.yaml`과 이중 관리됨 | 기본값을 `""`(yaml 유지)로 바꾸고 perception.launch.py처럼 비어 있지 않을 때만 덮기 |
| D4 | 낮음(문서) | `02b_priority_notes.md`의 "알려진 한계 1"(core에 package.xml 없음)과 `ash_e_priority/package.xml` 19~20행 주석이 낡았다. 지금은 core에 package.xml이 있어 colcon이 빌드한다. 의존 선언(`<depend>ash_e_core</depend>`)도 없어 `--packages-up-to`가 core를 끌어오지 않는다 | 주석·노트 갱신, 필요하면 exec_depend 추가 (pip -e와 colcon 설치 중복은 perception 노트 4절대로 둘 중 하나만) |
| D5 | 낮음 (동등성 해석 주의) | priority 노드의 10 Hz tick이 프레임 사이에 상태를 바꾸면(LOST_TIMEOUT 등) 그 `TargetStatus`는 detections stamp와 다른 stamp를 갖고, `dump_jsonl`의 `JsonlPairer`는 짝이 없는 target을 버린다. 프로토타입 로그는 `update`만 호출하므로 **이벤트 순서(10.2 "이벤트 순서 동일")가 어긋날 수 있다**. 결함이라기보다 비교 방법의 한계 | 동등성 실행 때만 `tick_rate_hz:=0.1`(7절)로 tick을 사실상 끄거나, dump_jsonl이 짝 없는 target을 별도 기록 |

### 설계서와 다른 점 (의도적, 확인만)
- 래퍼 전용 키 중 `sync_wait_s`, `info_wait_s`, `detections_topic` 등이 4.2절 표에 없는 추가 항목이다. 문제 없음.
- 설계서 10.2의 `run_webcam.py --log`는 없다. 대신 `prototype/log_replay_jsonl.py`가 그 역할을 한다(5a). 설계서 문구 갱신은 planner 몫.

## 6. QA가 추가·수정한 파일
| 파일 | 내용 |
| --- | --- |
| `prototype/log_replay_jsonl.py` (신규) | 영상 → proto.jsonl. stamp = `round(idx*1e9/fps)/1e9`(video_to_bag과 같은 ns 반올림), frame_id `webcam_optical`, 스로틀 끔, 우선순위 `update`만. holdout/P03 거부 |
| `prototype/compare_jsonl.py` (신규) | proto.jsonl 대 ros.jsonl 비교, 10.2 허용 오차, stamp/seq 짝짓기, 종료 코드 0/1 |
| `prototype/test_compare_jsonl.py` (신규) | 5개 시험 |
| 기존 코드 수정 | **없음** (오타 수정 포함 0건) |

## 7. RPi5 사용자 실행 목록 (Ubuntu 24.04, ROS2 Jazzy, 모델과 클립 복사 후)

전제: `02b_perception_notes.md` 4·5절의 설치·모델 복사(`models/pose.onnx`, `models/cig_roi_v6.onnx`, sha256 확인)를 마쳤고, 새 터미널마다 `source /opt/ros/jazzy/setup.bash; source ~/ash_e/venv/bin/activate; source ~/ash_e/ws/install/setup.bash`.

### 7.1 빌드 (12.4)
```bash
cd ~/ash_e/ws && colcon build --symlink-install --packages-select ash_e_msgs ash_e_core ash_e_perception ash_e_priority 2>&1 | tee build.log
grep -i warn build.log                                   # 경고 0이어야 한다
source install/setup.bash
ros2 interface show ash_e_msgs/msg/TargetStatus          # 3.5절과 같은지(상수 MODE_*, EVENT_* 포함)
ros2 interface show ash_e_msgs/msg/SmokerDetection
python3 -c "import ash_e_core.pipeline, ash_e_core.priority; print('core ok')"      # ROS 없이 import (10.1)
```

### 7.2 단독 기동
```bash
# 모델 없이 (ASH_E_MODEL_DIR 비우고) 빈 배열 발행 확인
ros2 launch ash_e_perception perception.launch.py color_topic:=/image_raw color_info_topic:=/camera_info use_depth:=false
ros2 topic echo /ash_e/detections --once ; ros2 topic hz /ash_e/detections      # 카메라 또는 `ros2 run usb_cam usb_cam_node_exe` 필요
# 토픽을 인자로 바꾼 뒤 구독 확인
ros2 node info /ash_e_perception | grep -A6 Subscribers
# 보정 파일 없이 software 모드: 경고 후 PROXY로 동작해야 함
ros2 launch ash_e_perception perception.launch.py depth_alignment:=software 2>&1 | grep -i -E "extrinsics|PROXY"
ros2 node info /ash_e/priority
```

### 7.3 fake 입력 시나리오 (12.2의 1·5·7·8)
```bash
ros2 launch ash_e_priority priority.launch.py                                       # 터미널 1
ros2 run ash_e_priority fake_detections_pub --ros-args -p list:=true                # 터미널 2
ros2 run ash_e_priority fake_detections_pub --ros-args -p scenario:=s5_mixed        # 시나리오 1: 점수 최고가 ACQUIRED
ros2 run ash_e_priority fake_detections_pub --ros-args -p scenario:=target_departs_oor   # 시나리오 5: OUT_OF_RANGE 후 즉시 다음 후보
ros2 run ash_e_priority fake_detections_pub --ros-args -p scenario:=s5_mixed -p silence_from_s:=10.0 -p silence_for_s:=5.0   # 시나리오 8: INPUT_TIMEOUT 후 IDLE
ros2 topic echo /ash_e/target --field last_event
# 시나리오 7(대상 0명)은 시나리오 파일의 빈 구간을 쓰거나: ros2 topic pub -r 8 /ash_e/detections ash_e_msgs/msg/SmokerDetectionArray "{header: {frame_id: x}}"
ros2 service call /ash_e/priority/set_lock std_srvs/srv/SetBool "{data: true}"
ros2 topic pub --once /ash_e/target_feedback ash_e_msgs/msg/TargetFeedback "{track_id: 1, result: 1}"
```
기대값은 `_workspace/02a_priority_notes.md` 시나리오 표와 같아야 한다.

### 7.4 동등성 (10.2) — 클립 3개 이상(S5, S8, S10 포함). 클립 하나당:
```bash
# (Windows) 기준 로그: 같은 영상, 같은 모델(v6), 스로틀 없음
.venv\Scripts\python prototype\log_replay_jsonl.py <clip.mp4> proto.jsonl
# (RPi5) bag 만들기
ros2 run ash_e_perception video_to_bag <clip.mp4> clip_bag --color-topic /image_raw --info-topic /camera_info --hfov-deg 70
# 노드 먼저 띄우고 연결될 때까지 몇 초 기다린 뒤 재생 (reliable이라도 구독 전 프레임은 잃는다)
ros2 launch ash_e_perception perception.launch.py use_sim_time:=true equivalence_mode:=true use_depth:=false color_topic:=/image_raw color_info_topic:=/camera_info &
ros2 run ash_e_priority priority_node --ros-args -r __ns:=/ash_e --params-file $(ros2 pkg prefix ash_e_priority)/share/ash_e_priority/config/priority.yaml -p use_sim_time:=true -p tick_rate_hz:=0.1 &
ros2 run ash_e_perception dump_jsonl ros.jsonl --idle-exit-s 5 --ros-args -p use_sim_time:=true &
sleep 5; ros2 bag play clip_bag -r 0.2 --clock
# 비교 (두 파일을 같은 PC로 복사해 Windows 또는 RPi5의 python3에서)
python3 prototype/compare_jsonl.py proto.jsonl ros.jsonl            # 종료 코드 0이면 10.2 표 전부 통과
python3 prototype/compare_jsonl.py proto.jsonl ros.jsonl --align seq # frame_seq 기준(D1 확인)
```
같은 백엔드·스레드 수(`num_threads`)를 맞출 것. 불일치 시 래퍼(색 순서, 해상도, stamp, QoS 누락, D1)를 먼저 의심하고 core는 마지막에 의심한다. x86 대 arm64 비교는 완전 일치를 기대하지 않는다. 같은 bag을 RPi5에서 두 번 재생해 `ros.jsonl`끼리 비교(결정론, `compare_jsonl.py ros1.jsonl ros2.jsonl`)도 권장.

### 7.5 뎁스 체크 (10.4, 10.5, Astra Pro 실물 필요)
```bash
lsusb | grep -i -E "2bc5|orbbec"; v4l2-ctl --list-devices; v4l2-ctl -d /dev/videoN --list-formats-ext    # B0 (notes 7절)
ros2 run ash_e_perception calib_astra_extrinsics capture --out ~/ash_e/calib --color-topic <컬러> --ir-topic <IR>
ros2 run ash_e_perception calib_astra_extrinsics calibrate ~/ash_e/calib --out ~/ash_e/astra_pro_extrinsics.yaml   # rms_px <= 0.5
ros2 launch ash_e_perception perception.launch.py camera_config:=$(ros2 pkg prefix ash_e_perception)/share/ash_e_perception/config/camera_astra_pro.yaml extrinsics_file:=$HOME/ash_e/astra_pro_extrinsics.yaml publish_debug_image:=true
ros2 topic hz /ash_e/detections                                  # >= 5 Hz (3명, 정렬 포함)
ros2 run ash_e_perception depth_check --dir <PNG 폴더> 또는 --bag <bag>    # 1/2/3/4/5 m 줄자 오차(<=5%/10%), 유효 비율, stamp 차 p95 <= sync_slop_s
# 10.4: 30분 연속 실행 중 `top`/`vcgencmd measure_temp`/`vcgencmd get_throttled`로 메모리(<=+50 MB)·온도 확인, USB 재연결 1회
```
로그의 `align avg ... ms`가 예산(5~15 ms)을 넘으면 `depth_align_decimate:=4` 또는 컬러 640x480.

## 8. 판정
Windows 범위: 통과(222 passed, 계약 대조·금지 import·core 무수정·설정 키·launch 정적 점검 모두 이상 없음). 단계 B 합격 여부는 **RPi5 미실행 항목(특히 7.1 빌드와 7.4 동등성)** 결과에 달려 있다. 결함 D1을 RPi5 실행 전에 고치는 편이 안전하다.
