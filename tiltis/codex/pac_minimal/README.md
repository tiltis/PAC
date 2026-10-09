# PAC 2026 손목 입력 및 기존 로봇 SDK 연결

2026-10-09: 이 노트북의 기존 hack_qut.py와 tiltis/PAC 코드를 기준으로 구성했다.
실제 로봇 모델과 연결은 아직 확인되지 않았다. 최신 포트 조회에는 Bluetooth COM3/COM4만
표시됐으며 자동 포트를 선택하지 않는다. 이전에 표시된 COM7도 로봇으로 간주하지 않았다.

## 노트북에서 실행

PowerShell에서 이 폴더로 이동한다. 비전·모의 연결용 Python 3.10 가상환경을
`C:/Users/tilti/.venvs/pac2026-vision310/`에 별도로 구성했다.
기존 Anaconda 환경은 보존한다. Windows MediaPipe의 모델 경로 문제를 피하기 위해
환경은 ASCII 경로에 둔다. 프로젝트 소스는 현재 한글 경로에 유지한다.

```powershell
$pacPython = Join-Path $env:USERPROFILE '.venvs/pac2026-vision310/Scripts/python.exe'
& $pacPython check_laptop.py
& $pacPython -m unittest discover -s tests -v
& $pacPython replay.py
& $pacPython hack_qut.py
```

브라우저에서 http://127.0.0.1:5001 을 연다. 다른 터미널에서 같은 Python으로
`robot_bridge.py`를 실행하면 **모의 로봇만** 연결한다. 손 하나를 노란 영역에 놓고
웹에서 입력을 활성화한 뒤 bridge 터미널에서 `arm`을 입력한다.
`stop`은 bridge 정지, `quit`은 종료. 웹 정지도 bridge의 hold를 유발한다.
양쪽 모두 정지 후 수동 활성화가 필요하다.

새 PC에서 환경을 만들 때는 Python 3.10으로 아래를 실행한다.

```powershell
python -m venv "$env:USERPROFILE/.venvs/pac2026-vision310"
$pacPython = Join-Path $env:USERPROFILE '.venvs/pac2026-vision310/Scripts/python.exe'
& $pacPython -m pip install -r requirements.txt
```

동일한 의존성을 재현하려면 requirements.lock.txt를 사용한다.
OpenCV 배포본 두 개가 같은 cv2 모듈을 덮어쓰지 않도록 MediaPipe가 요구하는
opencv-contrib-python 하나만 설치하고, NumPy와 함께 버전을 고정했다.
MediaPipe의 기존 solutions API를 사용하는 Python 3.10 서버다.

## 좌표와 API

- 입력 좌우 반전, landmark 0, 손 2개까지 검출하여 두 손이면 비활성화.
- 정규화 영상 좌표 u,v 각각 0.1~0.9만 허용.
- 위쪽 → +X, 오른쪽 → −Y. X 0.20~0.40m, Y −0.10~0.10m, Z 0.20m.
- 목표의 유클리드 이동 속도 0.05m/s, 긴 주기는 최대 50ms로 제한.
- 손 미검출, 작업영역 이탈, 200ms 초과 영상 지연은 latch 정지.
- 지연은 cap.read() 시작부터의 소프트웨어 경과시간이다. 카메라 내부의
  촬영/버퍼 지연은 장비 timestamp 없이 확인할 수 없어 현장 지연 검증이 추가로 필요하다.
- GET /api/state: position_m, motion_enabled, frame_id, frame_age_s, units,
  coordinate_frame, workspace. frame_age_s는 서버 monotonic 기반 경과시간이다.
- POST /api/enable, POST /api/stop: 입력 수동 활성화/정지.
- bridge는 영상 age에 HTTP 왕복시간을 보수적으로 더한다. 반복 frame ID는
  신선도를 갱신하지 않는다. frame ID 감소는 서버 재시작으로 보고 정지한다.
- Windows에서 같은 monotonic clock tick을 공유하는 입력은 이동 예산 0으로 처리한다.
  capture timestamp가 역행하면 수동 재활성화가 필요한 정지 상태로 전환한다.
- bridge의 arm과 첫 step이 같은 tick이면 SDK 명령을 건너뛰고 활성화를 유지한다.
  이후 양의 시간 간격에서 제어를 재개하며 입력 watchdog은 계속 적용한다.

## 작업 범위 설정

기본 `workspace.virtual.json`은 가상 검증 전용이다. `workspace.py`가 서버와
bridge에 같은 범위·Z·단위·속도 설정을 적용한다. API 설정이 다르면 전송하지 않는다.
가상 범위로 실기 Backend를 생성하면 오류를 반환한다.

현장에서는 `workspace.site.template.json`을 별도 파일로 복사해 실제 측정값을 넣는다.
이 템플릿의 null 값과 unconfigured profile은 실행 시 거부된다. 현장 검증을 마친
범위에만 `profile: commissioned`을 지정한다. profile 변경 자체가 안전 검증은 아니다.
서버와 bridge 양쪽에 같은 파일을 `--workspace 파일.json`으로 전달한다.
시작 EE가 해당 범위 및 고정 Z(허용 오차 1mm) 안에 있어야 활성화된다.
임의로 초기 EE에서 작업 범위 중앙까지 이동시키지 않는다.

이 방식은 화면 2D 조작 입력을 robot base의 XY 목표로 매핑한다. 카메라에서 측정한
3D 물리 좌표를 로봇으로 변환하는 방식이 아니므로 외부 보정행렬을 추측해 넣지 않는다.
실제 base 축 방향과 URDF의 미터 단위를 확인해야 한다. 다른 좌표계의 SDK라면
그 사양을 확인한 뒤 명시적인 변환 어댑터를 추가한다.

## 기존 제어 코드 재사용

이 폴더는 공동 저장소의 tiltis/codex/pac_minimal에 있다. 저장소 루트는 ../../..,
초기 SDK 검토 commit은 5aa74557f84c54d4b458f8b9643c5aa2982acfed 이다.
추가로 0e515a7의 검사 시스템을 검토했고, ../../claude-code/PAC2026_system에
station/robot.py, station/kinematics.py와 SO-101 URDF가 있다. 검토 차이는
상위 HANDOFF.md에 기록했다. 해당 URDF의 현장 일치는 아직 검증하지 않았다.

so101_backend.py는 기존 SO101Follower.get_observation/send_action과
RobotKinematics.forward_kinematics/inverse_kinematics를 호출한다.
새 IK나 자체 SDK를 구현하지 않았다. SDK 의존성은 실기 환경에서만 로드한다.
공동 저장소는 Python >=3.12를 요구하므로 Python 3.10 비전 환경과 HTTP로 분리한다.

실기 Backend는 이미 연결된 robot 객체와 보정된 kinematics 객체를 받아 사용한다.
이 단계에는 실제 로봇 실행 CLI가 없다. 현장 정보를 확인하고 검증한 뒤 추가한다.
필요 정보는 모델(SO-100/101 등), USB 포트, robot id/보정 파일, SDK 버전,
실제 URDF와 EE frame, base 축/단위, 현재 EE 위치, 관절 한계/속도, 충돌 환경이다.
보정과 torque 활성화는 SDK connect 과정에서 발생할 수 있으므로 단순 포트 검출과 구분한다.
SO-101 어댑터는 지원 후보이며 현장 모델이 SO-101로 확인된 것은 아니다.
실제 구동 전에 비상정지·주변 장애물·저속 범위를 확인하고 사용자 승인을 받아야 한다.

팔 5관절은 degree, gripper는 0~100이다. IK에는 gripper를 제외한 5관절만 넣고,
활성화 시 관측한 EE 회전과 그리퍼 명령을 유지한다. SO-101은 5 DOF여서
일정 자세의 XY 이동이 불가능한 경우가 있다. FK 위치/자세 잔차로 거부한다.
실기 초기 EE는 workspace 및 고정 Z에 있어야 arm 가능하다. 자동 이동하지 않는다.
예시 workspace는 도달 가능성을 검증한 값이 아니다.

So101Backend는 현장 joint limits, joint velocity limits와 path_validator를 요구한다.
path_validator는 관측 상태, 후보 action, dt를 받아 전체 경로 충돌과
EE 추종/속도를 검증해야 한다. 단순 True 콜백은 실기 검증이 아니다.
콜백은 제공된 상태와 경로를 검사하며 직접 SDK 명령을 전송하지 않아야 한다.
max_relative_target은 관절 목표 차이 제한이며 Cartesian 속도를 보장하지 않는다.
실기 어댑터는 SDK의 max_relative_target clipping을 거부한다. 이미 검사한 관절 경로가
SDK에서 다른 목표로 변경되지 않도록 bridge의 관절 step 검사로 제한한다.
SDK 반환 명령이 요청과 다르면 오류를 내고 hold한다. 이 검사는 전송 이후이며
이미 전송된 명령을 취소했다는 의미는 아니다.

## 정지와 로그의 한계

독립 watchdog이 입력 단절을 감지해 latch 정지한다. IK 또는 충돌 검사 중 watchdog이
발생하면 그 결과는 전송하지 않는다. SDK 관측·전송·hold는 lock으로 직렬화한다.
SDK 호출 자체가 멈추면 watchdog도 lock을 기다리므로 200ms 물리 정지는 보장하지 않는다.
현장에서는 SDK 통신 timeout/하드웨어 정지 수단과 실제 정지 지연을 검증해야 한다.
정상 통신 시 현재 관절을 읽어 그 위치로 send_action하는 소프트웨어 hold를 사용한다.
통신 단절로 hold 실패하면 hold_failed를 기록한다. disconnect의 torque off와 구분한다.

logs/bridge.jsonl에는 관측 관절/FK EE, 요청/제한된 EE 목표, IK action,
SDK 반환 action, 관측·전송 시작/끝의 로컬 monotonic 시간과 wall_time_ns를 기록한다.
이는 순차 관측/명령 기록이며 동시 측정 데이터가 아니다. 실제 적용 action은 SDK
반환값으로 구분하되 실제 도달 상태는 다음 관측에서 확인해야 한다.
FK EE는 관절 기반 계산값이다. 학습용 영상은 아직 기록하지 않는다.
mock=true 및 synthetic=true 데이터는 실측/학습 데이터로 취급하지 않는다.
관측과 명령의 시각을 한 호스트에서 기록하지만 실측 데이터 수집/동기화 정확도는
아직 검증하지 않았다. 학습 데이터 구축 시 카메라 frame과 후속 관측의 timestamp,
통신 지연, observation/action 이름 및 episode 경계를 추가 검증해야 한다.

## 이 노트북 검증 결과 (2026-10-09)

- 별도 Python 3.10.19 환경에서 자동 테스트 **50개 통과**.
  좌표/속도, API, watchdog, 느린 IK/충돌 검사 결과 취소,
  중복/오래된 프레임, 재활성화, hold 실패, SDK 단위/IK 잔차/자세/충돌 검증 차단,
  가상 범위의 실기 사용 차단, Windows clock tick, 실제 TCP HTTP 모의 연결을 검증했다.
  초기 48개에 bridge/SDK의 arm 직후 동일 tick 회귀 테스트 2개를 추가했다.
- 120프레임 모의 재생에서 120명령, 손 미검출 후 hold 1회 및 수동 재활성화 확인.
- MediaPipe 0.10.21 / OpenCV 4.11.0로 웹캠 640×480의 30프레임 처리 성공.
  마지막 측정에서 30프레임 모두 손이 검출됐다. 장시간 추적 정확도 검증은 아니다.
  처리 시간 중앙값 78ms, 첫 프레임 844ms, 200ms 초과 프레임 1개(시작 프레임).
  초기 지연 프레임은 제어에서 비활성화되며 신선한 입력 이후 수동 활성화가 필요하다.
- 실제 hack_qut.py를 짧게 실행해 최신 영상 frame ID/age, GET /api/state,
  웹 모니터 HTTP 200과 기본 motion_enabled=false를 확인한 뒤 종료했다.
  모니터 HTML의 첫 요청은 약 984ms였다. 이는 bridge API timeout을 늘리지 않고
  별도의 정적 페이지 검사 timeout으로 처리했다.
- pip check 통과. 설치 버전은 requirements.lock.txt에 기록했다.
- pyserial 3.5 설치. check_laptop.py는 포트 목록만 읽으며 연결하지 않는다.
- 손 추적 장시간 실행, 실제 FK/IK URDF, MuJoCo, 로봇 통신·동작·충돌·속도는 미검증.
- LeRobot/placo는 아직 미설치. 로봇 모델 확인 후 Python 3.12 환경을 구성해야 한다.

기존 로컬 검증 기록은 이전 작업 폴더의 logs/에 있으며 GitHub에는 업로드하지 않는다.
아래 재검증 실행 시 현재 폴더의 logs/에 새 기록을 만든다.
카메라 재검증은 `& $pacPython verify_camera.py --frames 30`, 실제 서버 재검증은
`& $pacPython verify_server.py`로 실행한다. 후자는 포트 5001이 비어 있을 때만 시작하고
자기가 생성한 프로세스만 종료한다. 실제 로봇 backend나 입력 활성화는 사용하지 않는다.

처음 프로젝트 내부 한글 경로에 만든 `.venv/`에서는 모델 파일이 존재하는데도
MediaPipe graph 로딩이 실패했다. 같은 버전의 ASCII 경로 환경에서는 성공했다.
실행 스크립트는 ASCII 환경을 사용한다. 임시 `.venv` 삭제는 도구 정책으로 차단되어
이전 로컬 작업 폴더에 남아 있지만 실행·패치·Git 추적 대상에서 제외했다.

간편 실행: 첫 PowerShell에서 `./start_tracker.ps1`, 두 번째에서
`./start_mock_bridge.ps1`. 실행 정책으로 차단되면 위의 Python 직접 실행을 사용한다.

## 원본과 변경 이력

`tiltis/codex/pac_minimal/`은 기존 hack_qut.py와 GitHub를 바탕으로 작성한 버전이다.
이후 작업은 이 저장소 폴더에서 한다. 바깥 로컬 pac_minimal은 이전 작업본으로 보존했다.
과거 클라우드 ZIP 자체와 `PAC_2026_existing_code.patch`는 현재 폴더에 없다.
클라우드의 /workspace/scratch 경로는 사용하지 않았다. 기존 ZIP 패치는 적용하지 않았다.
다른 PAC 검사 시스템의 station/sensor 코드는 변경하지 않았다.
원본 비교용 `PAC_2026_local_changes.patch`는 GitHub 업로드 전 초기 노트북 작업본의
검토용 snapshot이며 과거 ZIP에서 받은 패치가 아니다. 이후 수정은 Git 커밋 차이로
검토한다. 이 폴더에 패치를 다시 적용하지 않는다.
