# robot_setup — SO-101 새 PC 준비 팩

새 Windows PC에서 SO-101 팔을 바로 쓰기 위한 파일 모음.

| 파일 | 내용 |
|---|---|
| `driver_ch343\` | 로봇 제어보드 USB 직렬 드라이버(WCH CH343, `ch343ser.inf` 2.1.2025.7, Microsoft 서명). 노트북에서 내보낸 것 |
| `so101_follower.json` | 우리 팔의 LeRobot 보정값(2026-10-09 15:22, COM8에서 보정·읽기 확인) |
| `install_robot.bat` | 드라이버 설치 + 보정 파일 복사 |

## 사용

1. 로봇 USB를 꽂는다.
2. `install_robot.bat`을 **관리자 권한으로 실행**한다(드라이버 설치에 필요).
3. 장치 관리자 → 포트에 `USB-Enhanced-SERIAL CH343(COMx)`가 보이면 된다. 번호는 PC마다 다르다.
4. 파이썬 패키지(LeRobot)는 상위 폴더 `setup_station.bat -Robot`으로 설치한다.
5. 확인: `.venv-station\Scripts\lerobot-find-port` 로 포트 확인 후 `run_all.bat ... -Robot so101 -RobotPort COMx`.

## 주의
- 보정 파일은 **이 팔 전용**이다. 다른 SO-101에 쓰지 말고 `lerobot-calibrate`로 새로 만든다. 모터를 분해·교체했으면 다시 보정한다.
- 보정 파일 위치: `%USERPROFILE%\.cache\huggingface\lerobot\calibration\robots\so_follower\so101_follower.json` (`--robot.id=so101_follower`).
- Windows 11은 드라이버 없이도 기본 `usbser`로 잡히는 경우가 있다. 통신이 불안정하면 이 드라이버를 설치한다.
- 드라이버 원본: WCH 공식 https://www.wch-ic.com/downloads/CH343SER_ZIP.html
- `CP210x` 드라이버는 이 로봇에 필요 없다.
