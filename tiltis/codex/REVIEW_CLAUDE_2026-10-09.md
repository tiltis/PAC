# Codex → Claude 작업 검토 — 2026-10-09

## 확인한 버전과 범위

Claude의 로컬 대화에 남은 완료 보고와 GitHub 커밋 `f09b907`, `08cc7107d605e7b252003252ff736a87bf89e39c`를 대조했다. 새 커밋은 이전 경로에 생긴 중복을 정리하고 `tiltis/claude-code/PAC2026_system/`에 노트북 변경을 반영했다. Codex 작업본은 `08cc710`까지 fast-forward했다.

검토 시작 시 Git에 등록된 시스템 파일 91개는 `C:\PAC2026_system` 배포본과 줄바꿈을 제외하면 모두 같았다. 기존 시스템 전체를 Claude가 이번에 새로 작성했다고 해석하지 않는다. 이번 변경은 이전 `c64ac68` 대비 Claude 폴더의 16개 파일이며, 손목 제어 폴더는 바뀌지 않았다.

## 확인한 Claude 변경

- 흰 상자 70×70×90mm와 갈색 상자 80×80×45mm 후보 설정, 높이·앞면 길이를 이용한 후보 선택.
- `locate.py`: 축소 해상도, 거리 범위, 깊이 경계 분리, 후보 실패 진단, 평면 SVD의 `full_matrices=False` 적용.
- `grasp.py`: 높이 비례 파지 깊이(20~35mm), 접근·들어올림 20mm, 위치 찾기 재시도.
- 테이프 색 범위 H 35~95, 면별 테이프 개수·누락 ID, 웹 화면의 테이프·냉매 표시.
- 현장 설정을 테스트에서 분리하는 fixture, 서버의 영상을 받아 보여 주는 `live_view.py`, 설치·현장 절차 문서.

Claude가 기록한 카메라 PASS, 라이브 검출 4/5~5/5·반복 ±1.5mm, 테이프 fit/eval 결과는 [Claude HANDOFF](../claude-code/HANDOFF.md)의 실측 보고다. 이번 Codex 검토에서 실제 카메라 실험을 반복한 결과로 표시하지 않는다. 실기 로봇은 미검증이다.

## Codex가 직접 재검증한 결과

공유 LeRobot 저장소의 상위 `conftest.py`가 별도 시스템 테스트에도 로드되어 처음 실행은 import 오류로 막혔다. 상위 설정을 분리한 다음 명령으로 재실행했다. 별도의 SDK 설치나 서버 재시작 없이 기존 가상환경을 사용했다.

작업 폴더: `tiltis/claude-code/PAC2026_system`

```powershell
& 'C:\PAC2026_system\.venv-sensor\Scripts\python.exe' -m pytest sensor/tests -q --disable-warnings --rootdir . --confcutdir . -o 'addopts='
& 'C:\PAC2026_system\.venv-station\Scripts\python.exe' -m pytest station/tests -q --disable-warnings --rootdir . --confcutdir . -o 'addopts='
```

- Claude 원본 `08cc710`: 센서 **99 passed, 9 warnings / 40.48s**, 스테이션 **104 passed, 4 warnings / 57.74s**.
- 아래 깊이 집계 수정 후: 센서 **103 passed, 9 warnings / 43.47s**. 스테이션 소스는 이 수정에서 변경하지 않았다.
- 별도 가상 깊이 점검: 두 상자 모두 `downsample=1`과 서버 기본값 `2`, 거리 범위 200~700mm에서 올바른 후보를 선택했다. 노트북 계산 시간은 네 사례 각각 약 0.09~0.38초였다. 실제 영상 성능으로 일반화하지 않는다.

## 수정한 오류: 유효 깊이 과반이 NaN 때문에 사라짐

`sensor/server.py`는 무효 깊이를 NaN으로 만든 뒤 일반 `np.median`을 썼다. 한 픽셀의 5프레임이 `[400, 401, 0, 399, 0]`mm이면 유효한 3개가 과반인데도 중앙값이 NaN이 되고, 위치 찾기 함수에는 **0mm**가 전달됐다. 카메라 없이 FakeDepth와 FastAPI TestClient로 실제 `/object/locate` 경로에서 재현했다. 이 줄은 `08cc710` 이전에도 존재한 오류다.

Codex는 Git 작업본의 `sensor/server.py`에서 유한한 양수 샘플만 대상으로 masked median을 계산하도록 수정했다. 과반 미만은 계속 0으로 거부한다. `sensor/tests/test_server.py`에 부분 유효·과반 미만·전부 유효·전부 무효 네 회귀 사례를 추가했다. 수정 전 **1 failed, 3 passed**, 수정 후 전체 센서 **103 passed**를 확인했다.

실행 중인 `C:\PAC2026_system` 배포본에는 이 수정이나 서버 재시작을 적용하지 않았다. 해당 배포본과 Git 작업본의 차이는 이제 이 수정 두 파일이다. 다음 배포에서는 사용 중인 카메라·보정·데이터를 보존하면서 이 차이를 반영하고 서버 버전을 확인한다.

## 실기 전 해결할 접근 경로 문제

`station/grasp.py`의 접근점은 **윗면이 아니라 파지점**을 기준으로 계산한다.

```python
grasp_p = top - n * depth_mm / 1000.0
approach_p = grasp_p + n * cfg["approach_mm"] / 1000.0
```

현재 설정 파일을 직접 로드하고 기존 테스트의 가상 hand-eye/FK로 검증했다. 로봇 앞 0.20m, 집게 yaw 45°, 책상 z=0인 사례에서 둘 다 `plan.ok=True`였다.

| 시편 | 윗면 z | 파지 깊이 | 접근점의 집게 끝 z | 윗면 위 접근 여유 |
|---|---:|---:|---:|---:|
| 흰 상자 | 90mm | 35mm | 75mm | **−15mm** |
| 갈색 상자 | 45mm | 20mm | 45mm | **0mm** |

이는 README의 "손잡이 위 25mm에서 DryRun 확인"과 일치하지 않는다. IK 성공은 상자·집게·관절 이동 경로의 충돌 검증이 아니다. 열린 집게가 상자 양옆으로 들어갈 수 있는지는 실제 개구 폭·도구 형상·진입 경로에 달려 있어 충돌을 실측했다고 단정하지 않는다. **윗면을 넘는 접근 여유 또는 검증된 측면 진입 경로가 없는 현 설정을 실기 준비 완료로 취급하면 안 된다.**

다음 연결 작업에서 접근 기준을 명확히 정하고, 현재 관절→접근점→파지점의 경로와 충돌을 검증해야 한다. 윗면 위 여유를 요구하는 경로가 IK/관절 한계 때문에 불가능하면 계획을 거부하고 설치 위치나 집기 방식을 다시 정한다. 단순히 접근 높이를 낮춰 도달 가능성만 통과시키지 않는다. 이번 검토에서 임의의 새 실기 좌표나 여유값을 적용하지 않았다.

## 남은 연결 경계

- 웹 `/api/abort`는 sequencer의 중단 플래그를 설정한다. 현재 계약·테스트는 단계 경계 중단이며 진행 중인 SDK 이동을 즉시 중단하는 보장은 없다. `So101Robot.stop()`의 hold 통신 예외 무시도 남아 있다. 손목 bridge의 watchdog/수동 재활성화 계약을 이 코드에 그대로 만족한다고 간주하지 않는다.
- 실제 모델·포트·관절 보정·카메라–로봇 변환·도구 형상·충돌·물리 속도와 비상정지 확인, 사용자 실기 승인까지는 여전히 필요하다.
- 검사와 손목 제어는 분리된 구현이다. 이번 Claude 변경은 `/api/state.position_m`을 실제 SDK에 연결한 완료 근거가 아니다.
- 학습 데이터는 명령뿐 아니라 실제 관절/EE 관측과 시각을 함께 기록해야 한다. 이번 검토에서 실기 학습 데이터를 생성하지 않았다.

다음 Claude 작업은 이 기록과 [Codex HANDOFF](HANDOFF.md)를 읽고 진행한다. 로컬 로그·계정 정보·현장 테이프 기준값은 이 리뷰에 복사하지 않았다.
