#!/usr/bin/env bash
# 스테이션 PC(Mac/Linux) 설치: 가상환경 → 패키지 → 테스트.  실행: bash setup_station.sh [--advisor]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
ADVISOR=0
[[ "${1:-}" == "--advisor" ]] && ADVISOR=1

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
    PY="$c"; break
  fi
done
if [[ -z "$PY" ]]; then
  echo "Python 3.10 이상이 없음. Mac: brew install python@3.12 또는 https://www.python.org/downloads/ 설치 후 다시 실행" >&2
  exit 1
fi
echo "==> Python $("$PY" -c 'import platform; print(platform.python_version())') ($PY)"

VENV="$ROOT/.venv-station"
[[ -x "$VENV/bin/python" ]] || "$PY" -m venv "$VENV"
VPY="$VENV/bin/python"
"$VPY" -m pip install --disable-pip-version-check -q --upgrade pip

LOCK="$ROOT/station/requirements.lock.txt"
if [[ -f "$LOCK" ]] && "$VPY" -m pip install --disable-pip-version-check -r "$LOCK"; then
  echo "==> 고정 버전 설치 완료"
else
  echo "==> 범위 버전으로 설치"
  "$VPY" -m pip install --disable-pip-version-check -r "$ROOT/station/requirements.txt"
fi
if [[ $ADVISOR == 1 ]]; then
  echo "==> laya 조언자(선택, 약 2GB)"
  "$VPY" -m pip install --disable-pip-version-check -r "$ROOT/station/requirements-advisor.txt"
fi

echo "==> 테스트 (로봇·카메라 불필요)"
"$VPY" -m pytest "$ROOT/station/tests" -q -p no:cacheprovider
echo
echo "설치 완료. 혼자 시험: bash run_station.sh --mock-sensor  /  실제 센서: SENSOR_URL=http://<센서PC IP>:8001 bash run_station.sh"
