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

Claude Code 첫 교차 리뷰는 OAuth 만료 오류로 실패했다. 이후 브라우저 재인증, CLI Login successful, loggedIn=true, 짧은 실제 API 응답 OK로 인증 복구를 확인했다. 상대 REVIEW_STATUS.md에 기록했다. 읽기 전용 리뷰를 다시 실행했고 아래와 같이 결과를 검증·반영했다. Codex의 상대 코드 검토는 위에 기록한 대로 수행했다.

로봇 모델·포트·SDK 버전·보정·URDF/frame·base 방향/단위·현재 EE·관절/충돌/속도와 정지 수단을 확인한다. 현장 workspace를 설정하고 실제 backend 시작부를 추가한다. 실제 이동은 사용자 승인 후 저속으로 수행한다. 5001은 손목 앱이며 기존 8000/8001 배포 서버를 자동 변경하지 않는다.

## 후속 Codex 수정: arm 직후 같은 clock tick

모의 SDK로 `arm()` 직후 같은 monotonic tick에서 `step()`을 호출하면 dt=0이 되어 motion_validation_failed로 정지하는 문제를 재현했다. 신규 SDK 회귀 테스트가 수정 전 실패하는 것을 확인했다. `robot_bridge.py`는 이 경우 명령 전송을 건너뛰고 활성화를 유지한다. 다음 양의 dt에서 기존 속도/경로 검증을 수행하며 입력 watchdog은 계속 적용한다.

MockBackend와 기존 SDK 어댑터용 회귀 테스트 2개를 추가했다. 실제 TCP 통합 테스트 입력은 별도 카메라 주기를 나타내도록 40ms 간격을 둔다. 변경 후 unittest **50개 통과(1.340초)**, replay **120프레임·120명령·hold 1회·수동 재활성화 확인**. 모두 모의 검증이며 실기 연결은 실행하지 않았다.

## Claude 교차 리뷰 반영

실제 읽기 전용 Claude Code 리뷰는 정상 종료했고 도구 허가 거절은 없었다. [원문 리뷰](../claude-code/REVIEW_CODEX_2026-10-09.md)는 검토 당시 소스 줄 번호를 포함하며, 아래 표는 Codex의 판정이다. Claude는 테스트를 실행하지 않았다.

| 지적 | Codex 확인·조치 |
| --- | --- |
| 1. 전체 EE 자세와 임의 XY 이동의 양립 제약 | 기존 FK 자세 잔차 검사로 불가능한 후보를 이미 거부한다. SO-101 5 DOF 제약을 README에 구체화했다. 원래 사용자 계약인 전체 자세 유지를 yaw 자유화/접근축 유지로 바꾸지 않았다. 수직이 아닌 모든 경로가 불가능하다는 일반화나 특정 수직 각 gate는 실기·경로별 증거가 부족하여 채택하지 않았다. 실제 모델·URDF·보정과 경로 검증이 필요하다. |
| 2. arm 후 현재 목표로 접근 | 고정 목표를 따라가는 동작은 기존 test_command_rate_and_log에서도 확인된다. 화면 위치의 절대 XY 매핑에서 수동 arm은 이동 허용이다. 손이 멈춰 있어도 현재 목표와 EE가 다르면 접근한다는 동작을 README에 명시했다. 사용자 계약을 상대 매핑으로 바꾸거나 미검증 2cm 임계값을 추가하지 않았다. 실기 시작 전에 EE·목표 차이를 확인해야 한다. |
| 3. 거부 명령 로그 부족 | input_rejected·arm_rejected·command_rejected 이벤트를 추가했다. 후보 명령·관측·목표·dt와 원인을 남기며, 거부 이벤트에 전송 행동이 있었다고 주장하지 않는다. 기존 입력 거부/검증 실패 테스트를 보강하고 초기 EE 범위 및 신선도 arm 거부 테스트를 추가했다. |
| 4. 후속 폴링이 정지 원인을 덮어씀 | hold_failed와 손 미검출·camera_stopped가 후속 비활성/지연 폴링에 덮어써지는 실패를 회귀 테스트로 재현한 뒤 수정했다. 실제 입력 유효성은 계속 갱신하며 수동 활성화가 필요하다. |
| 5. SDK 카메라 설정 | config.cameras가 비어 있지 않으면 backend 생성 단계에서 거부하고 모의 SDK 회귀 테스트를 추가했다. 실제 로봇 연결 전에도 카메라 없는 config를 사용해야 한다. |
| 추가: replay의 assert | python -O에서 실제 제어 호출까지 제거되어 commands=0·holds=0으로도 성공처럼 출력되는 것을 재현했다. 호출과 검증을 명시적 require로 바꿨다. |

수정 전 회귀 실행에서 56개 중 실패 6개·오류 2개가 위 지적을 재현했다. 수정 후 Python 3.10.19에서 **56개 통과(1.328초)**. 일반 replay와 `python -O replay.py` 모두 **120프레임·120명령·hold 1회·수동 재활성화 필요**를 확인했다. 기존 서버 재시작 뒤 수동 재arm 테스트도 보강했다.

검사 스테이션의 hold 예외 무시와 이동 `_halt`/sequencer 중단 문제는 상대 HANDOFF에 남겼다. 실행 중인 검사 서버나 배포본을 수정하지 않았다. 실제 로봇 안전성·URDF 도달 가능성·충돌·모터 순간 속도/가속도·학습 데이터 동기화는 여전히 미검증이다.

## 2026-10-09 후속: 실제 Claude 노트북 변경 검토

Claude가 새로 push한 `f09b907`, `08cc710`을 가져와 [교차 검토 기록](REVIEW_CLAUDE_2026-10-09.md)을 작성했다. `08cc710` 기준 시스템 소스 91개가 로컬 배포본과 줄바꿈 외에 동일함을 확인했고, 중복 경로 정리와 상자 검출·테이프·집기 변경을 읽었다.

직접 재검증: 원본 센서 99개, 스테이션 104개 pytest 통과. 공유 저장소에서는 `--rootdir . --confcutdir . -o 'addopts='`로 LeRobot 상위 테스트 설정을 분리한다. 가상 깊이 두 상자는 서버 기본 축소 배수 2에서도 검출됐다.

Codex 수정: `claude-code/PAC2026_system/sensor/server.py`의 깊이 과반 집계에서 NaN이 유효 값을 지우는 기존 오류를 실제 모의 API로 재현했다. masked median으로 수정하고 `sensor/tests/test_server.py`에 4개 회귀 사례를 추가했다. 수정 전 해당 사례 1 fail/3 pass, 수정 후 전체 센서 **103 pass(43.47s)**. 실행 중 로컬 배포본과 카메라 설정에는 적용하지 않았다.

실기 전 남은 문제: 현재 흰 상자 접근점 집게 끝이 윗면보다 15mm 아래, 갈색 상자는 여유 0mm로 계획된다. IK만 통과한 상태이며 접근 경로·개구 폭·충돌 검증과 문서의 접근 높이 정합이 필요하다. 웹 abort는 단계 경계 중단이고 station stop의 hold 예외 무시가 남아 있다. 손목 bridge 연결과 실기 준비 완료로 보고하지 않는다. 상세 계산·근거·테스트 명령은 교차 검토 기록에 있다.
