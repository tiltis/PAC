# 센서 PC(Windows) 설치: 가상환경 → 패키지 → 테스트. 실행: setup_sensor.bat
param([string]$Python = "", [switch]$NoLock, [switch]$SkipTests, [switch]$Depth)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
. (Join-Path $root 'tools\common.ps1')

$py = Find-Python $Python
$venv = Join-Path $root '.venv-sensor'
$vpy = New-Venv $py $venv
Install-Requirements $vpy (Join-Path $root 'sensor') -NoLock:$NoLock
Write-Step 'flirpy (--no-deps)'
& $vpy -m pip install --disable-pip-version-check --no-deps 'flirpy==0.6.2'
if ($LASTEXITCODE -ne 0) { throw 'flirpy 설치 실패' }

if ($Depth) {
    Write-Step 'Orbbec 깊이 SDK (선택)'
    & $vpy -m pip install --disable-pip-version-check -r (Join-Path $root 'sensor\requirements-depth.txt')
    if ($LASTEXITCODE -ne 0) { throw '깊이 SDK 설치 실패' }
}
if (-not $SkipTests) {
    Write-Step '테스트 (카메라 불필요)'
    & $vpy -m pytest (Join-Path $root 'sensor\tests') -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw '테스트 실패' }
}
Write-Host ''
Write-Host '설치 완료. 다음: 카메라를 꽂고 check_cameras.bat 실행' -ForegroundColor Green
