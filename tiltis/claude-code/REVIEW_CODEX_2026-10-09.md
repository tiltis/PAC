# Claude Code → Codex 교차 리뷰 — 2026-10-09

이 문서는 실제 Claude Code의 읽기 전용 리뷰 응답입니다. 테스트 실행·실기 검증은 하지 않았습니다. 리뷰 중 Codex의 동일 tick 수정이 별도로 반영됐습니다. 아래 줄 번호는 검토 시점 소스 기준이며 현재 코드에서는 달라질 수 있습니다. Codex의 재현·반영 및 미반영 근거는 ../codex/HANDOFF.md에서 확인하세요.

읽기 전용 교차 검토를 마쳤습니다. 테스트나 스크립트는 실행하지 않았고, Read/Glob/Grep로 `codex/pac_minimal` 소스·테스트 5개, `station/robot.py`·`kinematics.py`·URDF, LeRobot 본체 `so_follower.py`·`model/kinematics.py`·`motors_bus.py`를 대조했습니다.

**결론.** 집중 검토 항목인 정지 뒤 명령 전송, watchdog, 오래된 입력, 수동 재활성화, 좌표·단위·작업 범위 검증에서는 재현 가능한 안전 버그를 찾지 못했습니다. 세대 번호 검사, lock 밖 IK 결과 폐기, 왕복시간 가산, 프레임 ID 중복 무시는 코드와 테스트가 일치합니다. 대신 실기에서 손목 제어를 사실상 막는 설계 계약 문제 1건, 운용 안전에 영향 있는 동작 1건, 진단·로그 문제 3건을 확인했습니다.

| 번호 | 심각도 | 요약 |
|---|---|---|
| 1 | 중 | 전체 EE 자세 유지는 도구 접근축이 수직일 때만 XY 이동과 양립 |
| 2 | 중 | arm 직후 손이 정지해 있어도 EE가 목표까지 자동 이동 |
| 3 | 하 | 거부된 명령의 action·관측이 로그에 남지 않음 |
| 4 | 하 | 정지 원인이 후속 폴링에 덮어써짐 |
| 5 | 하 | 카메라가 붙은 robot config를 실기 backend가 거부하지 않음 |

## 1. 검증 가능한 문제

**문제 1. 전체 EE 자세 유지 계약은 접근축이 수직일 때만 성립한다.**
`so101_backend.py:70-72`는 arm 시 저장한 회전행렬 전체를 IK 목표로 쓰고, `so101_backend.py:102-105`는 결과 자세를 전체 각 오차 0.02 rad로 검사합니다. `robot_bridge.py:141`은 기준 자세를 저장만 하고 수직 여부를 보지 않습니다.
근거는 URDF 구조입니다. `so101_new_calib.urdf:434-438`의 shoulder_pan 축은 수직이고, shoulder_lift·elbow_flex·wrist_flex 세 축은 서로 평행한 pitch 축입니다. wrist_roll 축은 `gripper_frame_joint`의 rpy 0 π 0 고정 변환을 거쳐 도구 z축과 일치합니다. 목표 XY가 바뀌면 pan이 바뀌고, 그 회전을 되돌릴 수 있는 관절은 roll뿐입니다. roll은 도구축 둘레 회전이므로 도구축이 pan 축과 평행할 때만 정확히 보상됩니다. 도구축이 수직에서 θ만큼 기울면 pan 변화 Δ에 대해 약 Δ·sinθ의 자세 오차가 1차로 남습니다.
재현 조건은 다음과 같습니다.

| 기준 자세 기울기 | 측면 이동 | 반경 | pan 변화 | 남는 자세 오차 | 허용치 |
|---|---|---|---|---|---|
| 30° | 2 cm | 0.3 m | 0.067 rad | 약 0.033 rad | 0.02 rad |

이 조건에서 매 step이 `motion_validation_failed`로 hold됩니다. 소프트웨어 재현은 `station/kinematics.py`의 `SO101.fk`로 같은 XY·Z에서 pitch·roll을 전수 탐색해 기준 회전과의 최소 각 오차가 허용치를 넘는 것을 보이면 됩니다. README 98~99행은 "불가능한 경우가 있다"고 썼지만 실제로는 수직 접근 자세를 제외한 모든 경우입니다. 현재 테스트의 FakeKinematics는 회전을 항상 단위행렬로 돌려주어 이 제약이 드러나지 않습니다. 해당 위치는 `test_so101_backend.py:22-25`입니다.
최소 수정은 arm 또는 backend에서 기준 회전의 z열과 world z의 각이 허용치 이내인지 검사하고, 아니면 `reference_tool_not_vertical`로 arm을 거부하는 것입니다. 근본 수정은 자세 검증을 접근축 각도만 비교하고 yaw를 자유 또는 고정값으로 두는 것이며, 이는 station IK 계약과 같습니다.

**문제 2. arm 직후 손이 정지해 있어도 EE가 목표까지 이동한다.**
`robot_bridge.py:142`는 commanded를 관측 EE로 두고, `robot_bridge.py:165-169`는 컨트롤러 목표로 매 step 접근합니다. 둘이 다르면 입력 변화 없이 0.05 m/s로 움직입니다. 기존 테스트 `test_bridge.py:22-25`가 이미 이 동작을 보여줍니다. 입력이 불변인데 EE가 모서리 쪽으로 이동합니다. 최대 이동은 가상 작업범위 대각선 기준 약 0.28 m, 약 5.7초입니다. README 68~69행의 "중앙까지 이동시키지 않는다"는 맞지만, 손 위치로 자동 이동한다는 점은 적혀 있지 않습니다.
최소 수정은 arm에서 목표와 EE 거리가 허용치, 예를 들어 0.02 m를 넘으면 `target_far_from_ee`로 거부하고, 모니터에 EE 위치를 함께 표시하는 것입니다. 대안은 활성화 시점 EE를 원점으로 한 상대 매핑입니다.

**문제 3. 거부된 명령의 맥락이 로그에 남지 않는다.**
`robot_bridge.py:180-185`에서 `stale_robot_observation`과 `motion_validation_failed`는 action·limited·observation·dt를 기록하지 않습니다. `hold` 이벤트에 reason 문자열만 남습니다. `receive` 거부와 `arm` 거부는 비활성 상태면 아무 기록이 없습니다. 각각 `robot_bridge.py:121-125`, `robot_bridge.py:135-140`입니다. 재현은 `test_validation_failure` 후 로그를 보면 `hold` 한 줄뿐인 것으로 확인됩니다. 현장에서 IK 잔차 실패를 진단할 근거가 없습니다.
최소 수정은 stop 직전에 `command_rejected` 이벤트로 action_requested·limited_position_m·observation·dt를 기록하고, arm·receive 거부도 reason과 함께 기록하는 것입니다.

**문제 4. 정지 원인이 후속 폴링에 덮어써진다.**
`robot_bridge.py:68-73`의 stop은 이미 정지된 상태에서도 reason을 바꿉니다. main 루프는 입력 비활성이면 매 주기 `input_disabled`로, HTTP 실패면 `receive_failure`로 stop을 호출합니다. 위치는 `robot_bridge.py:124`와 `robot_bridge.py:250`입니다. 따라서 `hold_failed`나 `motion_validation_failed`가 비전 쪽 정지나 서버 중단과 겹치면 한 주기 안에 사라집니다. 콘솔 스레드는 정지 전이를 출력하지 않습니다. 같은 패턴이 `control.py:63-65`에 있어, GET 요청이 200 ms 뒤 `camera_stopped`·`single_hand_required`를 `stale_frame`으로 바꿉니다.
모의 재현: hold를 예외로 바꾸고 `stop('receive_failure')`를 호출하면 reason이 `hold_failed`가 되고, 이어서 motion_enabled가 False인 상태를 receive하면 `input_disabled`로 바뀝니다.
최소 수정은 stop에서 활성 상태였을 때만 reason을 갱신하고 `hold_failed` 플래그를 별도 보관해 arm 성공 시 초기화하는 것입니다. Controller.state는 활성 상태일 때만 stop을 호출하고 valid=False는 유지하면 됩니다. 콘솔에 reason 변화를 출력하는 것도 권장합니다.

**문제 5. 실기 backend가 카메라가 붙은 robot config를 거부하지 않는다.**
`so101_backend.py:27-30`은 use_degrees와 max_relative_target만 검사합니다. LeRobot의 `get_observation`은 설정된 카메라를 매 호출마다 읽습니다. 위치는 `so_follower.py:189-200`입니다. observe와 hold가 bridge lock 안에서 실행되므로 매 step과 정지 경로에 카메라 지연이 더해지고, 손목 카메라와 장치를 다툴 수 있습니다. COLLABORATION 22행과 충돌합니다.
최소 수정은 생성자에서 `robot.config.cameras`가 비어 있지 않으면 거부하고, FakeSDK config에 cameras를 넣는 테스트를 추가하는 것입니다.

**테스트 공백.** EE가 범위 밖일 때 arm 거부, `source_restarted` 뒤 재arm, 문제 1·4·5에 대한 테스트가 없습니다. `replay.py`의 bare assert는 최적화 모드에서 사라집니다. station의 `test_kinematics.py:22`는 FK 위치만 ikpy와 비교하므로 회전은 미검증이며, 문제 1의 해법으로 station FK를 쓰려면 회전 비교가 필요합니다.

## 2. 문서에 명시된 실기 한계

아래는 버그로 보지 않았습니다. 이미 문서에 있거나 현장 확인 항목입니다.

- **lock 보유 중 SDK 정지.** README 117행대로 watchdog도 대기합니다. 통신 timeout과 하드웨어 정지 수단 검증이 필요합니다.
- **카메라 버퍼 지연.** README 48행. 처리 78 ms가 캡처 주기보다 느려 OpenCV 내부 버퍼가 차므로 프레임은 `captured`보다 수 프레임 오래됐을 수 있습니다. 완화안은 `CAP_PROP_BUFFERSIZE`를 1로 두고 grab으로 비우는 것과 현장 LED 지연 측정입니다.
- **관절 step 한계는 평균 속도만 제한.** Feetech 위치 모드는 목표까지 모터 자체 속도로 이동하며 `configure()`는 Goal_Velocity·Acceleration을 쓰지 않습니다. 위치는 `so_follower.py:159-171`입니다. README 107행을 "순간 속도 미보장"으로 보강하길 권장합니다.
- **send_action 반환 검사의 범위.** 반환값은 역정규화 전 값이고 DEGREES 역정규화는 범위 클리핑이 없습니다. 위치는 `motors_bus.py:904-907`입니다. 모터 측 제한은 반환값에 보이지 않으므로 joint_limits_deg는 보정 범위 안으로 현장에서 확정해야 합니다. README 110~111행과 일치합니다.
- **IK 수렴.** LeRobot IK는 soft task 8회 반복입니다. 2 mm 잔차 허용치에서 자주 거부될 수 있으나 보수적 실패입니다.
- **버전 차이.** station은 lerobot 0.6.1을 고정했고 저장소 본체는 더 새 API입니다. `SO101Follower`는 본체에서 별칭이고 `inverse_kinematics`의 `max_iters`는 본체에만 있으나 backend는 쓰지 않습니다. 양쪽 HANDOFF의 버전 확인 항목을 유지하면 됩니다.
- **소프트웨어 hold와 disconnect 시 torque off.** README 120행.

## 3. 상대 구현 재사용 제안

- **station IK 계약을 손목에 채택.** `station/kinematics.py:105`의 `ik(pos, down, yaw)`는 접근축과 yaw만 구속하므로 문제 1을 구조적으로 해결합니다. yaw를 arm 시점 값으로 고정하거나 None으로 두면 pan 변화가 허용됩니다. 어댑터는 `joint_names`, deg 입력 FK, deg 입력 IK를 제공하고 `from_lerobot`·`to_lerobot`과 joint_map을 적용하며, None 반환은 예외로 바꿔야 합니다. 실행 시간은 현재 관절을 seed로 주면 보통 수 ms이지만 최악은 9개 시작점 × 200회 반복이라 초 단위이므로, 30 Hz용으로는 seeds와 iters를 줄여야 합니다. 200 ms 초과 결과는 bridge가 폐기합니다.
- **station `robot.py`의 정지·이동은 손목에 재사용하지 않음.** `robot.py:301-302`는 hold 예외를 삼키고, `robot.py:175`의 `_lock`은 어디서도 쓰이지 않으며, `_halt`는 stop에서만 설정되는데 sequencer는 이동이 끝난 뒤에야 stop을 호출합니다. 위치는 `sequencer.py:174-181`과 `sequencer.py:372-379`입니다. Codex HANDOFF의 판단이 맞습니다.
- **station의 연결 패턴은 재사용 가능.** `robot.py:186`의 `SO101FollowerConfig(port, id, use_degrees=True)`는 max_relative_target과 cameras를 두지 않아 `So101Backend` 검사와 호환됩니다. 연결 후 내부 `_robot`을 backend에 넘기면 됩니다. 단 `so_follower.py:115-121`의 보정 프롬프트가 `input()`으로 막힐 수 있으니 서버 스레드에서 연결하지 않아야 합니다.
- **URDF와 도구 프레임.** station URDF의 `gripper_frame_link`는 LeRobot RobotKinematics의 기본 target frame과 같은 이름이므로, 같은 URDF를 쓰면 두 도구의 도구 프레임이 일치합니다. 실기 일치는 양쪽 HANDOFF대로 미검증입니다.
- **역방향 제안.** station은 Codex의 `send()` 반환 검사와 예외를 내는 `hold()`를 가져가면 `stop()`의 무음 실패를 없앨 수 있습니다. station `test_kinematics.py`의 FK 비교에 회전을 추가하면 손목 재사용 근거가 됩니다.

이 리뷰는 파일을 쓰지 않았으므로 COLLABORATION 16행에 따라 소유자가 `claude-code/` 폴더에 보관하고, Codex가 문제 1·2·4·5의 재현 테스트와 반영 또는 미반영 근거를 HANDOFF에 남기면 됩니다.
