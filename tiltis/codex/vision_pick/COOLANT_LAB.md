# 냉매 열화상 준비

현재 현장 `sensor/calib/rules.json`의 `coolant`는 null이다. 테이프/밑면 규칙은 유지하고 냉매 보정은 별도 작업 공간에서 진행한다. 기존 `sensor/rules.py`의 `coolant_delta`와 `rules_calib.py`의 기준값 맞추기를 재사용한다. 이 도구는 카메라, 로봇, 서버 설정을 제어하지 않는다.

현재 가진 냉매 있음 시료로는 표면/기준 영역과 반복성을 먼저 확인한다. 없음 시료가 없으면 유무 분리 성능이나 누락 검출 기준을 검증할 수 없다. 기존 저장 사진은 냉매 유무가 확인되기 전까지 unknown이다.

열화상은 상자 표면의 열 상태를 측정한다. 냉매 종류/초기 상태, 상자 재질·크기, 냉매 위치, 넣은 뒤 경과 시간, 촬영 면/자세, 주변 조건을 같이 기록한다. 냉매를 뺀 직후의 차가운 상자는 독립된 실온 없음 시료로 쓰지 않는다. 원시값은 섭씨가 아니며 자동 색상 미리보기의 파랑/빨강 자체를 판정값으로 쓰지 않는다. [FLIR 표면 측정 설명](https://docs.flir.com/T810603/en-US/latest/s07.html).

## 사용

저장 촬영에는 `meta.json`, `vis.png`, `lwir_y16.npz`가 필요하다. 카메라 영상을 새로 확보할 때 기존 센서 서버를 사용하며 별도 카메라 프로세스를 열지 않는다. 실제 로봇 검사 시작은 사용자 조작으로 한다.

PowerShell에서 이 파일과 같은 폴더로 이동한 뒤:

```powershell
$pacPy = 'C:/PAC2026_system/.venv-station/Scripts/python.exe'
$pacLab = 'C:/Users/tilti/PAC2026_data/coolant_lab_20261010'
& $pacPy coolant_lab.py --system-dir C:/PAC2026_system --workspace $pacLab init
```

열화상 원본 좌표(현장 320×256)에서 냉매 영향이 나타나는 **상자 표면**과 **고정된 독립 기준 패치**를 지정한다. RGB 테두리를 그대로 옮기지 않는다. 패치는 사람 손·로봇·다른 상자로 가려지면 안 된다. 아직 현장 ROI를 선정하지 않았으므로 숫자를 임의로 채우지 않았다.

```powershell
& $pacPy coolant_lab.py --system-dir C:/PAC2026_system --workspace $pacLab roi --capture '<촬영폴더>' --rois '<표면x0,y0,x1,y1>;<기준x0,y0,x1,y1>'
& $pacPy coolant_lab.py --system-dir C:/PAC2026_system --workspace $pacLab measure --captures '<냉매있음 촬영1>' '<냉매있음 촬영2>' '<냉매있음 촬영3>' --label present
```

출력은 표면−기준 영역의 중앙값 차이(counts), 각 촬영 내 프레임별 차이 범위, 원본 경로, 검사면, 화질 상태다. 같은 촬영의 8프레임을 독립 촬영 8개로 세지 않는다. 시료 상태가 확인되지 않았으면 `--label unknown`을 쓴다.

없음 조건 준비 후 같은 자세·면에서 각 조건 최소 3회 별도 촬영을 모은다. 이는 기존 보정기의 최소 입력 조건이며 충분한 성능 검증 표본 수를 의미하지 않는다.

```powershell
& $pacPy coolant_lab.py --system-dir C:/PAC2026_system --workspace $pacLab fit --on '<있음1>' '<있음2>' '<있음3>' --off '<없음1>' '<없음2>' '<없음3>' --source-id '<실험ID>'
```

같은 촬영 중복·양쪽 집단 재사용, 다른 검사면, 잘못된 ROI, 미확인 화질은 거부한다. 생성되는 `coolant_draft.json`은 항상 `validated=false`, `deployment_ready=false`인 초안이다. 분포가 분리돼도 별도 날짜/시편 촬영으로 확인해야 한다. 현재 테이프 설정에 덮어쓰지 말 것. 이후 냉매 검증을 독립 상태로 통합하고 `냉매 누락 의심`/`냉매 확인 필요`를 기존 UI 사유 표시와 연결한다.

남은 작업: 현장 열화상 ROI 선정, 있음 반복 촬영의 명시적 라벨링, 없음 조건 수집, 독립 평가, 실시간 검사 자세에서 ROI 유효성 확인, 최종 스테이션 통합. 아직 냉매 판정을 활성화하지 않았다.
