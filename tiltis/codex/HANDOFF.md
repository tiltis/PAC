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

Claude가 새로 push한 `f09b907`, `08cc710`과 검토 도중 추가된 `b6ec1a9`를 가져와 [교차 검토 기록](REVIEW_CLAUDE_2026-10-09.md)을 작성했다. `08cc710` 기준 시스템 소스 91개가 로컬 배포본과 줄바꿈 외에 동일함을 확인했고, 중복 경로 정리와 상자 검출·테이프·집기·3면 검사 변경을 읽었다. 원격에 동시 push가 있어 정상 merge로 양쪽 변경을 보존했다.

직접 재검증: 원본 센서 99개, 스테이션 104개 pytest 통과. 공유 저장소에서는 `--rootdir . --confcutdir . -o 'addopts='`로 LeRobot 상위 테스트 설정을 분리한다. 가상 깊이 두 상자는 서버 기본 축소 배수 2에서도 검출됐다.

Codex 수정: `claude-code/PAC2026_system/sensor/server.py`의 깊이 과반 집계에서 NaN이 유효 값을 지우는 기존 오류를 실제 모의 API로 재현했다. masked median으로 수정하고 `sensor/tests/test_server.py`에 4개 회귀 사례를 추가했다. 수정 전 해당 사례 1 fail/3 pass, 수정 후 전체 센서 **103 pass(43.47s)**. 실행 중 로컬 배포본과 카메라 설정에는 적용하지 않았다.

추가 C면 연결 수정: `b6ec1a9`의 3면 검사에서 FakeRig와 `rules_calib.py`/`calib.py` CLI가 C를 거부하는 실패 3개를 재현했다. `fake_rig.py`, 두 보정 CLI와 수동 촬영 도구 `capture_app.py`에 C면을 연결했다. C면 촬영 ID, 규칙 ROI→fit→누락 판정, 정합 CLI 저장/재검증 회귀 3개를 추가했다. 최종 센서 **106 pass(43.58s)**, 스테이션 **106 pass(54.26s)**. 실제 카메라 GUI·로봇 C면 자세는 이 검토에서 실행하지 않았다.

실기 전 남은 문제: 현재 흰 상자 접근점 집게 끝이 윗면보다 15mm 아래, 갈색 상자는 여유 0mm로 계획된다. IK만 통과한 상태이며 접근 경로·개구 폭·충돌 검증과 문서의 접근 높이 정합이 필요하다. 웹 abort는 단계 경계 중단이고 station stop의 hold 예외 무시가 남아 있다. 손목 bridge 연결과 실기 준비 완료로 보고하지 않는다. 상세 계산·근거·테스트 명령은 교차 검토 기록에 있다.

## 2026-10-09 후속: 파랑·빨강 영역 분류

사용자가 정상 포장은 파랑, 불량 포장은 빨강 영역으로 로봇팔이 옮기도록 요청했다. Claude의 기존 `sequencer.decide`와 `bin_ok`/`bin_human` 이동·그리퍼 해제 순서를 재사용했다. 새로운 로봇 제어기를 만들거나 기존 자세/DB 키를 바꾸지 않았다. 모든 설정 검사면이 정상이어야 파랑이며, 이상 의심·미판정·재촬영 후 측정 불가는 빨강(확인 필요 포함), 센서 오류·불완전 응답은 기존대로 중단한다.

변경: 상대 `station/sequencer.py`에 영역→기존 자세 매핑과 `/api/status`용 `zones`, `destination`, `robot_mode`를 추가했다. `web/index.html`은 파랑·빨강 안내, 목적지 색, 모의/실기 모드 표시를 제공한다. `teach.py`에 두 영역 티칭 설명을 추가하고 CONTRACT·station README·현장 순서·예시 자세 단위를 실제 `use_degrees=True` 코드와 맞췄다. `destination`은 런타임 상태이며 DB/CSV의 분류 키나 실측 위치를 대체하지 않는다.

검증: 기존 `station/tests/test_sequencer.py`에 3면 검사 후 정상·이상 의심·미판정·지속 측정 불가 각각의 목적지/그리퍼 해제/홈 복귀 확인 4개를 추가했고 모의 HTTP 통합 시험에서 새 메타데이터도 확인했다.

```powershell
# claude-code/PAC2026_system 에서
& 'C:/PAC2026_system/.venv-station/Scripts/python.exe' -m pytest station/tests -q --disable-warnings --rootdir . --confcutdir . -o 'addopts='
```

**110 passed, 4 warnings, 54.61s**. Node `vm.Script`로 브라우저 JS 구문, `JSON.parse`로 예시 자세 JSON 형식도 확인했다. 모두 모의 로봇 검증이며 센서 코드는 이번 분류 변경에서 수정하지 않았다. 실행 중 `C:/PAC2026_system` 카메라/스테이션 배포본 및 실제 `poses.json`은 교체하지 않았다. 별도 미리보기 서버 준비/실행 요청은 자동 도구 정책으로 차단되어 실행되지 않았으며 8002 화면을 열었다고 보고하지 않는다. 변경 UI는 소스로 제공하며 브라우저 렌더링은 미검증이다.

다음 작업: 현장 두 영역을 고정하고 `bin_ok`=파랑에서 내려놓는 자세, `bin_human`=빨강에서 내려놓는 자세로 티칭한다. 색으로 영역 좌표를 자동 검출하는 기능은 구현하지 않았다. 로봇 모델·연결·보정·현재 상태 확인, 기존 접근/중단 문제 해결, 두 경로의 도달성·충돌·실제 속도 검증과 사용자 실기 승인 후 저속 구동한다. 실제 분류 완료로 주장하지 않는다.

## 2026-10-09 후속: USB 로봇 연결 감지와 상태 조회 준비

사용자가 로봇을 연결했다고 알렸다. Windows 장치 열거에서 새 `USB-Enhanced-SERIAL CH343(COM8)`을 확인했다. 기존 COM7을 로봇 포트로 단정하지 않았다. 실제 보정 프로세스는 `lerobot-calibrate --robot.type=so101_follower --robot.port=COM8 --robot.id=so101_follower`로 실행 중이었다. 사용자에게 모델·기존 보정 ID를 질문했으며 팔 형상/현장 사양을 이 프로세스만으로 확정하지 않는다.

설치 환경은 `C:/PAC2026_system/.venv-station`: Python 3.12.3, LeRobot 0.6.1, feetech-servo-sdk 1.0.0, pyserial 3.5. 설치 SDK의 SOFollower 일반 connect는 보정/모터 configure를 수행하고 기본 disconnect는 토크를 끌 수 있다. 따라서 모터 설정 없이 상태 조회하는 `tools/robot_status.py`를 추가했다. 기존 SDK의 모터 정의와 하위 버스 handshake/read를 재사용하고 robot.connect/configure/calibrate 및 write/send_action을 호출하지 않는다. 버스를 닫을 때 `disable_torque=False`를 명시하고, 미보정 데이터는 raw tick으로만 표시한다. 카메라는 구성하지 않는다. SDK 0.6.1 이외 버전은 재검토 전 거부한다.

```powershell
# codex/tools 에서
& 'C:/PAC2026_system/.venv-station/Scripts/python.exe' -m unittest discover -s tests -v
& 'C:/PAC2026_system/.venv-station/Scripts/python.exe' robot_status.py --model so101 --port COM8 --id so101_follower --metadata-only
```

모의 **5개 unittest 통과(0.005s)**: 메타데이터만 조회, 보정된/미보정 상태 단위, handshake/읽기/누락/NaN 실패 시 토크 변경 없는 포트 정리, 기존 열린 버스 보존. 실제 설치 SDK로 `--metadata-only`도 성공했으며 **포트를 열지 않았다**. 일반 상태 조회·실제 관절/EE 관측·이동은 실행하지 않았다.

작업 도중 보정 파일 `~/.cache/huggingface/lerobot/calibration/robots/so_follower/so101_follower.json`이 15:16:13에 저장됐다. 0.6.1의 파일 디렉터리는 `so_follower`임에 주의한다. 저장 시점 base shoulder_pan 범위는 1959~2107(148tick)으로 작았으나 현장 허용 범위가 확인되지 않아 임의 임계값으로 보정 완료/실패를 확정하지 않았다. 재보정 프로세스가 새로 실행 중이므로 COM8에 중복 접속하지 않았고 프로세스를 종료하지 않았다. 당시 `C:/PAC2026_system/station/poses.json`은 없었다. 실제 보정 파일·로그·자세는 업로드하지 않는다.

다음: 사용자 모델 확인과 진행 중 보정 종료 후 최신 보정 범위를 다시 확인하고, 포트를 쓰는 프로그램이 없을 때 읽기 점검으로 모터 응답·보정 일치·실제 관절값을 확인한다. 모터 응답 확인만으로 두 분류 경로가 준비됐다고 주장하지 않는다. 파랑/빨강 티칭, 관절/접근/충돌/실제 속도/중단 문제 검증과 사용자 실기 승인이 남아 있다. 기존 검사 서버는 여전히 모의 로봇이며 배포본은 교체하지 않았다.

### 같은 작업 중 추가: 보정 종료 후 실제 버스 조회 성공

이후 COM8 보정 프로세스가 모두 종료된 것을 확인하고 15:22:50에 `robot_status.py --model so101 --port COM8 --id so101_follower`를 실행했다. **실제 모터 6개 handshake/read 성공, calibration_matches_motors=true, 6개 Torque_Enable=0**. 15:22:07에 새로 저장된 파일에서 shoulder_pan 범위는 2579tick으로 갱신됐다(위 148tick은 재보정 전 기록). 보정된 팔 관절 deg와 그리퍼 0~100 관측을 읽었고 종료 시 버스를 닫았다. 모터 목표·토크·보정·카메라 설정은 쓰지 않았다. 이 실제 조회는 위의 초기 미조회 단계 이후 결과이며, 모의 테스트를 실제 구동이라고 바꿔 적은 것이 아니다.

여전히 팔 형상/현장 frame·EE·관절 제한·분류 경로를 실측 검증한 것은 아니다. `motion_readiness=not_verified`를 유지하며 실제 이동은 하지 않았다. 분류 위치 파일도 없으므로 기존 station 실기 모드를 자동 시작하지 않는다. 파랑/빨강 및 집기/제시 자세 티칭과 기존 중단/접근 문제 검증이 다음 단계다.
