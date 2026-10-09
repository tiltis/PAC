# Claude Code 폴더 인계 — 2026-10-09

## 가져온 기존 구현

`0e515a7`의 `tiltis/PAC2026_system/`을 `PAC2026_system/`으로 이동했다. Git 비교에서 기존 **88개 시스템 파일 모두 R100**(내용 동일)로 확인했다. 실행 중인 배포본은 바꾸지 않았다. 이전 작성자를 이 폴더 이름으로 단정하지 않는다.

센서·스테이션 실행과 검증은 시스템 README와 SENSOR_ACCEPTANCE.md를 따른다. 이번 이동에서 센서/스테이션 테스트를 새로 실행했다고 주장하지 않는다.

## Codex가 확인한 재사용 경계

- `station/robot.py`: LeRobot SO101Follower, `use_degrees=True`, 관절 보간과 현재 관절 hold를 제공한다. `send_action()` 반환 목표를 확인하지 않고 `stop()`의 통신 예외를 무시하므로 손목 안전 계약에 그대로 연결할 수 없다. 수정 후보이며 이번 이동에서 변경하지 않았다.
- `station/kinematics.py`: numpy 기반 FK/IK, 입력 rad, LeRobot 변환 deg. 접근 방향·yaw 제약과 손목의 전체 EE 자세 유지 계약이 다르다. 교체 전에 잔차와 단위 테스트가 필요하다.
- `station/assets/so101_new_calib.urdf`가 있다. 실기 모델·frame·보정값과 일치하는지는 아직 확인되지 않았다.
- `station/requirements-robot.txt`의 LeRobot 버전과 저장소 본체 API가 다를 수 있다. 실제 환경 버전을 확인한다.

## 다음 작업

Claude Code 2.1.263 첫 리뷰는 OAuth 인증 만료로 실패했다. 이후 재인증과 실제 API 응답을 확인했고, 읽기 전용 교차 리뷰를 다시 실행했다. [실행 기록](REVIEW_STATUS.md)에 인증 복구를 남겼다. 완료된 리뷰 결과와 Codex 반영 근거를 기록한다.

Codex의 [HANDOFF](../codex/HANDOFF.md), `pac_minimal/robot_bridge.py`, `so101_backend.py`, 관련 테스트를 검토한다. 손목과 검사 흐름은 별도로 실행하고, 적합한 SDK·URDF·정지 개선만 근거를 기록하며 재사용한다. 실제 연결은 사용자 모델·포트 정보와 현장 검증 후 진행한다.
