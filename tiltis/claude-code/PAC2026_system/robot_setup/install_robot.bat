@echo off
rem SO-101 준비: CH343 드라이버 설치 + 보정 파일 복사. 관리자 권한으로 실행.
chcp 65001 >nul
setlocal
set HERE=%~dp0

net session >nul 2>&1
if errorlevel 1 (
  echo [오류] 관리자 권한으로 실행하세요. 파일을 우클릭 - 관리자 권한으로 실행
  pause
  exit /b 1
)

echo [1/2] CH343 드라이버 설치
pnputil /add-driver "%HERE%driver_ch343\ch343ser.inf" /install
if errorlevel 1 echo [경고] 드라이버 설치 실패. 이미 설치되어 있으면 무시해도 된다.

echo [2/2] 보정 파일 복사
set CAL=%USERPROFILE%\.cache\huggingface\lerobot\calibration\robots\so_follower
if not exist "%CAL%" mkdir "%CAL%"
if exist "%CAL%\so101_follower.json" (
  copy /Y "%CAL%\so101_follower.json" "%CAL%\so101_follower.json.bak" >nul
  echo 기존 보정 파일을 so101_follower.json.bak 으로 백업했다.
)
copy /Y "%HERE%so101_follower.json" "%CAL%\so101_follower.json" >nul
echo 보정 파일: %CAL%\so101_follower.json

echo.
echo 완료. 장치 관리자 - 포트에서 CH343 COM 번호를 확인하세요.
pause
