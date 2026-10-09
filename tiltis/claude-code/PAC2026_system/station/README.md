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

## HOME에서 내려온 뒤 앞으로 집기

`/pick-path`는 집기 전 접근 순서와 높이를 설정하는 화면이다. 기본값 `legacy`는 기존 집기를 유지한다. `home_descend_forward`는 **HOME의 X/Y·방향을 유지한 수직 하강 → 같은 높이에서 상자 쪽으로 전진 → 기존 마지막 집기 접근 → 집게 닫기**로 동작한다. 최초 집기와 빈손 재집기에 모두 적용하며, 뒤의 검사·분류 경로는 별도다.

집기 높이 보정은 카메라로 계산한 집기 높이에 **−10~+30 mm**를 더한다. HOME에서 내려오는 거리 자체를 입력하는 값이 아니다. 화면에서 경로 미리보기를 통과한 다음 설정 적용을 누르면 다음 검사부터 사용한다. 설정은 `station/calib/pick_path.json`에 저장된다. 새 방식은 120초 이내의 미리보기 확인값, 같은 높이 설정, 동일한 자세·보정 정보가 모두 맞아야 저장할 수 있다. 설정 중 검사 시작과 검사 중 설정 변경은 서로 차단된다.

적용 시 검증한 자세·보정 정보의 지문(`accepted_geometry_sha256`)도 저장한다. HOME을 다시 저장하거나 해당 정보가 바뀌면 새 경로 실행이 차단되고 `needs_preview=true`로 표시된다. 서버를 재시작해도 차단을 유지하며, 새 미리보기·적용을 마쳐야 다시 사용할 수 있다. 자동으로 기존 경로로 바꿔 실행하지 않는다. 별도 Codex guard 진입점도 같은 `bind_picker` 연결을 사용해 설정에서 검증하는 picker와 실제 실행 picker를 일치시킨다.

| API | 역할 |
|---|---|
| `GET /api/pick-path/settings` | 적용 방식·높이·저장 HOME의 관절 범위와 TCP 위치 확인 |
| `POST /api/pick-path/preview` | 현재 상자를 보고 경로 계산, 장비 이동 없음 |
| `PUT /api/pick-path/settings` | 검증된 설정 저장, 장비 이동 없음 |
| `POST /api/pick-path/home` | 현재 관절을 기존 스테이션 연결로 읽어 HOME 저장 |

이 화면과 API는 팔을 이동시키거나 토크를 변경하지 않는다. HOME 저장은 원본 자세 파일을 백업한 뒤 유효한 현재 관절과 책상 여유를 확인해 원자적으로 교체하며, 다른 자세와 보정은 보존한다. 별도 `teach.py`나 두 번째 COM8 연결을 열지 않는다.

`home_approach.py`가 하강·전진 전체 구간의 IK, 관절 한계, 보간 중 수직/수평 경로·방향과 바닥 여유를 확인한다. 수직 하강에서는 HOME 방향을 유지하고 전진하며 접근점 방향으로 보간한다. 도달 불가 시 대각선 이동이나 자유 회전으로 대체하지 않는다. sequencer는 HOME 이동 전 설정을 확인하고, 하강 전 실제 HOME 도달·하강/전진 후 도달을 엄격한 안정화와 관절 FK로 확인한다. `home_path_plans`·`home_path_checks`에 기록한다. 계산 경로 그림은 물리적 장애물·실제 추종을 검증한 영상이 아니다.

현재 저장 HOME의 `wrist_roll` −163.38°가 모델 하한 −157.21° 밖이어서 새 방식 활성화는 차단된다. 정상 범위의 HOME 또는 실제 장비와 모델/보정의 일치 여부를 확인해야 하며, 한계를 넓히거나 각도를 임의 치환해 통과시키지 않았다. **이번 HOME 설정 기능은 아직 실행본에 적용하지 않았고**, 빈 팔을 지지한 상태에서 서버 재시작 승인을 기다리는 중이다. 새 경로의 실기 이동은 검증하지 않았다.

검증은 station 전체 **273 passed, 4 warnings (126.90s)** 이후 명령 실패 회귀 2개를 추가해 HOME/분류/기존 순서 부분 **138 passed, 1 warning (10.30s)**를 재실행했다. 최종 HOME 관련 4개 파일(`test_home_approach.py`, `test_home_path_sequence.py`, `test_pick_path_api.py`, `test_pick_path_web.py`)은 **77 passed (6.73s)**: 경로 19개·순서 37개·API 19개·UI 2개다. HOME 변경 후 재시작 시 차단 유지와 실제 실행 picker 연결 회귀를 포함한다. 앞선 전체 실행 이후의 부분 검증이며 범위가 겹치므로 숫자를 합산하지 않는다.

## 검사 후 들어 올려 옮기기

`So101Robot`은 마지막 검사 자세에서 바로 낮은 분류 자세로 이동하지 않고, **제자리 상승 → 높은 위치에서 옆으로 이동 → 내려놓을 위치까지 하강 → 그리퍼 열기 → 수직 상승 → home** 순서로 실행한다. 기존 검사·파랑/빨강 판정과 가르친 놓기 자세는 재사용한다.

- `bin_ok`·`bin_human`과 같은 XY에서 더 높은 `bin_ok_up`·`bin_human_up` 자세가 필요하다. 상자별 `_brown`·`_white` 접미사도 지원한다. 2026-10-09 현장 상단 자세는 놓기 자세보다 120 mm 높지만, 다른 배치에도 이 값을 그대로 적용하지 않는다.
- 검사 직후 상승 목표는 현재 TCP보다 최소 15 mm 위와 목적지 상단 높이 중 높은 쪽이다. 이 15 mm는 SO-101의 해당 검사 자세에서 방향을 유지한 수직 IK를 고려한 값이다. 상자 치수·턱 중심 오프셋·책상 기준 높이로 계산한 최소 여유를 확보하지 못하면 옆 이동 전에 거부한다.
- `clearance_transfer.py`가 전체 경로를 먼저 계산한다. 관절 한계, 관절 보간 중 TCP 높이, 수직 구간의 XY·방향·상하 진행을 확인한다. 상단 자세 누락이나 IK/경로 검사 실패를 낮은 직접 이동으로 대체하지 않는다.
- 각 단계 후 `wait_settled`와 실제 관절 관측의 FK를 확인한다. 목표 위치 오차 5 mm·방향 오차 5° 이내이고, 상승·옆 이동·상승 복귀 완료 시 요구 높이에 도달해야 한다. 촬영 단계의 `is_still` 예외로 이 검사를 통과시키지 않는다. 상승·옆 이동 후 파지도 다시 확인한다.
- 놓기 직전 기존 `verify_at_release` 훅이 있으면 유지한다. 하강/놓기 검사 실패 시 집게를 열지 않고 정지한다. 놓은 뒤 상승 실패 시 `placed_bin` 기록을 보존하고 home으로 이동하지 않는다. 결과의 `transfer_plan`·`transfer_checks`에 계획과 단계별 확인을 기록한다.
- 명령 시간은 관절 20°/s와 FK 표본 기준 TCP 50 mm/s를 넘지 않도록 늘어난다. 실제 속도·가속도 측정이나 물체 미끄러짐·주변 장애물·바닥 접촉 검증을 대신하지 않는다. 모형의 상자 여유 계산은 턱 중심에 상자를 잡고 미끄러지지 않는다는 가정이며, home 경로는 기존 가르친 경로를 사용한다.

중단은 다음 경유점 경계에서 `stop()`으로 현재 위치를 유지한다. 즉시 작동하는 비상정지는 아니다. `MockRobot`처럼 계획 API가 없는 기존 어댑터는 이전 흐름을 유지하되, 가르친 `bin_*_up`이 있으면 놓은 뒤 해당 자세로 상승한다.

장비 없이 회귀 테스트하기(`PAC2026_system` 폴더):

```powershell
python -m pytest station/tests/test_clearance_transfer.py station/tests/test_transfer_robot.py station/tests/test_transfer_sequence.py station/tests/test_sequencer.py -q --disable-warnings --rootdir . --confcutdir . -o addopts=
```

2026-10-09 위 통합 테스트 **167 passed, 1 warning (15.83s)**. 적용 실행본의 검사 B/C × 정상/부적격 × 카메라 구역 배치(정보 없음/정상/뒤바뀜) **12개 조합도 오프라인 통과**했다. 실행본은 동시 작업 중 추가된 Claude의 `/zones` 기반 목적지 선택·처리 완료 표기를 보존하며, 해당 변경은 공유 저장소에 아직 별도 통합되지 않았다. 사용자 재연결 승인 후 **22:36 KST 배포·하드웨어 연결을 확인**했고, 상태는 `idle`/`busy=false`, 비전 집기·B/C 검사다. 새 검사/분류 사이클은 시작하지 않았다. 새 경로의 충돌 여유, 부하 상태의 추종·속도·안정적인 놓기는 아직 검증하지 않았다.

| 파일 | 역할 |
|---|---|
| `robot.py` | `RobotBase`, `MockRobot`, `So101Robot`(LeRobot) |
| `clearance_transfer.py` | 현장 자세·상자 치수·턱 오프셋을 이용한 상승/분류/하강/복귀 경로 검증 |
| `home_approach.py` | HOME 수직 하강·수평 전진의 전체 IK/관절/경로 검증 |
| `pick_path_api.py`, `web/pick_path.html` | 집기 경로·높이 설정, 이동 없는 미리보기, 기존 연결을 통한 HOME 기록 |
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

## 안전

- 화면의 "일시정지"와 "중단"은 소프트웨어 요청이며 비상정지가 아니다. 진행 중인 이동은 끝난 뒤 다음 동작 직전에 멈춘다. 물리적 정지는 로봇 전원 스위치다.
- 센서 오류, 자세 안정화 실패, 로봇 예외가 나면 즉시 정지하고(`robot.stop()`) 이후 동작을 하지 않는다.
- `So101Robot`의 `# 현장 확인` 줄은 이 PC에서 실행해 보지 못했다. 현장에서 처음 한 번 천천히 확인할 것.
