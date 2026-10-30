## 하네스: ASH-E (Autonomous Smoker-approaching Helper for Eco)

**목표:** Windows 일반 웹캠으로 흡연자·담배 소지자 인식 정확도를 먼저 검증한 뒤, RPi5(Ubuntu 24, ROS2 Jazzy)+뎁스카메라 ROS 노드로 이식하고, 다수일 때 우선순위로 접근 대상을 정하는 프로그램 개발

**호출 조건:** 흡연자 인식, 담배 검출, 타깃 우선순위, ASH-E ROS2 노드 개발·수정 요청 시 `ash-e-orchestrator` 스킬을 사용한다. 계획 단계는 opus, 나머지는 sonnet. 단순 질문에는 직접 답해도 된다.

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
| --- | --- | --- | --- |
| 2026-10-27 | Harness v2로 처음 구성 | 전체 | - |
| 2026-10-27 | Windows 웹캠 프로토타입(단계 A) → 사용자 합격 게이트 → ROS2 이식(단계 B) 흐름으로 변경. `windows-prototype` 스킬 추가, 구현·QA 에이전트에 단계 구분 반영 | 오케스트레이터, planner, perception-dev, priority-dev, qa | 정확도 검증을 ROS와 분리해 먼저 하려는 요구 |
