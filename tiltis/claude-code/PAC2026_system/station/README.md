# 스테이션 (로봇 + 작업 순서 + 모바일 웹 + 기록)

SO-101 로봇 팔이 지그에서 포장을 집어 설정된 검사면(A·B 또는 A·B·C)을 고정 카메라에 보여 주고, 센서 서버의 판정에 따라 파랑 또는 빨강 영역에 놓는다. 이 폴더는 로봇 제어, 작업 순서, 휴대폰용 웹 화면, 기록(SQLite/CSV)을 담당한다. 센서 서버와의 통신 약속은 [../CONTRACT.md](../CONTRACT.md)를 따른다.

## 파랑·빨강 영역 연결

| 최종 판정 | 영역 | 기존 API/DB 키 | 현장에 가르칠 자세 |
|---|---|---|---|
| 모든 검사면 `no_anomaly` | 파랑(정상) | `ok` | `bin_ok` |
| `suspect` | 빨강(불량 의심) | `human` | `bin_human` |
| `review` 또는 재촬영 후 `unmeasurable` | 빨강(확인 필요) | `human` | `bin_human` |

센서 오류·수신 단절·면 누락·알 수 없는 판정은 분류를 중단한다. 영역의 실제 좌표를 색만으로 추정하지 않는다. 두 영역에서 **상자를 내려놓을 자세**를 `teach.py`로 기록하며, 배치가 바뀌면 다시 가르친다. 기존 자세 파일과 키는 그대로 유지한다.

`GET /api/status`는 `zones`, 결정된 `destination`, `robot_mode`를 표시한다. `destination`은 목표이며 `placed_bin`·`routing_status`가 배치 진행 상태다. `mock`의 완료는 실제 로봇 이동이 아니다. 새 목적지 메타데이터는 상태 응답용이며 DB/CSV는 기존 분류 키를 사용한다. 실기 연결·경로·관절 한계·충돌·실제 속도 및 정지 검증과 사용자 승인 후에 실제로 움직인다.

| 파일 | 역할 |
|---|---|
| `robot.py` | `RobotBase`, `MockRobot`, `So101Robot`(LeRobot) |
| `teach.py` | 실기 자세 티칭 / 재생 확인 |
| `sensor_client.py` | 센서 서버 HTTP 클라이언트(오류는 `status="error"`로 변환) |
| `mock_sensor.py` | 센서 서버 모의 구현(포트 8001) |
| `sequencer.py` | 검사 작업 순서, 일시정지/중단, 재촬영 규칙 |
| `store.py` | SQLite 기록, CSV 내보내기 |
| `app.py`, `web/index.html` | 웹 API(포트 8000)와 모바일 화면 |
| `poses.example.json` | 자세 파일 예시(자리표시 0) |

## Mac 설정

Python 3.10 이상.

```bash
cd station
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests -q        # 목업 테스트
```

## 목업으로 전체 흐름 실행 (로봇/센서 없이)

터미널 2개, 둘 다 `station` 폴더에서 venv를 켠 상태로 실행한다.

```bash
# 터미널 1: 모의 센서 (시나리오: all_ok, suspect_B, unmeasurable_once, unmeasurable_twice, sensor_error, random)
MOCK_SCENARIO=all_ok uvicorn mock_sensor:app --port 8001

# 터미널 2: 스테이션 (기본값 ROBOT=mock)
uvicorn app:app --host 0.0.0.0 --port 8000
```

- 같은 Wi-Fi의 휴대폰에서 `http://<맥-IP>:8000` 으로 접속한다. (Mac IP: `ipconfig getifaddr en0`)
- 시나리오는 실행 중에도 바꿀 수 있다: `curl -X POST localhost:8001/mock/scenario -H 'content-type: application/json' -d '{"name":"suspect_B"}'`
- 기록은 `~/PAC2026_data/station.db`(환경변수 `DB`로 변경 가능)에 쌓이고 화면의 CSV 링크(`/api/runs.csv`)로 받는다.

## 현장 절차 (실기 SO-101)

1. LeRobot 설치: 공식 SO-101 가이드대로 `git clone https://github.com/huggingface/lerobot.git && cd lerobot && pip install -e ".[feetech]"` (같은 venv에서).
2. 포트 찾기: `lerobot-find-port` (팔 USB를 뺐다 꽂으며 확인). 예: `/dev/tty.usbmodem5A460812341`
3. 보정: `lerobot-calibrate --robot.type=so101_follower --robot.port=<포트> --robot.id=<id>` (명령 옵션은 설치된 버전의 공식 문서로 확인)
4. 자세 티칭: `python teach.py --port <포트> --id <id>`
   토크가 꺼지므로 팔을 손으로 옮긴 뒤, `home`, `pick_approach`, `pick`, `lift`, `face_A`, `face_B`, `bin_ok`(파랑 영역), `bin_human`(빨강 영역), `gripper_open`, `gripper_closed`를 차례로 입력하고 Enter. 3면 검사에는 `face_C`도 가르친다. 결과는 `poses.json`에 저장된다(`poses.example.json` 참고).
   - `gripper_closed`는 **빈손으로 끝까지 닫은** 상태에서 저장한다(집을 때 이 값으로 조여 쥔다).
   - 선택: 손잡이를 물린 채 손으로 닫고 `gripper_held` 저장 → 집기 확인 기준이 정확해진다.
   - **집기 확인**: 닫은 직후, 들어 올린 뒤, 각 면 촬영 직전에 그리퍼 위치를 읽는다. 끝까지 닫혔으면(빈손) 또는 떨어뜨렸으면
     촬영하지 않고 멈춘다(`집기 실패(pick): nothing_held`). 기록은 결과의 `grasp_checks`.
5. 재생 확인: `python teach.py --port <포트> --id <id> --replay` — 이동마다 Enter로 확인하며 천천히 움직인다. 팔 주변을 비우고, 위험하면 전원 스위치를 끈다.
6. 실행:
   ```bash
   ROBOT=so101 ROBOT_PORT=<포트> ROBOT_ID=<id> SENSOR_URL=http://<센서PC-IP>:8001 \
     uvicorn app:app --host 0.0.0.0 --port 8000
   ```

환경변수: `SENSOR_URL`(기본 `http://127.0.0.1:8001`), `ROBOT`(`mock`|`so101`), `ROBOT_PORT`, `ROBOT_ID`, `POSES`(자세 파일 경로), `DB`(DB 경로), `MOCK_SPEED`(목업 속도 배율, 기본 0.1).

## 상자 위치가 달라지는 자동 집기

`PICK_MODE=taught`는 저장된 집기 자세를 사용한다. 위치가 바뀌는 상자에는 전체 팀 체크아웃의 `run_station.ps1 -PickMode vision`을 사용한다. 기존 SDK/IK와 Codex 검증 picker를 연결해 매 작업 깊이에서 위치·높이를 새로 관측하고 접근·집기·들기를 계산한다. 옆 집기는 `grasp_mode=side`, 기존 위에서 집기는 `top`이다. 비전 집기와 재촬영에서 고정 집기/들기 자세로 되돌아가지 않는다. 검사면과 두 분류 영역 자세는 재사용한다.

카메라–로봇 좌표 보정은 설치 시 한 번 필요하며 상자가 몇 cm 옮겨졌다고 다시 가르치지 않는다. 카메라나 로봇 바닥을 옮겼을 때 재보정한다. FK 도구 기준점과 실측 workspace를 확인해야 하며, 공유 설정의 `workspace=null`은 실기 승인값이 없다는 표시다. 보정/workspace 미완료는 홈·그리퍼 명령 전에 거부한다. 실행된 앱의 `/api/status` `pick_mode`와 `/api/pick/readiness`로 모드/준비 상태를 확인한다. [읽기 전용 미리보기·검증·현장 연결 조건](../../../codex/vision_pick/README.md)을 먼저 따른다. 실행 중인 배포본은 소스 변경으로 교체되지 않는다.

## 안전

- 화면의 "일시정지"와 "중단"은 소프트웨어 요청이며 비상정지가 아니다. 진행 중인 이동은 끝난 뒤 다음 동작 직전에 멈춘다. 물리적 정지는 로봇 전원 스위치다.
- 센서 오류, 자세 안정화 실패, 로봇 예외가 나면 즉시 정지하고(`robot.stop()`) 이후 동작을 하지 않는다.
- `So101Robot`의 `# 현장 확인` 줄은 이 PC에서 실행해 보지 못했다. 현장에서 처음 한 번 천천히 확인할 것.
