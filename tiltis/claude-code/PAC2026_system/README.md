# PAC2026 크랭크: RGB·열화상 콜드체인 포장 검사 로봇

**윈도우 노트북 한 대**에서 센서와 스테이션을 함께 실행한다(2026-10-06 결정: Mac은 쓰지 않음).

| 프로그램 | 역할 | 폴더 | 포트 |
|---|---|---|---|
| 센서 서버 | Arducam(RGB) + FLIR Boson 320(열화상) + Gemini 2(깊이) 촬영, 정합, 품질·판정, 상자 위치 | `sensor/` | 8001 |
| 스테이션 | SO-101 로봇 순서 제어, 휴대폰 웹 화면, 기록 | `station/` | 8000 |

두 프로그램의 통신 형식은 [CONTRACT.md](CONTRACT.md)에 있다. 같은 PC에서는 `127.0.0.1`로 연결된다. 휴대폰은 `http://<노트북 IP>:8000`에 접속한다.

**가장 빠른 시작**: `setup_sensor.bat -Depth` → `setup_station.bat -Robot` → `run_all.bat -Depth -Robot so101 -RobotPort COM5` (설명은 아래)

## 0. 공통
- 압축은 **OneDrive·iCloud 밖**에 푼다(예: `C:\PAC2026_system`, `~/PAC2026_system`). 가상환경과 촬영 파일이 동기화되면 느려지고 충돌한다.
- **Python 3.12 이상**이 필요하다(LeRobot 0.6.1 요구사항). https://www.python.org/downloads/ (설치 때 "Add python.exe to PATH" 체크).
- 처음 설치할 때 인터넷이 필요하다. 설치 후 실행에는 인터넷이 필요 없다.
- 노트북과 휴대폰을 같은 Wi-Fi나 휴대폰 핫스팟에 연결한다. Windows 방화벽이 처음 물어보면 "개인 네트워크 허용"을 누른다.
- USB: 카메라 3대(RGB, 열화상, Gemini 2 USB3)와 로봇 1대. 노트북 포트가 모자라면 전원형 USB 허브를 쓰고, 두 카메라를 서로 다른 포트(가능하면 좌우)에 꽂는다.

## 1. 센서
```
setup_sensor.bat        :: 가상환경 생성, 패키지 설치, 테스트(카메라 불필요)
check_cameras.bat       :: 카메라 2대를 꽂고 8개 항목 PASS 확인
run_sensor.bat          :: 센서 서버 시작 (카메라 없이 시험: run_sensor.bat -Fake)
```
- Windows 카메라 앱, `capture_app.bat`이 켜져 있으면 카메라가 열리지 않는다. 서버를 켜기 전에 닫는다.
- **대회 로봇 손목 카메라**: 로봇 쪽 코드는 카메라를 열지 않으므로 노트북에 꽂지 않아도 된다. 꽂았는데 "이름의 장치가 2개" 오류가 나면
  `check_cameras.bat`가 보여 준 장치 목록에서 우리 RGB 카메라 이름을 골라 `set PAC2026_VIS_NAME=<이름 전체>` 후 실행한다.
  이름까지 같으면 `set PAC2026_VIS_INDEX=<번호>` (열화상은 `PAC2026_LWIR_NAME` / `_INDEX`).
- 미리보기·수동 촬영·정합 작업: `capture_app.bat`, 정합 도구: `sensor\calib.py`. 자세한 내용은 [sensor/README.md](sensor/README.md).
- **3화면(RGB·열화상·깊이) 동시 보기**
  - 조준·설치할 때(서버 꺼진 상태): `capture_app.bat --depth`
  - 시연 중(서버가 카메라를 쥐고 있을 때): 스테이션 웹 화면의 "실시간 카메라 → 켜기". 센서 `/live.jpg`를 스테이션이 받아 보여 준다.
  - 깊이를 쓰려면 설치 때 `setup_sensor.bat -Depth`.
- **시편 ID 마커(같은 물체 확인)**
  - `sensor\calib\specimen_markers.pdf`(S01~S12, 40mm ArUco)를 100%로 인쇄해 각 시편의 검사면이 아닌 곳, 두 자세 모두에서 RGB에 보이는 곳에 붙인다.
  - 검사 기록 `features.marker_ids / marker_expected / marker_match`와 실시간 화면(일치 초록, 불일치 빨강)에 나온다.
  - 아직 **기록만** 하고 판정에는 쓰지 않는다. 현장 인식률을 본 뒤 불일치를 오류로 처리할지 정한다.
- **3카메라 같은 물체 확인(예: 상자)** — `sensor/objects.py`. 학습 없이 배경 차이로 카메라마다 물체를 찾고 위치 대응으로 같은 물체인지 본다.
  1. 물체를 모두 치우고 배경 저장: `capture_app.bat --depth`에서 `g` (서버 실행 중이면 `POST http://<센서>:8001/object/background`)
  2. 상자를 작업 영역의 서로 다른 4~6곳에 놓으며 매번 `j` (서버: `POST /object/map-point`)
  3. 이후 화면·검사 기록에 `object_status`가 나온다: `same_object`(세 대 모두 찾고 위치 일치), `partial`(일부 카메라 미검출),
     `mismatch`(위치 불일치), `ambiguous`(여러 물체 의심), `unverified`(대응점 4개 미만). 서버 상태 확인: `GET /object/status`
  - 실온 상자는 열화상에서 배경과 온도가 같아 안 보일 수 있다(`partial`). 냉매가 든 상자는 차갑게 보인다.
  - 카메라·조명을 움직이면 배경을 다시 저장한다. 기록만 하고 판정에는 쓰지 않는다.
- PC에 python이 PATH에 없으면 `setup_sensor.bat -Python C:\경로\python.exe`.

## 2. 스테이션 (같은 노트북)
```
setup_station.bat -Robot                     :: 설치 + 테스트 (+ LeRobot, 수 GB. 로봇 없이 시험만 할 땐 -Robot 빼기)
run_all.bat -Fake                            :: 카메라·로봇 없이 센서+스테이션 함께 시험
run_all.bat -Depth                           :: 실제 카메라 3대 + 가짜 로봇
run_all.bat -Depth -Robot so101 -RobotPort COM5   :: 현장: 실제 로봇(가르친 자세로 집기)
```
- `run_all.bat`은 센서와 스테이션을 각각 새 창으로 띄운다. 끌 때는 두 창에서 Ctrl+C.
- 현장 로봇 준비(모두 `.venv-station\Scripts\` 안의 명령):
  1. `lerobot-find-port`로 COM 번호 확인
  2. `lerobot-calibrate --robot.type=so101_follower --robot.port=COM5 --robot.id=so101_follower`
  3. `.venv-station\Scripts\python station\teach.py --port COM5`로 자세 저장
  - 자세한 내용은 [station/README.md](station/README.md).

## 3. 선택: laya 기록 전용 조언자
laya(로컬 소형 판단 모델)가 매 검사마다 확인 / 재촬영 / 사람 확인 중 무엇을 고르는지 **기록만** 한다. 작업 순서는 규칙대로 간다.
- 사전 시험에서 추가 학습 없이 8개 중 5개만 맞혔다. Jev 판정은 FAIL(신뢰도 0.99), 정책은 STOP이라 결정권을 주지 않는다.
- 설치: `setup_station.bat -Advisor` (약 2GB, 행사 전 인터넷이 될 때 설치하고 한 번 실행해 모델을 받아 둘 것)
- 실행: 다른 창에서 `set LAYA_PORT=8766` 후 `.venv-station\Scripts\python -m laya.serve`, 그 뒤 `run_station.bat -AdvisorUrl http://127.0.0.1:8766`
- 기록은 스테이션 DB의 `inspections.advisor` 열에 남는다(규칙 행동, laya 선택, 확률, 일치 여부).

## 4. 테스트
- 설치 스크립트가 테스트를 자동으로 돌린다. 직접 돌릴 때: `.venv-sensor\Scripts\python -m pytest sensor\tests`, `.venv-station\Scripts\python -m pytest station\tests`
- 센서 테스트는 가상 영상으로 정합 정확도와 서버 동작을 확인한다. 스테이션 테스트는 가짜 로봇·센서로 작업 순서 전체를 확인한다.
- 회귀 테스트는 실제 SensorClient의 응답 검증, 근거 없는 정상 응답의 검토 분류, 한글 경로·반복 촬영, 잘못된 경로 입력, 저장 실패 롤백 및 반복 실행까지 포함한다. 화면의 저장 중 상태는 `saving`이며 저장이 끝날 때까지 다음 검사를 시작할 수 없다.

## 5. 폴더 구조
```
CONTRACT.md            두 PC 통신 약속
sensor/                Windows: rig(촬영) · calib/registration(정합) · quality(판정) · server(8001)
station/               스테이션: sequencer(순서) · robot(SO-101/가짜) · app+web(8000) · store(기록) · advisor(laya)
setup_* / run_*        설치·실행 스크립트(.bat). run_all.bat = 센서+스테이션 함께. (.sh는 예전 Mac용, 쓰지 않음)
make_package.py        이 폴더를 zip으로 묶기
```

## 6. 아직 현장에서만 확인할 수 있는 것
- SO-101 LeRobot 호출(`station/robot.py`의 `# 현장 확인` 표시), `teach.py`
- 면별 정합값: 로봇 자세를 정한 뒤 현장에서 계산(`sensor/calib.py homography`, 약 10분)
- 결함 판정 규칙: 시편 실험 뒤 `sensor/quality.py`에 추가. 지금은 품질 검사(흐림, 열화상 정지·포화)만 한다. 품질 통과는 `review`(미판정·검토)로 사람 확인 구역에 보내며 정상 판정하지 않는다. 모의 센서의 `all_ok`는 순서 테스트용 합성 판정이다.

## 7. 선택 뎁스와 동일 시료 데이터 연결

`run_sensor.bat -Depth`는 Orbbec 깊이 원시값·SDK mm 스케일·시각을 보조 기록한다. `-Depth -RequireDepth`는 누락/무효 깊이를 측정 불가로 처리한다. 기본 실행은 깊이를 열지 않으며 `-Fake`와 실제 깊이 혼용은 거부한다. 선택 SDK 버전은 `sensor/requirements-depth.txt`에 있다.

3대의 픽셀 정합은 전체 실행의 필수 조건이 아니다. 시료·면·회차·고유 트리거·취득 시각을 연결하고, 촬영 동안 한 시료를 고정한다는 운영 전제를 명시한다. 깊이 픽셀을 Arducam RGB 픽셀로 간주하지 않으며, 대상의 섭씨 온도나 임의 결함 임계값을 만들지 않는다. 상세 인수조건과 필요한 실측 입력은 [SENSOR_ACCEPTANCE.md](SENSOR_ACCEPTANCE.md)에 정리했다. 현재 결함 규칙이 없어 품질 통과 결과는 계속 `review`다.

## 7. 비전 집기 (방식 C: 깊이로 상자 손잡이를 찾아 집기)

기본은 가르친 자세로 집는다(방식 A). 비전 집기는 아래 현장 절차를 모두 통과했을 때만 켠다.

**준비물: 손잡이(파지부)**: 폭 25mm × 길이 60mm × 높이 15~20mm의 단단한 블록(나무·폼)을 상자 윗면 가운데에 긴 변 방향으로 붙인다.
- 상자(마운자로 160×130×50mm)는 눕힌 채로는 그리퍼(끝 간격 최대 약 125mm, 공식 CAD로 계산)에 들어가지 않는다.
- 크기가 다르면 `station/calib/grasp_config.json`에 `tab_size_mm`, `tab_height_mm`를 적는다.
- **손잡이 없는 작은 상자(10-09 시편: 약 70mm 흰 정육면체)**: 그리퍼 최대 벌림(약 125mm) 안이므로 상자를 바로 집는다.
  설정은 이미 넣어 두었다. 상자를 자로 재서 다르면 두 파일을 같이 고친다.
  - `sensor/calib/object_config.json`: `"box_mm": [70, 70, 70], "tab_height_mm": 0`
  - `station/calib/grasp_config.json`: `"grasp_depth_mm": 22` (윗면에서 아래로 집는 점까지. 집게 길이에 따라 20~25)
  - `teach.py`의 `gripper_open`은 상자 폭 + 15mm 이상 벌어진 값(약 90mm, 관절각 0.9rad 근처)으로 가르친다. 45°(78mm)로는 70mm 상자를 못 지나간다.
  - 테이프·마커는 **집었을 때 집게에 가리지 않는 옆면**에 붙인다. 위에서 집으면 윗면 가운데와 마주 보는 두 옆면이 집게에 가린다.
  - 가상 깊이 시험: 거리 250~500mm, 좌우 ±120mm, 회전 0~45°에서 찾기 결과는 `sensor/tests/test_locate.py`(70mm 사례)와 10-08 시뮬레이션 기록 참고.

**배치**
- 상자는 로봇 바닥 중심에서 약 20cm(18~22cm) 앞에 둔다. SO-101이 집게를 수직으로 내린 채 닿는 높이는 이 거리에서 약 90mm가 한계다.
- 깊이 카메라(Gemini 2)는 **지금처럼 세워 둔 채(책상 위 약 19cm, 약 14° 아래)** 써도 된다(10-06 결정). 단단히 고정하고 상자 앞면이 카메라를 향하게 둔다.
  - 기본 `locate_mode: "front"`: 카메라를 향한 앞면으로 위치·방향을 잡고, 알고 있는 상자 크기(`box_mm`)로 중심·손잡이 위치를 계산한다.
    실측: 앞면 158mm(실제 160), 같은 자리 3회 반복 중심 차이 1.2mm 이내.
  - 위에서 내려다보게 달 수 있으면 `"locate_mode": "top"`(윗면 직접 측정)도 쓸 수 있다. 낮은 각도에서는 윗면 안쪽이 잘려 130mm 변이 102~117mm로 잡혔다.
- `sensor/calib/object_config.json`의 `pick_roi_depth`에 집기 영역(깊이 픽셀)을 적으면 주변 가구를 무시한다.

**현장 순서**: 위에서부터 차례로. 실패하면 거기서 멈추고 방식 A로 시연한다.
1. `lerobot-calibrate` 후 `python station/teach.py --port ... --fk-check`
   - 집게 끝을 자로 위치를 잰 책상 위 점 3곳에 대고 계산값과 비교한다(로봇 바닥 중심 기준 x=앞, y=왼쪽, z=위).
   - 10mm 넘게 틀린 관절이 있으면 `station/calib/joint_map.json`에 부호·오프셋을 적는다. 예: `{"elbow_flex": {"sign": -1, "offset_deg": 0}}`
2. **방식 A 자세를 먼저 가르친다**(`teach.py`). 이렇게 해 두면 시연은 어떤 경우에도 된다.
3. `run_sensor.bat -Depth`를 켜고 `python station/teach.py --port ... --handeye --sensor-url http://<센서 IP>:8001`
   - 손잡이 붙은 상자를 6곳에 놓으며 카메라·로봇 좌표를 맞춘다.
   - **RMS 10mm 이하**일 때만 저장한다.
4. `run_all.bat -Depth -Robot so101 -RobotPort COM5 -PickMode vision -DryRun`으로 검사 1회 → 집게가 손잡이 위 25mm에 오는지 눈으로 확인(15mm 넘게 어긋나면 중단)
5. `-DryRun`을 빼고 실제 집기

- 비전 모드에서 상자를 못 찾거나 계산이 실패하면(손잡이 크기 불일치, 도달 범위 밖, 역기구학 해 없음 등) 가르친 자세로 바꾸지 않고 **멈춘다**.
- 실패 이유는 검사 기록의 `pick` 항목에 남는다.
- **집기 확인(두 방식 공통)**: 닫은 직후·들어 올린 뒤·각 면 촬영 직전에 그리퍼 위치를 읽는다. `gripper_closed`(빈손으로 끝까지 닫은 값)
  근처까지 닫혔으면 놓치거나 떨어뜨린 것으로 보고 촬영하지 않고 멈춘다. 빈 화면을 찍어 "테이프 없음"으로 기록하는 일을 막는다.
  손잡이를 물린 채 `gripper_held`를 가르치면 기준이 정확해진다. 10/9에 빈손으로 한 번, 상자를 물려 한 번 실행해 확인한다.

## 8. 포장 검사 규칙: 뚜껑 이음매 초록 테이프 3곳 + 냉매 유무 (`sensor/rules.py`)

로봇이 상자를 정해진 자세(면 A/B)로 보여 주므로 화면 속 위치가 거의 같다. 그래서 검사할 위치를 영역으로 고정한다.
- **테이프**: RGB 영역 안 검정 픽셀 비율 ≥ 기준이면 붙어 있음. 하나라도 없으면 `suspect`(`tape_missing_T2` 등)
- **냉매**: 열화상 원시값(상자 표면 영역 − 기준 패치 영역) ≤ 기준이면 냉매 있음. 없으면 `suspect`(`coolant_absent`)
  - 기준 근처(여유 폭 안)면 `review`(`coolant_uncertain`)
- 기준값은 **실제 시편으로 맞춘다.** 있음/없음이 겹치지 않을 때만 `validated=true`가 되고, 그 전에는 값만 기록하고 `review`로 둔다.

**현장 순서**
1. 시편 준비: **초록 테이프**를 뚜껑 이음매 3곳에 붙인 상자 / 테이프가 빠진 상자, 냉매 넣은 상자 / 냉매 없는 상자. 이음매가 RGB 카메라를 향하게 놓는다
   - 냉매를 넣고 겉면이 차가워질 때까지 몇 분 기다린다. 기다린 시간도 기록한다.
2. 영역 지정(테이프가 다 붙은 상자를 각 면 자세로 촬영한 폴더에서):
   - `python sensor\rules_calib.py roi-tape --capture <폴더> --face A --auto`: **초록 테이프 3개를 자동으로 찾아** 영역을 잡는다. 확인 그림은 `<폴더>\rules_tape_rois.jpg`. 직접 그리려면 `--auto`를 빼고 드래그 → Enter, 끝나면 Esc
   - `python sensor\rules_calib.py roi-coolant --capture <폴더> --face A`: ① 냉매가 닿는 상자 표면 ② 기준 패치(검은 절연테이프)
3. 기준값 맞추기(종류별 3장 이상):
   - `python sensor\rules_calib.py fit --tape-on … --tape-off … --coolant-on … --coolant-off … --source-id 1009_s1`
4. **다른 세션 촬영으로** 확인: `python sensor\rules_calib.py eval --tape-on … --tape-off … --coolant-on … --coolant-off …`
5. 정상 구역 판정을 켜려면 아래 두 가지도 필요하다(같은 시료 연결 조건). 하나라도 없으면 결과는 계속 `review`(사람 확인)다.
   - 센서 서버로 5번 이상 찍은 세션에서 `python sensor\rules_calib.py timing --session <세션 폴더>` → 시각 차 허용값 저장
   - `run_all.bat ... -SingleSpecimen`: 로봇이 시료 하나를 들고 촬영이 끝날 때까지 움직이지 않는다는 운영 전제

- 테이프 3곳은 두 촬영 자세(면 A/B) 중 어디서든 RGB에 보여야 한다. 윗면이나 뒷면에 있으면 그 면을 보여 주는 자세가 필요하다.
- 실제 로봇 모드에서는 가짜 카메라 결과(`-Fake`)를 정상으로 통과시키지 않는다(`simulated_inspection`).
