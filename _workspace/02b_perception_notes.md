# 02b 인식 단계 B (ROS2 이식) 구현 노트

작성: perception-dev, 2026-11-18. 기준: `_workspace/01_planner_spec.md` v2.1 (11장 B1~B5, 4장, 5.8, 6장, 10장).
**ROS가 없는 Windows에서 작성했다. rclpy 코드는 한 번도 실행하지 못했다.** 검증 상태는 맨 아래 "Windows에서 못 한 검증"에 있다.

## 1. 구현 목록

| 경로 | 내용 | Windows 검증 |
| --- | --- | --- |
| `src/ash_e_msgs/` | ament_cmake. msg 5종: `SmokerDetection`, `SmokerDetectionArray`, `TargetCandidate`, `TargetStatus`, `TargetFeedback` (3장 표 그대로, 상수는 core IntEnum과 같은 값). 소유자는 perception-dev | pytest가 .msg를 파싱해 core dataclass와 필드 이름·순서·타입·상수값 대조 |
| `src/ash_e_core/ash_e_core/depth_align.py` (신규) | `DepthExtrinsics`, `DepthCalibration`, `load_extrinsics/save_extrinsics`(5.8 yaml 형식), `DepthAligner`(z-버퍼, decimate, 빈칸 채움, `depth_pixel_offset_uv`), `rotation_to_quaternion` | `src/ash_e_core/test/test_depth_align.py` 13개 (항등, 평행이동 6.25 px, z-버퍼 순서 무관, 0/NaN 무시, 빈칸, 크기, 결정론, yaml 왕복) |
| `src/ash_e_core/package.xml`, `resource/ash_e_core`, `setup.py`(data_files 6줄) | 오케스트레이터 요청: colcon이 core도 빌드하도록 패키징만 추가. 코드 변경 없음. pip install -e와도 호환 | pytest 통과 |
| `src/ash_e_perception/ash_e_perception/perception_node.py` | 노드 `ash_e_perception`. 아래 2절 | 미실행(py_compile만) |
| `.../convert.py` | core `Detection/DetectionArray` <-> msg 변환. rclpy 무관 순수 함수(메시지 클래스를 인자로 받음). `target_status_from_msg`(dump 도구용) 포함. TargetStatus의 core->msg는 priority 쪽 소유 | .msg에서 자동 생성한 가짜 클래스로 왕복 테스트 |
| `.../inputs.py` | 뎁스 단위 변환(16UC1 mm / 32FC1 m -> float32 m), CameraInfo->`CameraIntrinsics`(크기 다르면 K 비례 보정, K=0이면 무시), hfov 환산, 경로 탐색, cv_bridge 없는 Image 디코더(도구용) | pytest |
| `.../sync.py` | `FrameMatcher`: 컬러 기준 최근접 뎁스 매칭(slop), 최신 프레임만 처리, 파트너가 `sync_wait_s` 안에 안 오면 뎁스 없이(PROXY) 처리 | pytest 4개 |
| `.../params.py` | 래퍼 전용 파라미터 기본값 한 곳. `/camera/` 문자열은 여기에만 있다 | pytest(grep) |
| `.../tools/video_to_bag.py` | mp4 -> rosbag2 (stamp = frame_idx/fps, frame 0 -> 0.0 s, CameraInfo = hfov 핀홀). 토픽 이름은 필수 인자 | 스탬프·CameraInfo 순수 부분만 |
| `.../tools/dump_jsonl.py` | `/ash_e/detections`(+`/ash_e/target`)를 `serialize.frame_to_jsonl`로 JSONL 기록. 같은 stamp끼리 짝짓기(`JsonlPairer`) | 짝짓기 로직만 |
| `.../tools/calib_astra_extrinsics.py` | `capture`(ROS, Enter로 컬러/IR 쌍 저장) + `calibrate`(체커보드 -> 내부/외부 파라미터 -> `astra_pro_extrinsics.yaml`, rms 0.5 px 판정) | 합성 보드 투영으로 R,t 복원 검증, 렌더 보드 코너 검출 |
| `.../tools/depth_check.py` | 10.5 도구. `--dir`(PNG) 또는 `--bag`. core를 PROXY/정렬뎁스로 두 번 돌려 비교표(비율, 평균·표준편차, 줄자 오차, 유효 비율, stamp 차 중앙값·95%, 정렬 결정론) 출력 | 요약표, 최근접 매칭, 스텁 모델로 end-to-end |
| `config/perception.yaml` | `/**: ros__parameters:` 아래 core 키 전부(=`PerceptionConfig` 기본값과 동일) + 래퍼 키 일부. 카메라 관련 키는 넣지 않음 | pytest: 키 집합·값이 core와 같음 |
| `config/camera_astra_pro.yaml` | 토픽·정렬·sync 값. **전부 [추정], B0 후 갱신** | 키가 래퍼 키인지 pytest |
| `config/astra_pro_extrinsics.example.yaml` | 형식 예시(플레이스홀더). 실제 파일은 `astra_pro_extrinsics.yaml`로 보정 후 생성 | 형식은 core 로더 테스트로 검증 |
| `launch/perception.launch.py` | 4.2 파라미터를 launch 인자로 노출(빈 문자열 = yaml 유지), `camera_config`, `publish_static_tf`+`cam_x/y/z`(base_link -> 컬러 광학 프레임, H7 기본값 [현장 확인]) | py_compile만 |

priority-dev의 `ash_e_all.launch.py` 연동: 그쪽이 `perception_node`를 이름 없이 띄우고 `share/ash_e_perception/config/perception.yaml`을 읽으므로 perception.yaml은 **`/**:` 키**로 썼고, `setup.py`가 `config/*.yaml`과 `launch/*.py`를 share에 설치한다. 노드 기본 이름은 `ash_e_perception`.

## 2. perception_node 동작 요약

- 파라미터: core 키 전부(`PerceptionConfig` 필드 그대로) + 래퍼 키(4.2): `color_topic`, `color_info_topic`, `depth_topic`, `depth_info_topic`, `use_depth`, `depth_alignment`(software/hardware/none), `extrinsics_file`, `color_frame_id_override`, `sync_slop_s`, `input_qos`, `equivalence_mode`, `publish_debug_image`, `publish_extrinsics_tf`. 추가로 `detections_topic`, `debug_image_topic`, `depth_frame_id`, `sync_wait_s`(0.12), `info_wait_s`(5.0), `model_dir`, `log_period_s`, `depth_log_period_s`. 모두 dynamic typing이라 yaml에 `70`을 써도 float 키가 오류 나지 않는다.
- 입력: 컬러(+뎁스) 구독, QoS는 `input_qos`(기본 best_effort, keep_last 1). CameraInfo는 best_effort keep_last 1.
- 처리: `cv_bridge.imgmsg_to_cv2(bgr8)`, 뎁스는 passthrough 후 mm->m 변환. `software`면 `DepthAligner`(뎁스·컬러 내부 파라미터가 바뀔 때만 재생성), `hardware`면 컬러와 크기가 같을 때만 그대로 사용(아니면 경고 후 PROXY), `none`이면 뎁스 미구독.
- 내부 파라미터 우선순위(컬러): CameraInfo(크기 일치) > 보정 파일 color_K(크기 일치, 경고) > CameraInfo를 비례 보정(경고) > `info_wait_s`(5 s) 지난 뒤 `hfov_deg` 근사(경고). 대기 중에는 프레임을 조용히 건너뛴다. 뎁스는 depth CameraInfo > 보정 파일 depth_K.
- 보정 파일이 없거나 깨졌으면 경고 후 뎁스 없이(PROXY) 계속 동작. 모델 파일이 없어도 기동해 빈 배열(상태 NONE)을 발행한다(core 스텁).
- `frame_id` = `color_frame_id_override` > 컬러 헤더 > `frame_id` 파라미터. stamp는 컬러 이미지 헤더 stamp.
- `process_rate_hz`(8) 스로틀은 노드 시계 기준. `equivalence_mode:=true`면 reliable keep_last 100, `process_rate_hz=0`, `roi_every_n=1`로 모든 프레임 처리.
- 발행: `/ash_e/detections`(reliable, keep_last 5, 빈 배열도 발행), 옵션 디버그 이미지(구독자가 있을 때만 그림), 옵션 정적 TF(컬러 프레임 -> 뎁스 프레임, 보정 파일 R,t).
- 로그: `log_period_s`마다 Hz·추론 ms 평균/최대·정렬 ms·스킵/드롭·뎁스 파트너 없음 횟수, `depth_log_period_s`(10 s)마다 정렬 뎁스 유효 비율·DEPTH 거리 비율·컬러-뎁스 stamp 차 중앙값/95%.
- 프레임 처리 예외는 잡아서 로그하고 계속 돈다.

QA D1 수정(2026-11-18): `video_to_bag`는 이제 프레임마다 CameraInfo를 Image보다 먼저 기록한다. 노드는 `equivalence_mode`에서 CameraInfo를 기다리지 않고 바로 `hfov_deg` 근사 내부 파라미터로 처리해 프레임을 하나도 버리지 않는다(프로토타입도 hfov 근사라 같은 값). 일반 모드는 최대 `info_wait_s` 동안 대기하며 건너뛴 횟수를 주기 로그의 `waiting-for-info`에 센다.

설계서와 다른 점(의도적):
1. `message_filters.ApproximateTimeSynchronizer` 대신 자체 `FrameMatcher`. 표준 동기화기는 뎁스가 끊기거나 직사광으로 안 오면 영원히 안 나가고, 설계서 6.2의 "뎁스 무효 -> 프록시로 자동 전환"을 만족하지 못한다. 컬러 프레임을 뎁스 파트너 없이도 `sync_wait_s` 뒤에 처리한다.
2. `ash_e_core`를 colcon 패키지로도 빌드 가능하게 했다(오케스트레이터 지시). 코드는 그대로.

## 3. core 무수정 확인

- 기존 core `.py` 14개의 SHA-256은 작업 전후 동일(작업 전 목록과 `sha256sum -c`로 비교, 불일치 0). 신규 파일은 `depth_align.py` 하나.
- 변경된 core 폴더 파일: `src/ash_e_core/setup.py`(data_files 추가, 패키징만), 신규 `package.xml`, `resource/ash_e_core`.
- 필요했지만 고치지 않은 것: 없음. `distance.py`의 `depth_median_position`은 그대로 쓴다.
- core import 금지어 검사(`rclpy, rospy, sensor_msgs, cv_bridge, openni, ultralytics, win32, msvcrt`) pytest로 자동화함.

## 4. RPi5 설치 절차 (Ubuntu 24.04, ROS2 Jazzy) — 사용자 실행, 미검증

```bash
# 1) ROS2 Jazzy (공식 apt 설정 후)
sudo apt install ros-jazzy-ros-base ros-jazzy-cv-bridge ros-jazzy-tf2-ros ros-jazzy-rosbag2 \
     ros-jazzy-rosbag2-storage-default-plugins ros-jazzy-usb-cam ros-jazzy-v4l2-camera \
     python3-colcon-common-extensions python3-venv python3-opencv python3-yaml v4l-utils git
# 2) 작업 폴더 (저장소를 git clone 또는 scp로 복사: models/ 와 data/ 는 git에 없다)
mkdir -p ~/ash_e && cd ~/ash_e && git clone <저장소 URL> ws && cd ws
# 3) venv: 시스템 패키지를 보게 하고 numpy는 올리지 않는다 (cv_bridge가 시스템 numpy 1.26 기준)
source /opt/ros/jazzy/setup.bash
python3 -m venv --system-site-packages ~/ash_e/venv && source ~/ash_e/venv/bin/activate
pip install onnxruntime "numpy<2"          # aarch64 wheel. numpy 2.x가 깔리면 cv_bridge가 깨진다
pip install -e src/ash_e_core --no-deps    # --no-deps: pip용 opencv-python 대신 apt python3-opencv 사용
python -c "import ash_e_core.pipeline, ash_e_core.priority; print('core ok')"      # ROS 없이도 성공해야 함 (10.1)
# 4) 모델 파일 (Windows PC에서 복사, 아래 5절)
# 5) 빌드 (venv를 켠 채로: console_script 셔뱅이 venv python이 된다)
cd ~/ash_e/ws && colcon build --symlink-install --packages-select ash_e_msgs ash_e_core ash_e_perception ash_e_priority
source install/setup.bash
ros2 interface show ash_e_msgs/msg/TargetStatus           # 3.5절과 같은지 확인 (12.4)
```
새 터미널마다 `source /opt/ros/jazzy/setup.bash; source ~/ash_e/venv/bin/activate; source ~/ash_e/ws/install/setup.bash`.
(colcon이 ash_e_core를 설치하면 `pip install -e`와 중복될 수 있다. 하나만 쓰면 되고, 충돌하면 `pip uninstall ash_e_core`.)

## 5. 모델 파일 복사 (Windows PC -> RPi5)

`models/`는 git에 없고 이 PC에만 있다. 필요한 것은 `models/cig_roi_v6.onnx`(기본 담배 모델)와 `models/pose.onnx` 두 개다.
```powershell
# Windows PowerShell, 저장소 루트에서 (OpenSSH 클라이언트 기본 포함)
Get-FileHash models\pose.onnx, models\cig_roi_v6.onnx -Algorithm SHA256      # 원본 해시 기록
ssh <사용자>@<RPi5 주소> "mkdir -p ~/ash_e/models"
scp models\pose.onnx models\cig_roi_v6.onnx <사용자>@<RPi5 주소>:~/ash_e/models/
```
```bash
sha256sum ~/ash_e/models/*.onnx           # 위 해시와 같은지 비교 (대소문자 무시)
export ASH_E_MODEL_DIR=~/ash_e/models     # 노드가 상대 경로 models/xxx.onnx를 여기서 찾는다 (또는 launch model_dir:=...)
```
모델이 없으면 노드는 기동하되 경고를 내고 빈 결과만 발행한다. `pose.onnx`가 없을 때 프로토타입은 ultralytics로 내보내지만(`run_webcam.py`), RPi5에는 ultralytics를 깔지 않는다. 이 PC에서 만든 파일을 복사한다.

## 6. 실행법

```bash
# 인식 노드만 (드라이버는 따로)
ros2 launch ash_e_perception perception.launch.py \
    camera_config:=$(ros2 pkg prefix ash_e_perception)/share/ash_e_perception/config/camera_astra_pro.yaml \
    extrinsics_file:=$HOME/ash_e/astra_pro_extrinsics.yaml publish_debug_image:=true
# 컬러 전용(D4) 또는 웹캠 시험: 토픽 이름은 인자로 바꾼다 (12.4: ros2 node info로 구독 확인)
ros2 launch ash_e_perception perception.launch.py color_topic:=/image_raw color_info_topic:=/camera_info use_depth:=false
# 전체(priority-dev 소유): ros2 launch ash_e_priority ash_e_all.launch.py use_depth:=false color_topic:=/image_raw ...
ros2 topic echo /ash_e/detections --once ; ros2 topic hz /ash_e/detections
```
- 보정 파일 없이 `depth_alignment:=software`: 경고 후 PROXY로 동작한다(12.4 확인 항목).
- `extrinsics_file`의 상대 경로는 현재 폴더 -> 패키지 share 순으로 찾는다. 실제 파일은 절대 경로로 주는 것이 안전하다(보정 파일은 git에 없음).

### 동등성 검사 절차 (10.2, 프록시 모드)
```bash
# PC 또는 RPi5, 같은 백엔드·스레드 수. 프로토타입 쪽(Windows):
.venv\Scripts\python prototype\run_webcam.py --replay clip.mp4 --no-throttle --no-gui
# 주의: 현재 run_webcam.py에는 --log 옵션이 없다(설계서 10.2의 --log proto.jsonl). proto.jsonl은 core.serialize.frame_to_jsonl로
# 직접 쓰는 작은 스크립트가 필요하다. --replay/--video 의 stamp 정의도 확인할 것. 오케스트레이터·QA 확인 필요.
# ROS 쪽
ros2 run ash_e_perception video_to_bag clip.mp4 clip_bag --color-topic /image_raw --info-topic /camera_info --hfov-deg 70
ros2 launch ash_e_perception perception.launch.py use_sim_time:=true equivalence_mode:=true use_depth:=false \
    color_topic:=/image_raw color_info_topic:=/camera_info
ros2 launch ash_e_priority priority.launch.py use_sim_time:=true &          # target 비교가 필요할 때
ros2 run ash_e_perception dump_jsonl ros.jsonl --idle-exit-s 5 --ros-args -p use_sim_time:=true
ros2 bag play clip_bag -r 0.2 --clock
```
주의: `video_to_bag`의 frame_id 기본값은 `webcam_optical`(프로토타입과 같음). `run_webcam.py`의 `--video` 로그 stamp 정의(프레임 번호 시작값)를 비교 전에 한 번 확인할 것(여기서는 frame 0 -> 0.0 s). 비교 스크립트(10.2 표)는 QA 소관이다.

## 7. B0 카메라 드라이버 확보 절차 (RPi5 실물 필요, 사용자 실행, 전부 미검증)

시간 상자는 설계서 11장 그대로(D1 2일, D3 3일). 결과는 `_workspace/02b_camera_notes.md`와 `config/camera_astra_pro.yaml`에 기록한다.
1. **실물 확인**: `lsusb | grep -i -E "2bc5|orbbec"`(Astra Pro vs Pro Plus PID 확인), `v4l2-ctl --list-devices`, `v4l2-ctl -d /dev/videoN --list-formats-ext`(컬러 해상도·MJPEG 여부. 1280x720 가능한지가 핵심, 5.5절).
2. **D1 `ros2_astra_camera` 소스 빌드**(Jazzy·arm64 지원 표기 없음, 컴파일 오류 가능):
   ```bash
   sudo apt install libgflags-dev libgoogle-glog-dev libusb-1.0-0-dev libeigen3-dev nlohmann-json3-dev \
        ros-jazzy-image-transport ros-jazzy-image-publisher ros-jazzy-camera-info-manager \
        ros-jazzy-backward-ros ros-jazzy-image-geometry libuvc-dev
   cd ~/ash_e/ws/src && git clone https://github.com/orbbec/ros2_astra_camera.git
   cd ros2_astra_camera/astra_camera/scripts && sudo bash install.sh && sudo udevadm control --reload && sudo udevadm trigger
   cd ~/ash_e/ws && colcon build --event-handlers console_direct+ --cmake-args -DCMAKE_BUILD_TYPE=Release \
        --packages-select astra_camera_msgs astra_camera
   ls src/ros2_astra_camera/astra_camera/launch        # astra_pro 계열 런치 이름 확인 후 실행
   ros2 launch astra_camera <astra_pro 런치 파일> ; ros2 topic list
   ```
   (apt 패키지 이름은 Ubuntu 24.04에서 다를 수 있다. README의 의존성 목록을 우선한다.) 뎁스는 `16UC1`, 컬러는 `use_uvc_camera` 옵션을 확인.
3. **D1 실패 시 D3**: 뎁스는 Orbbec OpenNI2 SDK(arm64 Linux 배포본) + Python 바인딩으로 읽어 `/…/depth/image_raw`(16UC1 mm)와 CameraInfo를 발행하는 얇은 노드 `ash_e_camera`를 새로 만든다. 컬러는 `ros2 run usb_cam usb_cam_node_exe --ros-args -p video_device:=/dev/videoN -p image_width:=1280 -p image_height:=720 -p pixel_format:=mjpeg2rgb`(파라미터 이름은 설치된 버전 `ros2 param list`로 확인). 이 노드는 B0 결과가 나온 뒤에 만든다(아직 없음).
4. **D1·D3 모두 실패 시 D4**: 컬러 전용. `ros2 launch ash_e_perception perception.launch.py use_depth:=false color_topic:=/image_raw color_info_topic:=/camera_info`. 거리는 PROXY이고 정확도 저하를 보고서에 적는다.
5. 성공한 드라이버의 토픽·QoS·frame_id·인코딩을 `ros2 topic info -v <topic>`, `ros2 topic echo --once <info topic>`로 기록해 `camera_astra_pro.yaml`을 고친다. UVC 컬러의 `frame_id`가 이상하면 `color_frame_id_override`.
6. **외부 보정(5.8)**: 체커보드 9x6, 25 mm. IR 토픽 이름을 확인한 뒤
   ```bash
   ros2 run ash_e_perception calib_astra_extrinsics capture --out ~/ash_e/calib --color-topic <컬러> --ir-topic <IR 이미지>
   ros2 run ash_e_perception calib_astra_extrinsics calibrate ~/ash_e/calib --out ~/ash_e/astra_pro_extrinsics.yaml
   ```
   프로젝터를 가리거나 끄고 간접광에서 20쌍 이상(거리 0.6~2 m, 기울기 다양). rms_px <= 0.5가 합격. 이어서 `depth_check`로 10.5 검증. 사용 후 실제 hfov는 `inputs.hfov_from_intrinsics`(= 2·atan(W/2fx))로 구해 priority.yaml `hfov_deg`에 반영한다.

## 8. 알려진 한계 · 주의

1. **rclpy 노드·launch·rosbag 도구는 실행해 본 적이 없다.** 첫 실행에서 import 이름, rosbag2_py `TopicMetadata` 시그니처(둘 다 시도하게 해 둠), cv_bridge 인코딩 변환(UVC가 `yuv422_yuy2`를 낼 때) 등에서 수정이 필요할 수 있다.
2. **뎁스 정렬 비용**: 이 PC(Windows x86)에서 1280x720 컬러, decimate 2 기준 `align` 약 18 ms. RPi5에서는 2~3배(약 40~60 ms)일 수 있고 설계서 예산(5~15 ms)을 넘을 수 있다. 빈칸 채움(최소값 필터)이 비용의 큰 부분이다. 완화: `depth_align_decimate:=4`, 컬러를 640x480으로 낮추기, 그래도 안 되면 정렬을 몸통 ROI만 하도록 core를 바꾸는 방안(core 변경이므로 보고 후 결정).
3. **빈칸 채움 반경**: 설계서는 `fill_radius=decimate`였으나 컬러 해상도가 뎁스보다 크면 구멍 간격이 `decimate x 배율`이라 부족해 `ceil(decimate x 배율 x 0.75)`로 했다(1280x720 컬러+640x480 뎁스, decimate 2 -> 3 px). 경계에서 전경이 최대 이 반경만큼 번질 수 있다. 렌즈 왜곡은 무시한다(5.8).
4. CameraInfo 구독이 best_effort volatile이다(설계서 4.3). 드라이버가 CameraInfo를 **한 번만 transient_local로** 발행하면 받지 못하고 5 s 뒤 hfov 근사로 동작한다(경고가 뜬다). 그런 드라이버면 `camera_info_url` 방식으로 매 프레임 발행하게 하거나 이 부분을 고친다.
5. `depth_frame_id`가 비어 있으면 정적 TF는 첫 뎁스 헤더의 frame_id를 쓴다. 정적 TF는 RViz 확인용이다(좌표 계산은 보정 파일 R,t를 직접 사용).
6. `prototype/config/perception.yaml`은 저장소에 없다(프로토타입은 `PerceptionConfig` 기본값을 쓴다). 그래서 설계서 8장의 "두 yaml의 core 키 집합 비교"는 ROS yaml과 core 기본값을 비교하는 것으로 대신했다.
7. 설계서 10.4의 30분 연속 실행·USB 재연결 복구는 하지 못했다. 카메라 토픽이 끊기면 노드는 살아 있고 "NO FRAMES" 경고만 낸다(재구독 로직 없음, 드라이버가 같은 토픽으로 복구하면 자연히 재개).
8. 모델: v6는 P03 hold-out 불합격 수치를 알고 받아들인 예비 합격 모델이다. 단계 B 실기 재평가에서 다시 확인한다.
9. `ash_e_perception` 의존 중 `ash_e_core`와 `onnxruntime`은 ROS 패키지가 아니라 pip이다(rosdep이 설치하지 않음).

## 9. Windows에서 못 한 검증 (RPi5·ROS에서 해야 함)

- `colcon build` 경고 없이 성공 여부, msg 생성, `ros2 interface show` 비교 (12.4).
- 노드 기동, 모델 없이 빈 배열 발행, `ros2 node info`로 토픽 파라미터 반영 확인, 보정 파일 없는 software 모드의 PROXY 폴백.
- `launch/perception.launch.py` 실제 동작(인자 override 병합 순서, static_transform_publisher 인자).
- cv_bridge 변환, QoS 연결(best_effort/reliable 조합), CameraInfo 수신.
- 10.2 rosbag 동등성, 10.4 실기(처리율 >= 5 Hz, 지연 <= 300 ms, 30분), 10.5 뎁스 교체 검증, B0 드라이버 확보, 5.8 외부 보정과 실제 RMS.
- `video_to_bag`, `dump_jsonl`, `calib_astra_extrinsics capture`, `depth_check --bag`의 ROS 입출력부.
- RPi5에서의 `DepthAligner.align` 실측 시간.

## 10. Windows에서 한 검증 (`.venv\Scripts\python -m pytest`)

저장소 전체 217개 통과(작업 전 core+prototype 137개 + `test_depth_align.py` 13개 + 이 패키지 `src/ash_e_perception/test/` 39개 + priority-dev 테스트). 이 패키지 테스트는 msg<->core 대조, 변환 왕복, 입력 변환, 매처, 도구 순수 로직, 보정 복원, 하드코딩·금지 import grep, yaml 키 검사를 포함한다.
