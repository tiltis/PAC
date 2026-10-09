# 센서 PC ↔ 스테이션 PC 통신 약속

- **센서 서버**: Windows 노트북, 포트 8001. 카메라 촬영과 판정을 맡는다. 코드는 `sensor/`.
- **스테이션**: Mac, 포트 8000. 로봇 제어, 작업 순서, 웹 화면, 기록을 맡는다. 코드는 `station/`.
- 휴대폰은 스테이션 웹 화면(`http://<mac-ip>:8000`)에만 접속한다. 센서 영상도 스테이션을 거쳐 보여 준다.

## GET /health (센서)

```json
{"ok": true, "sensors": {"vis": true, "lwir": true, "depth": false}, "boson_part": "20320A050-6PAAX", "ffc_mode": "manual"}
```

## POST /inspect (센서)

요청:
```json
{"session": "demo_1009", "specimen_id": "S01", "face": "A", "attempt": 0}
```
- `face`: `"A"`, `"B"` 또는 `"C"` (기본 A·B. 3면 테이프 검사는 스테이션 `FACES=A,B,C`로 C까지 보여 준다)
- `attempt`: 같은 면의 0번째 촬영이면 0, 재촬영이면 1
- `trigger_id`: 요청마다 새로운 고유 문자열. 스테이션이 생성하고 센서는 그대로 응답·저장한다. `single_stationary_specimen=true`는 촬영 종료까지 한 시료를 고정한다는 호출자의 전제이며 자동 재식별 증거가 아니다.
- `session`·`specimen_id`는 최대 80자의 문자·숫자·밑줄·하이픈·내부 점만 허용한다. 경로 구분자, 선두·끝 점, Windows 예약 이름은 거부한다. 잘못된 요청은 촬영·로봇 이동 전에 HTTP 422로 거부한다.

응답 (HTTP 200):
```json
{
  "status": "ok",
  "error": null,
  "specimen_id": "S01",
  "face": "A",
  "attempt": 0,
  "verdict": "no_anomaly",
  "reasons": [],
  "features": {"rgb_sharpness": 182.4, "lwir_roi_delta": -12.3},
  "capture_id": "S01_A_20261009_101500",
  "images": {
    "rgb": "/captures/demo_1009/S01_A_20261009_101500/vis.png",
    "lwir": "/captures/demo_1009/S01_A_20261009_101500/lwir_preview.png"
  },
  "elapsed_ms": 1234
}
```
- `status`: `"ok"`는 촬영과 분석을 마쳤다는 뜻이다(판정 결과와는 무관). `"error"`는 카메라나 서버 오류이며 `error`에 원인이 들어간다. 스테이션은 `"error"`를 받으면 다음 동작으로 넘어가지 않고 멈춘다.
- `verdict`
  - `"no_anomaly"`: 검사 범위 안에서 이상이 검출되지 않음
  - `"suspect"`: 이상 의심
  - `"review"`: 결함 판정 근거가 없어 미판정·사람 검토 필요. 촬영 품질 통과만으로 `no_anomaly`를 반환하지 않는다. 현재 quality-only 규칙은 `defect_rules_unavailable` 사유로 이 상태를 반환한다. 재촬영으로 결함 규칙 부재를 해결할 수 없으므로 재촬영 대상이 아니다.
  - `"unmeasurable"`: 흐림·가림·자세 이탈 등으로 판정 불가. 재촬영 대상이다
- `reasons`: 판정 근거 코드 목록. 예: `rgb_blur`, `occluded`, `pose_out_of_range`, `lid_gap_rgb`, `lwir_local_contrast`
- `features`: 숫자 특징값. 형식은 자유이며 스테이션은 기록만 한다
- `no_anomaly`는 구현·검증된 결함 검사 결과에만 사용한다. 스테이션은 `features.defect_inspected`가 JSON `true`이고 `features.defect_rules_version`이 비어 있지 않은 문자열인 경우에만 정상 분류 근거로 받아들인다. 이 필드는 검사 수행·규칙 버전의 선언이며 정확도 보증이 아니다. 품질 전용 센서는 이 근거를 만들지 않는다.
- 근거가 없거나 `features.rules_version`이 `quality-only-`로 시작하는 구형 센서의 `no_anomaly`는 `review`로 보정한다. 원래 판정은 검사 기록의 `sensor_verdict` 및 DB에 저장되는 `features.sensor_verdict`에 남긴다.
- 모의 센서는 `features.simulated=true`와 `defect_rules_version=mock-only-0.1`을 표시한다. 모의 정상 판정은 MockRobot 순서 시험에만 사용하며 실제 로봇 모드에서는 `review`로 보정한다.
- 정상 센서 응답의 `specimen_id`·`face`·`attempt`는 요청과 정확히 일치해야 한다. 누락·불일치·잘못된 특징/사유 형식은 센서 오류로 중단한다.
- `images`: 센서 서버 기준 경로. 스테이션이 `GET http://<sensor>:8001<path>`로 받아 화면에 보여 준다
- `sensor_data`: `schema_version=pac-sensors-1`. RGB/열/깊이 원본 단위, 취득 시각, 깊이 스케일·유효 비율·ROI/전체 프레임 거리, 시각 차, 정합 기능 가용성, 시료·트리거 연결 조건, 결함 검사 미구현 여부를 기록한다.
- `artifacts`: RGB PNG, 열화상 raw NPZ/상대 미리보기, metadata JSON, 선택 depth raw NPZ의 센서 기준 경로. 깊이 미수신 시 원시 파일 경로를 만들지 않는다.
- 성공 응답의 `session`·`trigger_id`도 요청과 일치해야 한다. `sensor_data.association`의 시료·면·회차·트리거·capture_id를 추가로 대조한다. 구형 서버가 이 필드를 반환하지 않으면 새 클라이언트는 오류로 처리하므로 센서/스테이션 코드를 함께 갱신한다.
- 시간 연결은 촬영 요청 이후 새 프레임으로 제한하고, 현장 허용 시각 차 정책이 있을 때만 고정 단일 시료 조건의 연결로 표시한다. 정책 부재·정합 부재만으로 데이터를 버리거나 동일 물체 재식별 성공이라고 주장하지 않는다. 정량 결함 근거가 없으면 최종 `review`다.
- 열화상 단위는 `raw_counts`이며 대상 °C가 아니다. 깊이는 SDK scale을 적용한 `mm`, 좌표계는 깊이 픽셀이다. 두 센서의 장치 시각(ms)과 호스트 수신 시각(s)은 직접 빼지 않는다.
- 기본 깊이는 꺼져 있다. 명시적으로 활성화하면 보조 기록, 필수 모드에서는 누락/무효/이전 트리거 프레임을 측정 불가 처리한다. 실측 면별 깊이 ROI·허용거리 정책이 있을 때만 `pose_out_of_range`를 적용한다.
- 스테이션은 새 센서 상세 데이터와 원시 파일 참조를 기존 기록과 함께 DB에 보존한다. `GET /api/runs/{run_id}/inspections`로 조회한다. 기존 DB의 검사 기록을 지우지 않고 필요한 열만 추가한다.
- 타임아웃: 스테이션은 15초 안에 응답이 없으면 `"error"`로 처리한다

## 최종 판정 규칙 (스테이션)

- 두 면 중 하나라도 `suspect` → 최종 `suspect`, 사람 확인 구역으로 분류
- 아니면, 재촬영 뒤에도 `unmeasurable`인 면이 있으면 → 최종 `unmeasurable`, 사람 확인 구역으로 분류
- 두 면 모두 `no_anomaly` → 최종 `no_anomaly`, 정상 구역으로 분류
- 이상 의심·측정 불가가 없고 한 면이라도 `review` → 최종 `review`, 사람 확인 구역으로 분류
- A/B 두 면이 모두 있어야 하며 알 수 없는 판정값은 오류로 중단한다.
- 완료 기록 저장 실패는 스테이션 상태 `error`와 `persistence_error`로 노출한다. 이미 끝난 검사 판정·실제 분류함은 보존하며 추가 로봇 동작이나 자동 재실행은 하지 않는다. 실패 기록은 DB에 없을 수 있으므로 `/api/status`의 `last_result`를 확인한다.
- `/api/status`의 `busy`는 기록 저장까지 실행 중인지 나타낸다. 저장 중에는 `state=saving`, `busy=true`이며 새 검사·일시정지·재개·중단 요청은 HTTP 409로 거부한다. 저장이 끝나야 완료 상태와 다음 실행을 허용한다.
- 한 면에서 이상이 나와도 다른 면 검사는 그대로 진행해 기록한다. 다른 면의 정상 결과로 이상을 지우지 않는다.
- 재촬영은 **포장 하나당 최대 1회**다(면별 1회가 아님).

## GET /object/locate (센서, 방식 C 비전 집기)

깊이 카메라(`run_sensor -Depth`)로 집기 영역의 상자 위치·방향을 돌려준다. 새 깊이 프레임 5장의 중앙값을 쓰며 약 1초 걸린다.
```json
{"found": true, "frame": "depth_camera_mm", "top_center_cam_mm": [0.6, 70.8, 283.3], "top_height_mm": 59.7,
 "top_size_mm": [161.1, 91.3], "long_axis_cam": [...], "short_axis_cam": [...], "table_normal_cam": [...],
 "far_edge_invalid_frac": 0.29, "frames": 5, "intrinsics": {"fx": 613.9, "fy": 613.9, "cx": 636.4, "cy": 401.1}}
```
- 책상 평면 위로 솟은 덩어리 가운데, 윗면이 상자 모양(두 변 20~400mm, 채움 0.6 이상)인 가장 큰 것을 고른다. 손잡이가 있으면 가장 높은 윗면인 손잡이가 잡힌다.
- `sensor/calib/object_config.json`의 `locate_mode`
  - `"front"`(기본): 앞면 길이로 상자를 확인하고(설정 `box_mm`의 변과 25mm 이내), 상자 크기로 중심을 계산한다. 손잡이 위치는 계산값이다(`mode: "front_face_model"`, `top_size_mm: null`).
  - `"top"`: 윗면을 직접 잰다.
- 좌표는 깊이 카메라 기준 mm다. 로봇 좌표 변환은 스테이션의 hand-eye 보정(`station/calib/handeye.json`)으로 한다.
- 못 찾으면 `found=false`와 `reason`을 돌려준다. 깊이가 꺼져 있으면 HTTP 409다. 스테이션은 이 경우 가르친 자세로 바꾸지 않고 멈춘다.
