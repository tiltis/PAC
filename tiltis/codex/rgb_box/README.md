# 1단계: 실제 RGB 화면의 상자 검출·SAM 마스크

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

이는 **모델 추론 시간**이며 카메라 촬영·업로드/통신·로봇 제어 지연을 포함하지 않는다. 결과는 `C:/Users/tilti/PAC2026_data/rgb_box/colab_T4_20261009`와 실행한 비공개 Colab 노트북에 저장했다. Git에는 출력 없는 재실행용 코드만 넣는다. 다운로드 후 GPU 런타임을 종료했다. 현재 SAM은 상자 전체 표면 마스크다. 윗면 분리·3D 방향·집게 정렬은 다음 연결부에서 별도로 검증해야 한다.

## 다음 단계

1. RGB 검출/마스크를 위치 변경·회전·흰/갈색·빈 장면에서 더 확인한다. 네이티브 RGB 및 촬영 시각을 연결하고 필요하면 빠른 모델/추적을 평가한다.
2. RGB에서 찾은 상자와 깊이의 동일 물체 대응을 검증해 카메라 좌표 3D 위치를 표시한다. 별도 카메라의 호모그래피는 일반 3D 정합을 대신하지 않는다.
3. FK/실측 도구점과 카메라–로봇 좌표 보정·실측 workspace를 확인하고 시뮬레이션에서 도달성/경로/충돌을 검증한다. 실제 조건은 별도 확인한다.
4. 현장 확인과 사용자 승인 후 실제 저속 집기를 검증한다. 현재 모듈에는 모터 호출이 없으며 상자 위치로 로봇을 움직이지 않는다.
