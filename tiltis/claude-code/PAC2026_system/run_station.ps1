# 스테이션 실행(포트 8000). 실행: run_station.bat [-MockSensor] [-SensorUrl http://IP:8001] [-Robot so101 -RobotPort COM5]
param([string]$SensorUrl = 'http://127.0.0.1:8001', [string]$Robot = 'mock', [string]$RobotPort = '',
      [switch]$MockSensor, [string]$MockScenario = 'all_ok', [string]$AdvisorUrl = '', [int]$Port = 8000,
      [ValidateSet('taught', 'vision')][string]$PickMode = 'taught', [switch]$DryRun, [switch]$SingleSpecimen,
      [string]$Faces = 'A,B', [switch]$VisionPreview, [string]$Handeye = '')  # 3-face: -Faces A,B,C (needs face_C pose)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$vpy = Join-Path $root '.venv-station\Scripts\python.exe'
if (-not (Test-Path $vpy)) { throw '먼저 setup_station.bat 실행' }
$env:SENSOR_URL = $SensorUrl
$env:ROBOT = $Robot
if ($RobotPort) { $env:ROBOT_PORT = $RobotPort }
if ($AdvisorUrl) { $env:ADVISOR_URL = $AdvisorUrl }
$env:PICK_MODE = $PickMode
if ($Handeye) { $env:HANDEYE = $Handeye }
$env:FACES = $Faces
$env:PICK_DRY_RUN = if ($DryRun) { '1' } else { '0' }
$env:SINGLE_SPECIMEN = if ($SingleSpecimen) { '1' } else { '0' }  # 로봇이 시료 하나를 들고 고정(같은 시료 연결 전제)
$stationApp = 'app:app'
$stationAppDir = Join-Path $root 'station'
if ($PickMode -eq 'vision' -or $VisionPreview) {
    $guardDir = Join-Path (Split-Path (Split-Path $root -Parent) -Parent) 'codex\vision_pick'
    if (-not (Test-Path -LiteralPath (Join-Path $guardDir 'station_app.py'))) {
        throw 'Vision mode needs tiltis/codex/vision_pick next to tiltis/claude-code/PAC2026_system. Use the full team checkout.'
    }
    $env:PAC_SYSTEM_DIR = $root
    $stationApp = 'station_app:app'
    $stationAppDir = $guardDir
}
$mock = $null
if ($MockSensor) {
    $env:MOCK_SCENARIO = $MockScenario
    $env:SENSOR_URL = 'http://127.0.0.1:8001'
    $stationDir = Join-Path $root 'station'
    $mock = Start-Process $vpy -ArgumentList "-m uvicorn mock_sensor:app --app-dir `"$stationDir`" --port 8001" -PassThru -NoNewWindow
    Start-Sleep -Seconds 2
}
Write-Host "스테이션: http://<이 PC IP>:$Port  (휴대폰은 같은 Wi-Fi에서 접속, Ctrl+C로 종료)" -ForegroundColor Green
try {
    & $vpy -m uvicorn $stationApp --app-dir $stationAppDir --host 0.0.0.0 --port $Port
} finally {
    # venv의 python.exe는 실제 파이썬을 자식으로 띄우므로 프로세스 트리째 종료한다
    if ($mock) { try { & taskkill /T /F /PID $mock.Id | Out-Null } catch { } }
}
