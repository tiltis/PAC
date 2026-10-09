"""센서 서버(/health, /inspect) HTTP 클라이언트. 예외를 밖으로 던지지 않고 status="error" 결과로 바꾼다."""
from __future__ import annotations

import os
from typing import Optional, Tuple
import uuid

import httpx

VERDICTS = ("no_anomaly", "suspect", "unmeasurable", "review")


def error_result(msg: str, specimen_id: str = "", face: str = "", attempt: int = 0, session: str = "", trigger_id: str | None = None) -> dict:
    return {"status": "error", "error": msg, "session": session, "trigger_id": trigger_id, "specimen_id": specimen_id, "face": face,
            "attempt": attempt, "verdict": None, "reasons": [], "features": {},
            "capture_id": None, "images": {}, "elapsed_ms": 0}


class SensorClient:
    def __init__(self, base_url: str, timeout_s: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._http = httpx.Client(timeout=timeout_s)

    def close(self) -> None:
        self._http.close()

    def health(self) -> dict:
        try:
            r = self._http.get(self.base_url + "/health", timeout=3.0)
            if r.status_code != 200:
                return {"ok": False, "error": f"HTTP {r.status_code}"}
            data = r.json()
            return data if isinstance(data, dict) else {"ok": False, "error": "응답 형식 오류"}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def locate(self) -> dict:
        """깊이로 집기 영역의 상자(손잡이) 위치를 받는다. 실패해도 예외 대신 found=False."""
        try:
            r = self._http.get(self.base_url + "/object/locate", timeout=10.0)
            data = r.json()
            if r.status_code != 200 or not isinstance(data, dict):
                return {"found": False, "reason": f"센서 HTTP {r.status_code}: {str(data)[:120]}"}
            return data
        except Exception as e:
            return {"found": False, "reason": f"센서 연결 실패: {type(e).__name__}: {e}"}

    def inspect(self, session: str, specimen_id: str, face: str, attempt: int) -> dict:
        trigger_id = uuid.uuid4().hex
        body = {"session": session, "specimen_id": specimen_id, "face": face, "attempt": attempt,
                "trigger_id": trigger_id,
                # 로봇이 시료 하나를 들고 촬영이 끝날 때까지 움직이지 않는다는 운영 전제. 현장에서 확인한 뒤 SINGLE_SPECIMEN=1로 켠다
                "single_stationary_specimen": os.environ.get("SINGLE_SPECIMEN", "0") == "1"}
        err = lambda m: error_result(m, specimen_id, face, attempt, session, trigger_id)  # noqa: E731
        try:
            r = self._http.post(self.base_url + "/inspect", json=body, timeout=self.timeout_s)
        except httpx.TimeoutException:
            return err(f"센서 응답 시간 초과({self.timeout_s:.0f}초)")
        except httpx.HTTPError as e:
            return err(f"센서 연결 실패: {type(e).__name__}: {e}")
        if r.status_code != 200:
            return err(f"센서 HTTP {r.status_code}")
        try:
            data = r.json()
        except ValueError:
            return err("센서 응답이 JSON이 아님")
        if not isinstance(data, dict) or data.get("status") not in ("ok", "error"):
            return err("센서 응답 형식 오류(status 없음)")
        if data["status"] == "error":
            data.setdefault("error", "센서 오류")
            data["error"] = data["error"] or "센서 오류"
        elif data.get("verdict") not in VERDICTS:
            return err(f"알 수 없는 verdict: {data.get('verdict')!r}")
        if data["status"] == "ok":
            for key, expected in (("session", session), ("specimen_id", specimen_id), ("face", face),
                                  ("attempt", attempt), ("trigger_id", trigger_id)):
                if type(data.get(key)) is not type(expected) or data.get(key) != expected:
                    return err(f"센서 응답 불일치: {key}")
            if data.get("error"):
                return err(f"정상 응답에 오류가 포함됨: {data['error']}")
            if not isinstance(data.get("features", {}), dict) or not isinstance(data.get("images", {}), dict):
                return err("센서 응답 형식 오류(features/images)")
            for key in ("sensor_data", "artifacts"):
                if key in data and not isinstance(data[key], dict):
                    return err(f"센서 응답 형식 오류({key})")
            if data.get("features", {}).get("simulated") is not True and data.get("sensor_data", {}).get("schema_version") != "pac-sensors-1":
                return err("실장비 응답에 pac-sensors-1 association 스키마 필요")
            if data.get("sensor_data", {}).get("schema_version") == "pac-sensors-1":
                association = data["sensor_data"].get("association")
                if not isinstance(association, dict) or any(
                        type(association.get(key)) is not type(expected) or association.get(key) != expected
                        for key, expected in (
                        ("session", session), ("specimen_id", specimen_id), ("face", face),
                        ("attempt", attempt), ("trigger_id", trigger_id), ("capture_id", data.get("capture_id")))):
                    return err("센서 데이터의 촬영 연결 불일치")
            reasons = data.get("reasons", [])
            if not isinstance(reasons, list) or not all(isinstance(reason, str) for reason in reasons):
                return err("센서 응답 형식 오류(reasons)")
        data.setdefault("specimen_id", specimen_id)
        data.setdefault("face", face)
        data.setdefault("attempt", attempt)
        data["reasons"] = data.get("reasons") or []
        data["features"] = data.get("features") or {}
        data["images"] = data.get("images") or {}
        return data

    def fetch_image(self, path: str) -> Optional[Tuple[bytes, str]]:
        """센서 서버에서 이미지를 받아 (바이트, content-type). 실패하면 None."""
        try:
            r = self._http.get(self.base_url + path, timeout=10.0)
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        return r.content, r.headers.get("content-type", "application/octet-stream")
