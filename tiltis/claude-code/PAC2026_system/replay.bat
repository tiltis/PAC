@echo off
title PAC2026 replay
"%~dp0.venv-station\Scripts\python.exe" "%~dp0station\teach.py" --port COM8 --replay --box %1
echo.
echo (done) press any key to close
pause >nul
