---
name: windows-prototype
description: Windows PC와 일반 웹캠(뎁스 없음)으로 흡연자·담배 소지자 구분 정확도를 먼저 검증하는 프로토타입을 만들고, 검증 후 ROS2로 이식하는 방법. 윈도우 테스트, 웹캠 프로토타입, 인식 정확도 평가, ROS 이식·포팅 요청 시 사용한다.
---

# Windows 프로토타입 → ROS2 이식 가이드

## 왜 이 순서인가
인식 정확도(담배를 제대로 구분하는가)는 ROS와 무관한 문제다. Windows에서 빠르게 반복해 정확도를 확정하고, 그 뒤에 ROS 배선만 얹으면 디버깅 대상이 분리된다. 이식 때 로직을 다시 쓰지 않으려면 처음부터 구조를 맞춰야 한다.

## 구조 (이식의 핵심)
```
src/ash_e_core/            # ROS 의존 0. Windows/RPi5 공용
  detector.py              # 프레임 → 검출 결과 (사람, 담배, 상태)
  stabilizer.py            # N프레임 투표 안정화
  tracker.py               # 간단한 ID 트래커
  priority.py              # 점수·타깃 선택 (target-priority 스킬)
  types.py                 # dataclass: Detection, Target (ROS 메시지와 필드 1:1)
prototype/                 # Windows 전용
  run_webcam.py            # cv2.VideoCapture → core → 화면 오버레이
  eval_images.py           # 라벨된 이미지/영상 폴더로 정확도 측정
src/ash_e_perception/, src/ash_e_priority/   # 나중에 만드는 얇은 ROS 래퍼
```
`types.py`의 필드는 설계서의 ROS 메시지와 이름·단위를 맞춘다. 그래야 이식이 변환 코드 몇 줄로 끝난다.

## 웹캠에는 뎁스가 없다
거리는 대체 신호로 근사한다: 사람 박스 높이(픽셀)가 클수록 가깝다. 이 근사값을 `distance_proxy`로 두고 core는 `distance_m`을 받는 인터페이스를 유지한다. 프로토타입은 프록시를 미터로 환산해 넣고, ROS 단계에서 뎁스 중앙값으로 교체한다. 프록시 환산 상수는 정확하지 않으므로 우선순위 가중치를 이 값으로 최종 튜닝하지 않는다.

## 정확도 평가
- 데이터: 직접 촬영한 영상/이미지에 `smoking / holding / none` 라벨. 최소 시나리오: 흡연, 담배 쥠, 펜·막대 등 담배 유사물(오검출 확인), 손으로 입 가리기, 다수 인원, 거리 변화, 실내외 조명.
- 지표: 클래스별 precision/recall, 혼동행렬, 오검출 상위 사례 이미지, 프레임당 추론 시간.
- 안정화 파라미터(N, M)는 이 단계에서 정한다.
- 합격선은 사용자와 정한다. 합의 전에는 "통과"라고 선언하지 않는다.

## 모델 주의
- Windows에서 쓰는 모델은 RPi5에서도 돌아야 한다. ONNX로 내보낼 수 있는 경량 모델만 쓴다. PC에서만 돌아가는 무거운 모델로 정확도를 재면 이식 후 결과가 달라진다.
- 추론 시간은 PC 값과 RPi5 예상 값(보통 5~10배 느림)을 구분해 기록한다.

## 이식 절차 (정확도 합격 후)
1. `ash_e_core`를 수정 없이 RPi5로 복사해 import가 되는지 확인한다(ROS·Windows 전용 import가 섞였는지 점검).
2. ROS 래퍼를 만든다: 이미지/뎁스 구독 → core 호출 → 설계서 메시지 발행. 거리는 뎁스 중앙값으로 교체.
3. 동일 영상을 rosbag으로 재생해 Windows 프로토타입과 같은 결과가 나오는지 비교한다(동등성 검사).
4. 결과가 다르면 래퍼(색상 순서 BGR/RGB, 해상도, 타임스탬프)를 먼저 의심하고 core는 마지막에 의심한다.
