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

## 2026-10-09 Claude 최신 실행 코드 참고 검토

사용자가 Claude Code의 코드에도 접근해 참고할 것을 요청했다. 공유 소스와 `C:/PAC2026_system/` 최신 실행본을 직접 비교했다. 검토 당시 HEAD/origin은 3c4cef4로 동일하지만 실행본의 robot/grasp/teach/sequencer 및 sensor locate/server에는 미공유 변경이 있다. 상세 근거와 재사용 조건은 [Claude 폴더의 읽기 전용 검토](../claude-code/reviews/CODEX_RUNTIME_REVIEW_20261009.md)에 기록했다.

기존 SO101 SDK·FK/IK·깊이 수집은 재사용한다. 실행본의 접근 높이·턱 중심 오프셋·가까운 IK 해 선택·실제 관절과 FK/계획 TCP 오차 기록은 유용한 통합 후보다. 실행본은 여전히 radial yaw이며, 공유 상자 3D 축 정렬/preflight/접근 후 재확인/계산 lift 연결이 없으므로 전체 파일로 덮어쓰지 않는다. 관절 안정화 2→5° 완화와 절대 Z 옵션은 실측 검증 없이 적용하지 않는다. 기존 registration은 LWIR↔RGB homography이며 RGB↔depth 3D 정합으로 쓰지 않는다.

이번 변경은 검토 문서와 이 인계뿐이다. Git fetch/status, 해시/정규화 차이·관련 함수 읽기를 수행했고 기능/자동 테스트는 새로 실행하지 않았다. 배포 파일·서버·카메라·COM8·실측 보정/자세에 쓰기나 로봇 명령 없음. 다음은 유용한 후보를 상자 방향/기존 guard를 유지하는 회귀와 함께 통합하고 RGB-depth/TCP/실측 경로·속도·stop을 확인하는 것이다. 실행본의 dry_run은 물리 이동이 있으므로 이번 검토에서 호출하지 않았다.

## 2026-10-09 Claude 새 푸시 3dffdae 확인

사용자 요청으로 origin/main을 fetch하고 7c5a302→3dffdae fast-forward했다. 35파일 변경에 현장 턱 오프셋/접근/IK·자동 hand-eye·면별 테이프 count-golden과 인계가 포함됐다. 현장 보정/자세 Git 제외를 보존했다. 인계의 전 과정 2회 완주를 읽었고, 실행 서버 GET status/runs에서도 hardware mode 및 run31/32 done/suspect/placed_bin=human/error=null을 확인했다. 새 실기/영상 확인이 아닌 서버 기록 증거다.

상대 집기 관련 부분 테스트 24 pass(19.51s), 센서 rules 13 pass(7.10s). 반면 Codex vision_pick 22 fail/36 pass(5.23s), rgb_box 6 fail/37 pass(1.20s): 공유에서 camera_grasp_point/side_box_alignment 및 table_roi/object_mask, preflight/접근 후 재확인/계산 lift 연결이 삭제됐다. 상자 회전 도달 불가를 radial 자세로 바꿔 통과하는 회귀도 확인했다. 촬영 timestamp/엄격 ROI·복수 후보 거부/미보정 해시 검사가 제거된 점은 diff로 확인. 결과와 실제 명령/한계는 [새 푸시 검토](../claude-code/reviews/CODEX_PUSH_REVIEW_3dffdae.md)에 있다.

이번에는 검토/테스트/인계만 수행해 기능 코드는 변경하지 않았다. 기존 8000/8001 및 C:/PAC2026_system, 실측 보정/자세·COM8에 쓰기/로봇 명령 없음. 다음 통합은 현장 개선을 보존하면서 SAM–depth 계약, 상자 축 정렬, guard, 현재 lift를 연결해 위 실패를 해결해야 한다. 파랑 분류/흰 상자/열화상 기준은 Claude 인계에서 남은 실기 항목이다.

## 2026-10-09 빠른 통합 및 읽기 전용 실행

사용자 요청으로 3dffdae 현장 개선과 기존 SAM/guard 연결을 실제 통합했다. 기존 28개 실패(guard22/RGB6)를 먼저 재현한 검토에 이어, sensor locate의 table_roi/object_mask·엄격 ROI·복수 후보/수직 평면 basis와 회귀, sensor server 촬영 시각, Windows vision wrapper, 미보정 프로필 해시 거부를 복구했다. 상대 rules/count-golden, 접근 높이/거리 탐색·턱 TCP 오프셋·가까운 IK 분기·grasp dry stage/관측 오차·재집기 home·이동 시간/안정화 변경은 유지했다.

공유 grasp는 상자 3D 변을 먼저 정렬하고 그 자세의 턱 오프셋으로 TCP를 보정한다. 보정 중 radial 방향으로 다시 돌리지 않는다. 경사진 책상 축을 수평화한 뒤 직교화해 실제 도구 회전 행렬을 사용한다. 도달 불가 자세는 거부한다. sequencer의 preflight, 접근/재시도 후 재확인, 현재 계산 lift 및 재촬영 lift 재사용, status pick_mode를 연결했다. wrapper는 dry_stage/dry_hold도 보존한다. tests는 새 grasp-first/높인 접근 동작을 검사하고 임의 회전 도달 불가 거부도 유지한다. 예시 config의 105mm면 임의 회전 정렬 가능하다는 문구는 갈색 80mm 대각선113mm와 불일치해 수정했다. 현장 config 수치는 변경하지 않았다.

추가로 auto hand-eye에서 `frac`를 그리퍼 개방률로 재사용해 camera 높이 대응점을 바꾸던 오류를 수정했다. 수동/자동 보정의 카메라 점은 공통 helper를 쓰고 로봇 점은 설정된 턱 중심을 FK 회전/이동으로 계산한다. 기존 handeye.json이 이 기준에 맞는지 현장 검증이 필요하다. 기존 현장 파일을 재작성/복사하지 않았다. 새 모의 회귀는 80% 그리퍼 개방에도 50% 높이 대응을 유지하고 수동/자동 턱 중심 기록을 확인한다.

실행 테스트(각 폴더의 `python -m pytest ... -q --disable-warnings --rootdir . --confcutdir . -o addopts= --tb=short`): RGB/깊이43 pass(2.54s), 최종 Codex vision60 pass/1warning(11.10s), sensor 전체121 pass/9warnings(54.43s), station 전체115 pass/4warnings(62.84s). 그 후 새 보정 회귀2 pass(0.41s), 마지막 직교화 후 정렬14 pass(1.28s) 및 station vision+auto17 pass/1warning(26.55s; 해당 시점 auto 1case, 이후 manual case도2 pass로 확인). 누락 해시 회귀를 복구한 test_grasp_check는 최종 부분 실행 결과를 아래에 추가한다. AST/JSON/PowerShell parser/diff whitespace도 확인했다. 전체 station 117개를 한 번에 재실행했다고 주장하지 않는다.

`preview_server.py`/test/README를 추가하고 공유 최신 코드 + C:/PAC2026_system 보정 읽기 + 기존 센서 HTTP로 127.0.0.1:8002에 실행했다. SDK/직렬/카메라 핸들 없음, 실행 API 없음, motion_enabled=false. 실제 GET API와 RGB/열화상/Gemini2 합성 영상을 확인했고 IAB에 열어 화면을 보관했다. 서버 프로세스10408, exec session30647(이전 preview27372만 새 코드 반영을 위해 종료). 8000/8001 및 실제 배포 파일/COM8은 유지했다. 촬영 자료/스크린샷은 C:/Users/tilti/PAC2026_data/integration_20261009에만 있다.

현장 결과: 기존 8001은 found=true 상자 약80×80×47.6mm를 반환했지만 candidate_count/captured_at_s가 없는 구버전 계약이다. API는 single_box_not_confirmed/workspace_not_measured 및 sam_live_connected=false로 차단한다. 첫 확인 영상에는 상자 두 개, 이후 화면에는 한 개가 보였으나 후보 수를 구버전 응답으로 확정하지 않는다. 실제 RGB-depth 정합/paired frame reader, 실측 workspace, 수정된 파지 기준의 hand-eye/TCP 검증이 아직 필요하다. 가상 값으로 채우거나 실기 완료라고 주장하지 않는다. 실제 이동 승인 요청은 실행 가능한 실측 조건을 확보한 뒤에 한다.

최종 누락 보정 해시 회귀 `station/tests/test_grasp_check.py`: 8 pass/1warning(1.45s). 코드 셀/노트북이나 GPU는 이번에 실행하지 않았다. 실행 화면은 별도8002이고 실제8000으로 통합 소스를 배포한 결과가 아니다.


## 2026-10-09 Claude 실행 폴더 추가 작업 GitHub 반영 (Codex)

사용자의 전체 푸시 요청으로 origin/main 4ce4d59를 fast-forward한 뒤 C:/PAC2026_system과 파일별 비교했다. Claude 실행본의 밑면 골판지 영역/edge·dark 판정과 bottom-golden 보정 CLI, 추가 테이프 허용 설정, suspect 조기 종료·skipped_faces 기록, 정지 확인 후 안정화 경고, 분류 이동 4초, 관련 sequencer 테스트를 공유 소스에 반영했다. 최신 저장 poses와 가운데 흰 면 pick ROI도 기존 추적 경로에 반영했다. 갈색/흰색/common replay 및 Linux 실행·설치 스크립트를 복원했다. 현재 GitHub grasp는 실행본과 동일하며 기존 통합 변경은 유지했다.

직접 검증: station/tests/test_sequencer.py 49 passed, 1 warning (8.32s); sensor/tests/test_rules.py 13 passed, 4 warnings (11.61s); 변경 Python 5개 AST/JSON 2개 파싱 통과. 실기 이동·서버 재시작·실행본 교체 없음. 신규 밑면 현장 성능은 이번에 실측하지 않았다.

동시 작업으로 남아 있던 native RGB-D/depth/server 및 codex RGB/SAM/preview 변경은 이 Claude 실행본 스냅샷 커밋에 포함하지 않는다. 영상·로그·DB·가상환경·비밀값과 현장 보정 백업 파일도 제외한다. 기존에 추적하지 않던 robot_setup 팩은 3dffdae에서 제거된 이력이 있어 자동으로 재추가하지 않았다.

추가 전체 검증: station/tests **118 passed, 4 warnings (82.50s)**. 명령: 시스템 폴더에서 C:/PAC2026_system/.venv-station/Scripts/python.exe -m pytest station/tests -q --disable-warnings --rootdir . --confcutdir . -o addopts=. 초기 경로 지정 두 건은 수집 실패 후 올바른 폴더/파일로 재실행했다.

## 2026-10-09 Gemini RGB-D 시각 복구 / SAM 윗면 / 놓기 거부 연결

현재 사용자 요구는 SAM 윗면/상자 각도에 맞춘 집기, 윗면에서 이어지는 3개 테이프 판정, 바닥면을 아래로 놓기다. 승인된 기존 radial 1회 run33은 42.09s에 완료했으나 사용자가 옆 놓기/빨강 판정을 지적했다. 이후 이번 수정으로 로봇에 새 이동 명령을 보내지 않았다. 동시에 Claude/사용자가 8000에서 X1/X3/X4/R212711 등을 실행했으므로 사진/실행 주체를 혼동하지 말 것. X3 기록은 no_anomaly/ok 완료이며 Codex 새 SAM 실행 결과가 아니다.

변경: 공유 sensor의 native_rgbd.py/depth.py/server.py와 tests; codex rgb_box의 preview_geometry/guided_top/top_tape/colab_native_top 및 테스트; shared grasp의 선택적 side_alignment=box와 sequencer held/release hooks; own guard/placement/station_app/preview_server. README에 입력 계약/명령/실측과 모의 경계를 기록했다. peer 기본 radial 방식은 유지하고 Codex guard는 box 방향을 요구한다. 위치·TCP·정합 코드를 복제하지 않고 기존 SDK/locator/hand-eye/IK/FK를 재사용한다.

Gemini 컬러와 깊이는 같은 SDK pipeline의 factory intrinsics/extrinsics로 rectified export. native depth와 기존 hand-eye 프레임을 유지한다. host arrival과 capture exposure를 분리했다. 장치 시각이 21474836480us로 고정되고 global 시각이 오래돼 strict NPZ를 503으로 막는 실패를 실제 재현했다. Windows PowerShell은 실행 정책 기본 Restricted였다. 관리자 helper 프로세스에만 RemoteSigned를 적용했고 지속 설정은 변경하지 않았다. 공식 obsensor_metadata_win10.ps1은 없는 MetadataBufferSizeInKB0 조회에서 예외를 냈다. 연결된 Gemini PID0670의 depth/IR/RGB 인터페이스, 2개 공식 DeviceClasses에 공식 요구 DWord 값5를 추가하고 6개 전부 조회 검증했다. 다른 장치/인터페이스나 허브를 수정하지 않았다. 기존값·helper·전체 로그는 C:/PAC2026_system/Log/codex_metadata_*에 보관한다.

21:35 이후 다른 작업에서 센서가 재시작된 것으로 PID13828→26888 변경을 확인했다. 소유 변경 시 Codex 재시작은 취소했다. 이후 /health gemini_rgbd ready=true/capture_time_verified=true/error=null, 장치 exposure clock 증가, host/global 시각 일치 확인. strict /vision/rgbd.npz에서 약1.89MB의 실제 쌍을 받고 두 촬영 시각 차이12.54ms 확인. 증거 verified_capture_rgbd.npz/metadata.json은 아래 데이터 폴더. 센서 현재 소스와 실행본 diff는 마지막 old-preview 폐기 처리 3줄씩뿐이며 그 변경은 아직 실행본에 덮어쓰지 않았다. 8000 station/COM8/현장 calibration/poses는 이번 수정으로 교체하거나 재시작하지 않았다.

실제 Gemini 저장 사진 SAM: 단일 brown positive에서는 테이프가 제외되고 IoU 최대0.6981로 거부됨. 9개 surface positives+4 negatives를 함께 줘 기존 IoU≥0.7 기준에서0.8048 통과. Colab Tesla T4에서 공유 코드를 실행해 전체 DINO/SAM926.11ms, SAM/depth 경계 RMS5.922px 확인(보정 RMS 아님). DINO의 책상 전체 흰 상자 오검출도 보존해 제어 확정으로 쓰지 않았다. raw SAM 마스크와 SAM 자체 convex quad polygon을 모두 저장했다. 윗면 테이프 rule은 H처럼 이어진 접점3을 모의 검증했지만 실제 저장 사진은 1개 확정/폭 과다 후보1개로 unmeasurable; 기존 rules에 자동 적용하지 않았다. 매번 학습 없이 설치 보정+현재 측정으로 처리하는 방향이지만 실제 정상/누락 여러 면 확인이 남는다.

현재 8002: own preview PID28876/exec89586 (추후 재시작 시 바뀜), 3카메라 live와 별도 saved_photo_only SAM 결과. /api/sam-result는 입력파일의 motion/ready 값을 false로 강제하고 live_connected=false. 공유 8000의 실제 구동은 원래 Claude 코드다. SAM 실기에는 factory 정합의 현장 검증, 실제 작업 범위/관절/도구점/경로, 5축 SO101의 각도 도달성을 확인해야 한다. placement는 실제 관절 FK로 예상 자세/바닥 높이/영역을 검사하며 box slip/실제 접촉/놓기 안정성은 증명하지 않는다. 측정 placement 설정이 없으면 own station_app preflight에서 거부; 모의 범위를 현장에 넣지 않았다.

직접 테스트: RGB 전체53 pass (8.38s); own vision_pick 전체67 pass/1warn (32.87s); 공유 station sequencer+vision_pick65 pass/1warn (49.97s); shared sensor native_rgbd/depth/server58 pass/2warn (9.49s). 마지막 추가 회귀: native_rgbd10 pass (1.63s), own preview_server2 pass/1warn (2.23s), placement+preview 부분8 pass/1warn (4.49s). 마지막 두 회귀는 앞 전체 개수와 구별한다. 공통 각 폴더 .venv-station/.venv-sensor python -m pytest 지정tests -q --disable-warnings --rootdir . --confcutdir . -o addopts=. Python compileall/git diff --check도 수행. 초기 전체 실패는 4ce4d59가 side_box_alignment를 제거해 14건과 RGB연결1건 재현; optional box mode로 복원했고 기존 radial field 선택은 보존했다. 테스트 fixture 응답 누락2건 및 편집 indentation 수집 오류는 수정 후 재실행했다.

증거: C:/Users/tilti/PAC2026_data/integration_20261009 (native 사진/prompt/15개 raw SAM mask 진단, Colab ZIP 해제 결과/colab_proof.png, 검증된 capture 파일). 미디어/NPZ/log/weights/보정값은 Git 제외. Colab 결과 노트북 https://colab.research.google.com/drive/1R6e5vQvYaSt0QAA57ZZf3plskmLyPpJI. 다운로드 완료 후 브라우저 제어가 응답하지 않아 마지막 T4 해제는 확인되지 않았다. 다음에는 notebook 런타임 상태를 확인할 것.

최종 현장 재확인: 센서 PID가 26888→26644로 바뀌며 잠시 ready=false/연결 거부가 있었고 이후 복구했다. 복구 후 12회 연속 /health에서 ready=true/capture_time_verified=true, 장치 시각 증가, 촬영 age77~294ms 확인(짧은 표본이며 장시간 안정성을 증명하지 않음). strict paired capture의 skew12.54ms 증거는 유지한다. 마지막 8000의 R212711 오류는 no_candidate_box_matched이며 새 SAM/놓기 계획을 Codex가 실행한 결과가 아니다. 8002 최종 own PID26140/exec83974, 현재 3카메라와 저장 사진 SAM을 구별한 화면을 C:/Users/tilti/PAC2026_data/integration_20261009/preview_final.png에 저장했다. post_registration_health_samples.json도 같은 폴더. 서버 소유/상자 배치를 다시 확인하고 실제 실행할 것.

## 2026-10-09 Codex — 상자 빨간 윤곽과 분류 이유 UI

사용자 요청: 기존 Claude 현장 판정은 유지하며 비저블 상자에 빨간 테두리, 웹앱에 테이프 누락 개수/아랫면 결함 등 빨강 분류 이유를 표시. 검사 데이터에는 tape_missing_count_1/bottom_open과 features가 이미 있었지만 UI가 내부 코드를 그대로 표시했다. 실행본 index의 자동 시료 ID 변경을 보존해서 공유 소스에 통합했다.

변경: 공유 station/web/index.html의 독립 PacReasons 블록으로 면별 최신 시도/최종 사유/기록 사유를 표시한다. 검증된 실제 suspect만 누락/아랫면 결함으로 표시하고 미검증·측정 불가·모의·실행 오류를 구분한다. 여러 면에 이어지는 같은 테이프를 합산하지 않는다. 기존 GET inspections API를 재사용하며 DB/규칙/로봇 제어에는 변경 없다. codex/vision_pick/preview_server.py도 같은 JS 블록을 읽고 현재 실행 상태와 별도로 최근 저장 판정을 표시한다.

codex/vision_pick/box_overlay.py는 기존 sensor/rules.py의 CARDBOARD/GREEN 색을 재사용해 /live.jpg의 첫 RGB 480x360 패널에만 빨간 윤곽을 그린다. SAM이 아닌 표시용 색 기반 후보이며, 현재 서로 닿은 여러 상자는 한 영역으로 묶일 수 있다. 빨간선은 불합격 표시가 아니며 파지/판정 입력으로 사용하지 않는다. 열화상/깊이 배열과 원본 입력은 불변이고 JPEG 재압축은 있다. 흰 상자/배경 갈색 물체/가림에 대한 일반 검출 성능을 주장하지 않는다.

검증: Node station/tests/test_reason_presentation.cjs 14 passed(0.50s), Python vision_pick tests/test_preview_server.py + tests/test_box_overlay.py 12 passed/1warning(3.85s). 실제 기록70을 읽어 B면 테이프1개 누락(2/3관측), 웹 이력62에서 C면 아랫면 결함(벌어짐 의심)을 확인. 실제 결함 정확도를 새로 실험한 것이 아니라 기존 판단의 표시 검증이다. 원인 없는 suspect·재검사 우선·중복 합산 금지·측정 불가·미검증·모의·연결 실패·RGB 이외 무변경 회귀 포함.

사용자가 요청한 화면 적용: C:/PAC2026_system/station/web/index.html만 기존 hash 비교 후 백업하고 배포(서버 재시작 불필요). 백업 C:/PAC2026_system/Log/codex_ui_reasons_20261009/index.before.html. 로봇8000/센서8001 코드/보정/프로세스에는 쓰기/중단 없음. 소유 확인된 Codex8002만 재시작(최종PID3576, exec70420). station 카메라는 노트북 localhost에서8002 annotated GET 사용, 실패시 기존 /sensor-live로 복귀. 원격 접속은 기존 원본 영상 유지. 실제 모터 명령/검사 시작 없음. 동시 Claude 실행에서 나온 multiple_boxes/IK실패는 이번 UI 작업의 실행 결과가 아니다.

증거: C:/Users/tilti/PAC2026_data/ui_reasons_20261009 (현재 영상/화면/실제 API 결과), Git에는 미디어·DB·보정·로그 제외. 현재 갈색 상자 윤곽 표시와 이유 설명만 추가했으며 SAM 정렬/새 놓기 guard는 여전히 별도 실기 검증 필요.

## 2026-10-09 Codex — 검사 후 상승·분류 이동·하강·놓기·상승 복귀

재현 조건: 사용자가 검사 후 옆으로 이동할 때 상자를 바닥에 긁는다고 보고했다. 공유 sequencer는 마지막 검사 자세에서 낮은 `bin_ok`/`bin_human`으로 바로 관절 이동했다. Claude 실행본에는 놓은 뒤 `bin_*_up`으로 빠지는 변경과 `mark_processed`가 이미 있으므로 이를 보존하고, 기존 분류 규칙·집기·현장 자세를 재사용한다. 기존 SAM 각도 정렬이나 미측정 placement를 이번 변경으로 완료했다고 해석하지 말 것.

변경 파일: 공유 `station/clearance_transfer.py`(신규), `station/robot.py`, `station/sequencer.py`, 관련 `test_clearance_transfer.py`·`test_transfer_robot.py`·`test_transfer_sequence.py`, `station/README.md`. 현재 관절을 읽은 뒤 전체 경로를 먼저 계획하고 `lift → travel → lower → open → retract → home`으로 실행한다. 현장 상단 자세는 놓기보다 120 mm 위이며, 검사 직후 수직 상승은 현재 높이 +15 mm와 목적지 상단 높이 중 높은 쪽을 목표로 한다. 15 mm는 해당 검사 자세의 방향 보존 IK 한계를 고려한 값으로, 더 높은 임의 수치로 조건을 통과시키지 않는다. 상자 치수·보정된 턱 오프셋·책상 높이로 상자 경계 구를 계산해 이동 여유를 검증한다.

기존 IK/FK와 joint map을 재사용한다. 완전한 5개 팔 관절 목표(그리퍼 제외), 유한 수치, 전체 4단계와 기록 형식을 이동 전에 검사한다. 관절 보간 표본의 관절 한계·최소 TCP 높이, 수직 구간 XY·방향·단조 상승/하강을 검사하며 실패 시 낮은 직접 이동으로 대체하지 않는다. 각 단계는 엄격한 `wait_settled` 뒤 실제 관절 FK로 목표 위치 5 mm/방향 5° 및 요구 높이를 확인한다. 촬영용 `is_still` 예외는 적용하지 않는다. 상승·옆 이동 뒤 파지 확인, 기존 held/release 훅, 상자별 `_up` 이름도 유지한다. 실패 시 stop/hold, 놓기 전 실패면 그리퍼 유지, 놓은 뒤 상승 실패면 배치 사실을 남기고 home 금지. 경유점마다 일시정지/중단을 확인하며 중단에도 best-effort stop을 추가했다. 물리적 비상정지는 아니다.

분류 이동의 명령 시간은 실제 시작 관절과 FK 표본으로 늘려 관절 20°/s·모델 TCP 50 mm/s를 제한한다. 실제 속도·가속도 계측이나 충돌 검증은 아니다. 결과에 `transfer_plan`·`transfer_checks`를 남긴다. 계획 API 없는 기존 mock 경로는 보존한다.

최종 검증: `PAC2026_system`에서 `C:/PAC2026_system/.venv-station/Scripts/python.exe -m pytest station/tests/test_clearance_transfer.py station/tests/test_transfer_robot.py station/tests/test_transfer_sequence.py station/tests/test_sequencer.py -q --disable-warnings --rootdir . --confcutdir . -o addopts=` → **167 passed, 1 warning, 15.83s**. 시간 확장 회귀 4개를 포함한 최종 통합 실행이다. 배포 예정인 정확한 실행본은 검사 B/C × 정상/부적격 × 카메라 구역 배치 3가지(정보 없음/정상/뒤바뀜)의 **12개 조합 모두 오프라인 검증 통과**했으며 모터/직렬 연결 없이 수행했다.

동시 변경 보존: 실제 프로세스를 멈추기 전 실행 파일 hash 검사가 Claude의 새 변경을 포착해 최초 배포를 취소했다. 최신 실행본은 `/zones`의 색 영역 위치로 놓기 자세를 선택하는 `place_pose_from_zones`·`_place_pose`가 추가돼 있었다. 이를 다시 합쳐 실행본의 `self._place_pose(bin_name)`이 선택한 목적지를 transfer planner로 넘기며 `mark_processed`도 보존했다. 위 12개 검증은 이 정확한 재통합본 기준이다. 공유 저장소 소스에는 기존 routing을 유지했고, Claude의 색 영역 선택 코드가 정식 push되면 별도로 검토·통합해야 한다. 저장소와 실행본이 완전히 같다고 보고하지 말 것.

배포 완료: **2026-10-09 22:36:00 KST**, 사용자가 빈 그리퍼·지지된 팔을 확인하고 재연결을 승인한 뒤, 실행 파일 hash를 다시 확인해 검증한 파일 3개를 적용했다. 실행본 전체를 공유 소스로 덮지 않고 현장 `mark_processed`와 색 영역 선택 등 Claude 변경을 보존했다. 시작 후 GET status에서 `robot_mode=hardware`, `pick_mode=vision`, `state=idle`, `busy=false`, 검사면 B/C를 확인했으며 수신 프로세스 PID는 27040이었다. `/api/run`이나 새 분류 사이클은 호출하지 않았다. 백업은 `C:/Users/tilti/PAC2026_data/transfer_20261009/runtime_backup_223600`, 같은 증거 폴더에 `deployment.json`·`startup_verification.json`과 12개 오프라인 검증 결과가 있다.

현장 연결/적용은 확인됐으나 새 경로의 상자 미끄러짐·바닥 접촉·주변 장애물·부하 상태의 실제 추종/속도·안정적인 놓기는 미검증이다. home은 기존 경로이며 센서 보정·현장 자세를 새 값으로 재작성하지 않았다. 실제 검사/분류 완료로 보고하지 말 것.

## 2026-10-09 Codex — HOME 수직 하강 후 전진 집기와 사용자 설정

사용자가 집기 시작 때 HOME에서 대각선으로 바로 접근하지 않고 먼저 수직 하강한 뒤 앞으로 들어가도록 요청했고, 적용 구간을 집기 전 접근으로 확인했다. 기존 `teach.py`는 별도 COM 연결을 만들므로 실행 중인 8000의 로봇 소유 객체를 재사용한다. 새 경로는 앞서 배포한 검사 후 상승/분류/놓기와 다른 기능이다.

변경: `station/home_approach.py`, `pick_path_api.py`, `web/pick_path.html`, app 등록과 기존 검사 화면 링크, `sequencer.py`, `test_home_approach.py`·`test_pick_path_api.py`·`test_pick_path_web.py`·`test_home_path_sequence.py`. `/pick-path`에서 기본 `legacy`와 `home_descend_forward`를 선택하고, 비전이 계산한 집기 높이에 −10~+30 mm를 더할 수 있다. 하강 거리 입력값이 아니다. `station/calib/pick_path.json` 저장은 성공한 미리보기 token과 설정/자세/보정 지문 일치, 120초 이내 유효성을 요구한다. 미리보기나 적용 API 자체에 이동/토크 조작은 없다.

API는 `GET /api/pick-path/settings`, `POST /api/pick-path/preview`, `PUT /api/pick-path/settings`, `POST /api/pick-path/home`. HOME 기록은 기존 스테이션 로봇의 현재 관절 읽기만 수행하며 모델 관절 한계·TCP 책상 여유를 확인한다. poses 원본 변경 감지·백업·원자적 교체로 다른 자세를 보존한다. 설정 mutex를 추가해 검사와 설정을 동시에 실행하지 못하게 한다. 별도 COM8 연결·장비 이동·토크 해제 API를 만들지 않았다.

최종 검토에서 HOME 재저장 뒤 이전 경로 승인이 재사용될 수 있는 문제와 별도 Codex 진입점의 picker 연결 차이를 수정했다. 검증된 geometry 지문 `accepted_geometry_sha256`을 설정에 영구 저장하고, HOME 기록 전에 기존 승인을 무효화해 서버 재시작 후에도 새 미리보기·적용 전에는 실행하지 못한다. 실행 설정과 UI는 `needs_preview`를 표시하며 기존 legacy 방식으로 조용히 돌아가지 않는다. `PickPathService.bind_picker`와 `codex/vision_pick/station_app.py` 연결을 추가해 Guarded 진입점에서도 미리보기/설정과 실제 실행이 같은 picker를 사용한다.

계획기는 기존 IK/FK를 사용해 HOME X/Y·전체 방향을 유지하며 접근 높이까지 내린 뒤, 같은 높이의 직선을 따라 접근점 방향으로 보간한다. 관절 보간 표본의 관절 한계, 바닥 여유, 수직·수평 오차와 단조 진행을 검사한다. 마지막 기존 approach→grasp도 수평/바닥 여유를 확인한다. 도달 불가 경로를 대각선/임의 방향으로 대체하지 않는다. sequencer는 초기 HOME 이동 전에 설정을 확인하고, 첫 하강 전 실제 HOME 도달과 각 단계 후 도달을 strict settle/FK로 검사한다. 최초/재집기 모두 새 경로를 사용하며, 실패 시 정지하고 그리퍼를 닫지 않는다. 기존 dry-run 종료·held/release·분류 경로는 유지하며 `home_path_plans`·`home_path_checks`에 기록한다.

실제 테스트: `PAC2026_system`에서 `.venv-station` Python `-m pytest station/tests -q --disable-warnings --rootdir . --confcutdir . -o addopts=` → **273 passed, 4 warnings (126.90s)**. 이후 홈 경유점 명령 실패 2개를 추가하고 `station/tests/test_home_path_sequence.py station/tests/test_transfer_sequence.py station/tests/test_sequencer.py` → **138 passed, 1 warning (10.30s)**. 최종 지문 무효화/재시작/실행 picker 연결 수정 후 `station/tests/test_home_approach.py station/tests/test_home_path_sequence.py station/tests/test_pick_path_api.py station/tests/test_pick_path_web.py` → **77 passed (6.73s)**: 경로 19개, 순서 37개, API 19개, UI 2개다. 앞선 UI 부분 2개(3.04s)·비전 포함 순서 152개도 통과했으나 범위가 겹치므로 숫자를 합산하거나 최종 전체 실행으로 주장하지 않는다.

현장 제약: 저장 HOME `wrist_roll` −163.38°가 모델 하한 −157.21° 밖이므로 새 경로는 활성화하지 않았다. 기존 실행 모드는 유지하며 정상 HOME 또는 실제 로봇/모델 보정 일치를 확인해야 한다. 한계를 넓히거나 각도를 임의 감아 통과시키지 않았다. 직전 실제 기록 R221924(22:38:35~22:39:08)는 두 번의 집기 모두 `nothing_held`로 검사/분류 전에 중단됐으며, 이번 새 HOME 경로의 실행 결과가 아니다.

배포 준비만 진행 중이다. Claude가 바꾼 실행본의 글꼴/새 검사 화면, `place_spot`, 색 영역 선택, `mark_processed`를 보존한 staging을 준비한다. 이 기록 시점에는 HOME 기능의 실행본 교체·서버 재시작·새 검사 호출을 하지 않았다. 사용자의 빈 팔 지지·재연결 승인 대기이며 실제 경로/충돌/추종/파지 성공은 미검증이다. 이전 22:36 transfer 배포 완료 기록과 이번 HOME 기능 상태를 구별할 것.


## 2026-10-09 Codex — 최신 스테이션 디자인 동기화

사용자가 바뀐 스테이션 디자인으로 전환을 요청했다. 현재 실행본의 Claude 디자인(Pretendard, 네이비 PAC 상단 바, 흰 카드, 1280px 반응형 2열)을 공유 소스의 station/web/index.html로 가져오고, 기존 /pick-path 링크를 새 상단 바에 유지했다. 실행본의 글꼴 제공 경로를 app.py에 통합하고 PretendardVariable.woff2 및 SIL OFL LICENSE.txt를 함께 보존했다. 집기 경로 설정 pick_path.html도 같은 디자인으로 맞췄으며 모든 ID와 JavaScript는 유지했다(스크립트 SHA-256 전후 동일).

실제 8000 탭을 새로고침해 새 상단 바와 검사/진행/분류/카메라 카드 표시를 확인했다. 실행본 디자인은 이미 적용돼 있어 이번 작업은 서버 재시작이나 로봇/설정 변경을 하지 않았다. HOME 경로 설정 기능의 실기 배포 대기는 그대로다. 화면 증거: C:/Users/tilti/PAC2026_data/station_design_20261009/station_updated.png. 기존 집기 UI 테스트 2 passed (7.59s); 분류 이유 Node 테스트 14 passed (3.06s), git diff --check 통과.


## 2026-10-09 23:51 KST — HOME 설정 기능 실행본 배포

사용자가 팔을 받쳤다고 확인한 뒤 검증한 HOME 기능 6개 파일을 C:/PAC2026_system/station에 적용하고 기존 8000 서버를 재연결했다. 배포 전 PID/생성 시각/명령·단일 listener·idle·파일 hash·poses 불변을 확인했다. 최신 Claude 실행본의 색 영역 선택, place_spot, mark_processed, 글꼴/디자인을 보존했다. 실행본 전체를 공유 소스로 덮지 않았으며 기존 poses/calibration은 수정하지 않았다.

실제 확인: 수신 PID34848, robot_mode=hardware, pick_mode=vision, state=idle, busy=false. /pick-path 페이지와 GET /api/pick-path/settings 정상, 화면에서 새 방식 선택 시 유효하지 않은 HOME 때문에 미리보기/적용 버튼이 비활성화된다. vis/lwir/depth 수신 및 Gemini ready/capture_time_verified=true 확인. 적용한 여섯 파일 hash 일치와 poses.json 변경 없음도 재확인했다. 기존 모드는 legacy다. HOME wrist_roll -163.38°가 모델 하한 -157.21° 밖이어서 새 경로 활성화·실기 이동은 하지 않았다. /api/run을 호출하지 않았다. 이전 배포 대기 기록은 이 배포 확인으로 갱신한다.

증거는 C:/Users/tilti/PAC2026_data/home_approach_20261009의 deployment.json, startup_verification.json, deployed_settings.png, station_restart.log 및 runtime_backup_235059에 보관한다. 새 모터/경로 시험이 아니라 배포·연결·UI 상태 확인이며 기존 모의 테스트 결과와 구분한다. 다음은 실제 HOME과 SDK 관절 보정/URDF 대응을 확인한 뒤 유효한 수직 하강 경로를 미리보기로 검증하는 것이다.

추가 읽기 진단: 설치 LeRobot so_follower.py의 calibrate는 wrist_roll을 full_turn_motor로 지정하고 해당 range를 실측하지 않고 0..4095로 저장한다. 현장 파일도 같은 범위이고 DEGREES 정규화는 약 -180..180도를 표현한다. station/kinematics.py는 joint_map.json이 없으면 SDK↔URDF 각도 1:1을 가정하며 URDF 손목 범위는 -157.21..162.79도다. 따라서 현재 거부는 드라이버/모델 범위 불일치의 증거이며 실제 기계 위험이나 새 HOME만으로 해결됨을 단정하지 않는다. 실제 영점/방향/기계·케이블 여유 확인 없이 한계를 확대하거나 offset을 만들지 않았다.


## 2026-10-10 — 사용자가 직접 HOME/하강 끝 위치를 기록하는 창

사용자가 하강 후 전진을 시작할 위치를 직접 지정하겠다고 요청해 codex/vision_pick/home_teach.py와 home_teach.html을 추가했다. 기존 So101Robot의 connect/current_joints/disable_torque/hold를 재사용한다. 자동 연결/이동 없이 8003에 창을 먼저 열며 사용자가 팔 받침 체크와 해제 버튼을 누른 뒤 연결한다. HOME 관측과 하강 끝 관측을 별도로 기록하고 station/calib/home_path_teaching.json에 원자 저장/이전 기록 백업한다. 모델 범위 밖 관측도 원본 기록은 허용하며 hardware_motion_validated=false다. 기존 poses.json, 보정, 집기 모드와 경로 승인을 바꾸지 않는다. 저장은 토크 고정과 별개이고 현재 자세 고정 버튼을 제공한다.

실제 적용: 기존 8000 listener PID34848의 정체/idle/포트 단독 소유를 재확인한 뒤 사용자 수동 티칭 요청으로 종료했다. 8003 전용 창을 브라우저에 열어 버튼 표시와 초기 미연결 상태를 확인했다. release 버튼에서 8000 서버가 살아 있으면 연결을 거부한다. Codex는 release/capture/hold/save 버튼을 누르지 않았다. 사용자가 두 위치를 가르치는 중에는 8000을 자동 재시작하거나 COM8을 중복 연결하지 말 것. 저장된 관측을 실제 이동에 쓰기 전 경로를 별도 검증해야 한다.

검증: fake robot 및 API tests/test_home_teach.py 31 passed, 1 warning (1.88s); HTML inline JS 문법/중복 ID 및 가짜 fetch 전체 버튼 흐름 통과. 증거/서버 로그/8000 복구 메타데이터/teaching_window.png는 C:/Users/tilti/PAC2026_data/home_teach_20261010. 서버는 같은 폴더 코드로 127.0.0.1:8003에서 실행 중이다. 창을 닫아도 백엔드는 살아 있으므로 완료 후 hold 상태와 포트 소유를 확인해 검사 서버로 돌려놓아야 한다. 새 수직 하강 경로의 실제 이동 완료가 아니다.


### 실제 Windows 연결 오류 수정 및 티칭 연결 확인

첫 창의 release는 종료된 localhost8000 확인에 timeout=1s를 써 실제 Windows의 약2.046s/WSAECONNREFUSED(10061) 응답보다 빨리 실패했다. 실제 재현 후 timeout=5s로 수정했고, 연결 여부 미확인/다른 오류는 계속 거부한다. 미연결 티칭 서버만 재시작했다. 중간 재시작이 base Python으로 실행돼 uvicorn 누락을 냈으며 즉시 .venv-station 실행 파일로 교정했다. 최종 listener PID28228, POST /api/release 200, GET status connected=true/free=true/error=null과 브라우저의 HOME 기록 활성화를 실제 확인했다. 사용자 팔 지지 체크와 반복된 연결 요청 범위에서 Codex가 1번을 실행했다. HOME/하강 위치 기록과 저장 버튼은 사용자가 지정하며 Codex가 대신 누르지 않았다. 8000은 멈춰 있고 COM8은 8003 티칭 서버가 단독 소유한다. 증거 connected_teaching.png/server.log.

추가 회귀는 종료된 서버/열린 listener/시간초과/기타 소켓 오류 4개이며 최소5s 확인 시간과 실패시 연결금지를 검증했다. home_teach 전체 35 passed, 1 warning (2.70s). 모의 테스트로 실제모터를 호출하지 않았다.


## 2026-10-10 — 가르친 두 점 실행 연결과 가까운 상자 IK 허용

사용자가 HOME/LOWER 저장을 확인하고 실행 UI를 요청했다. 실제 파일 home_path_teaching.json의 두 관측과 저장 시각을 확인했다. 새 HOME은 모델상 (212.7,17.2,248.4)mm, LOWER는 (294.3,69.6,0.5)mm로 같은 XY의 수직 이동이 아니다. 이 차이와 기존 10mm 바닥 여유 미달을 알린 뒤 사용자가 그대로 진행하도록 명시했다. 따라서 새 모드는 완전 수직 IK 모드가 아니라 가르친 관절 경유점 모드이며 UI에도 명시한다. 이전 strict Cartesian 한계를 조용히 바꾼 것이 아니다.

Codex 전용 vision_pick/taught_approach.py, retained_robot.py, taught_station.py와 세 테스트 파일을 추가했다. 실행 경로는 HOME→기록 LOWER→기존 카메라 접근→기존 집기다. home/box별 HOME은 실행 객체 메모리에서만 기록 HOME으로 대체하며 원본 poses.json과 handeye/grasp 보정은 유지한다. 초기/복귀 HOME 및 HOME→LOWER→approach→grasp 관절 보간의 모델 한계/1도 표본/TCP z>=0을 검사한다. 이번에 사용자가 지정한 낮은 경유점만 0mm 기준으로 검증하며 기존 비전 grasp 목표의 최소높이 설정은 유지한다. 20deg/s·모델TCP50mm/s 명령 시간 확대와 실제 도달/그리퍼 검사는 기존 sequencer를 재사용한다. 실측 속도/충돌/수직직선 경로를 보장하지 않는다.

8003에서 hold를 실행해 connected=true/free=false/saved=true를 확인한 뒤 종료하고 8000 실행 UI로 전환했다. 기존 SDK connect/configure의 토크 끄기를 피하기 위해 이전에 검토한 codex/tools/robot_status.make_reader를 재사용한 RetainedSo101Robot을 사용한다. bus.connect(handshake=True)와 보정/토크6개ON/position mode0/현재각도 읽기만 수행하며 torque/goal/PID/보정 쓰기는 없다. 종료/실패도 disable_torque=False다. 이미 모터가 고정된 동일 현장 세션의 소유권 인수용이며 전원 켠 새 장비의 초기 설정을 대체하지 않는다. SDK0.6.1만 허용한다.

사용자가 가까운 상자 제한 수정을 요청해 TaughtPicker는 원본 cfg를 깊은 복사한 뒤 옆집기 최소반경만 0으로 설정해 기존 IK에 판단을 맡긴다. 최대반경490mm와 이후의 관절/접근/높이 검사는 유지한다. 기존 코드는 턱/TCP 보정 전 상자중심에도 최소370mm를 적용해 도달 가능한 가까운 상자를 거부했다. 현장 보정+합성345mm 입력은 수정 전 거리 거부, 수정 후 IK 및 기록 LOWER→접근→집기 모델 경로 통과(보정후TCP반경378.4mm)다. 원본 grasp_config.json의 범위370~490mm는 불변이며 이 별도 실행 진입점에서만 하한 판단을 변경한다.

테스트: retained_robot 17passed(0.86s), taught_approach 17passed(0.63s), taught_picker 11passed(1.25s). 정확한 현장 소스를 쓰는 오프라인 fake/API 검사에서 LOWER 관절 명령 일치, 2단계 순서, UI/status 모드, 가르친 파일 변경 시 시작409, 구 설정 API로 모드 덮기 불가를 확인했다. 실제 장비 명령과 구분한다. 증거는 C:/Users/tilti/PAC2026_data/home_teach_20261010의 taught_entry_mock_checks.json, taught_station_verified.json, near_reach_model_check.json, taught_execution_ui.png, 두 launch/deployment JSON과 로그다.

실제 8000 하드웨어 연결·카메라3대 수신·taught_home_lower 모드·저장 HOME/LOWER 일치를 확인하고 검사 시작 버튼이 있는 UI를 열었다. Codex는 검사 시작을 누르지 않았다. 사용자가 직접 실행한 초기 시도는 상자344mm 거리제한으로 실패했고, 상자를 옮긴 후 시도는 비전416.4mm IK 성공 뒤 home_start 실제도달 위치오차12.94mm/방향2.78도로 하강 전에 실패했다. 관절 안정화 허용5도와 Cartesian 허용5mm가 다르므로 추가대기만으로 해결됨을 주장하지 않으며 도달 검사를 완화하지 않았다. 가까운 상자 수정 배포 때 실행 중을 감지해 첫 재시작은 취소했고 idle/error가 된 뒤 토크 유지 방식으로 재시작했다. 아직 가르친 LOWER의 실제 도달/집기/검사/분류 완주를 확인하지 않았다.

현재 실행 진입점은 Codex vision_pick/taught_station.py(환경 PAC_SYSTEM_DIR=C:/PAC2026_system, ROBOT_PORT=COM8, PICK_MODE=vision, 기존 현장 환경 재사용)다. 일반 station/app.py로 시작하면 이 별도 모드가 적용되지 않는다. 저장 파일 변경은 실행 전409로 막고 새 검증/재연결이 필요하다. 기존8003 티칭서버는 종료됐고8000만 COM8 소유. 현장 원본 파일 전체를 덮어쓰지 않았다.

## 2026-10-10 — RGB 테두리를 현재 작업대 상자 하나로 제한

사용자가 현재 대상 상자 하나만 빨간 테두리로 표시하도록 요청했다. 기존 box_overlay는 현장 RGB에서 상자 외 사람/의자까지 갈색 후보 4개를 표시했다. codex/vision_pick/box_overlay.py는 정규화 화면 ROI [0,0.4,1,1] 안에 완전히 들어온 후보 중 빨강/파랑 분류 종이 위 후보를 제외하고, 정확히 하나 남을 때만 윤곽을 그린다. 여러 후보에서 가장 큰 물체를 임의로 고르지 않으며 0개/복수이면 표시하지 않는다. 화면 ROI는 고정 카메라 배경 제거용이며 로봇 작업 범위 변경이 아니다. 단안 색 기반 표시라 흰 상자/맞붙은 상자/가림의 일반적 식별을 보장하지 않는다.

상대 live sensor/zones.py의 paper_hulls를 재사용했다. 이 파일이 공유 소스에 없어서 C:/PAC2026_system/sensor/zones.py를 수정 없이 claude-code/PAC2026_system/sensor/zones.py에 복사했다. 분류 종이 검출에만 사용하며 ProcessedMemory를 생성하거나 /object/locate를 화면 갱신에 호출하지 않는다. Arducam↔깊이 카메라 object_map.json과 배경 보정이 없어 실제 로봇 선택 ID와 RGB 윤곽을 연결했다고 주장하지 않는다. 후보가 여러 개인 장면의 정확한 타깃 표시는 추후 카메라 대응 보정/선택 메타데이터가 필요하다.

preview_server.py 안내/헤더 변경, overlay 및 preview API 테스트 합계 30 passed, 1 warning (2.43s). 기존 영상은 4개→가운데 상자1개로 줄었고 입력/열화상/깊이 불변, 분류 구역 배제, 복수 후보 무표시를 검증했다. 실행 중 8002 preview PID3576만 확인 후 재시작해 새 listener32224, /camera.jpg HTTP200 X-Box-Candidates=1 확인. 열린8000페이지의 실시간카메라를 켜서 실제표시를 확인했다. 증거 C:/Users/tilti/PAC2026_data/target_overlay_20261010 (before/after/deployed.jpg, single_box_ui.png, preview.log). 로봇/센서 서버를 종료하거나 이동 명령을 보내지 않았다. 종료 확인 시8001센서정상이나8000리스너는 사라져 검사UI에 연결끊김 표시가 있었다. 원인은 이번 표시작업에서 확인되지 않았고 로봇 서버를 임의로 재시작하지 않았다. 기존 HOME 도달오차 미해결 상태는 그대로다.
