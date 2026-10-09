# 새 푸시 검토 — 3dffdae (2026-10-09)

사용자 요청: Claude Code가 새로 푸시한 변경을 확인할 것.
`origin/main`을 fetch하고 깨끗한 로컬 main을 7c5a302 → 3dffdae로 fast-forward했다.
변경은 35개 파일, 304줄 추가/1151줄 삭제다. 실행 중인 `C:/PAC2026_system/`은
이 Git 동기화 대상이 아니며 교체하지 않았다.

## 확인한 현장 성과

Claude 인계의 갈색 옆집기 → 들기 → A/B/C 검사 → 빨강 영역 → home 2회 완료
기록을 읽었다. 로컬 서버의 GET `/api/status`, `/api/runs?limit=5`도 읽었다.
서버는 `robot_mode=hardware`, `state=done`, `busy=false`였고 아래 두 완료 기록이 있다.

- run 31, GOLD2: 19:21:39–19:22:13, done/suspect/placed_bin=human, error=null.
- run 32, OK1: 19:28:18–19:28:54, done/suspect/placed_bin=human, error=null.

이는 서버 기록 확인이며 Codex가 현장 움직임을 새로 실행하거나 영상으로 재검증한
결과는 아니다. 인계의 남은 항목은 정상 테이프 3개 상자의 파랑 분류, 흰 상자 집기,
냉매 열화상 기준이다.

턱 중심 오프셋, 가까운 IK 해, 접근 거리 조절, 재집기 시 home으로 시야 확보,
면별 `tape_counts`/count-golden, 실제 관절/FK 목표 오차 기록을 공유 코드에서
확인했다. 현장 poses/handeye를 Git에서 제외한 변경은 유지한다.

## 재현한 연결 회귀

1. **SAM–깊이 계약 삭제:** sensor/locate.py:45의 `locate_box()`에서 `table_roi`와
   `object_mask`가 제거됐다. 기존 sam_depth.py가 호출하면
   `unexpected keyword argument 'table_roi'`로 이동/회전한 상자 추정과 통합이 실패한다.
2. **상자 방향 정렬 삭제:** station/grasp.py:168–169는 측정한 상자 축 대신 radial yaw다.
   `side_box_alignment()`가 없어졌고, 상자 방향 그대로는 도달 불가인 회귀 장면을
   radial 자세로 바꿔 성공 처리한다. 사용자의 SAM 윗면 각도 정렬 요구와 다르다.
   SO101 5축 도달성 제약을 유지하며 두 구현을 통합해야 한다.
3. **집기 재확인/준비 검사 연결 삭제:** sequencer에서 preflight_ready와 접근/재시도 후
   verify_at_grasp 호출이 빠졌다. 모의 테스트에서 준비가 없는 설치에서도 home/그리퍼
   명령이 기록되고, 접근 후 상자 이동을 닫기 전에 거부하지 않는다. run_station.ps1:28도
   vision 모드에서 Codex guard wrapper를 거치지 않고 app:app으로 실행한다.
4. **계산된 lift 삭제:** sequencer.py:417/428에서 비전 계획의 들기 목표 대신 저장된
   lift를 다시 사용한다. 저장 pick/lift 없이 상자 위치를 바꾸는 자동 작업 및 재촬영
   회귀가 실패한다. 위치마다 새 계획을 사용하는 연결을 유지해야 한다.
5. sensor/server.py:172의 locate 응답에서 `captured_at_s`/`last_frame_at_s`가 삭제됐다.
   guard가 필요로 하는 촬영 신선도 계약이 빠졌다. locate의 엄격한 탐색 ROI/별도 책상 ROI,
   복수 후보 거부와 수직 하향 평면 basis도 제거됐고 해당 test_pick_area.py가 삭제됐다.
   이 항목은 diff 검토이며 삭제된 센서 테스트를 이번에 따로 복원/실행하지는 않았다.
6. import_grasp_profile.py:37–38는 보정 해시가 양쪽 모두 None일 때 같은 것으로 통과한다.
   해당 누락 해시 거부 회귀도 제거됐다. 이 항목은 코드 비교로 확인했다.

상대의 현장 성공 기록을 부정하는 결과가 아니라, 기존 Codex/SAM 및 위치 변화에 대한
연결 계약이 공유 최신 소스에서 유지되지 않는다는 결과다. 기존 설정의 집기 성공을
임의 상자 회전/다중 상자/오래된 관측까지 일반화하지 않는다.

## 실제 실행한 테스트

각 작업 폴더에서 `C:/PAC2026_system/.venv-station/Scripts/python.exe -m pytest ...
-q --disable-warnings --rootdir . --confcutdir . -o addopts= --tb=short`를 실행했다.

| 작업 폴더 | 대상 | 결과 |
| --- | --- | --- |
| codex/vision_pick | tests | 22 failed / 36 passed / 1 warning, 5.23s |
| codex/rgb_box | tests | 6 failed / 37 passed, 1.20s |
| claude-code/PAC2026_system | station/tests/test_vision_pick.py station/tests/test_grasp_check.py | 24 passed / 1 warning, 19.51s |
| claude-code/PAC2026_system | sensor/tests/test_rules.py | 13 passed / 4 warnings, 7.10s |

테스트는 모의 입력/모의 로봇/기구학 계산이다. 전체 공유 테스트나 새 count-golden의
실제 판정 성능 평가를 실행한 결과는 아니다. 기존 정렬 테스트 중 1개는 mock IK의
q0 호출 형태 변경으로도 실패하므로 22개를 모두 독립적인 제품 결함 수로 세지 않는다.

이번 작업은 fetch/소스 동기화/검토/테스트/인계 문서만 수행했다. 로봇 명령, 카메라
점유, 실행 설정 변경, 서버 재시작, 배포 파일 쓰기 없음. 현장 개선을 보존한 상태에서
SAM 계약·상자 축 정렬·guard·현재 lift를 통합하고 이 실패 회귀를 통과시키는 작업이 남는다.
