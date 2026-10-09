# Codex 인계 — 2026-10-09

## 구현

`pac_minimal/`은 기존 hackathon `hack_qut.py`와 공동 저장소 SDK를 확인한 로컬 구현이다. 과거 클라우드 ZIP은 현재 PC에 없었고 기존 ZIP 패치를 적용하지 않았다.

손목 landmark 0 → 좌우 반전 화면의 제한된 XY 매핑, 고정 Z, 0.05m/s 목표 변화 제한, 수동 복구 정지, Flask 모니터/API를 제공한다. `robot_bridge.py`는 반복/오래된 프레임·단절·느린 IK 결과 취소와 hold를 처리한다. `so101_backend.py`는 기존 SDK/IK 호출, 단위·한계·잔차·현장 경로 검증과 상태/명령 timestamp 기록을 제공한다. 실제 로봇 CLI는 아직 없다.

## 검증과 환경

기존 로컬 검증: Python 3.10.19 독립 환경에서 unittest 48개, 120프레임 모의 재생, pip check 통과. 실제 웹캠 30프레임 처리와 Flask API 기본 비활성화 확인. 상세 수치와 한계는 구현 README에 있다.

업로드 전 새 `tiltis/codex/pac_minimal/` 위치에서 재실행: unittest **48개 통과**(2.442초), replay **120프레임·120명령·hold 1회**, 수동 재활성화 확인. 이 재검증은 카메라·직렬 장치를 사용하지 않았다.

```powershell
$pacPython = Join-Path $env:USERPROFILE '.venvs/pac2026-vision310/Scripts/python.exe'
# pac_minimal/에서 실행
& $pacPython -m unittest discover -s tests -v
& $pacPython replay.py
```

로그와 이미지·가상환경은 업로드에서 제외했다. LeRobot/placo 실기 환경, 실제 FK/IK, MuJoCo, 장시간 추적, 로봇 통신·이동·충돌·실제 속도 및 정지 지연은 미검증이다.

## 상대 구현 검토

Claude Code 폴더의 `station/robot.py`, `station/kinematics.py`, URDF와 의존성을 읽었다. SDK 연결과 URDF는 재사용 후보다. station IK의 rad/접근 방향 계약은 손목 full orientation 유지와 다르다. station hold 실패를 무시하는 처리와 SDK 반환 명령 미검사는 직접 재사용하지 않았다. 상대 [HANDOFF](../claude-code/HANDOFF.md)에 근거를 남겼다.

## 다음 연결부

Claude Code 첫 교차 리뷰는 OAuth 만료 오류로 실패했다. 이후 브라우저 재인증, CLI Login successful, loggedIn=true, 짧은 실제 API 응답 OK로 인증 복구를 확인했다. 상대 REVIEW_STATUS.md에 기록했다. 읽기 전용 리뷰를 다시 실행했고 결과를 검증·반영한다. Codex의 상대 코드 검토는 위에 기록한 대로 수행했다.

로봇 모델·포트·SDK 버전·보정·URDF/frame·base 방향/단위·현재 EE·관절/충돌/속도와 정지 수단을 확인한다. 현장 workspace를 설정하고 실제 backend 시작부를 추가한다. 실제 이동은 사용자 승인 후 저속으로 수행한다. 5001은 손목 앱이며 기존 8000/8001 배포 서버를 자동 변경하지 않는다.

## 후속 Codex 수정: arm 직후 같은 clock tick

모의 SDK로 `arm()` 직후 같은 monotonic tick에서 `step()`을 호출하면 dt=0이 되어 motion_validation_failed로 정지하는 문제를 재현했다. 신규 SDK 회귀 테스트가 수정 전 실패하는 것을 확인했다. `robot_bridge.py`는 이 경우 명령 전송을 건너뛰고 활성화를 유지한다. 다음 양의 dt에서 기존 속도/경로 검증을 수행하며 입력 watchdog은 계속 적용한다.

MockBackend와 기존 SDK 어댑터용 회귀 테스트 2개를 추가했다. 실제 TCP 통합 테스트 입력은 별도 카메라 주기를 나타내도록 40ms 간격을 둔다. 변경 후 unittest **50개 통과(1.340초)**, replay **120프레임·120명령·hold 1회·수동 재활성화 확인**. 모두 모의 검증이며 실기 연결은 실행하지 않았다.
