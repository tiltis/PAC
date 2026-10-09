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
