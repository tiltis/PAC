"""배포용 zip 만들기. 가상환경·캐시·촬영 결과·DB는 넣지 않는다.

    python make_package.py            # → ../PAC2026_system_<날짜>.zip
"""
import datetime as dt
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKIP_DIRS = {".venv-sensor", ".venv-station", "__pycache__", ".pytest_cache", "check_out", "Log"}  # Log: Orbbec SDK 로그
SKIP_SUFFIX = {".db", ".pyc"}
SKIP_NAMES = {"debug_faceA.png", "debug_faceB.png"}
EXEC = {".sh"}


def files():
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if p.is_dir() or any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.suffix in SKIP_SUFFIX or p.name in SKIP_NAMES:
            continue
        yield p, rel


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / f"PAC2026_system_{dt.date.today():%Y%m%d}.zip"
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p, rel in files():
            info = zipfile.ZipInfo.from_file(p, f"PAC2026_system/{rel.as_posix()}")
            if p.suffix in EXEC:
                info.create_system = 3  # Unix로 표시해야 macOS가 아래 권한을 읽는다
                info.external_attr = (0o100755 << 16)  # Mac에서 풀어도 실행 권한 유지
            with open(p, "rb") as f:
                z.writestr(info, f.read(), zipfile.ZIP_DEFLATED)
            n += 1
    print(f"{out}  ({n}개 파일, {out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
