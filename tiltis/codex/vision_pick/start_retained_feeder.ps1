# Run manually when the automatic tool cannot restart arm 2.
# Startup reads the retained motor state; it never starts feed/HOME/gripper motion.
param([int]$ExpectedOldPid = 25712)
$ErrorActionPreference = 'Stop'
$pacStationDir = 'C:/PAC2026_system/station'
$pacPython = 'C:/PAC2026_system/.venv-station/Scripts/python.exe'
$pacEntry = Join-Path $PSScriptRoot 'retained_feeder.py'
if (-not (Test-Path -LiteralPath $pacEntry) -or -not (Test-Path -LiteralPath $pacPython)) {
    throw 'Required retained feeder entry or Python runtime is missing.'
}

# Verify the known arm's USB adapter without opening its motor port.
$pacUsbSerial = & $pacPython -c "from serial.tools import list_ports; print(next((p.serial_number or '' for p in list_ports.comports() if p.device == 'COM10'), ''))"
if ($LASTEXITCODE -ne 0 -or $pacUsbSerial.Trim() -ne '5AE6080853') {
    throw 'COM10 is not the identified arm 2 adapter; no server stopped.'
}
$pacInspect = Invoke-RestMethod 'http://127.0.0.1:8000/api/status' -TimeoutSec 5
$pacAuto = Invoke-RestMethod 'http://127.0.0.1:8000/api/hub/auto' -TimeoutSec 5
if ($pacInspect.busy -or $pacAuto.state -eq 'running') {
    throw 'Inspection or automatic cycle is running; reconnect cancelled.'
}
$pacOwners = @(Get-NetTCPConnection -LocalPort 8004 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
if ($pacOwners.Count -gt 0) {
    $pacStatus = Invoke-RestMethod 'http://127.0.0.1:8004/api/status' -TimeoutSec 5
    if ($pacStatus.busy) { throw 'Arm 2 is busy; reconnect cancelled.' }
    if ($pacOwners.Count -ne 1 -or $pacOwners[0] -ne $ExpectedOldPid) {
        throw 'Arm 2 server changed; verify its PID before restarting.'
    }
    $pacOld = Get-CimInstance Win32_Process -Filter "ProcessId=$ExpectedOldPid"
    if ($pacOld.CommandLine -notmatch 'feeder_server:create_feeder_app' -or $pacOld.CommandLine -notmatch '--port 8004') {
        throw 'Expected arm 2 feeder process identity does not match.'
    }
}
$pacCalib = 'C:/PAC_knu/red_arm/outputs/assistant-arm/calibration'
if (-not (Test-Path -LiteralPath "$pacCalib/so101_purple2.json") -or -not (Test-Path -LiteralPath "$pacStationDir/poses_red.json")) {
    throw 'Existing arm 2 calibration/poses are missing; no server stopped.'
}
$pacProof = 'C:/Users/tilti/PAC2026_data/arm2_reconnect_20261010'
New-Item -ItemType Directory -Path $pacProof -Force | Out-Null
if ($pacOwners.Count -gt 0) {
    $pacStatus | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$pacProof/before.json" -Encoding utf8
    Stop-Process -Id $ExpectedOldPid
    Start-Sleep -Milliseconds 300
}
if (Get-NetTCPConnection -LocalPort 8004 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8004 is still occupied; no new server started.'
}
$env:RED_ROBOT_PORT = 'COM10'
$env:RED_ROBOT_ID = 'so101_purple2'
$env:RED_CALIB_DIR = $pacCalib
$env:RED_POSES = "$pacStationDir/poses_red.json"
$env:FEED_LEVELS = '3'
$env:FEED_STEP_MM = '45'
$env:FEED_PLACE_OUT_MM = '10'
$env:SENSOR_URL = 'http://127.0.0.1:8001'
$env:PURPLE_STATION_URL = 'http://127.0.0.1:8000'
$env:PAC_STATION_DIR = $pacStationDir
$pacStarted = Start-Process -FilePath $pacPython -ArgumentList 'retained_feeder.py' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$pacProof/server.stdout.log" -RedirectStandardError "$pacProof/server.stderr.log"
Write-Host "Arm 2 retained feeder started: PID $($pacStarted.Id)"
$pacConnection = $null
for ($pacAttempt = 0; $pacAttempt -lt 30; $pacAttempt++) {
    Start-Sleep -Seconds 1
    try {
        $pacConnection = Invoke-RestMethod 'http://127.0.0.1:8004/api/robot/connection' -TimeoutSec 2
        break
    } catch { }
}
if (-not $pacConnection -or -not $pacConnection.connected) {
    Get-Content -LiteralPath "$pacProof/server.stderr.log" -Tail 25
    throw 'Arm 2 did not reconnect. Retained attachment does not enable disabled torque or overwrite calibration.'
}
$pacConnection | ConvertTo-Json -Depth 4 | Tee-Object -FilePath "$pacProof/connection.json"
Write-Host 'Connected. No feed, HOME or gripper action was requested.'
