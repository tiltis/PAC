# Claude Code 폴더 인계 — 2026-10-09

## 가져온 기존 구현

`0e515a7`의 `tiltis/PAC2026_system/`을 `PAC2026_system/`으로 이동했다. Git 비교에서 기존 **88개 시스템 파일 모두 R100**(내용 동일)로 확인했다. 실행 중인 배포본은 바꾸지 않았다. 이전 작성자를 이 폴더 이름으로 단정하지 않는다.

센서·스테이션 실행과 검증은 시스템 README와 SENSOR_ACCEPTANCE.md를 따른다. 이번 이동에서 센서/스테이션 테스트를 새로 실행했다고 주장하지 않는다.

## Codex가 확인한 재사용 경계

- `station/robot.py`: LeRobot SO101Follower, `use_degrees=True`, 관절 보간과 현재 관절 hold를 제공한다. `send_action()` 반환 목표를 확인하지 않고 `stop()`의 통신 예외를 무시하므로 손목 안전 계약에 그대로 연결할 수 없다. 수정 후보이며 이번 이동에서 변경하지 않았다.
- `station/kinematics.py`: numpy 기반 FK/IK, 입력 rad, LeRobot 변환 deg. 접근 방향·yaw 제약과 손목의 전체 EE 자세 유지 계약이 다르다. 교체 전에 잔차와 단위 테스트가 필요하다.
- `station/assets/so101_new_calib.urdf`가 있다. 실기 모델·frame·보정값과 일치하는지는 아직 확인되지 않았다.
- `station/requirements-robot.txt`의 LeRobot 버전과 저장소 본체 API가 다를 수 있다. 실제 환경 버전을 확인한다.

## 다음 작업

Claude Code 2.1.263 첫 리뷰는 OAuth 인증 만료로 실패했다. 이후 재인증과 실제 API 응답을 확인했고, 읽기 전용 교차 리뷰가 정상 종료했다. [실행 기록](REVIEW_STATUS.md), [리뷰 원문](REVIEW_CODEX_2026-10-09.md), [Codex 반영 근거](../codex/HANDOFF.md)에 결과를 남겼다.

Codex의 [HANDOFF](../codex/HANDOFF.md), `pac_minimal/robot_bridge.py`, `so101_backend.py`, 관련 테스트를 검토한다. 손목과 검사 흐름은 별도로 실행하고, 적합한 SDK·URDF·정지 개선만 근거를 기록하며 재사용한다. 실제 연결은 사용자 모델·포트 정보와 현장 검증 후 진행한다.

## 다음 Claude 작업의 출발점

Codex는 정지 원인 보존, 거부 명령 로그, SDK 카메라 설정 차단, arm 직후 0 dt 처리와 최적화 모드 replay를 수정했다. 56개 unittest 및 일반/-O 120프레임 재생 통과를 직접 기록했다. 다음 작업은 이 변경과 반영 표를 먼저 읽고 이어서 한다.

station 쪽에는 stop의 hold 예외 무시, `_lock` 미사용, 동작 중 `_halt`/sequencer 취소 전달 여부가 검토 후보로 남았다. 실기 연결 전에 별도의 재현 테스트와 중단 계약을 정하고 수정해야 한다. station IK는 접근축/yaw 계약이므로 전체 자세를 유지하는 손목 backend에 그대로 교체하지 않는다. 기존 88개 시스템 소스는 이번 손목 수정에서 변경하지 않았다.

## 2026-10-09 노트북 작업 반영 (tiltis, 커밋 f09b907 → 이 커밋으로 경로 정정)

f09b907은 옮기기 전 경로 `tiltis/PAC2026_system/`에 다시 올라갔던 것이라 이 커밋에서 지우고, 같은 내용을 `claude-code/PAC2026_system/`에 넣었다. 로컬 배포본 `C:\PAC2026_system`과 동일하다.

### 바뀐 것(모두 센서·스테이션 코드 안, 손목 bridge·codex 폴더는 건드리지 않음)
- 10-09 시편: 흰 70×70×90, 갈색 80×80×45(손잡이 없음). `sensor/calib/object_config.json` `boxes_mm` 후보 여러 개를 측정 높이로 고른다. `station/calib/grasp_config.json` 집는 깊이 = 상자 높이×0.4(20~35mm), 접근·들어올림 20mm. 90mm 상자에 접근 25mm는 수직 도달 한계를 넘어 역기구학이 안 풀리는 것을 계산으로 확인해 낮췄다.
- 상자 찾기(`sensor/locate.py`): 평면 맞추기의 전체 SVD가 2만 점에서 3GB·17초를 쓰던 것을 `full_matrices=False`로 고침(노트북 18초 → 0.5초). `near_far_mm`(기본 200~700) 거리 범위, 깊이 급변 경계에서 덩어리 분리, 후보 상자 높이(±15mm)로 덩어리 선택(카메라가 낮으면 윗면이 얇은 띠로만 보여 종전 "짧은 변 ≥20mm" 조건에 걸렸음), `downsample`(기본 2), 후보 전부 실패 시 후보별 이유·`rejected` 반환, `/object/locate?save_debug=1`로 깊이 영상 저장.
- 비전 집기(`station/grasp.py`): `grasp_depth_mm` / `grasp_depth_frac` 옵션, locate 3회 재시도.
- 테이프 규칙(`sensor/rules.py`): 초록 범위 H 35~85 → 35~95(시편 청록 테이프 H 81~84 실측). 면별 `tape_expected / tape_present_count / tape_missing_count / tape_missing_ids` 기록. 웹 화면(`station/web/index.html`)에 "테이프 n/N (누락 Tx)"·냉매 표시.
- 설정 로더가 UTF-8 BOM 허용(`objects.py`). 테스트는 현장 설정 파일과 분리(`sensor/tests/conftest.py`, `station/tests/conftest.py`).
- `tools/live_view.py` + `live_view.bat`: 서버가 켜진 채 실시간 3화면 창.
- 문서: README 7절(정육면체·두 상자), 5-1절(테이프·냉매 절차), `내일_로봇_순서.md`, `sensor/calib/cube70_sim_20261008.md`.

### 실제로 실행한 것(노트북, 실제 카메라, 가짜 로봇)
- `check_cameras --depth` 전부 PASS(RGB 27fps, 열화상 60, 깊이 31, USB3).
- `/object/locate` 라이브: 흰 상자 49cm에서 4/5~5/5 찾음, 중심 반복 ±1.5mm, 높이 90.4~92.4mm, 앞면 74mm(실제 70), 0.5초. 서버 시작 직후 첫 1회 실패(재시도로 보완).
- 테이프: `roi-tape --auto` → 있음 3장(17.3%)·없음 3장(1.5%) → `fit` validated(fill_min 0.094) → 다른 세션 2장 `eval` 2/2 → 라이브로 "테이프 0/1 (누락 T1)" suspect/사람확인함, 돌려 놓으면 "1/1". 이 기준값(`rules.json`)은 이 책상 기준이라 올리지 않았고, 현장에서 로봇 자세로 다시 fit 한다.
- 테스트: 센서 99 통과, 스테이션 104 통과(각각 `.venv-*` 에서 pytest).

### 아직 못 한 것
- 실제 로봇 전부(포트·보정·자세·집기 확인), 냉매 기준값, timing_policy, 카메라–로봇 좌표 맞추기, 면 B 규칙(없으면 `faces_without_checks_ok`).
- 열화상이 RGB보다 왼쪽을 보고 있어 현장에서 재조준 필요.
