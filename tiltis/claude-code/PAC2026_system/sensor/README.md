# sensor — RGB + 열화상 촬영

Windows 전용(DirectShow). 카메라: Arducam IMX179(RGB), FLIR Boson 320(열화상, Y16 원시값).

## 설치 (새 PC)

```powershell
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\pip install --no-deps flirpy
```

이 데스크톱에는 `D:\PAC2026_env`에 같은 환경이 설치되어 있다.

## 1. 카메라 확인 (새 PC에서 가장 먼저)

```powershell
venv\Scripts\python check_cameras.py
```

8개 항목이 모두 PASS여야 한다. `5초 동시 수신`이 실패하면 두 카메라를 서로 다른 USB 포트(가능하면 좌우 반대편)에 꽂는다. 샘플 영상은 `check_out\`에 저장된다.

## 2. 미리보기와 촬영

```powershell
venv\Scripts\python capture_app.py --session 20261003_calib --specimen target01
```

키 설명은 `capture_app.py` 맨 위에 있다. 실험 촬영 전에는 다음을 지킨다.
- Boson을 켜고 15~20분 예열한다.
- `m`으로 FFC를 수동으로 바꾼다. SPACE를 누를 때만 FFC가 일어난다.
- 조명을 맞춘 뒤 `l`로 RGB 노출·화이트밸런스를 고정한다.
- 화면 한쪽에 기준 패치(검은 절연테이프)를 둔다.

저장 위치: `D:\PAC2026_data\<session>\<시편>_<면>_<시각>\` (D:가 없으면 `%USERPROFILE%\PAC2026_data`)

| 파일 | 내용 |
|---|---|
| `vis.png` | RGB 1장 (기본 1600×1200) |
| `lwir_y16.npz` | 열화상 원시값 `stack[8,256,320]` uint16. 분석할 때 프레임 평균을 쓴다 |
| `lwir_preview.png` | 보기용 색상 영상. 분석에 쓰지 않는다 |
| `meta.json` | 시편·면·시각, RGB 설정값, FPA 온도, FFC 시각, Boson 부품번호 |

## 확인된 동작 (2026-10-02, 데스크톱)
- RGB 1600×1200 MJPEG 30fps, 열화상 Y16 320×256 60fps 동시 수신.
- 촬영 1회 약 1.2초(FFC 약 0.4초 + 대기 0.5초 포함), 촬영쌍 1개 약 2.4MB.
- 프레임 사이 원시값 잡음(픽셀별 표준편차 평균)은 약 2~5카운트.
- FFC 후 대기 0.5/1/2초 사이에 잡음 차이가 없다(각 3회). 대기 0.5초를 유지한다.
- 연속 FFC 9회(약 30초) 동안 가운데 영역 평균이 최대 약 90카운트 움직였다. 장면이 완전히 정지 상태가 아니어서 카메라 변동인지 아직 구분하지 못했다. 정지 장면에서 `measure_drift.py drift`로 확인할 것.
- RGB 자동 초점 여부는 미확인. 미리보기에서 렌즈 앞에 손을 가까이 대 보고 초점이 움직이는지 확인할 것.

## 측정 스크립트

```powershell
venv\Scripts\python measure_drift.py settle                        # FFC 후 대기시간 비교 (약 30초)
venv\Scripts\python measure_drift.py drift --minutes 30 --every 30  # 예열 곡선 (전원 넣자마자 시작)
```

## 주의
- Arducam은 크기를 먼저 정하고 MJPG를 지정해야 적용된다. 순서가 바뀌면 YUY2로 열리고 1600×1200에서 3fps로 떨어진다. `open_vis`가 이를 검사한다.
- 이 Boson 펌웨어는 FFC 완료 상태(3)를 보고하지 않는다. 마지막 FFC 프레임 번호가 바뀌는 것으로 완료를 판단한다.
- 열화상 원시값은 섭씨가 아니다(비방사측정형). 같은 세션 안에서, 기준 패치 대비 상대값으로만 비교한다.
