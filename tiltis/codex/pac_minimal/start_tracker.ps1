$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pacPython = Join-Path $env:USERPROFILE '.venvs/pac2026-vision310/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pacPython)) { throw 'ASCII 경로의 별도 Python 3.10 환경을 먼저 생성하고 requirements.txt를 설치하세요.' }
Write-Host '브라우저: http://127.0.0.1:5001 / 로봇 연결 없이 손목 입력만 실행'
& $pacPython hack_qut.py
