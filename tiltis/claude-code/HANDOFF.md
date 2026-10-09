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

### 추가: 3면 검사(face_C), 2026-10-09 12:40
- 요구: 테이프 3면 모두 확인, 1개라도 없거나 냉매 없으면 부적격(사람 확인 구역). 로봇이 상자를 돌려 A→B→C 세 면을 보여 준다.
- 스테이션 `FACES` 환경변수(`run_all.bat ... -Faces A,B,C`, 기본 A,B). `sequencer.parse_faces/decide(faces)`, `robot.POSE_NAMES`에 `face_C`, 웹 화면은 검사하는 면 수만큼 카드 표시. 센서 `/inspect`와 rig가 face C 허용. CONTRACT 갱신.
- 실행: 노트북 실제 카메라 + 가짜 로봇으로 `FACES=A,B,C` 1회 → 이동 순서 home > pick_approach > pick > lift > face_A > face_B > face_C > bin_human > home, 면 3개 모두 기록. 테스트: 스테이션 106 통과(3면 순서·누락 면 거부 테스트 추가).
- 현장: `teach.py`에서 `face_C` 자세를 가르치고, 면 B·C 테이프 영역을 `roi-tape --face B/C --auto`로 잡아 fit 할 것. face_C 자세가 없으면 `-Faces A,B`로 실행.

## Codex 후속: 파랑·빨강 분류 (2026-10-09)

사용자 요청에 따라 기존 정상 `ok`/`bin_ok`는 파랑 영역, 불량 의심·확인 필요 `human`/`bin_human`은 빨강 영역으로 연결했다. 기존 검사·티칭·SDK·DB 키를 유지했다. `station/sequencer.py`의 명시적 영역 매핑과 상태 메타데이터, `web/index.html`의 색/모의 로봇 표시, `teach.py`의 영역 안내 및 CONTRACT·station README·현장 순서·예시 자세 설명을 갱신했다. 상대 폴더 변경 이유는 사용자 요구이며 검사 순서 구현을 중복하지 않기 위해 이 연결부를 수정했다.

3면 검사에서 정상/이상 의심/미판정/지속 측정 불가 각각의 목적지와 도착 후 그리퍼 해제·홈 복귀 회귀 4개 및 기존 모의 API 확인을 추가했다. 전체 스테이션 **110 passed, 4 warnings(54.61s)**. [Codex 인계](../codex/HANDOFF.md)에 실행 명령과 한계가 있다. 런타임 `destination`은 배치/실측 증거가 아니며 DB/CSV는 기존 `bin`, `placed_bin`을 유지한다.

현장 `bin_ok`, `bin_human`의 실제 위치는 미티칭이며 실기 구동은 수행하지 않았다. 실행 중 배포본도 교체하지 않았다. 별도 8002 미리보기 실행은 자동 정책에 차단되어 변경 화면은 소스에서 검토해야 한다. 다음 Claude 작업은 두 영역 티칭·기존 접근 및 중단 문제·현장 경로 검증을 먼저 확인하고 이어서 한다.

## Codex 후속: 깊이 기반 위치 변경 집기 (2026-10-09)

사용자 요청으로 기존 검출/IK/분류기를 재사용해 [Codex 검증 picker와 미리보기](../codex/vision_pick/README.md)를 연결했다. 기존 아래쪽 탐색/ROI 밖 포함 문제를 재현하고 `sensor/locate.py`에서 탐색과 평면 맞춤 ROI를 분리했다. 동일/상이한 후보 상자가 여러 개면 거부하며, 수직 하향 카메라의 평면 basis도 보강했다. `sensor/server.py`가 프레임 수신 시각을 보낸다. `station/sequencer.py`에는 선택적 `verify_at_grasp()` 연결만 추가하여 접근 후 이동한 상자를 하강·닫기 전에 거부한다. `run_station.ps1 -PickMode vision`이 Codex wrapper를 선택한다.

`station/grasp.py`/`teach.py`에는 hand-eye와 집기에서 같은 파지점을 쓰는 helper를 적용했다. 손잡이 없는 상자에서 윗면 vs 20~35mm 아래 파지점이 달랐던 문제를 수정한 것이며, 배포본의 guided 모드/상자별 자세를 덮어쓰지 않았다. 현재 기준 소스의 위에서 집기 planner와 배포본의 옆 집기 티칭을 같은 동작으로 취급하지 않는다.

실제 실행: 센서 **117 passed, 9 warnings(56.71s)**, 스테이션 **110 passed, 4 warnings(66.67s)**, Codex guard **38 passed, 1 warning(3.16s)**. 명령·변경 근거·실제 깊이 프레임 재검사 한계는 [Codex HANDOFF](../codex/HANDOFF.md) 마지막 절에 있다. 실제 카메라 API는 현재 후보를 확정하지 못했고, 새 검출기의 오프라인 후보도 영상 가장자리라 승인하지 않았다. 읽기 전용 미리보기는 모터 명령을 보내지 않는다.

현재 hand-eye/실측 workspace가 없어 guarded 계획은 승인되지 않는다. FK/단위·도구 기준점, 실제 집게 폭/경로 충돌/속도/stop, 분류 자세와 사용자의 실기 승인이 남아 있다. 이번 변경은 source만이며 실행 중 C:/PAC2026_system, 티칭/COM8, 실제 poses/calibration, 8000/8001 서버를 자동 교체하지 않았다. 먼저 배포본의 상대 guided 변경을 보존하여 통합하고 카메라/로봇을 고정한 상태에서 좌표 보정을 이어갈 것.
## Codex 후속: 옆 집기 통합과 작업별 위치 재계산 (2026-10-09)

사용자 요청은 위치 변경마다 다시 티칭하는 것이 아니라 깊이로 상자 위치를 찾아 움직이는 것이다. `C:/PAC2026_system/station`의 미커밋 옆 집기/상자별 자세/guided/replay 변경을 기존 guard와 3-way 통합했다. 원본 실행 폴더와 COM8/8000/8001, 실측 poses/calibration은 교체하지 않았다. 공유의 grasp/teach는 위·옆 모드 모두 같은 도구 기준점을 참조한다. 시편 설정은 side이며 실측 workspace가 필요하다.

`sequencer`의 비전 집기 후 고정 lift 복귀와 재촬영 고정 lift 복귀를 수정해 그 작업에서 계산한 목표를 사용한다. 검사면·분류 위치·그리퍼 기준만 재사용하고 매 작업 깊이→좌표 변환→IK를 새로 계산한다. 설치 보정은 카메라/로봇을 고정한 상태에서 한 번 수행하며 상자 이동만으로 재보정하지 않는다. 정적 guard 준비 검사, pick_mode/readiness API도 추가했다. 임의 방향 상자가 105mm 개구에서 항상 정렬된다는 설명은 갈색 대각선 약 113mm와 맞지 않아 제거했으며 개구/회전은 실기 검증이 필요하다.

상대 테스트의 누락 import 도구 오류를 재현 후 `import_grasp_profile.py`도 연결했다. 두 보정 해시가 모두 없는 경우의 오인 통과를 차단했다. 최종 스테이션 **113 pass(109.13s)**, Codex **44 pass(10.04s)**. 같은 가상 보정값으로 흰/갈색 각각 세 위치의 집기·3면 검사·분류, 저장된 pick/lift 부재, FK/재촬영/미보정 이동 차단을 확인했다. 명령과 세부 증거는 [Codex HANDOFF](../codex/HANDOFF.md) 마지막 절에 있다.

확인 시 Claude는 COM8에서 일회성 hand-eye 보정을 진행 중이며 아직 보정 파일/실측 workspace가 없었다. 뒤에 추가된 배포 teach의 점 검사 경고는 실행 파일에 그대로 보존했고, 특정 책상 z 범위를 일반화하지 않았다. 보정·FK/실측 범위·경로/개구/속도/stop 확인과 사용자 승인 뒤 전체 공유 소스의 센서 captured_at_s 및 `run_station -PickMode vision` entry를 배포해야 한다. 기존 8000 서버는 이 통합으로 바뀌지 않았다. 실기 자동 집기/학습 데이터 완료로 보고하지 않는다.

## 2026-10-09 노트북 동기화 (tiltis)
- 변경: station(grasp/robot/sequencer/teach/web), sensor(locate/rules/server), 리플레이 bat, handeye.json·poses.json, sh 실행 스크립트 추가
- 테스트: 이번 커밋에서 새로 실행한 테스트 없음 (작업 중 코드 공유용 스냅샷)
- 남은 일: 실제 로봇에서 grasp/sequencer 검증

## 2026-10-09 Colab 학습 노트북 (tiltis)
- 추가: PAC2026_system/colab/train_lerobot_colab.ipynb (Colab Pro+ GPU에서 LeRobot 정책 학습, Drive 체크포인트, HF Hub 업로드)
- 테스트: Colab에서 아직 실행 안 함
- 남은 일: DATASET_REPO_ID를 실제 데이터셋으로 바꾸고 첫 실행 확인. 팀 계정 비번은 저장소에 적지 말 것

## 2026-10-09 Codex RGB/Colab 및 공유 guard 복구 검토
`codex/rgb_box/`가 실제 RGB 인식 1단계다. Colab T4에서 갈색 두 위치와 흰 상자 포함 4장 Grounding DINO+SlimSAM 검증 완료 (추론 0.387~0.446초/장, 통신 지연 제외). 현재 마스크는 전체 상자이며 다음 사용자 요구는 윗면/각도/집게 정렬이다. 기존 LeRobot 학습 노트북은 그대로 보존했다. 자세한 실행/출력/한계는 ../codex/HANDOFF.md 및 ../codex/rgb_box/README.md.

c2aec11 스냅샷에서 prior guard 연결이 빠져 8개 회귀 실패를 재현했다. grasp 공통 점 계산, sequencing preflight·접근 후/재시도 후 재확인·현재 lift, Windows vision entry wrapper, 센서 captured_at_s/ROI/중복 후보 거부, 미보정 프로필 import 차단을 복구했다. 새 재시도 및 top_face 후보 선택은 보존하고 그 후보 모드도 ambiguity를 거부한다. 테스트: station 전체115, sensor 전체119, codex guard45, RGB16 pass. 후속 추가 테스트 sensor pick_area13 / station grasp_check8도 pass. 배포본을 자동 교체하지 않았으며 실제 구동 검증이 아니다. 18:20:56 handeye RMS15.91mm는 10mm 허용 기준을 넘는다. 실측 workspace와 TCP/FK/좌표 보정 확인 뒤에만 배포/실기 검증한다.

## 2026-10-09 촬영 샘플 HF 업로드 스크립트 (tiltis)
- 추가: tools/upload_captures_hf.py — PAC2026_data(station.db 제외)를 HF 비공개 데이터셋 tiltis/pac2026_sensor_captures로 업로드
- 테스트: 아직 실행 안 함 (로컬 HF 로그인 필요)

## 2026-10-09 Codex SAM 윗면/깊이 축/집게 방향 후속

사용자 요청에 따라 `codex/rgb_box/`에 SAM 면 후보·영상 변 각도, `sam_depth.py`의 검증된 RGB–depth 투영/윗면 3D 축과 기존 sensor/guard/IK 어댑터, 오프라인 bundle CLI를 추가했다. Colab T4에서 실제 4장 실행/다운로드/화면 확인. 테이프와 앞면도 나와 RGB 면 점수로 윗면을 확정하지 않으며 깊이 평면/실측 치수가 필요하다. 3D 연결은 가상 입력으로 검증했고 실제 Arducam–Gemini2 정합/paired frame API는 미확보다.

공유 변경 이유/재현: plan_side가 상자 회전을 무시하고 중심 radial 방향으로만 집었다. `station/grasp.py`에서 두 3D 상자 축을 hand-eye 회전하여 접근·집게 축을 정렬하고 도달 불가 자세는 거부한다. 기존 station 1개/guard 2개 테스트가 위치가 바뀌어도 고정 상자 방향으로 항상 성공한다고 가정해 실패했으며, 도달 가능한 변 정렬 장면과 회전/도달 불가 거부를 분리해 수정했다. `sensor/locate.py`에는 선택적 object_mask만 연결해 기존 책상 평면·검사 코드를 재사용했다. 원래의 빈 집기 재시도/3면 검사/분류 기능은 유지했다.

검증: RGB/깊이43, guard58, sensor 전체121, station 전체115 pass. 마지막 축 검증 후 station vision_pick 부분16 pass. 가상 SAM/depth→공유 guard→IK/FK 통합, CLI 저장, 노트북 AST/출력 없음/실행 GPU 결과 보관도 확인. 자세한 계약·명령·제한은 ../codex/rgb_box/README.md 및 ../codex/HANDOFF.md. 런타임 C:/PAC2026_system 교체/서버 재시작/로봇 호출 없음. 최신 handeye 파일은 18:28:38 n5/RMS8.62/max11.7mm(읽기만 수행); 기존 15.91mm 기록은 과거 상태다. TCP/FK·실측 작업 범위·RGB-depth 정합·개구 폭/충돌·실제 속도/stop과 사용자 승인 전 자동 집기 완료로 보고하지 말 것.
