@echo off
title PAC2026 replay white
"%~dp0.venv-station\Scripts\python.exe" "%~dp0station\teach.py" --port COM8 --replay --box white
echo.
echo (done) press any key to close
pause >nul
