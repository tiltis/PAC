# 스테이션 PC 설치(Windows에서 시험할 때). Mac은 setup_station.sh. 실행: setup_station.bat
param([string]$Python = "", [switch]$NoLock, [switch]$SkipTests, [switch]$Advisor, [switch]$Robot)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
. (Join-Path $root 'tools\common.ps1')

$py = Find-Python $Python
$venv = Join-Path $root '.venv-station'
$vpy = New-Venv $py $venv
Install-Requirements $vpy (Join-Path $root 'station') -NoLock:$NoLock
if ($Robot) {
    Write-Step 'LeRobot (실제 SO-101용, 수 GB)'
    & $vpy -m pip install --disable-pip-version-check -r (Join-Path $root 'station' | Join-Path -ChildPath 'requirements-robot.txt')
    if ($LASTEXITCODE -ne 0) { throw 'LeRobot 설치 실패 (Python 3.12 이상 필요)' }
}
if ($Advisor) {
    Write-Step 'laya 조언자(선택, 약 2GB)'
    & $vpy -m pip install --disable-pip-version-check -r (Join-Path $root 'station\requirements-advisor.txt')
    if ($LASTEXITCODE -ne 0) { throw 'laya 설치 실패' }
}
if (-not $SkipTests) {
    Write-Step '테스트 (로봇·카메라 불필요)'
    & $vpy -m pytest (Join-Path $root 'station\tests') -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw '테스트 실패' }
}
Write-Host ''
Write-Host '설치 완료. 혼자 시험: run_station.bat -MockSensor  /  실제 센서 연결: run_station.bat -SensorUrl http://<센서PC IP>:8001' -ForegroundColor Green
