# 노트북 한 대에서 센서 서버(8001)와 스테이션(8000)을 각각 새 창으로 띄운다. 창을 닫거나 Ctrl+C로 끈다.
#   run_all.bat -Fake                                  카메라·로봇 없이 시험
#   run_all.bat -Depth                                 실제 카메라 3대, 가짜 로봇
#   run_all.bat -Depth -Robot so101 -RobotPort COM5    현장 실기(가르친 자세로 집기)
#   ... -PickMode vision -DryRun                       비전 집기: 손잡이 위 접근 위치까지만 시험
param([switch]$Fake, [switch]$Depth, [string]$Robot = 'mock', [string]$RobotPort = '',
      [ValidateSet('taught', 'vision')][string]$PickMode = 'taught', [switch]$DryRun, [switch]$SingleSpecimen)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$ps = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-NoExit', '-File')
$sensorArgs = @()
if ($Fake) { $sensorArgs += '-Fake' }
if ($Depth) { $sensorArgs += '-Depth' }
Start-Process powershell -ArgumentList ($ps + @("`"$root\run_sensor.ps1`"") + $sensorArgs)
Write-Host '센서 서버가 카메라를 여는 중...'
$ok = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep 1
    try { if ((Invoke-RestMethod http://127.0.0.1:8001/health -TimeoutSec 2).ok) { $ok = $true; break } } catch { }
}
if (-not $ok) { Write-Host '센서 서버가 준비되지 않음. 센서 창의 오류를 확인' -ForegroundColor Yellow }
$stationArgs = @('-Robot', $Robot, '-PickMode', $PickMode)
if ($RobotPort) { $stationArgs += @('-RobotPort', $RobotPort) }
if ($DryRun) { $stationArgs += '-DryRun' }
if ($SingleSpecimen) { $stationArgs += '-SingleSpecimen' }
Start-Process powershell -ArgumentList ($ps + @("`"$root\run_station.ps1`"") + $stationArgs)
# 기본 게이트웨이가 있는 실제 네트워크(Wi-Fi·유선)의 주소. WSL·Hyper-V 가상 어댑터는 제외
$ip = (Get-NetIPConfiguration -ErrorAction SilentlyContinue | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } |
       Select-Object -First 1).IPv4Address.IPAddress
if (-not $ip) { $ip = '<이 PC IP>' }
Write-Host "스테이션: http://$ip`:8000  (휴대폰은 같은 Wi-Fi에서 이 주소로 접속)" -ForegroundColor Green
