"""laya 기록 전용 조언자(섀도 모드). 판단을 기록만 하고 작업 순서는 절대 바꾸지 않는다.

laya(github.com/NandhaKishorM/laya)는 로컬에서 도는 소형 판단 모델이다(오프라인, 수십 ms).
2026-10-03 사전 시험: 추가 학습 없이 8개 가상 상황 중 5개만 맞혔다.
Jev 검증 결과는 FAIL(신뢰도 0.99), 정책은 STOP이었다.
그래서 결정권을 주지 않고, 규칙 판정 옆에 laya의 선택을 기록해 실제 검사 데이터로 비교만 한다.

환경변수 ADVISOR_URL(예: http://127.0.0.1:8766)이 없으면 꺼진다. laya 서버는 `python -m laya.serve`로 띄운다.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

ACTIONS = {
    "confirm": "the observation is clear and usable; keep the current verdict",
    "retake": "the image is blurred, occluded, has glare, or the pose is off; capture the same face again",
    "human": "the sensors disagree or an anomaly is suspected; send the package to a human",
}


def rule_action(entry: dict, retakes_left: int) -> str:
    """규칙이 실제로 한 행동. laya 선택과 나란히 기록해 비교한다."""
    v = entry.get("verdict")
    if v == "unmeasurable":
        return "retake" if retakes_left > 0 else "human"
    if v in ("suspect", "review"):
        return "human"
    return "confirm"


def summarize(entry: dict, retakes_left: int) -> str:
    f = entry.get("features", {})
    parts = [f"Face {entry.get('face')}, attempt {entry.get('attempt')}.",
             f"Rule verdict: {entry.get('verdict')}.",
             f"Reasons: {', '.join(entry.get('reasons') or []) or 'none'}."]
    for k in ("rgb_sharpness", "lwir_temporal_std", "lwir_roi_delta"):
        if k in f:
            parts.append(f"{k} = {f[k]}.")
    parts.append(f"Retakes left for this package: {retakes_left}.")
    return " ".join(parts)


class LayaAdvisor:
    def __init__(self, url: str, timeout_s: float = 1.0, model: str = "typed-decisions"):
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s
        self.model = model

    def advise(self, entry: dict, retakes_left: int) -> dict:
        """예외를 던지지 않는다. 실패하면 {"error": ...}만 남긴다."""
        allowed = {k: v for k, v in ACTIONS.items() if k != "retake" or retakes_left > 0}  # 예산이 없으면 재촬영 제외
        q = {"action": {"type": "choice",
                        "instructions": "One face of a cold-chain package was inspected by RGB and thermal cameras. "
                                        "Which allowed action should the station take next?",
                        "criteria": allowed}}
        out = {"source": "laya", "mode": "shadow", "allowed": list(allowed),
               "rule_action": rule_action(entry, retakes_left)}
        try:
            r = httpx.post(f"{self.url}/v1/systemone", timeout=self.timeout_s,
                           json={"state": summarize(entry, retakes_left), "questions": q, "model": self.model})
            r.raise_for_status()
            a = r.json()["answers"]["action"]
            out.update(choice=a.get("choice"), probabilities=a.get("probabilities"),
                       answer_confidence=a.get("answer_confidence"))
            out["agrees_with_rule"] = out["choice"] == out["rule_action"]
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"[:200]
        return out


def from_env() -> Optional[LayaAdvisor]:
    url = os.environ.get("ADVISOR_URL", "").strip()
    return LayaAdvisor(url) if url else None
