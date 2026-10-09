# 깊이 기반 위치 변경 집기

Claude의 `sensor/locate.py`, `station/grasp.py`, FK/IK와 기존 분류 sequencer를 재사용한다. 이 폴더는 관측 검증, 이동 직전 재확인과 읽기 전용 미리보기를 제공한다. 별도 SDK/제어기를 만들지 않는다.

카메라에 보이며 도달 가능한 책상 작업 영역의 **상자 하나**를 대상으로 한다. 매 작업 새로운 깊이 관측 → 카메라–로봇 좌표 변환 → 접근·집기·들기 IK를 계산한다. 상자를 몇 cm 옮겨도 집기 위치를 다시 가르치지 않는다. 기존 검사면·파랑/빨강 분류 자세와 그리퍼 기준은 재사용한다.

Claude의 현장 옆 집기 계획을 통합했고 공유 시편 설정은 `grasp_mode=side`다. `top` 모드도 보존했다. 옆 집기는 상자 바닥 중심·측정 높이로 집는 높이를 계산하고 수평 접근한다. 37~47cm 반경은 모델의 후보 설정이며 승인된 실기 범위가 아니다. 상자 회전 허용 범위·실제 개구 폭·자기 정렬은 아직 실측하지 않았다. 가림, 여러 상자, 뒤집힘, 시야 밖과 도달 불가능한 위치도 보장하지 않는다.

## 바뀐 연결

- 센서의 상자 탐색 기본 영역은 전체 깊이 영상. 책상 평면은 별도 `table_roi_depth`(기본 아래 45%)에서 계산한다. `pick_roi_depth`를 설정하면 그 안에서만 찾는다. 픽셀 영역은 물리적 로봇 작업 범위를 대신하지 않는다.
- 같은 종류의 상자가 여러 개거나 서로 다른 후보 모델이 동시에 검출되면 거부한다. 클러터/가림 때문에 검출하지 못한 물체의 부재까지 보장하는 것은 아니다.
- `captured_at_s`는 중앙값 계산에 사용한 첫 프레임의 수신 시각, `last_frame_at_s`는 마지막 프레임, 기존 `time`은 계산 완료 시각이다. 오래된 서버의 `time`만으로는 신선한 영상이라고 승인하지 않는다.
- `GuardedVisionPicker`는 서로 다른 관측 3회에서 위치 5mm·회전 10° 이내 안정성, 영상 나이 2초 이내, 올바른 frame/단위/유한값, hand-eye 강체 변환·점 4개 이상·RMS 10mm 이하를 확인한다. 이 수치는 조정 가능한 소프트웨어 기본값이며 실측 안전 기준이 아니다.
- 기존 IK가 실패하거나 허용 수평 거리 밖이면 거부한다. IK 계산 후에도 영상 나이를 재검사한다. 접근 후 다시 관측해 상자가 움직였으면 하강·그리퍼 닫기를 수행하지 않고 기존 오류/stop 흐름으로 간다. 자동 추적 재시도나 자동 재시작은 하지 않는다.
- 화면 가장자리 8px 이내 후보는 거부한다. `grasp_config.json`의 `workspace`에 실측 `frame=base_link`, `units=m`, `min/max` 좌표가 없으면 계획을 승인하지 않는다. 접근·집기·들기 각 IK 해의 FK 도구 위치가 모두 이 범위 안인지 확인한다. 도구 점의 범위 확인은 로봇 전체 링크의 충돌 검증을 대신하지 않는다. 전체 영상에서 나온 후보를 모두 책상 위 상자라고 간주하지 않는다.
- hand-eye 티칭과 집기 계산이 같은 `camera_grasp_point`를 쓴다. 손잡이 없는 상자를 보정할 때 이전 코드가 윗면을 참조하고 집기에서 20~35mm 아래를 참조하던 불일치를 수정했다.
- 옆 집기 보정에서도 같은 도구 기준점을 사용한다. 비전 집기 뒤 고정 `lift` 자세로 돌아가던 연결을 제거했다. 검사 재촬영 때도 해당 작업에서 계산한 들기 관절값을 쓴다. 비전 계획이 실패하면 티칭 집기 위치로 대체하지 않는다.
- 설치 보정/workspace가 없으면 홈·그리퍼 명령 전 거부한다. `GET /api/pick/readiness`는 사용 모드와 설치 준비 상태를 읽기 전용으로 보여 준다. `GET /api/status`의 `pick_mode`로 실제 선택된 `vision/taught`를 확인한다.

## 포트를 열지 않는 확인

이 폴더에서 실행한다. Python은 설치된 station 환경을 재사용한다.

```powershell
& 'C:/PAC2026_system/.venv-station/Scripts/python.exe' preview.py --sensor-url http://127.0.0.1:8001
```

기본 코드는 팀 저장소의 `claude-code/PAC2026_system`을 사용한다. 다른 기존 설치를 검토하려면 `--system-dir C:/PAC2026_system`을 지정한다. `--handeye`에 실측 보정 파일을 지정할 수 있다. 없으면 실패 이유를 출력하며 가상 보정값을 생성하지 않는다. 종료 코드 0은 수학적 계획 생성 성공, 2는 준비되지 않음이다. 두 경우 모두 `motion_enabled=false`이며 로봇 포트를 열지 않는다. 실제 구동 완료를 의미하지 않는다.

## 기존 웹/분류 흐름에 연결

팀 저장소의 `run_station.ps1 -PickMode vision`은 이 폴더의 `station_app:app`을 사용하고 기존 sequencer의 picker를 검증 picker로 교체한다. 전체 `tiltis/claude-code` 및 `tiltis/codex` 구조가 필요하다. `-VisionPreview`만 쓰면 티칭 집기 설정을 유지하며 `GET /api/pick/preview`를 추가한다. 실행 중 분류 작업이 있으면 미리보기는 409로 거부한다. 미리보기 API 자체는 모터 명령을 보내지 않는다.

현재 실행 중인 `C:/PAC2026_system`과 8000/8001 서버는 이번 소스 수정으로 자동 교체되지 않는다. 기존 설치에 파일을 덮어쓰거나 티칭을 종료하지 않는다. 이 구조로 센서/스테이션을 배포하는 작업은 다른 작업 종료 후 별도로 수행한다. `PICK_DRY_RUN=1`은 실제 로봇이면 접근 이동과 홈 복귀를 수행하므로 읽기 전용이 아니다.

## 현장 연결 조건

카메라와 로봇 바닥을 고정하고 먼저 URDF/관절 단위·부호·도구 기준점의 FK를 실측 비교한다. 그 뒤 여러 위치(6곳 권장)의 동일한 집는 점 쌍으로 기존 hand-eye 보정을 **설치 시 한 번** 수행한다. 이는 작업별 동작 학습이 아니다. 상자가 이동해도 보정값을 재사용하며, 카메라/로봇 설치를 옮기거나 도구 기준점을 바꾸면 재보정한다. 과거 손잡이 중심 방식으로 얻은 보정 파일은 새 집는 점과 일치하는지 확인한다. 공유 설정의 `workspace=null`은 현장 실측이 아직 필요하다는 표시다.

실제 집게 폭, 손가락과 상자/책상 충돌, 현재 위치→접근·하강·들기 경로의 링크 충돌, 관절 범위, 실제 속도/가속도, 통신 단절/stop 성공과 두 분류 위치를 검증해야 한다. 기존 `robot.stop()`의 hold 예외 무시 문제는 남아 있다. IK 성공과 관측 검증으로 이 조건들을 충족했다고 주장하지 않는다. 현장 확인 및 사용자의 실기 승인 전 실제 로봇 모드로 시작하지 않는다.

## 테스트

```powershell
& 'C:/PAC2026_system/.venv-station/Scripts/python.exe' -m pytest tests -q --rootdir . --confcutdir . -o 'addopts='
```

센서의 이동/회전·탐색 영역·다중 상자 회귀 테스트는 공유 구현의 `sensor/tests/test_pick_area.py`에 있다. 실제 관절/EE와 영상·명령을 동기화한 학습 데이터 수집은 별도 작업이며 이번 미리보기 결과는 학습용 실측 데이터가 아니다.

`test_each_cycle_recomputes_pick_for_shifted_box_without_teaching`는 같은 가상 설치 보정으로 흰/갈색 상자를 각각 3곳에 옮겨 3면 검사와 파랑 분류를 연속 실행한다. 모의 로봇에는 집기·들기 티칭 자세가 없으며 새 관측의 목표점과 실제 FK 계산 결과를 비교한다. 재촬영·미보정 설치의 이동 전 거부도 검사한다. 이 시험은 소프트웨어/모델 검증이며 실제 로봇 집기를 의미하지 않는다.

## 최신 통합 코드와 현장 영상 확인

```powershell
& 'C:/PAC2026_system/.venv-station/Scripts/python.exe' preview_server.py --site-dir C:/PAC2026_system --port 8002
```

`http://127.0.0.1:8002`는 공유 최신 기구학 코드와 현장 보정/기존 센서 API를 읽는 별도 미리보기다. 카메라/로봇 핸들을 열지 않으며 `/api/run`과 모터 명령이 없다. 현재 영상, 깊이 상자 위치와 변 방향 후보, 실측 workspace/센서 촬영 계약의 준비 상태를 표시한다. RGB–depth 정합/동기화 reader가 없는 경우 `sam_live_connected=false`다. 기존 8000/8001은 유지한다.

Claude 현장 코드의 턱 TCP 오프셋·높이/접근 조절·가까운 IK 해 선택·재집기 시 home·오차 로그·면별 테이프 판정은 보존했다. 턱 보정 때문에 상자 방향을 radial로 다시 돌리지 않는다. 도달 불가이면 거부한다. `dry_stage=grasp` 설정은 wrapper에서도 유지하고 하강 전에 관측을 재확인한다. 이 dry 모드는 실제 이동이 있으므로 8002 읽기 전용 확인과 구별한다.

보정 티칭의 카메라 점과 로봇 점은 같은 파지 기준점이어야 한다. 자동 보정에서 그리퍼 개방률이 상자 높이 비율을 덮어쓰던 오류를 수정했고, 수동/자동 모두 설정된 턱 중심 오프셋을 FK에 적용한다. **이 수정 전 만든 hand-eye 파일은 해당 기준점에 맞는지 확인해야 한다.** 기존 현장 파일을 자동 재작성하지 않는다. 실측 workspace 없이 로봇 작업 범위를 임의로 채우지 않는다.

## 2026-10-09 SAM 정렬/놓기 확인

공유 `grasp.py`의 `side_alignment=radial`은 Claude 현장 방식으로 보존했다. Codex GuardedVisionPicker는 명시적으로 `box`를 선택해 측정한 상자 두 축을 hand-eye로 회전하여 접근/집게 방향에 사용한다. 턱 TCP 오프셋 보정 후에도 방향을 유지하고 IK 불가 시 radial로 대체하지 않는다. SO101 5축은 먼 위치의 임의 옆집기 각도를 풀지 못할 수 있으며, 현재 현장 좌표의 새 각도 정렬은 실기 검증되지 않았다.

`placement.py`는 실제 집기 관절 FK와 관측 상자 윗면/치수로 상자 모서리를 tool frame에 결합하고, 놓기 관절 FK에서 예상 기울기·바닥 높이·분류 영역 전체 포함을 확인한다. `require_flat_placement=true`이면 측정한 placement 설정이 없는 설치를 preflight에서 거부한다. `station_app.py`의 새 제어 진입점에 이 요구를 적용했다. `placement`는 source_id/validated/frame=base_link/units=m, normal_base/plane_d_m, max_tilt_deg, bottom_clearance_m[min,max], zones_xy_m의 ok/human[min_xy,max_xy]가 필요하다. 가상 예시를 현장에 저장하지 않았다.

공유 sequencer는 선택적 capture_held_box/verify_at_release hooks를 연결한다. 재집기의 새 관측을 사용하며, 실패/관절 읽기 오류에서는 집게를 열기 전에 기존 stop 경로로 끝낸다. 가상 테스트에서 옆 자세·높은 낙하·분류 영역 이탈·미측정 설정 거부와 실제 release 전 검사 순서를 확인했다. box slip/접촉/놓은 뒤 안정성은 이 FK 모델로 증명하지 못한다. 기존 실기 8000은 교체하거나 재시작하지 않아 이 guard가 적용된 상태가 아니다.

## 카메라 윤곽 및 검사 이유 표시

8002는 기존 8001의 합성 영상을 읽어 첫 RGB 패널의 갈색 상자 후보를 빨간 윤곽으로 표시한다. 기존 골판지/초록 테이프 색 기준을 재사용하는 표시 전용 기능이며 SAM 결과나 불합격 색, 제어 목표가 아니다. 서로 붙은 상자는 하나의 영역으로 묶일 수 있고 흰 상자는 지원하지 않는다. RGB 패널 규격이 바뀌면 box_overlay.annotate_jpeg의 rgb_width(현재480)를 함께 변경해야 한다.

8000의 기존 reasons/features를 웹의 PacReasons로 설명한다. 예: 테이프 1개 누락(2/3개 관측), 아랫면 결함(벌어짐 의심). 미검증/측정 불가를 결함으로 바꾸지 않으며 면간 누락 개수를 합산하지 않는다. 8002의 최근 판정은 저장 기록이고 현재 라이브 물체와 자동 연결하지 않는다. 현재 실행 오류는 별도로 표시한다. station/web/index.html은 FileResponse라 UI 파일 적용 후 새로고침만 필요하고 로봇 서버 재시작은 필요 없다. 노트북 station 카메라는8002를 사용하고 실패하면 원본 /sensor-live로 돌아간다. 기본8000/8001 포트 기준이며 원격 브라우저는 원본 영상을 사용한다.

UI 테스트: `node --test station/tests/test_reason_presentation.cjs` (공유 시스템 폴더). Python 표시/API 테스트: `python -m pytest tests/test_box_overlay.py tests/test_preview_server.py -q --rootdir . --confcutdir . -o addopts=` (이 폴더).
