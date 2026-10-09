# 센서 서버 실행(포트 8001). 실행: run_sensor.bat  /  카메라 없이: run_sensor.bat -Fake
# 주의: 이 서버가 카메라를 독점한다. Windows 카메라 앱과 capture_app.py는 닫을 것
param([switch]$Fake, [string]$BlurFaces = "", [int]$Port = 8001,
      [switch]$Depth, [switch]$RequireDepth)
$ErrorActionPreference = 'Stop'
if ($Fake -and $Depth) { throw '-Fake에서 실제 -Depth를 함께 열지 않음' }
if ($RequireDepth -and -not $Depth) { throw '-RequireDepth는 -Depth와 함께 사용' }
$vpy = Join-Path $PSScriptRoot '.venv-sensor\Scripts\python.exe'
if (-not (Test-Path $vpy)) { throw '먼저 setup_sensor.bat 실행' }
$serverArgs = @((Join-Path $PSScriptRoot 'sensor\server.py'), '--port', $Port)
if ($Fake) { $serverArgs += '--fake-rig' }
if ($BlurFaces) { $serverArgs += @('--blur-faces', $BlurFaces) }
if ($Depth) { $serverArgs += '--depth' }
if ($RequireDepth) { $serverArgs += '--require-depth' }
Write-Host "센서 서버: http://<이 PC IP>:$Port  (Ctrl+C로 종료)" -ForegroundColor Green
& $vpy @serverArgs
