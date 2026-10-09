# RGB/SAM 상자·면 후보와 깊이 윗면 방향

사용자 요청에 따라 물체 인식부터 단계별로 확인한다. 기존 센서 서버의 `GET /live.jpg`를 읽어 RGB 패널만 사용한다. 새 카메라 핸들을 열거나 로봇 포트를 열지 않는다. 기존 검사·보정·제어 서버를 수정하거나 재시작하지 않는다.

현재 기존 RGB 검출은 `sensor/objects.py`의 빈 배경 비교이며 배경이 없으면 `no_background`다. 이 폴더는 별도로 학습하지 않은 [Grounding DINO](https://huggingface.co/IDEA-Research/grounding-dino-tiny)로 상자 후보를 찾고, `--sam`이면 후보 박스를 자동 프롬프트로 넣어 [SlimSAM](https://huggingface.co/Zigeng/SlimSAM-uniform-77) 마스크를 만든다. 매 상자마다 사람이 클릭하거나 자세를 가르치지 않는다. 두 모델은 고정 revision의 safetensors를 사용한다. 로컬 실행은 영상 업로드 없이 처리하고, 사용자가 지정한 Colab GPU 실행에서는 검증할 RGB 사진만 해당 세션에 업로드한다.

## 현재 노트북 실행

```powershell
# 이 폴더에서, 이미 준비한 별도 Python 3.12 환경 사용
& 'C:/PAC2026_system/.venv-rgb/Scripts/python.exe' run.py --sam --samples 1
# 새 사진 세 번 확인; 실시간 영상 FPS와 다르다
& 'C:/PAC2026_system/.venv-rgb/Scripts/python.exe' run.py --sam --samples 3 --interval 1
# 기존 RGB 사진 재검사
& 'C:/PAC2026_system/.venv-rgb/Scripts/python.exe' run.py --image 'C:/Users/tilti/PAC2026_data/tape-on/TON3_B_20261009_113356_917801/vis.png' --sam
```

기본 출력은 `C:/Users/tilti/PAC2026_data/rgb_box`의 원본 RGB 패널·표시 PNG·개별 mask PNG·JSON이다. `--output`으로 바꿀 수 있다. 데이터/영상/가중치는 Git에 넣지 않는다. JSON의 `found`, 후보 수, bbox/중심/마스크는 RGB 픽셀 관측이며 로봇 좌표가 아니다. 모델 점수·예측 IoU는 측정한 정확도와 다르다. `motion_enabled=false`, `robot_ready=false`, `depth_association=not_established`를 명시한다.

이 설치의 RGB 패널은 480×360이다. 합성 영상의 첫 480px만 읽으며 열화상·깊이는 입력에 포함하지 않는다. 다른 설치에서는 `--rgb-width`를 확인한다. 원본 RGB 카메라의 해상도를 추정하지 않으며, 프레임의 실제 촬영 시각이 없는 미리보기라 `capture_time_verified=false`다. 이후 원본 RGB/정확한 시각 API와 RGB–depth 관계를 확보해야 한다. 같은 픽셀 좌표를 다른 카메라의 깊이에 그대로 대입하지 않는다.

## 환경 재현

현재 `.venv-rgb`는 기존 `.venv-station`의 torch/torchvision/OpenCV 등을 읽기 전용 경로로 재사용하고 Transformers를 새 환경에 설치했다. station 환경은 설치/업그레이드하지 않았다.

```powershell
& 'C:/PAC2026_system/.venv-station/Scripts/python.exe' -m venv 'C:/PAC2026_system/.venv-rgb'
Set-Content -LiteralPath 'C:/PAC2026_system/.venv-rgb/Lib/site-packages/pac_station_dependencies.pth' -Value 'C:/PAC2026_system/.venv-station/Lib/site-packages' -Encoding ascii
& 'C:/PAC2026_system/.venv-rgb/Scripts/python.exe' -m pip install -r requirements.txt
& 'C:/PAC2026_system/.venv-station/Scripts/hf.exe' download IDEA-Research/grounding-dino-tiny model.safetensors config.json preprocessor_config.json tokenizer.json tokenizer_config.json special_tokens_map.json added_tokens.json vocab.txt --revision a2bb814dd30d776dcf7e30523b00659f4f141c71
& 'C:/PAC2026_system/.venv-station/Scripts/hf.exe' download Zigeng/SlimSAM-uniform-77 model.safetensors config.json preprocessor_config.json --revision 79c09c1ce6b4ae51f00634ed171d9b8e888f6911
```

## 실제 검증 2026-10-09

Intel Iris Xe를 탑재한 노트북의 CPU에서 실제 센서 RGB 패널로 실행했다. 18:13의 초기 threshold 0.28에서 갈색 상자는 세 장 모두 검출했지만 배경/영상 가장자리도 낮은 점수의 후보로 나온 경우가 있어 완료로 간주하지 않았다. 기본값은 공식 사용 예제와 같은 0.4로 조정했다. 현장 검증/별도 평가가 필요한 후보 기준이다.

최종 `--sam --samples 3`: 18:20:14 / 18:20:32 / 18:20:50 각각 한 상자 검출. 중심은 (331.50,239.62), (181.56,259.27), (181.23,259.70)px, 검출 점수 0.6353/0.6658/0.7032. 상자가 오른쪽에서 왼쪽으로 옮겨진 두 위치에서도 자동 검출/분리가 됐다. 표시 결과를 직접 보아 마스크가 상자 표면을 포함하는지 확인했다. DINO 11.4~12.5초, SAM 5.1~6.1초로 합계 약 16.5~18.6초/장이다. 실시간 추적/실기 제어에 적용된 결과로 주장하지 않는다.

실제 저장된 흰 상자 RGB 사진 `tape-on/TON3_B_20261009_113356_917801/vis.png`도 상자 한 개(점수 0.4678, bbox 약 [937,327,1159,628])로 검출했다. 이는 그 사진의 검출 결과이며 다양한 조명·가림·회전·여러 상자·빈 장면의 정확도 평가를 대신하지 않는다.

```powershell
& 'C:/PAC2026_system/.venv-rgb/Scripts/python.exe' -m pytest tests -q --disable-warnings --rootdir . --confcutdir . -o 'addopts='
```

최종 **16 passed (0.85s)**. 중복 후보 NMS, 별개 물체 유지, 잘못된/비유한 좌표 거부, RGB만 자르기, 연결 실패의 이전 사진 재사용 차단, 마스크 형식·빈 영역 거부와 CUDA 미지원 시 CPU로 몰래 전환하지 않는 처리를 확인했다. 실제 모델 검증은 카메라/저장 사진 및 아래 Colab 실행이며 단위 테스트와 구별한다.

## Colab GPU 실행 및 실제 결과

[Colab에서 새 GPU 노트북 열기](https://colab.research.google.com/github/tiltis/PAC/blob/main/tiltis/codex/rgb_box/colab/PAC_RGB_SAM_GPU.ipynb).
`colab/PAC_RGB_SAM_GPU.ipynb`는 이 폴더의 모듈을 그대로 포함하며 `python make_colab.py`로 갱신한다. 기존 Claude의 LeRobot 정책 학습 노트북은 그대로 보존했다. 이 노트북은 학습 없이 검출·분리를 검증한다.

T4 GPU 런타임 선택 → 위에서부터 실행 → RGB 사진 업로드 → bbox/마스크/JSON/시간 확인 → 결과 ZIP 다운로드. 파일 위젯이 안 되면 왼쪽 파일 패널에서 업로드하고 `IMAGE_FILES`를 지정한다. CUDA 모델 파라미터를 확인하고 시간 측정 전후 GPU를 동기화한다. GPU 워밍업 한 장을 시간에서 제외한다. 로컬 CLI에서도 `--device cuda`를 명시할 수 있으며 CUDA가 없으면 오류로 중단한다.

2026-10-09 18:41, **Tesla T4 / torch 2.11.0+cu130 / Transformers 5.13.0**에서 실제 4장을 실행했다. 갈색 상자 두 위치의 3장과 저장된 흰 상자 1장 모두 한 후보·유효 SAM 마스크를 반환했고 표시 결과를 확인했다.

| 사진 | DINO | SAM | 합계 |
|---|---:|---:|---:|
| 갈색 오른쪽 | 199.6ms | 187.0ms | 386.6ms |
| 갈색 왼쪽 1 | 217.2ms | 188.0ms | 405.2ms |
| 갈색 왼쪽 2 | 206.6ms | 187.3ms | 393.9ms |
| 흰 상자 | 210.7ms | 235.2ms | 445.9ms |

이는 **모델 추론 시간**이며 카메라 촬영·업로드/통신·로봇 제어 지연을 포함하지 않는다. 결과는 `C:/Users/tilti/PAC2026_data/rgb_box/colab_T4_20261009`와 실행한 비공개 Colab 노트북에 저장했다. Git에는 출력 없는 재실행용 코드만 넣는다. 다운로드 후 GPU 런타임을 종료했다. 이 최초 결과는 상자 전체 표면 마스크이며, 후속 윗면 연결은 아래와 같다.

## 윗면 → 3D 방향 → 집게 정렬

사용자 요구는 매번 상자가 옮겨지거나 회전해도 로봇이 관측한 위치·방향으로 잡는 것이다. `top_face.py`는 자동 positive/negative point 프롬프트로 SAM 면 후보를 만들고 사각형과 두 영상 변의 각도를 표시한다. **SAM은 윗면이라는 의미를 보장하지 않는다.** 테이프 일부와 앞면도 높은 모델 점수로 분리된다. `selected_top=null`, `top_confirmed=false`, `robot_yaw_deg=null`로 남기며 영상 각도를 로봇 yaw에 직접 넣지 않는다. 영상은 x 오른쪽, y 아래쪽이고 각도는 180° 대칭으로 표시한다.

```powershell
# RGB 면·영상 각도 미리보기, 모터 명령 없음
& 'C:/PAC2026_system/.venv-rgb/Scripts/python.exe' run.py --sam --faces --samples 1
```

2026-10-09 19:11 Colab T4에서 동일한 실제 4장에 공유 `top_face.py`를 실행했다. 사진별 중복 제거 후 면 후보 2/2/2/3개, 면 후보 추론 321.5/325.9/331.9/592.2ms. 이 시간은 추가 면 후보 단계만이며 DINO·상자 전체 SAM·통신 시간을 포함하지 않는다. 갈색 왼쪽/흰 상자의 윗면 후보가 보였지만 테이프·앞면 후보도 함께 나왔다. 윗면 자동 확정 성공률을 측정한 결과가 아니다. 실제 PNG·마스크·JSON·실행 노트북·화면 증거를 `C:/Users/tilti/PAC2026_data/rgb_box/sam_faces_T4_20261009`에 보관하고 T4를 해제했다.

`sam_depth.py`의 실제 선택 경로는 **상자 전체 SAM 마스크 → 검증된 RGB–depth 투영 → 깊이에서 책상 위 상자 윗면 → 3D 중심·긴/짧은 변 → 기존 hand-eye/IK**다. 기존 `sensor/locate.py`의 deprojection·RANSAC·최소 외접 사각형을 재사용한다. 새 `object_mask` 인자는 상자 후보만 제한하며 책상 평면 추정 영역은 유지한다. 윗면 평면의 RMS·법선·가시 범위와 실측 상자 크기도 검사한다. 테이프만 보이는 작은 마스크/얇은 윗면 띠로 상자 중심을 확정하지 않는다.

`SamDepthSensorAdapter`는 기존 센서 `inspect()`를 그대로 위임하고 `locate()`만 새 관측으로 제공한다. 이것을 기존 `GuardedVisionPicker`에 전달하면 기존 3프레임 안정성·촬영 시각·workspace·접근 후 재확인·수동 복구·IK 제한을 재사용한다. reader가 새 RGB/depth 묶음과 SAM 마스크를 제공해야 하며, 현재 `/live.jpg` 미리보기에는 필요한 정보가 없어 실기 입력으로 승인되지 않는다. 카메라/직렬 포트 접근 코드는 이 어댑터에 없다.

공유 `station/grasp.py`의 옆집기 버그도 수정했다. 이전에는 상자 각도와 관계없이 로봇→상자 중심 방향으로 집게 자세를 정했다. 이제 hand-eye 회전으로 3D 상자 두 축을 로봇 기준으로 바꾸고 가까운 면의 변에 수직으로 접근하며 다른 변 방향으로 집게를 정렬한다. 접근·집기·들기 IK 모두 같은 방향을 사용한다. 두 축이 평면 위에 없거나 서로 직교하지 않으면 거부한다. SO101은 5자유도여서 고정 위치에서 임의의 옆집기 자세가 풀리지 않을 수 있다. 이때 원래의 중심 방향으로 대체하지 않고 계획을 거부한다. 위에서 잡는 기존 계획도 짧은 변 방향으로 yaw를 계산하지만 도달 높이·개구 폭·손잡이/상자 크기 설정은 별도로 확인해야 한다.

## 깊이 어댑터 입력 계약

`locate_sam_top()`은 상자 전체 RGB `bool` 마스크, 깊이 `mm` 배열, 두 카메라 내부 파라미터, 등록 보정과 촬영 metadata를 받는다. 결과의 `frame=depth_camera_mm`, `bbox_px`는 **네이티브 깊이 픽셀**이며 기존 station 계약과 같다. `top_center_cam_mm`, `long_axis_cam`, `short_axis_cam`, `top_normal_cam`, `box_mm`를 반환한다. `found=true`도 기하 후보일 뿐이며 `motion_enabled=false`, `robot_ready=false`를 유지한다.

- registration: 실측 `source_id`, `validated=true`, `from_frame=depth_camera_mm`, `to_frame=rgb_camera_mm`, `units=mm`, 3×3 `R`, 3D `t_mm`, `rms_px`, 두 `*_camera_id`와 `*_intrinsics`. 내부 파라미터는 `fx,fy,cx,cy,width,height`를 포함한다.
- 두 영상은 보정에 쓰인 동일 카메라/해상도/내부 파라미터의 **rectified** 입력이어야 한다. `rgb_rectified`, `depth_rectified`를 증거 없이 true로 만들지 않는다. Arducam과 Gemini 2는 다른 카메라다. 같은 픽셀 대입·단순 resize·책상 호모그래피는 이 3D 정합을 대신하지 않는다. RGB 시점에서 가려진 깊이 점은 z-buffer로 제외한다.
- captures: `rgb`와 `depth` 각각 `camera_id`, 검증한 `captured_at_s`, `clock=host_unix_seconds`, `capture_time_verified=true`. 장치 ms를 host s로 그대로 대입하지 않는다. 기본 시각 게이트는 age≤2s, skew≤100ms이고 추론 뒤에도 age를 다시 확인한다.
- 실측 `table_roi`는 깊이 픽셀 `[x0,y0,x1,y1]`, `box_models_mm`는 실측 `[긴 변,짧은 변,높이]` 목록이다. 모델을 고유하게 판별하지 못하면 거부한다. 재투영 RMS≤2px, 윗면 RMS≤4mm/책상과 법선차≤10°/평면 인라이어≥85%, 치수 오차≤10mm는 소프트웨어 게이트이며 실제 설치에서 검증해야 한다.

카메라 정합과 camera→robot hand-eye는 설치 시 확인하며 상자 위치가 바뀔 때마다 다시 티칭하지 않는다. 카메라를 옮겼거나 렌즈/해상도를 바꿨으면 해당 보정을 다시 확인한다. 실제 TCP/FK/관절 단위, 그리퍼 최대 개구와 잡는 높이, 경로 충돌, 실제 속도·가속도/통신 stop은 별도 실기 검증 사항이다.

오프라인 파일 묶음 검증도 제공한다. NPZ는 `sam_mask`, `depth_mm`; metadata JSON은 `depth_intrinsics`, `rgb_intrinsics`, `captures`, `box_count`, `table_roi`, `box_models_mm`를 포함한다. 실행 실패는 종료 코드 2이며 원래 촬영 시각을 현재 시각으로 바꾸지 않는다.

```powershell
& 'C:/PAC2026_system/.venv-rgb/Scripts/python.exe' estimate_top.py --bundle bundle.npz --metadata metadata.json --registration verified_registration.json --now-s <같은_시계의_평가시각> --output top_result
```

## 윗면 연결 검증 결과

최종 RGB/면/깊이 어댑터 **43 pass**. 가상 rectified RGB/depth에서 상자 위치·회전 0/30/−40/80°를 바꾸어 3D 중심/축/치수 확인, 다른 깊이 물체 배제와 책상 평면 보존, 투영 이동·가림 제거, 부분 테이프/불완전 윗면/미보정/단위/카메라 변경/시각 오류/과도한 잔차/여러 상자 거부를 확인했다. 세 묶음의 가상 관측 → 실제 공유 guard → 공유 IK/FK까지 연결한 테스트도 통과했다. 가상 bundle의 CLI 결과는 `C:/Users/tilti/PAC2026_data/rgb_box/synthetic_top_bundle`에 보관했으며 **실측 보정 파일로 쓰면 안 된다**.

공유 sensor 전체 **121 pass**, station 전체 **115 pass**, Codex vision guard **58 pass**. 마지막 planner 축 검사를 추가한 뒤 station `tests/test_vision_pick.py`도 재검증했다. 실제 카메라 정합·윗면 3D 측정·로봇 집기 결과와 구별한다. 노트북 JSON/출력 없는 셀/AST, CLI 저장 결과, `git diff --check`도 확인했다. C:/PAC2026_system 실행 코드·현재 8000 화면은 이번 변경으로 교체하거나 재시작하지 않았다.

## 다음 단계

1. RGB 검출/마스크를 위치 변경·회전·흰/갈색·빈 장면에서 더 확인한다. 네이티브 RGB 및 촬영 시각을 연결하고 필요하면 빠른 모델/추적을 평가한다.
2. 현장 카메라의 rectified RGB/depth·동기화 묶음 API와 실측 RGB–depth 정합을 확보해 `SamDepthSensorAdapter`를 연결하고, 실제 화면에서 윗면 3D 중심/두 축을 확인한다. 현재 새 코드가 실행 중인 8000 화면에 자동 적용된 상태는 아니다.
3. FK/실측 도구점과 카메라–로봇 좌표 보정·실측 workspace를 확인하고 시뮬레이션에서 도달성/경로/충돌을 검증한다. 실제 조건은 별도 확인한다.
4. 현장 확인과 사용자 승인 후 실제 저속 집기를 검증한다. 현재 모듈에는 모터 호출이 없으며 상자 위치로 로봇을 움직이지 않는다.

## 2026-10-09 Gemini 네이티브 RGB-D와 저장 사진 SAM 검증

`sensor/server.py --depth --depth-rgb`는 Gemini의 깊이와 자체 컬러를 **같은 pipeline**에서 받는다. Arducam RGB와 같은 픽셀이라고 가정하지 않는다. SDK factory intrinsics/extrinsics와 OpenCV rectification을 사용하고 native depth/mm 및 기존 hand-eye 기준을 유지한다. 등록은 factory 출처이고 `validated=false`; 현장 재투영 검증 완료를 뜻하지 않는다.

- `/vision/rgbd.npz`: 증가하는 device clocks, SDK global exposure timestamps, age≤2s/skew≤100ms를 검증한 쌍만 반환. 미검증은 503이다.
- `/vision/preview_rgbd.npz`: host arrival 기준의 관찰 전용 쌍. 촬영 시각 검증을 대신하지 않는다.
- Windows에서는 UVC metadata 등록이 필요하다. SDK의 `shared/obsensor_metadata_win10.md`를 따른다. 현장에서는 공식 스크립트의 없는 속성 조회가 예외를 내, 연결된 Gemini 2의 3개 인터페이스/2개 DeviceClasses에 동일한 `MetadataBufferSizeInKB0=5`를 설정하고 6곳 모두 검증했다. 기존값 백업과 실행 기록은 C:/PAC2026_system/Log/codex_metadata_*에 있다. Windows PowerShell은 기본 Restricted였고 등록 프로세스만 RemoteSigned로 실행했다. 지속 실행 정책은 바꾸지 않았다.

`preview_geometry.py`는 기존 depth top locator의 네이티브 윗면을 Gemini 컬러에 투영한다. `guided_top.py`는 표면 안 9개 positive와 밖 4개 negative를 함께 사용한다. 단일 갈색 positive만 쓰면 테이프가 SAM 마스크에서 빠지는 실제 사진을 재현했다. 깊이 prompt를 SAM 결과로 대체하지 않고, SAM mask IoU≥0.7 및 SAM 자체 4각 hull로 경계를 검증한다.

`colab_native_top.py`는 업로드한 Gemini 사진/투영 prompt에 T4 추론을 실행하는 **오프라인** 검증이다. 2026-10-09 사진에서 IoU 0.8048, 경계 RMS 5.922px, 전체 DINO/SAM 단계 926.11ms를 측정했다. 경계 RMS는 이 사진의 SAM/depth 차이이며 보정 RMS가 아니다. DINO는 실제 갈색 상자 외 책상 전체를 흰 상자로 오검출한 결과도 그대로 보존한다. 실시간 입력·로봇 각도 정렬 완료로 보고하지 않는다.

`top_tape.py`는 정규화한 윗면의 서로 다른 변에 이어진 초록 테이프 접점을 센다. 연결된 H 모양을 한 덩어리로 세는 오류를 피하지만, 가림/너무 넓은 패치/윗면 미확정은 unmeasurable이다. 원본 SAM mask와 SAM convex quadrilateral 영역을 구별해 저장한다. 실제 사진에서는 접점 하나와 폭 과다 후보가 나와 추가 검증이 필요하며, 3개라고 강제하거나 기존 검사 규칙에 자동 적용하지 않았다.

저장 결과 표시: `vision_pick/preview_server.py --site-dir C:/PAC2026_system --port 8002 --sam-result-dir C:/Users/tilti/PAC2026_data/integration_20261009/colab_native_sam`. 3카메라 live와 저장 SAM 사진을 구별한다.
