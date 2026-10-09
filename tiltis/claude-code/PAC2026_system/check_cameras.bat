@echo off
"%~dp0.venv-sensor\Scripts\python.exe" "%~dp0sensor\check_cameras.py" %*
pause
