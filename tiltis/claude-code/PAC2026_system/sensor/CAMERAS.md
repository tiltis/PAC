# 카메라 스펙

센서 서버가 쓰는 카메라 3대. "제조사 공개값"은 데이터시트 기준이고, "이 장비에서 확인"은 `check_cameras.py`·실측 결과다.

## 요약

| 역할 | 기종 | USB ID | 해상도(사용) | 프레임률(확인) | 연결 |
|---|---|---|---|---|---|
| RGB | Arducam IMX179 8MP (UVC) | 1BCF:0B15 | 1600×1200 MJPEG | 27~30fps | USB2 |
| 열화상 | FLIR Boson 320 | 09CB:4007 | 320×256 Y16 | 60fps | USB2 (UVC + 시리얼 제어 포트) |
| 깊이 | Orbbec Gemini 2 | 2BC5:0670 | 깊이 + RGB + IR | 깊이 31fps | USB3 필수 |

Windows 장치 이름: `Arducam IMX179 8MP Camera`, `FLIR Video`, `Orbbec Gemini 2 Depth/RGB/IR Camera` (2026-10-09 노트북에서 확인).

## Arducam IMX179 8MP (RGB)

제조사 공개값
- 센서: Sony IMX179, 1/3.2", 8MP(3264×2448), 픽셀 1.4µm, 롤링 셔터
- 출력: MJPEG / YUY2, UVC(드라이버 불필요)
- 대표 모드: 3264×2448 @15fps, 1920×1080 @30fps, 1600×1200 @30fps (MJPEG)
- 화각·초점 방식: 렌즈 옵션에 따라 다름(모듈 라벨 확인)

이 장비에서 확인
- 1600×1200 MJPEG 30fps(노트북 27fps). 크기를 먼저 정하고 MJPG를 지정해야 한다. 순서가 바뀌면 YUY2로 열려 3fps.
- 자동 초점 여부 미확인.
- 오디오(MEDIA) 인터페이스는 Windows에서 Error 상태지만 영상에는 영향 없음.

## FLIR Boson 320 (열화상)

제조사 공개값
- 비냉각 VOx 마이크로볼로미터, 320×256, 픽셀 피치 12µm
- 파장: LWIR 8~14µm
- 감도(NETD): <50mK (Industrial 등급 <40mK)
- 프레임률: 60Hz (수출 규제판 <9Hz)
- 출력: USB UVC(8비트 영상 / 16비트 Y16 원시값), CMOS·MIPI 옵션
- 화각: 렌즈별(약 12°~92° HFOV). 이 장비 렌즈는 `meta.json`의 Boson 부품번호로 확인
- 전력: 약 0.5W, 셔터(FFC) 내장

이 장비에서 확인
- Y16 320×256 60fps. 비방사측정형이라 원시값은 섭씨가 아님 → 같은 세션 안에서 기준 패치 대비 상대값만 비교.
- 15~20분 예열, FFC 수동. 이 펌웨어는 FFC 완료 상태(3)를 보고하지 않음.
- 프레임 사이 잡음 약 2~5카운트.

## Orbbec Gemini 2 (깊이)

제조사 공개값
- 방식: 능동 스테레오 IR
- 깊이: 최대 1280×800 @30fps, 범위 약 0.15~10m(최적 0.2~5m), 화각 약 91°H × 66°V
- 정밀도: 2m에서 약 2% 이하
- RGB: 1920×1080 @30fps, 화각 약 86°H × 55°V
- IMU 내장, USB 3.0 Type-C(전원 겸용)
- SDK: Orbbec SDK / pyorbbecsdk

이 장비에서 확인
- USB3 연결에서 깊이 31fps. USB2로 잡히면 `check_cameras --depth`가 실패 처리.
- 설치: 책상 위 약 19cm, 약 14° 아래. 흰 상자 49cm에서 중심 반복 ±1.5mm.
