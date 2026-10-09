#!/usr/bin/env bash
# 스테이션 실행(포트 8000).
#   bash run_station.sh --mock-sensor                     # 가짜 센서와 함께 혼자 시험
#   SENSOR_URL=http://192.168.0.10:8001 bash run_station.sh  # 실제 센서 PC 연결
#   ROBOT=so101 ROBOT_PORT=/dev/tty.usbmodemXXXX SENSOR_URL=... bash run_station.sh  # 현장 실기
# 선택: ADVISOR_URL=http://127.0.0.1:8766 (laya 기록 전용 조언자)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
VPY="$ROOT/.venv-station/bin/python"
[[ -x "$VPY" ]] || { echo "먼저 bash setup_station.sh 실행" >&2; exit 1; }
export SENSOR_URL="${SENSOR_URL:-http://127.0.0.1:8001}" ROBOT="${ROBOT:-mock}"
MOCK_PID=""
if [[ "${1:-}" == "--mock-sensor" ]]; then
  export SENSOR_URL="http://127.0.0.1:8001" MOCK_SCENARIO="${MOCK_SCENARIO:-all_ok}"
  "$VPY" -m uvicorn mock_sensor:app --app-dir "$ROOT/station" --port 8001 &
  MOCK_PID=$!
  trap '[[ -n "$MOCK_PID" ]] && kill "$MOCK_PID" 2>/dev/null' EXIT
  sleep 2
fi
echo "스테이션: http://$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}'):8000  (휴대폰은 같은 Wi-Fi, Ctrl+C로 종료)"
"$VPY" -m uvicorn app:app --app-dir "$ROOT/station" --host 0.0.0.0 --port 8000
