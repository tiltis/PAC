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

## 2026-10-09 후속: 위치가 바뀌는 상자의 깊이 기반 집기 연결

사용자가 깊이 카메라로 상자 위치를 찾아 집도록 요청했다. 상대의 기존 `locate.py`, `grasp.VisionPicker`, hand-eye/FK/IK, sequencer를 검토·재사용했다. 별도 SDK나 로봇 제어기를 만들지 않았다. Codex 검증 코드는 [vision_pick/README.md](vision_pick/README.md)에 분리했다. 원격 `764c41e`, `03dba0d`를 먼저 확인하고 fast-forward로 반영했다.

상대 구현 수정 근거: 기본 탐색은 화면 아래쪽으로 제한되고 명시적인 ROI도 x 범위를 벗어나는 물체를 포함하던 마스크였다. 책상 평면 맞춤 영역과 탐색 영역을 분리하고 기본 탐색은 전체 깊이 화면으로, 명시적인 pick ROI는 엄격하게 제한했다. 같은/다른 상자 후보가 여러 개면 거부한다. 카메라가 수직으로 내려볼 때 평면 basis의 0 나눗셈도 수정했다. 센서 결과에 중앙값 영상의 첫 프레임 수신 시각 `captured_at_s`와 마지막 `last_frame_at_s`를 추가했다. 응답 완료 `time`과 구별한다.

`codex/vision_pick/guard.py`는 기존 picker를 확장한다. 서로 다른 관측 3회, 이동 5mm·회전 10° 이내, 영상 나이 2초 이내, frame/단위/유한값, 이미지 가장자리 8px 여유, hand-eye 강체 변환·점 수·RMS를 검사한다. 물리적 workspace에 가상 좌표를 기본값으로 넣지 않았다. `grasp_config.json`의 실측 workspace(`base_link`, m, min/max)가 있어야 하고 접근/집기/들기 IK 해의 FK 도구 점이 모두 안에 있어야 한다. 접근 후 다시 관측해 상자가 바뀌면 하강/닫기 전에 기존 error/stop 흐름으로 전환한다. 이 체크는 링크 충돌/실제 속도/hold 성공 검증이 아니다.

`station_app.py`가 기존 웹 앱과 sequencer에 guard를 연결한다. 공유 `run_station.ps1 -PickMode vision`도 이 entry를 선택한다. `-VisionPreview` 또는 `preview.py`는 읽기 전용 계획 확인을 제공한다. `PICK_DRY_RUN=1`은 실기에서 실제 접근/홈 이동이므로 읽기 전용과 다르다. 손잡이 없는 상자의 hand-eye 티칭은 윗면을 참조하고 집기 계산은 20~35mm 아래를 참조하던 불일치가 있었으므로 공통 `camera_grasp_point`를 사용하도록 최소 수정했다. 배포본의 guided 티칭 변경은 덮어쓰지 않았다.

실행 결과:

```powershell
# claude-code/PAC2026_system 에서
& 'C:/PAC2026_system/.venv-sensor/Scripts/python.exe' -m pytest sensor/tests -q --disable-warnings --rootdir . --confcutdir . -o 'addopts='
& 'C:/PAC2026_system/.venv-station/Scripts/python.exe' -m pytest station/tests -q --disable-warnings --rootdir . --confcutdir . -o 'addopts='
# codex/vision_pick 에서
& 'C:/PAC2026_system/.venv-station/Scripts/python.exe' -m pytest tests -q --disable-warnings --rootdir . --confcutdir . -o 'addopts='
& 'C:/PAC2026_system/.venv-station/Scripts/python.exe' preview.py --system-dir C:/PAC2026_system
```

센서 **117 passed, 9 warnings (56.71s)**, 스테이션 **110 passed, 4 warnings (66.67s)**, Codex guard **38 passed, 1 warning (3.16s)**. 센서 회귀는 여러 실제 픽셀 위치·수평 회전(-30/30/55°)의 가상 깊이 영상, 엄격한 ROI, 두 종류/같은 종류 다중 상자, 수직 하향 카메라를 포함한다. guard는 신선도·연결 실패·관측 반복/회전/이동·보정/실측 workspace 거부, IK 계산 중 입력 노화, 접근 후 이동 시 하강/닫기 전 중단, 같은 앱에 연결, 미리보기 API의 모터 명령 부재를 확인했다. PowerShell parser와 `git diff --check`도 통과했다.

실제 카메라 API의 읽기 전용 미리보기는 `found=false/no_candidate_box_matched`, `motion_enabled=false`였다. 17:06:59의 실제 깊이 프레임을 로컬 데이터 폴더에 저장해 새 검출기로 오프라인 재검사했을 때 화면 위쪽 후보가 나왔으나 bbox `[76,4,242,124]`로 가장자리 검사에 걸리는 위치다. 이 후보를 실제 상자로 확정하거나 로봇 좌표로 승인하지 않았다. 해당 bbox 거부 회귀를 추가했다. 영상/깊이 파일·실측 보정·poses.json은 Git에 넣지 않았다.

실기 미완료: 현재 `C:/PAC2026_system/station/calib/handeye.json` 없음, 실측 workspace 없음, 관절 부호/URDF/도구 기준점 FK 확인·링크 충돌/실제 속도/통신 정지·분류 위치 티칭 미완료. 기존 planner는 위에서 집기이며 현재 guided 옆 집기와 동일하지 않다. 상태–행동 학습 데이터나 실제 집기 완료로 주장하지 않는다. 실행 중 티칭/8000/8001 서버, COM8, 실측 자세/보정 파일을 수정·종료하지 않았다. 다음은 상대의 배포본 guided 변경을 보존하여 소스와 통합하고, 티칭 종료 뒤 물리적 좌표 보정/범위 검증을 수행하는 것이다. 사용자의 실기 승인 전 로봇 모드를 켜지 않는다.
## 2026-10-09 후속: 작업마다 새 깊이 좌표로 옆 집기

사용자는 상자 위치 변경마다 티칭하지 않고 깊이로 인식해 로봇이 이동할 것을 요청했다. Claude의 실행 폴더 `C:/PAC2026_system/station`에 아직 Git에 없는 옆 집기/상자별 자세/guided/replay 변경이 있어 `03dba0d` 기반 3-way 비교로 기존 `a0176e0` 검증 코드를 보존해 통합했다. 원본 비교 스냅샷은 로컬 `C:/PAC2026_system/Log/codex_side_merge_normalized_20261009_173050`에만 보관했다. 상대 실행 파일과 실측 데이터를 덮어쓰지 않았다.

변경: 공유 `grasp.py`는 기존 옆 집기 IK를 재사용하며 옆 집기 보정/계획도 같은 `camera_grasp_point`를 쓴다. `teach.py`에 guided 15단계와 상자별 replay를 통합하고 설치 시 한 번 보정임을 안내한다. `sequencer.py`가 깊이 높이로 상자 종류를 선택해 기존 그리퍼 기준을 재사용한다. 비전 집기 직후 무조건 저장된 `lift`로 이동하던 부분을 제거했고, 재촬영도 그 작업에서 계산한 들기 목표를 재사용한다. `robot.py`/`app.py`의 상자별 자세/API를 보존했다. 시편 설정은 side이고 `workspace=null`이라 실측 없이 승인되지 않는다. 37~47cm 모델 반경, 5cm 접근, 10cm 들기는 실기 검증값이 아니다. 대각선 105mm이면 임의 회전 갈색 상자까지 정렬된다는 기존 설명은 근거가 부족해 제거했다(80mm 정사각형 대각선 약 113mm).

Codex `guard.py`의 정적 준비 검사는 보정/workspace가 없을 때 홈/그리퍼 명령 전 거부한다. 불량 옆 집기 좌표는 IK 전에 거부한다. `station_app.py`에 읽기 전용 `/api/pick/readiness`를 추가하고 공유 status에 `pick_mode`를 노출했다. 이 모드는 실제 실행 entry에서 선택된 값을 보고하며, taught 모드를 자동 비전으로 오인하지 않는다.

통합 테스트에서 상대 테스트가 참조하는 `import_grasp_profile.py`가 공유 소스에 없는 `ModuleNotFoundError`를 재현했다(112 pass/1 fail). 기존 상대 import 도구도 연결하고, 양쪽 보정 해시가 모두 없는 경우를 같은 보정으로 통과시키던 조건을 수정했다. 실제 프로필/자세/보정 파일은 복사하거나 Git에 넣지 않았다.

재검증:

```powershell
# claude-code/PAC2026_system 에서
& 'C:/PAC2026_system/.venv-station/Scripts/python.exe' -m pytest station/tests -q --disable-warnings --rootdir . --confcutdir . -o 'addopts='
# codex/vision_pick 에서
& 'C:/PAC2026_system/.venv-station/Scripts/python.exe' -m pytest tests -q --disable-warnings --rootdir . --confcutdir . -o 'addopts='
```

최종 **스테이션 113 passed, 4 warnings (109.13s)**, **Codex 44 passed, 1 warning (10.04s)**. 이번 변경에 센서 코드는 없으며 직전 센서 117 pass는 재실행 결과와 구별한다. Python AST, JSON, `git diff --check`도 확인했다. 새 테스트는 같은 가상 hand-eye를 재사용해 흰/갈색 각각 (0.40,-0.025), (0.42,0), (0.44,0.025)m에서 3회 연속 자동 집기·3면 검사·파랑 분류를 실행한다. 모의 로봇에는 저장된 pick/lift 자세가 없으며 새 목표에 대한 실제 FK를 3mm 이내로 확인했다. 재촬영의 계산 lift 재사용, 접근 후 이동 거부, 미보정 설치의 이동 전 거부도 통과했다. 가상 workspace를 실기 파일에 저장하지 않았다.

현장 상태: 17:17 저장 `poses.json`은 집기 두 종류·3면·파랑/빨강/그리퍼를 포함하고 FK 검사 없는 상태다. 이번 통합 중 Claude의 COM8 replay가 끝나고 `teach.py --handeye --points 6`로 바뀌어 좌표 보정을 수행 중임을 프로세스로 확인했다. 마지막 확인에서 handeye.json과 실측 workspace는 아직 없었다. 이후 Claude가 배포 teach.py에 점 검증 경고를 추가한 것도 별도 검토했다. 특정 로봇 z=-20~70mm를 모든 설치에 공통 적용하는 부분은 공유에 추가하지 않았으며 해당 실행 파일은 보존했다. 상자 높이 불일치/손 가림과 FK 도구 점을 확인해 보정 점을 수집해야 한다.

다음: 설치 보정 완료 및 FK/관절·도구점/실측 범위·개구 폭/경로 충돌·실제 속도/통신 stop 확인 후 사용자 실기 승인. 그 뒤 기존 센서의 captured_at_s 버전과 전체 팀 폴더를 배포하고 `-PickMode vision` wrapper로 실행하여 상태 모드를 확인한다. 현재 8000은 기존 app entry이며 이 커밋으로 재시작하거나 교체하지 않았다. 작업별 집기 티칭을 반복할 필요는 없지만, 실제 자동 집기 완료·실측 학습 데이터 확보라고 주장하지 않는다.

## 2026-10-09 RGB/SAM 1단계와 Colab T4 실제 검증 (Codex)

사용자가 RGB 인식부터 단계별 진행 및 Colab GPU 실행을 요청했다. `rgb_box/`에 Grounding DINO tiny와 SlimSAM 검출/분리, 읽기 전용 센서 RGB 패널/사진 CLI, 명시적 CPU/CUDA 선택, 검증 코드와 출력 없는 Colab 노트북을 추가했다. 모델 revision 고정, 로봇/직렬 포트 호출 없음, `motion_enabled=false`/`robot_ready=false`. `make_colab.py`로 공유 모듈을 노트북에 포함한다. 기존 Claude LeRobot 정책 학습 노트북은 보존했다.

실제 로컬 RGB 세 장에서 상자가 오른쪽→왼쪽으로 옮겨졌어도 마스크 생성. CPU DINO+SAM 16.5~18.6초/장. Colab 팀 계정의 Tesla T4에서 같은 갈색 3장과 흰 상자 1장 모두 검출/분리. GPU DINO/SAM 합계 386.6/405.2/393.9/445.9ms (워밍업 제외, CUDA 동기화; 통신 지연 제외). torch 2.11.0+cu130, Transformers 5.13.0. 실제 결과 PNG/마스크/JSON/실행 노트북/화면 증거는 `C:/Users/tilti/PAC2026_data/rgb_box/colab_T4_20261009`에 내려받고 확인했다. 영상/출력/가중치는 Git에 넣지 않음. 다운로드 후 해당 GPU 런타임 해제. 사진 검증이며 실시간 카메라 적용이나 정책 학습/로봇 구동 완료가 아니다. 현재 SAM은 상자 전체 마스크. 사용자 후속 요구는 윗면 분리→3D 방향→집게 각도 정렬이다.

Colab 실행 결과: https://colab.research.google.com/drive/1R6e5vQvYaSt0QAA57ZZf3plskmLyPpJI (기존 계정 권한 유지).

상대 코드 재검토: 새 `c2aec11` 런타임 스냅샷이 이전 위치 재확인/preflight/계산된 lift/센서 capture timestamp·strict ROI·여러 상자 거부 연결을 덮어썼다. guard 테스트 **8 fail / 36 pass**로 재현했고 이 연결을 복구했다. 새 빈 집기 재시도·top_face 후보 모드는 보존하고 재시도 후에도 닫기 직전 위치를 재확인한다. top_face 후보 모드에도 table ROI 및 여러 후보 거부를 적용했다. 보정 해시가 양쪽 모두 없을 때 import를 거부하는 처리/회귀도 복구했다. 실제 C:/PAC2026_system 배포본 교체·서버 재시작·로봇 호출 없음.

최종 검증: rgb_box 16 pass (0.85s), vision_pick 45 pass / 1 warning (10.74s), station 전체 115 pass / 4 warnings (93.50s), sensor 전체 119 pass / 9 warnings (80.52s). 이후 새 top_face 모드의 2상자/모델 ambiguity 테스트 2개를 추가하여 sensor `tests/test_pick_area.py` **13 pass (10.98s)**, 보정 해시 회귀 추가 후 station `tests/test_grasp_check.py` **8 pass / 1 warning (2.66s)**. 공통 명령: 각 폴더에서 해당 .venv의 `python -m pytest tests -q --disable-warnings --rootdir . --confcutdir . -o addopts=` (부분 재검증은 위 파일 지정). 노트북 JSON/모든 코드 셀 AST 및 git diff --check 확인.

보정 감사: 17:51 handeye는 n4/RMS33.87/max54.92mm, 카메라 0.1mm 차이에 로봇 82.7mm 차이인 대응쌍이 있었다. 18:20:56 새 결과도 n5/RMS15.91/max24.76mm로 guard 10mm 기준 초과. 해당 시점 기록이며 이후 보정 변경은 다시 확인해야 한다. 카메라 측정 후 상자를 옮기는 대응쌍을 쓰지 말고 실제 TCP/FK/단위와 동일 물리점을 검증해야 한다. RGB와 Gemini2 깊이는 서로 다른 카메라여서 동일 픽셀 대입 금지. 실측 workspace/좌표 변환·실제 관절/개구/경로·stop과 사용자 승인 전 실제 자동 집기 금지.

## 2026-10-09 SAM 윗면·3D 축·집게 정렬 후속 (Codex)

사용자 요구: SAM으로 윗면을 분리하고 그 변 방향에 집게를 맞춰 접근/집기. `rgb_box/top_face.py`는 자동 point/negative prompts와 사각형/영상 각도 후보를 추가했다. 같은 실제 4장을 19:11 Colab T4에서 공유 코드로 실행하고 2/2/2/3개의 중복 제거 면 후보와 마스크를 내려받았다. 추가 면 단계 시간 321.5/325.9/331.9/592.2ms. 갈색/흰 상자 윗면 후보뿐 아니라 테이프/앞면도 나와 RGB 점수만으로 윗면을 확정하지 않는다. `top_confirmed=false`, 영상 각도와 robot yaw 구별. 출력 `C:/Users/tilti/PAC2026_data/rgb_box/sam_faces_T4_20261009`에는 PNG/JSON/실행 노트북/Colab 화면 증거가 있다. 결과 보관 후 임시 GPU 런타임 종료. Git에는 코드와 출력 없는 재실행 노트북만 넣었다.

`rgb_box/sam_depth.py`: 검증된 rectified RGB–depth 정합 R/t_mm로 상자 전체 SAM 마스크를 네이티브 깊이에 투영, RGB 시점 가림 z-buffer 제외, 공유 depth locator/RANSAC 재사용하여 윗면 중심·높이·두 3D 축 생성. 공유 `sensor/locate.py`에 선택적 object_mask 연결만 추가해 테이블 평면 데이터는 유지한다. 윗면 평면/법선/실측 치수/가시 범위 확인. 미보정·미동기화·카메라/해상도/단위 변경·부분 테이프·복수 상자는 거부한다. `SamDepthSensorAdapter`는 기존 검사 API를 위임하고 기존 GuardedVisionPicker에 들어가는 locate 계약을 제공한다. 실제 paired_frame_reader와 현장 정합이 없으므로 실행 중인 8000에 연결하지 않았다. `estimate_top.py`는 NPZ+metadata+registration 오프라인 검증 CLI다. 가상 bundle 결과는 `C:/Users/tilti/PAC2026_data/rgb_box/synthetic_top_bundle`; 실측으로 사용 금지.

재현한 공유 오류: `station/grasp.py` plan_side가 상자 두 축을 사용하지 않고 로봇→상자 중심 방향만으로 접근·yaw를 결정했다. side_box_alignment로 카메라 3D 축을 hand-eye 회전해 가까운 면에 정렬한 접근 축과 직교하는 집게 축을 만들고 3개 IK에 동일하게 전달한다. PCA 180° 부호를 고정하고 부적절한/평면 밖 축을 거부한다. SO101의 임의 옆집기 자세가 도달 불가이면 거부하며 radial fallback 없음. 이전 station 1개/guard 2개 테스트는 고정 상자 각도인데 위치만 달라도 항상 성공한다는 잘못된 전제를 갖고 있어 실패했다. 도달 가능한 모의 장면은 상자 변도 해당 radial 방향으로 돌려 테스트하고, 임의 회전/방향 누락/잘못된 축/도달 불가를 별도로 검증한다. 가상 조건을 현장 파일에 저장하지 않음.

검증: RGB/면/깊이 **43 pass (최종 5.26s)**, Codex guard **58 pass / 1 warning (8.32s)**, sensor 전체 **121 pass / 9 warnings (75.81s)**, station 전체 **115 pass / 4 warnings (81.43s)**. 마지막 planner 축 검사를 추가한 뒤 station `tests/test_vision_pick.py` **16 pass / 1 warning (15.51s)**. 가상 위치/회전 변화 → SAM/depth 어댑터 → 실제 공유 guard → IK/FK 계획 통합도 pass. CLI JSON/mask 저장, 노트북 JSON/모든 셀 AST/출력 없음, 실행 GPU 노트북 보관, diff whitespace 확인. 실제 윗면 3D/실기 집기 완료가 아니다. 상대 최신 9ae6d67 HF 업로드 도구/인계는 fast-forward로 보존했으며 실행하지 않았다.

현장 보정 재확인: C:/PAC2026_system/station/calib/handeye.json은 created 18:28:38, n5/RMS8.62/max11.7mm로 갱신되어 이전 15.91mm 기록보다 개선됐다. 파일과 보정/배포/실기 동작은 수정하지 않았다. 잔차 통과가 실제 TCP/FK와 집기 정확도를 보장하지 않는다. Arducam–Gemini2 정합 보정 파일은 확인되지 않았다. 다음은 두 카메라 rectified frame/검증한 공통 촬영 시각과 실측 R/t·내부 파라미터·상자 크기 확보, 실제 3D 윗면 중심/두 축의 정적 화면 검증, 도달성·개구 폭·경로/속도/stop·workspace 확인 후 사용자 승인에 따른 저속 실기다. 카메라 설치 보정은 위치가 달라진 상자를 매번 다시 티칭하는 작업과 다르다.
