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

### 추가: 2026-10-09 현장(경북대) 실기 — 비전 옆집기로 전 과정 완주
- 로봇: COM8(CH343), lerobot-calibrate 완료(전 관절 190~227°). 자세 teach.py --guided(안내 모드, w=토크 고정/f=풀기), 상자 종류별 자세 접미사 _white/_brown.
- 좌표 맞추기: teach.py --handeye-auto — 로봇이 5곳으로 가서 집게를 벌리고, 사용자는 상자만 끼움; 집게를 닫아 상자를 가운데로 정렬한 뒤 FK 기록, home으로 뺀 뒤 깊이로 측정. RMS 8.6mm(5점).
- 깊이: 현장은 카메라가 위에서 내려다봐 locate_mode top(locate_box_top_any: 후보 높이·윗면 크기로 선택), pick_roi 전체, near_far 200~700.
- 옆집기(grasp_mode side) 핵심 수정: 도구 기준점(gripper_frame_link)은 손가락 끝이고 턱 가운데는 끝에서 (−28, +19, −35)mm(URDF) → 턱 가운데를 상자 중심에 맞추고 접근축이 로봇 중심을 지나도록 반복 계산. 높이는 책상 기준 절대값(끝 최소 10mm). 접근은 같은 높이에서 뒤→앞(2~5cm, 가까우면 자동 축소). 상자는 로봇 중심에서 36~41cm. 안정화 허용 5°, 면 이동 3~3.5초, 대기 8초.
- 놓치면 집게 열고 home으로 뺀 뒤 다시 찾아 한 번 더 집기. 상자 종류는 잰 높이로 자동.
- 결과: 갈색 상자 집기(holding 0.50) → 들기 → 면 A/B/C(손목 꺾기: 앞면·윗면·아랫면) → 빨강 영역에 놓기 → home, 전 과정 완주 2회.
- 테이프: 영역 고정 대신 면별 초록 덩어리 개수(tape_counts). rules_calib.py count-golden으로 정상 상자 1회 촬영에서 면 A 2개·면 B 3개 기준 설정(면 C 검사 없음). 테이프 2개 상자 → 면 B 2/3 → 빨강 확인. 면적 보정은 끔(1개 빠져도 면적 85% 남아 위험).
- 타이밍 정책: 현장 촬영 5장으로 생성. SINGLE_SPECIMEN=1.
- 현장 보정 파일(poses.json, handeye.json, rules.json, timing_policy.json, grasp/object config)은 Git에 올리지 않고 OneDrive/PAC2026_노트북용/현장보정_20261009/에 백업.
- 남은 일: 테이프 3개 상자 → 파랑 확인, 흰 상자 집기 확인, 냉매(열화상) 기준(roi-coolant + fit).

## Codex 확인: 새 푸시 3dffdae의 연결 회귀

사용자 요청으로 새 푸시를 동기화하고 읽기/모의 테스트를 수행했다. GET status/runs에서 hardware 및 run31/32 done/human/error=null 기록을 확인했다. 현장 개선은 보존했다. 상대 집기 부분24/rules13 pass이지만 Codex vision_pick22 fail/36 pass, rgb_box6 fail/37 pass이다. 공유의 상자 축 정렬·camera_grasp_point·SAM table_roi/object_mask, preflight/접근 후 재확인/계산 lift 연결이 빠졌다. 촬영 timestamp·ROI/복수 후보·누락 보정 해시 검사 제거도 diff로 확인했다. 상세 근거/명령/범위는 [검토 기록](reviews/CODEX_PUSH_REVIEW_3dffdae.md). 이번에는 검토/기록만 수행하고 기능/배포/로봇은 변경하지 않았다. 현장 개선과 기존 SAM/guard 계약을 함께 통합하는 작업이 남는다.

## Codex 통합: 현장 개선 유지 + SAM/guard 계약 복구

사용자 요청으로 위 회귀를 수정했다. 턱 TCP·높이/접근 탐색·가까운 IK·재집기 home·dry grasp/오차 로그·면별 테이프 판정은 유지한다. 상자 변에 맞춘 접근/집게 각도를 턱 오프셋 계산에서도 유지하며 도달 불가 시 radial로 대체하지 않는다. sensor의 SAM mask/별도 table ROI/다중 후보 거부·capture timestamp와 회귀, Windows vision guard wrapper, sequencer preflight/접근 후 재확인/현재 lift·재촬영 lift, 미보정 프로필 해시 거부를 복구했다.

auto hand-eye의 frac(높이 비율)를 그리퍼 개방률로 덮어쓰는 오류와 camera 상자 중심↔robot 손가락 끝 대응을 수정했다. 수동/자동은 설정된 턱 중심과 공통 카메라 파지점을 기록한다. 기존 실측 handeye 파일은 해당 기준과 일치하는지 검증할 것. 기존 C:/PAC2026_system 파일과 poses/calibration/COM8, 8000/8001은 교체/호출하지 않았다.

검증: RGB43, guard60, sensor 전체121, station 전체115 pass. 추가 보정2 pass, 마지막 직교화 후 정렬14/vision+auto17 부분 pass도 확인했다. 자세한 시간/명령/범위는 ../codex/HANDOFF.md. 별도 읽기 전용 preview_server가 127.0.0.1:8002에서 실제 3카메라를 표시하며 SDK/카메라 핸들/모터 명령 없음. 현재 구버전 8001의 후보 수·촬영 시각 계약 및 실측 workspace가 없어 자동 이동 차단. SAM 실기에는 rectified RGB-depth 정합/신선한 paired reader가 필요하다. 가상 값으로 이 조건을 통과시키지 않았다.

### 정정 (2026-10-09 20:30): Codex 통합 커밋(66bbb31) 위에서 옆집기 계획만 실기 검증본으로 되돌림
- 66bbb31 의 plan_side(side_box_alignment: 상자 변 방향으로 접근)는 시뮬에서 yaw 0/10/20/30/45° 모두 IK 실패(5축 팔은 접근축이 로봇 중심을 지나야 함).
  노트북 실기에서 집기 성공(holding 0.50, 2회 완주)한 plan_side(턱 중심 URDF 오프셋 + 반복 계산 + 절대 높이)로 되돌리고,
  Codex teach.py 가 쓰는 camera_grasp_point 보조 함수는 Codex 버전에서 가져와 유지했다. locate.py·server.py·테스트·가드는 Codex 버전 그대로.
- 검증: 스테이션 117 통과, 센서 121 통과. 실기 DryRun 결과는 아래 줄에 추가.
- poses.json/handeye.json 은 노트북 실측본으로 갱신. 동기화는 삭제 없이 덮어쓰기만.


## 2026-10-09 Claude 실행 폴더 추가 작업 GitHub 반영 (Codex)

사용자의 전체 푸시 요청으로 origin/main 4ce4d59를 fast-forward한 뒤 C:/PAC2026_system과 파일별 비교했다. Claude 실행본의 밑면 골판지 영역/edge·dark 판정과 bottom-golden 보정 CLI, 추가 테이프 허용 설정, suspect 조기 종료·skipped_faces 기록, 정지 확인 후 안정화 경고, 분류 이동 4초, 관련 sequencer 테스트를 공유 소스에 반영했다. 최신 저장 poses와 가운데 흰 면 pick ROI도 기존 추적 경로에 반영했다. 갈색/흰색/common replay 및 Linux 실행·설치 스크립트를 복원했다. 현재 GitHub grasp는 실행본과 동일하며 기존 통합 변경은 유지했다.

직접 검증: station/tests/test_sequencer.py 49 passed, 1 warning (8.32s); sensor/tests/test_rules.py 13 passed, 4 warnings (11.61s); 변경 Python 5개 AST/JSON 2개 파싱 통과. 실기 이동·서버 재시작·실행본 교체 없음. 신규 밑면 현장 성능은 이번에 실측하지 않았다.

동시 작업으로 남아 있던 native RGB-D/depth/server 및 codex RGB/SAM/preview 변경은 이 Claude 실행본 스냅샷 커밋에 포함하지 않는다. 영상·로그·DB·가상환경·비밀값과 현장 보정 백업 파일도 제외한다. 기존에 추적하지 않던 robot_setup 팩은 3dffdae에서 제거된 이력이 있어 자동으로 재추가하지 않았다.

추가 전체 검증: station/tests **118 passed, 4 warnings (82.50s)**. 명령: 시스템 폴더에서 C:/PAC2026_system/.venv-station/Scripts/python.exe -m pytest station/tests -q --disable-warnings --rootdir . --confcutdir . -o addopts=. 초기 경로 지정 두 건은 수집 실패 후 올바른 폴더/파일로 재실행했다.

## 2026-10-09 Codex Gemini RGB-D / SAM / release hook 인계

Codex가 sensor의 native_rgbd.py를 추가하고 기존 depth/server에 --depth-rgb, strict /vision/rgbd.npz와 preview 전용 /vision/preview_rgbd.npz, health diagnostics를 연결했다. 기존 depth좌표/mm/locator 및 hand-eye 기준을 유지하며 Gemini 자체 RGB를 동일 SDK pipeline에서 받는다. Arducam과 같은 픽셀로 쓰지 않는다. 장치 exposure 시각 고정/오래된 global시각에서는 strict API503을 실제 재현했다.

Windows 관리자 metadata 등록: SDK 공식 script의 없는 속성 조회가 예외를 내 연결된 Gemini depth/IR/RGB 3개 인터페이스×2개 공식 DeviceClasses의 MetadataBufferSizeInKB0 DWord5를 같은 목적으로 등록하고 6곳 모두 값 확인. 기존값/실행근거는 C:/PAC2026_system/Log/codex_metadata_*; 지속 실행 정책은 변경하지 않았다. 다른 작업의 센서 재시작 후 ready/capture_time_verified true, 실제 strict NPZ 촬영 skew12.54ms 확인. 센서 소유 PID가 바뀌어 Codex 재시작은 취소했다. 8000/COM8/calibration/poses는 이번 변경으로 교체하지 않았다.

공유 grasp.py의 field 기본 side_alignment=radial은 보존했다. optional box 모드를 추가하고 own GuardedVisionPicker가 box로 명시 선택, 상자 3D 변과 TCP 보정 후 방향 유지, IK 불가 시 radial fallback 금지. 공유 sequencer에 optional capture_held_box/verify_at_release를 추가: 실제 관절 읽기와 새 재집기 관측 사용, release check 실패면 집게 열기 전 기존 stop으로 종료. 기존 VisionPicker에는 hook이 없으므로 기본 field 흐름은 보존된다. Codex placement는 예상 FK/무미끄럼 가정이며 실제 바닥 접촉/놓기 안정성을 증명하지 않는다. 미측정 placement를 가짜값으로 설정하지 말 것. 현재 실기 station에는 새 hooks를 배포하지 않았다.

Gemini 저장 사진을 Colab T4의 SAM으로 분리: 다중 surface positives로 테이프 재질 제외 문제를 줄여 IoU0.8048, 전체 DINO/SAM926.11ms. 영상 변 각도는 robot yaw와 다르다. DINO 책상 오검출도 남아 있고 factory reprojection/field/RGB-D 정합 검증이 필요하므로 사진 결과를 제어로 쓰지 않았다. top_tape는 서로 다른 윗면 접점으로 merged tape를 다루지만 실제 사진의 넓은 패치에서 unmeasurable; 기존 rules에 자동 적용되지 않았다. actual 정상/누락 여러 면 검증이 남는다. 8002에는 3카메라 live와 saved_photo_only 결과를 구별하여 표시한다.

검증: RGB53, own guard67(1warn), station sequencer+vision_pick65(1warn), sensor native_rgbd/depth/server58(2warn) pass. 마지막 추가 회귀 native_rgbd10 및 preview2 pass, 전체와 별도 결과. own/peer README 및 ../codex/HANDOFF.md에 정확한 명령/시간/증거/실패 수정/남은 항목 기록. 런타임 sensor와 소스의 마지막 preview 폐기 3줄씩만 아직 다르며 자동 덮어쓰기하지 않았다. raw영상/NPZ/로그/가중치/현장보정은 Git에 넣지 않는다.

최종 현장 재확인: 센서 PID가 26888→26644로 바뀌며 잠시 ready=false/연결 거부가 있었고 이후 복구했다. 복구 후 12회 연속 /health에서 ready=true/capture_time_verified=true, 장치 시각 증가, 촬영 age77~294ms 확인(짧은 표본이며 장시간 안정성을 증명하지 않음). strict paired capture의 skew12.54ms 증거는 유지한다. 마지막 8000의 R212711 오류는 no_candidate_box_matched이며 새 SAM/놓기 계획을 Codex가 실행한 결과가 아니다. 8002 최종 own PID26140/exec83974, 현재 3카메라와 저장 사진 SAM을 구별한 화면을 C:/Users/tilti/PAC2026_data/integration_20261009/preview_final.png에 저장했다. post_registration_health_samples.json도 같은 폴더. 서버 소유/상자 배치를 다시 확인하고 실제 실행할 것.

## 2026-10-09 Codex — 상자 빨간 윤곽과 분류 이유 UI

사용자 요청: 기존 Claude 현장 판정은 유지하며 비저블 상자에 빨간 테두리, 웹앱에 테이프 누락 개수/아랫면 결함 등 빨강 분류 이유를 표시. 검사 데이터에는 tape_missing_count_1/bottom_open과 features가 이미 있었지만 UI가 내부 코드를 그대로 표시했다. 실행본 index의 자동 시료 ID 변경을 보존해서 공유 소스에 통합했다.

변경: 공유 station/web/index.html의 독립 PacReasons 블록으로 면별 최신 시도/최종 사유/기록 사유를 표시한다. 검증된 실제 suspect만 누락/아랫면 결함으로 표시하고 미검증·측정 불가·모의·실행 오류를 구분한다. 여러 면에 이어지는 같은 테이프를 합산하지 않는다. 기존 GET inspections API를 재사용하며 DB/규칙/로봇 제어에는 변경 없다. codex/vision_pick/preview_server.py도 같은 JS 블록을 읽고 현재 실행 상태와 별도로 최근 저장 판정을 표시한다.

codex/vision_pick/box_overlay.py는 기존 sensor/rules.py의 CARDBOARD/GREEN 색을 재사용해 /live.jpg의 첫 RGB 480x360 패널에만 빨간 윤곽을 그린다. SAM이 아닌 표시용 색 기반 후보이며, 현재 서로 닿은 여러 상자는 한 영역으로 묶일 수 있다. 빨간선은 불합격 표시가 아니며 파지/판정 입력으로 사용하지 않는다. 열화상/깊이 배열과 원본 입력은 불변이고 JPEG 재압축은 있다. 흰 상자/배경 갈색 물체/가림에 대한 일반 검출 성능을 주장하지 않는다.

검증: Node station/tests/test_reason_presentation.cjs 14 passed(0.50s), Python vision_pick tests/test_preview_server.py + tests/test_box_overlay.py 12 passed/1warning(3.85s). 실제 기록70을 읽어 B면 테이프1개 누락(2/3관측), 웹 이력62에서 C면 아랫면 결함(벌어짐 의심)을 확인. 실제 결함 정확도를 새로 실험한 것이 아니라 기존 판단의 표시 검증이다. 원인 없는 suspect·재검사 우선·중복 합산 금지·측정 불가·미검증·모의·연결 실패·RGB 이외 무변경 회귀 포함.

사용자가 요청한 화면 적용: C:/PAC2026_system/station/web/index.html만 기존 hash 비교 후 백업하고 배포(서버 재시작 불필요). 백업 C:/PAC2026_system/Log/codex_ui_reasons_20261009/index.before.html. 로봇8000/센서8001 코드/보정/프로세스에는 쓰기/중단 없음. 소유 확인된 Codex8002만 재시작(최종PID3576, exec70420). station 카메라는 노트북 localhost에서8002 annotated GET 사용, 실패시 기존 /sensor-live로 복귀. 원격 접속은 기존 원본 영상 유지. 실제 모터 명령/검사 시작 없음. 동시 Claude 실행에서 나온 multiple_boxes/IK실패는 이번 UI 작업의 실행 결과가 아니다.

증거: C:/Users/tilti/PAC2026_data/ui_reasons_20261009 (현재 영상/화면/실제 API 결과), Git에는 미디어·DB·보정·로그 제외. 현재 갈색 상자 윤곽 표시와 이유 설명만 추가했으며 SAM 정렬/새 놓기 guard는 여전히 별도 실기 검증 필요.

## 2026-10-09 Codex — 검사 후 바닥 긁힘 방지용 분류 경로

사용자가 옆 이동 중 상자가 바닥을 긁는다고 보고했다. 마지막 검사 자세에서 낮은 bin 자세로 바로 이동하던 공유 경로를 `상승 → 높은 위치에서 이동 → 하강 → 놓기 → 상승 → home`으로 분리했다. 기존 Claude 집기/검사/판정과 놓기 자세를 재사용하며 실행본의 놓은 뒤 `bin_*_up` 복귀·`mark_processed` 등 현장 변경을 보존한다. 실행본 전체 덮어쓰기를 하지 않는다.

공유 변경은 `station/clearance_transfer.py`(신규), `robot.py`, `sequencer.py`, 세 transfer 테스트 파일과 README다. 기존 FK/IK·joint map·현장 상자 치수/턱 오프셋/책상 기준을 사용해 전체 경로를 먼저 검사한다. 기존 상단 자세는 놓기보다 120 mm 위다. 검사 후 상승은 현재 TCP +15 mm와 목적지 상단 높이 중 높은 쪽이며, 해당 검사 자세의 방향 보존 IK 제약 때문에 큰 임의 상승량을 강제하지 않는다. 관절 한계·보간 중 상자 여유·수직 구간을 검증하고, 단계별 엄격한 관절 안정화와 실제 관절 FK 위치 5 mm/방향 5°/요구 높이를 확인한다. `is_still`로 분류 이동 검사를 우회하지 않는다. 실패는 stop/hold하고 낮은 직접 이동으로 대체하지 않으며, 놓기 전 실패면 집게를 열지 않는다. 놓은 뒤 상승 실패면 `placed_bin`은 보존하되 home으로 이동하지 않는다. 기존 held/release 훅과 상자별 자세도 유지한다. 경유점 중단은 stop을 호출하지만 즉시 비상정지는 아니다.

명령 시간은 관절 20°/s·FK 표본 TCP 50 mm/s에 맞춰 늘린다. 실제 속도 계측이 아니다. `transfer_plan`·`transfer_checks`에 계획과 확인 결과를 기록한다. 상자 경계 구는 올바른 턱 중심 파지와 미끄러짐 없음 가정이며 실제 장애물/바닥 접촉·home 경로 충돌을 검증한 것은 아니다.

최종 검증 명령은 `PAC2026_system`에서 `.venv-station` Python으로 `-m pytest station/tests/test_clearance_transfer.py station/tests/test_transfer_robot.py station/tests/test_transfer_sequence.py station/tests/test_sequencer.py -q --disable-warnings --rootdir . --confcutdir . -o addopts=`. 시간 제한 회귀 4개까지 포함해 **167 passed, 1 warning (15.83s)**. 배포 예정인 정확한 재통합 실행본의 검사 B/C × 정상/부적격 × 카메라 색 구역 배치 3가지(정보 없음/정상/뒤바뀜), **12개 조합 모두 오프라인 통과**했으며 장치 연결/모터 명령은 없다.

동시 변경: 배포 직전 hash 검사가 최신 Claude 실행본 변경을 찾아 프로세스를 멈추기 전에 최초 배포를 취소했다. 새 `place_pose_from_zones`·`_place_pose`의 `/zones` 기반 색 구역 선택을 다시 보존해, 실행본에서는 `self._place_pose(bin_name)`이 선택한 자세를 transfer planner에 전달한다. `mark_processed`도 유지한다. 위 12개 검증은 이 재통합본으로 실행했다. 공유 저장소는 기존 routing을 유지하며 Claude의 해당 변경 push 후 후속 통합이 필요하다. 현재 저장소와 실행본이 완전히 같지는 않다.

배포 완료: **2026-10-09 22:36:00 KST**. 사용자가 빈 그리퍼·지지된 팔 상태에서 재연결을 승인한 뒤, 변경 hash를 재확인한 파일 3개를 적용했다. GET status는 `robot_mode=hardware`, `pick_mode=vision`, `state=idle`, `busy=false`, 검사면 B/C이며 수신 PID는 27040이었다. `/api/run` 또는 새 분류 사이클 호출은 없다. 백업은 `C:/Users/tilti/PAC2026_data/transfer_20261009/runtime_backup_223600`, 증거는 같은 상위 폴더의 `deployment.json`·`startup_verification.json`과 12개 오프라인 검증 결과다. 새 실제 분류 사이클·바닥 긁힘 해소·물리 충돌·안정적인 놓기 완료를 주장하지 않는다. [station README](PAC2026_system/station/README.md)와 [Codex 인계](../codex/HANDOFF.md)에 경로 계약과 남은 검증을 기록했다.

## 2026-10-09 Codex — 집기 전 HOME 하강/전진 경로 설정

사용자 요청은 집기 전 `HOME → 수직 하강 → 같은 높이에서 전진 → 집기`이며 검사 후 분류 경로와 구별한다. `station/home_approach.py`·`pick_path_api.py`·`web/pick_path.html`, app 등록/검사 화면 링크, sequencer와 관련 테스트를 추가했다. 기존 Claude 비전 집기/판정을 감싸고, 최초/재집기에만 선택적으로 경로를 적용한다. 실행본의 새 글꼴/검사 UI, `place_spot`·색 구역 선택·`mark_processed`는 staging에 보존한다.

`/pick-path`는 방식 선택과 비전 집기 높이 보정 −10~+30 mm를 제공한다. 이 값은 HOME 하강 거리 자체가 아니다. 기본값은 기존 `legacy`, 새 방식 `home_descend_forward`는 경로 미리보기 성공 후 같은 설정과 보정 지문의 120초 이내 token으로 적용해야 한다. 저장 파일은 `station/calib/pick_path.json`. API는 `GET /api/pick-path/settings`, `POST /api/pick-path/preview`, `PUT /api/pick-path/settings`, `POST /api/pick-path/home`이다. API에는 이동/토크 기능이 없다. HOME 저장은 기존 서버 로봇 객체에서 관절을 읽고 한계/책상 여유를 검증한 뒤 기존 poses 백업·원자적 교체를 수행한다. 두 번째 COM8 연결을 열지 않으며 검사/설정 동시 실행을 차단한다.

최종 검토 수정: 검증된 자세/보정 지문 `accepted_geometry_sha256`을 영구 저장한다. HOME 재저장 시 이전 승인을 먼저 무효화하고 서버 재시작 후에도 `needs_preview=true`로 새 경로 실행을 차단한다. 새 미리보기·적용이 필요하며 자동 legacy 우회는 없다. `PickPathService.bind_picker` 및 `codex/vision_pick/station_app.py`를 연결해 별도 Guarded 진입점도 설정에서 검증하는 picker와 실제 실행 picker를 공유한다.

HOME X/Y·방향을 유지한 하강과 같은 높이의 전진/방향 보간, 마지막 approach→grasp를 기존 IK/FK로 검증한다. 관절 한계/보간 경로/바닥 여유 실패 시 대각선 우회 없이 중단한다. 초기 HOME 이동 전 설정 검증, 하강 전 실제 HOME 도달, 단계별 strict settle/FK 확인을 추가했다. 초기·재집기/중단/속도 시간 제한·기존 held/release 훅을 보존하며 `home_path_plans`·`home_path_checks`를 기록한다.

테스트: `.venv-station` Python으로 `-m pytest station/tests -q --disable-warnings --rootdir . --confcutdir . -o addopts=` → **273 passed, 4 warnings (126.90s)**. 이후 명령 실패 2개 추가 후 `test_home_path_sequence.py`·`test_transfer_sequence.py`·`test_sequencer.py` 부분 **138 passed, 1 warning (10.30s)**. 마지막 지문/재시작/picker 연결 수정 후 `test_home_approach.py`·`test_home_path_sequence.py`·`test_pick_path_api.py`·`test_pick_path_web.py` 묶음 **77 passed (6.73s)**: 경로 19개·순서 37개·API 19개·UI 2개. 앞선 전체 실행 이후의 부분 검증이고 범위가 중복돼 합산하지 않는다.

현재 HOME 손목 회전 −163.38°는 모델 하한 −157.21° 밖이라 새 경로 활성화가 차단된다. 실제 HOME 또는 모델/보정 일치를 먼저 확인하며 가짜 관절 한계/각도 치환으로 통과시키지 않았다. 이 HOME 기능은 아직 실행본 적용/서버 재시작 전이고, 사용자의 빈 팔 지지·재연결 승인을 기다린다. 이전 22:36 분류 경로 배포와 혼동하지 말 것. 최근 R221924의 두 번 `nothing_held`는 기존 집기 단계 실패이고 새 경로 실기 결과가 아니다. 물리 이동·충돌·추종·파지 성공은 검증하지 않았다.


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

### 상시 별도 카메라 창에도 적용
사용자가 웹이 아닌 별도 RGB/LWIR/Depth 창을 지정했다. 기존 tools/live_view.py 기본 URL을8001/live.jpg에서8002/camera.jpg로 바꾸고 기존 --url 원본/원격 지정은 유지했다. --position X Y 옵션으로 기존 외부 모니터 위치를 유지했다. 공유 소스와 C:/PAC2026_system/tools/live_view.py에 동일 수정, AST 구문 확인. 실제 pythonw viewer PID9556만 명령을 대조한 뒤 교체했고 robot/sensor/preview 서버는 재시작하지 않았다. Computer Use로 새 PAC2026 Live RGB-LWIR-Depth 창에서 RGB 상자 하나에 빨간 윤곽이 표시되는 것을 직접 확인했다. 증거 target_overlay_20261010/standalone_outline.jpg. 다음 live_view.bat 실행에도 기본 테두리 영상이 열린다. 8002 preview가 켜져 있어야 하며 원본은 --url http://127.0.0.1:8001/live.jpg 로 선택 가능하다.


## 2026-10-10 — 면 이름 대신 검사 항목과 간결한 분류 이유

사용자가 B면/C면은 의미 없으므로 테이프 n개 누락, 냉매 누락 의심처럼 표시하도록 요청했다. 기존 상대 station/web/index.html과 현재 현장판, sequencer의 required_checks를 확인했다. B 촬영은 테이프/냉매를 함께 다루므로 단순 B→테이프 치환 대신 관측 feature/reason을 기준으로 테이프 검사·밑면 검사·냉매 검사 카드 3개로 재구성했다. 진행 단계와 기록에서도 A/B/C면 표시를 없앴으며 프로토콜 face/자세 코드, DB, 센서/분류/로봇 제어는 그대로 사용한다.

카드는 최신 재촬영을 우선하고 검증된 관측에서만 테이프 n개 누락, 아랫면 결함(벌어짐 의심), 냉매 누락 의심을 표시한다. 미검증/불완전 관측은 확인 필요, 해당 관측이 없으면 검사 대기다. 두 촬영에서 보인 동일 wrapping tape 개수를 더하지 않는다. 기록의 동일 이유를 중복 제거하고 필수 항목이 확인되지 않으면 냉매 확인 필요 등 의미 있는 이름으로 표시한다. 사진은 검사 사진 보기 안에 접어 두었다. 이는 기존 판정의 표현 개선이며 센서 정확도나 냉매 오판을 교정했다는 의미가 아니다.

변경: claude-code/PAC2026_system/station/web/index.html, station/tests/test_reason_presentation.cjs. 검증 명령: Node --test station/tests/test_reason_presentation.cjs, 18 tests passed. 항목별 독립 판정, 미검증 결과 단정 금지, 재촬영 우선, 테이프 개수 중복 합산 금지, 필수 관측 부족을 추가 검증했다. inline JS 전체 파싱 통과. 실기 테스트를 실행하지 않았다.

현장 C:/PAC2026_system/station/web/index.html만 백업 원본과 hash 일치를 확인한 뒤 의미별 UI로 갱신했다. 현장에 이미 있던 Claude HOME 복귀·/hub 링크/처리 코드는 유지했다. 공유 저장소 app.py에는 해당 endpoint가 없으므로 이 두 현장 기능을 이번 UI 커밋에 새로 복사하지 않았다. 서버 재시작/카메라 재연결/로봇 명령은 없었다. GET / 200 및 3카드, 브라우저 JS 오류 없음, 사용자의 시료 R021713/갈색 상자 선택 보존을 확인했다. 저장된 실제 run166 관측에 새 표현 함수를 적용해 테이프 1개 누락 / 냉매 누락 의심 / 밑면 검사 대기를 확인했고 기록 표에서도 면 접두어 없이 표시됐다. 실제 새 검사는 실행하지 않았다.

증거/복구본: C:/Users/tilti/PAC2026_data/station_semantic_ui_20261010/index.before.html, semantic_cards.png. 현장 idle/hardware 상태에서 UI만 적용했으며 냉매 정확도/집기·분류 완주/안전 검증은 이번 작업 범위에서 추가 확인하지 않았다. 사용자 요청과 현재 판정 정책을 유지한 표시 변경이므로 기존 Claude 제어 변경을 덮어쓰지 않았다.


## 2026-10-10 — 상단 가르친 경로 문구 제거

사용자 화면 요청에 따라 상단 집기 경로 배지와 taught_station.py가 삽입하던 긴 경로 안내를 제거했다. 변경 파일은 codex/vision_pick/taught_station.py와 상대 station/web/index.html이다. 기존 실행 서버는 Python 함수를 이미 로드했으므로 현장 HTML에 legacy #taught-path 숨김/DOM 제거를 함께 넣어 재시작 없이 즉시 적용했다. 다음 실행에서는 wrapper가 해당 안내를 삽입하지 않는다. /pick-path의 과거 링크는 /로 이동한다. 로봇 경로·API·실제 로봇 표시·비상정지 안내는 변경하지 않았다.

현장 파일을 백업하고 동시 변경 유무를 확인해 해당 3개 UI 수정만 적용했다. 현장 강제 HOME/H 버튼 등 최근 Claude 변경을 보존했고 로봇/센서 서버 재시작과 이동 명령은 없었다. 현재 열린 8000을 새로고침한 실제 DOM에서 경로 배지와 aside 제거를 확인하고 시료/상자 선택을 보존했다. wrapper AST와 공유/현장 inline JavaScript 파싱 통과. 단순 표시 삭제라 새 테스트는 추가하지 않았다. 증거 C:/Users/tilti/PAC2026_data/station_header_clean_20261010/header_clean.png, index.before.html. 기존 미커밋 bootstrap.py는 이번 작업/커밋에서 제외한다.


## 2026-10-10 — 스테이션 카메라 복구와 자동 표시

사용자가 스테이션 카메라가 나오지 않는다고 보고했다. 8000은 idle/hardware로 정상이나 8001 연결 거부, 8002 camera.jpg는503이었다. 실행 프로세스 목록에서 sensor/server.py와 별도 카메라 capture 프로그램이 없음을 확인했다. sensor 종료 원인은 이번 작업에서 확인하지 못했다. .venv-sensor의 기존 sensor/server.py를 --port8001 --depth --depth-rgb --data-root C:/Users/tilti/PAC2026_data로 숨김 실행해 복구했다(부모PID37264, 실제리스너32384). 기존 robot8000, preview8002, 별도 live_view를 재시작하지 않았고 로봇 이동 요청은 없다.

상대 station/web/index.html은 새로고침마다 liveOn=false여서 화면이 다시 꺼졌다. 초기 켜기/숨김/false 상태를 끄기/표시/true로 바꾸고 초기 liveNext()를 호출하도록 수정했다. 사용자가 수동 끄기는 계속 가능하다. 현장 파일을 백업한 뒤 네 항목만 동일 적용했고 최근 Claude 강제 HOME 코드 등은 그대로 유지했다. 상단 안내 제거와 의미별 검사 카드를 유지한다.

실제 /health ok=true, vis/lwir/depth=true, live모드와 Gemini RGBD ready를 확인했다. 8000 브라우저를 새로고침해 시료/상자/세션을 보존하고 자동으로 img 로드 완료·1506x360·8002 camera.jpg·상자 위치 테두리 표시 상태를 확인했다. 세 카메라가 보이는 실제 스크린샷을 저장했다. 공유/현장 inline JavaScript 파싱 통과. 단순 표시 초기값 수정이라 새 테스트는 추가하지 않았다. 카메라 원본 촬영/현재 로봇 검사를 새로 실행하지 않아 냉매 판정과 로봇 완주 검증을 주장하지 않는다.

증거/복구본: C:/Users/tilti/PAC2026_data/station_camera_restore_20261010/cameras_restored.png, health.json, index.before.html, sensor.stdout.log, sensor.stderr.log. 기존 미커밋 codex/vision_pick/bootstrap.py는 이번 변경에서 제외한다.


## 2026-10-10 — 영상 갱신 지연 개선과 카메라 아래 문구 삭제

사용자가 웹 영상 프레임 드랍과 카메라 아래 두 안내 문구 삭제를 요청했다. 기존 index.html/preview_server.py는 프레임 응답 뒤 800ms를 더 기다리고 preview는 매 요청마다 HTTP 클라이언트를 새로 만들었다. live.jpg는 화면 갱신에도 전체 마커/센서 association 분석을 수행했다. 원래 검사·로봇 코드를 확인한 뒤 표시 경로만 수정했다.

변경 파일: codex/vision_pick/preview_server.py 및 tests/test_preview_server.py, 상대 claude-code/PAC2026_system/sensor/server.py 및 sensor/tests/test_server.py, station/web/index.html. 화면 요청은 직전 프레임 완료 후 최대15fps 주기로 예약하고 숨겨진 탭은 요청을 멈춘다. preview는 수명이 관리되는 httpx.Client를 재사용하며 live.jpg?fast=1을 요청한다. fast 표시 경로는 반복 마커/association 분석을 생략하고 기존 기본 live.jpg 및 inspect/locator 동작을 유지한다. 연결 실패는 이전 영상 캐시를 정상 응답으로 돌려주지 않는다. 가운데 흰 영역의 상자 하나만 표시하는 기존 윤곽 조건은 유지한다. outlineStatus 요소/CSS/JavaScript 참조와 '빨간 테두리는…불합격 표시와 별개' 문단을 함께 제거했다.

실제 검증: .venv-station Python -m pytest tiltis/codex/vision_pick/tests/test_preview_server.py tiltis/codex/vision_pick/tests/test_box_overlay.py --confcutdir=tiltis/codex/vision_pick -q →37 passed,1 warning(7.27s). .venv-sensor Python -m pytest sensor/tests/test_server.py --confcutdir=sensor -q -k 'live_jpg_and_marker_recorded or fast_live_image' →2 passed,27 deselected,1 warning(5.91s). 최초 confcutdir 미지정 실행은 루트 conftest의 미설치 LeRobot import에서 실패해 수집 범위를 교정했다. 마지막 문구 삭제 후 공유/현장 HTML inline JavaScript 파싱 통과. fake 카메라/API 테스트이며 실제 로봇 검증이 아니다.

현장 HTML은 최신 Claude 강제 HOME/H·hub 기능과 나머지 동작을 보존한 부분 수정으로 적용했고 실제8000을 새로고침해 두 문구 삭제와 세 카메라 표시를 확인했다. 센서 파일에도 fast 표시 경로를 부분 적용했지만 기존 Python 프로세스는 구 코드를 캐시하고 있어 백엔드 최적화는 아직 활성화되지 않았다. 실행 중 센서8001 PID32384와 미리보기8002 PID20996의 종료/재시작 명령은 자동 승인 검토가 차단했다(구체적인 이유 미제공). 사용자 수동 종료 확인 뒤에도 같은 PID/listener와 구 OpenAPI를 확인해 새 프로세스 시작을 취소했다. 중복 카메라 소유자를 시작하거나 로봇8000을 종료하지 않았다. 수동 명령의 실제 오류/출력 확인 및 두 포트 해제 후 동일 venv/인자로 시작하고 성능을 재측정해야 한다.

성능 증거: C:/Users/tilti/PAC2026_data/station_video_fps_20261010/before.json에서 sensor 응답 중앙값356.6ms, preview534.1ms(각5개 요청). 화면 갱신 대기만 제거한 뒤 브라우저 요청 주기는 약1.31회/s였으며 새 백엔드의 실제fps 또는15fps 달성을 주장하지 않는다. 같은 폴더에 sensor.before.py, index.before.html, browser_pacing.json, camera_captions_removed.png가 있다. 기존 미커밋 bootstrap.py는 이번 수정/커밋에서 제외한다.
