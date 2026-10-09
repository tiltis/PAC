# 로봇 연결 상태 점검

`robot_status.py`는 기존 LeRobot 0.6.1의 SO101Follower 모터 정의를 재사용한다. 모델·포트·보정 ID를 확인한 뒤 사용한다. 모터 이동·토크·보정 레지스터를 쓰지 않고 버스 ping/read로 현재 위치와 보정 일치를 조회한다. 일반 `robot.connect()`는 설정/보정을 변경할 수 있어 호출하지 않는다. 카메라도 연결하지 않는다.

보정·티칭·실기 스테이션이 같은 포트를 사용 중이면 **동시에 실행하지 않는다**. Windows의 보정 프로세스가 끝나고 포트를 놓은 뒤 실행한다. 기존 프로세스를 자동 종료하거나 포트 권한을 강제로 가져오지 않는다.

```powershell
# 이 폴더에서. COM8/so101_follower는 확인 후 실제 값으로 지정
& 'C:/PAC2026_system/.venv-station/Scripts/python.exe' robot_status.py --model so101 --port COM8 --id so101_follower --metadata-only
# 모델 확인·보정 완료·포트 미점유일 때 상태 조회
& 'C:/PAC2026_system/.venv-station/Scripts/python.exe' robot_status.py --model so101 --port COM8 --id so101_follower
# 하드웨어 없는 회귀 검증
& 'C:/PAC2026_system/.venv-station/Scripts/python.exe' -m unittest discover -s tests -v
```

`--metadata-only`는 USB를 열지 않고 파일/SDK만 확인한다. 실제 조회에서는 미보정이면 raw tick만 반환하며 deg/EE 위치를 추정하지 않는다. 팔 관절의 보정 단위는 deg, 그리퍼는 SDK의 0~100이다. 정규화 전/후 값은 각각 별도 읽기이며 취득 시간 구간도 별도로 반환한다. 상태 출력은 학습용 시간 동기화 데이터가 아니다.

SDK 버스 handshake는 기대 모터 ID/모델/펌웨어를 확인하고, 보정 일치는 범위/오프셋을 읽어서 비교한다. 관절 제한·충돌·실제 속도·정지 검증을 대신하지 않는다. `motion_readiness`는 항상 `not_verified`다. `bin_ok`(파랑), `bin_human`(빨강)의 실제 내려놓을 자세는 검사 시스템의 기존 `station/teach.py`로 가르친다. 실제 이동은 현장 검증과 사용자 승인 뒤 수행한다.
