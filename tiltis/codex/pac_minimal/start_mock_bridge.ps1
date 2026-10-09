$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pacPython = Join-Path $env:USERPROFILE '.venvs/pac2026-vision310/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pacPython)) { throw 'ASCII 경로의 별도 Python 3.10 환경을 먼저 생성하고 requirements.txt를 설치하세요.' }
& $pacPython robot_bridge.py
