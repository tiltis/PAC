# tiltis(진성현) 작업 폴더 — 콜드체인 포장 다면 검사 시스템

`PAC2026_system/`: 팀 크랭크 검사 시스템(센서 서버 + 로봇 스테이션). LeRobot 본체와는 별개로 독립 실행한다.

- 설치·실행: [PAC2026_system/README.md](PAC2026_system/README.md)
- 센서↔스테이션 통신 형식: [PAC2026_system/CONTRACT.md](PAC2026_system/CONTRACT.md)
- 10/9 현장 순서: [PAC2026_system/내일_로봇_순서.md](PAC2026_system/내일_로봇_순서.md)

압축은 OneDrive 밖(예: `C:\PAC2026_system`)에 두고 `setup_sensor.bat -Depth` → `setup_station.bat -Robot` → `run_all.bat -Depth`.
가상환경(.venv-*), 촬영 데이터, DB는 올리지 않는다.
