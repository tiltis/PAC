"""테이프·냉매 규칙과 현장 설정 도구를 가상 촬영으로 시험한다."""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rules  # noqa: E402
import rules_calib  # noqa: E402

GREEN_BGR = (60, 180, 40)  # 도구 기본값인 초록 테이프
TAPES = [[100, 100, 200, 160], [350, 100, 450, 160], [600, 100, 700, 160]]
BOX, REF = [100, 80, 200, 160], [250, 80, 290, 120]


def capture(tapes=(True, True, True), coolant=True, rng=None, face="A", tape_bgr=(15, 15, 15)):
    rng = rng or np.random.default_rng(0)
    vis = np.full((600, 800, 3), 235, np.uint8)  # 흰 상자
    vis[300:400, 200:600] = 70  # 인쇄된 어두운 무늬(영역 밖)
    for on, (x0, y0, x1, y1) in zip(tapes, TAPES):
        if on:
            vis[y0 + 5:y1 - 5, x0 + 5:x1 - 5] = tape_bgr  # 테이프(기본 검정)
    lw = 22000 + rng.normal(0, 2, (256, 320))
    if coolant:
        lw[BOX[1]:BOX[3], BOX[0]:BOX[2]] -= 120  # 냉매 쪽 표면이 차가움
    lw += rng.normal(0, 30)  # FFC·예열로 생기는 화면 전체 이동
    return vis, lw.astype(np.float32), face


def cfg(validated=True, fill_min=0.4, delta_max=-60.0, margin=15.0):
    return {"version": "tape-coolant-test", "validated": validated, "tape_color": rules.BLACK,
            "tapes": [{"id": f"T{k}", "face": "A", "roi_rgb": r, "fill_min": fill_min} for k, r in enumerate(TAPES, 1)],
            "coolant": {"face": "A", "roi_lwir": BOX, "ref_roi_lwir": REF, "delta_max_counts": delta_max, "margin_counts": margin},
            "faces_without_checks_ok": ["B"]}


def test_all_good_is_no_anomaly():
    vis, lw, _ = capture()
    v, r, f = rules.judge_face("A", vis, lw, cfg())
    assert v == "no_anomaly" and r == [] and f["defect_inspected"] is True
    assert all(f[f"tape_T{k}_present"] for k in (1, 2, 3)) and f["coolant_present"] is True


def test_missing_tape_and_no_coolant_are_suspect():
    vis, lw, _ = capture(tapes=(True, False, True), coolant=False)
    v, r, f = rules.judge_face("A", vis, lw, cfg())
    assert v == "suspect" and "tape_missing_T2" in r and "coolant_absent" in r


def test_near_threshold_is_review():
    vis, lw, _ = capture()
    d = rules.measure("A", vis, lw, cfg())["coolant_delta_counts"]
    v, r, _ = rules.judge_face("A", vis, lw, cfg(delta_max=d + 5, margin=15))
    assert v == "review" and "coolant_uncertain" in r


def test_unvalidated_rules_only_record():
    vis, lw, _ = capture(tapes=(False, False, False))
    v, r, f = rules.judge_face("A", vis, lw, cfg(validated=False))
    assert v == "review" and r == ["defect_rules_unvalidated"] and f["defect_inspected"] is False
    assert "tape_T1_fill" in f


def test_face_without_checks():
    vis, lw, _ = capture(face="B")
    assert rules.judge_face("B", vis, lw, cfg())[0] == "no_anomaly"
    c = cfg()
    c["faces_without_checks_ok"] = []
    assert rules.judge_face("B", vis, lw, c) is None


def write_capture(d, vis, lw, face):
    d.mkdir(parents=True)
    cv2.imwrite(str(d / "vis.png"), vis)
    np.savez_compressed(d / "lwir_y16.npz", stack=np.stack([lw, lw]).astype(np.uint16))
    (d / "meta.json").write_text(json.dumps({"face": face}), encoding="utf-8")


@pytest.fixture
def calib_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(rules, "CALIB_DIR", tmp_path / "calib")
    monkeypatch.setattr(rules, "PATH", tmp_path / "calib" / "rules.json")
    return tmp_path


def make_set(root, name, n, **kw):
    out = []
    for i in range(n):
        d = root / f"{name}_{i}"
        vis, lw, face = capture(rng=np.random.default_rng(i + 10), tape_bgr=GREEN_BGR, **kw)
        write_capture(d, vis, lw, face)
        out.append(str(d))
    return out


def test_calibration_tool_fits_and_validates(calib_dir):
    root = calib_dir / "caps"
    on = make_set(root, "good", 4)
    rules_calib.cmd_roi_tape(argparse.Namespace(capture=on[0], face="A", rois=";".join(",".join(map(str, r)) for r in TAPES)))
    rules_calib.cmd_roi_coolant(argparse.Namespace(capture=on[0], face="A", rois=f"{','.join(map(str, BOX))};{','.join(map(str, REF))}"))
    tape_off = make_set(root, "notape", 3, tapes=(False, False, False))
    cool_off = make_set(root, "nocool", 3, coolant=False)
    rules_calib.cmd_fit(argparse.Namespace(tape_on=on, tape_off=tape_off, coolant_on=on, coolant_off=cool_off, source_id="t"))
    c = rules.load()
    assert c["validated"] is True and all(t["fill_min"] is not None for t in c["tapes"])
    assert c["coolant"]["delta_max_counts"] < 0
    vis, lw, _ = capture(tapes=(True, True, False), rng=np.random.default_rng(99), tape_bgr=GREEN_BGR)
    assert rules.judge_face("A", vis, lw, c)[0] == "suspect"


def test_calibration_tool_refuses_overlap(calib_dir):
    root = calib_dir / "caps"
    on = make_set(root, "good", 3)
    rules_calib.cmd_roi_coolant(argparse.Namespace(capture=on[0], face="A", rois=f"{','.join(map(str, BOX))};{','.join(map(str, REF))}"))
    rules_calib.cmd_fit(argparse.Namespace(tape_on=[], tape_off=[], coolant_on=on, coolant_off=make_set(root, "same", 3), source_id="t"))
    assert rules.load()["validated"] is False


def test_server_uses_validated_rules(calib_dir, monkeypatch):
    from fastapi.testclient import TestClient
    import server
    from fake_rig import FakeRig
    from rig import RigConfig
    rules.CALIB_DIR.mkdir(parents=True)
    rules.PATH.write_text(json.dumps(cfg()), encoding="utf-8")
    app = server.create_app(lambda: FakeRig(RigConfig(vis_width=800, vis_height=600, data_root=calib_dir / "data")))
    with TestClient(app) as c:
        r = c.post("/inspect", json={"specimen_id": "S01", "face": "A"}).json()
    assert r["status"] == "ok" and r["verdict"] == "suspect" and "tape_missing_T1" in r["reasons"]  # 가짜 영상엔 테이프가 없다
    assert r["features"]["defect_inspected"] is True and r["sensor_data"]["assessment"]["defect_inspected"] is True
    assert r["features"]["rules_version"] == "tape-coolant-test"


def test_full_chain_can_reach_ok_bin_only_with_all_preconditions(calib_dir, monkeypatch):
    """검증된 규칙 + 시각 차 허용값 + '시료 하나 고정' 전제가 모두 있어야 정상 구역. 하나라도 빠지면 사람 확인."""
    import importlib.util
    from fastapi.testclient import TestClient
    import server
    from fake_rig import FakeRig
    from rig import RigConfig
    rules.CALIB_DIR.mkdir(parents=True)
    c = cfg()
    c.update(tapes=[], coolant=None, faces_without_checks_ok=["A", "B"])  # 검사 항목 없이 통과하는 면(사슬 시험용)
    rules.PATH.write_text(json.dumps(c), encoding="utf-8")
    monkeypatch.setattr(server, "CALIB_DIR", rules.CALIB_DIR)
    (rules.CALIB_DIR / "timing_policy.json").write_text(json.dumps(
        {"validated": True, "source_id": "test", "max_rgb_lwir_skew_s": 1.0}), encoding="utf-8")
    station = Path(__file__).resolve().parents[2] / "station"

    def load(name):
        spec = importlib.util.spec_from_file_location(f"chain_{name}", station / f"{name}.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def run(single, real_robot=False):
        monkeypatch.setenv("SINGLE_SPECIMEN", "1" if single else "0")
        app = server.create_app(lambda: FakeRig(RigConfig(vis_width=800, vis_height=600, data_root=calib_dir / "data")))
        robot = load("robot").MockRobot(speed=0)
        robot.is_mock = not real_robot  # 실제 로봇 모드에서는 가짜 카메라 결과를 정상으로 쓰지 않는다
        with TestClient(app) as http:
            sensor = load("sensor_client").SensorClient("http://testserver")
            sensor._http.close()
            sensor._http = http
            return load("sequencer").Sequencer(robot, sensor).run("CHAIN", "t")

    ok = run(single=True)
    assert ok["state"] == "done" and ok["final_verdict"] == "no_anomaly" and ok["bin"] == "ok", ok["inspections"][0].get("reasons")
    held = run(single=False)
    assert held["final_verdict"] == "review" and held["bin"] == "human"
    fake_on_real = run(single=True, real_robot=True)
    assert fake_on_real["bin"] == "human" and "simulated_inspection" in fake_on_real["inspections"][0]["reasons"]


def test_green_tape_is_found_even_on_dark_print():
    # 진회색 인쇄 위에 붙인 테이프: 검정 테이프는 인쇄와 구분이 안 되지만 초록 테이프는 구분된다
    vis = np.full((300, 300, 3), 235, np.uint8)
    vis[:, 150:] = (75, 75, 75)                    # 진회색 인쇄 무늬
    roi = [160, 100, 260, 160]
    assert rules.tape_fill(vis, roi, rules.BLACK) > 0.9   # 테이프가 없어도 '검정'으로 가득 참(오탐)
    assert rules.tape_fill(vis, roi, rules.GREEN) == 0.0
    vis[110:150, 170:250] = (60, 180, 40)          # 초록 테이프(BGR)
    assert rules.tape_fill(vis, roi, rules.GREEN) > 0.5


def test_auto_tape_rois_find_three_green_tapes(calib_dir):
    root = calib_dir / "caps"
    on = make_set(root, "green", 1)
    rules_calib.cmd_roi_tape(argparse.Namespace(capture=on[0], face="A", rois="", auto=True, count=3))
    c = rules.load()
    assert [t["id"] for t in c["tapes"]] == ["T1", "T2", "T3"]
    for t, (x0, y0, x1, y1) in zip(c["tapes"], TAPES):  # 각 영역이 실제 테이프를 감싼다(왼쪽→오른쪽 순서)
        r = t["roi_rgb"]
        assert r[0] <= x0 + 5 and r[2] >= x1 - 5 and r[1] <= y0 + 5 and r[3] >= y1 - 5
    missing = make_set(root, "two", 1, tapes=(True, False, True))
    with pytest.raises(SystemExit):
        rules_calib.cmd_roi_tape(argparse.Namespace(capture=missing[0], face="A", rois="", auto=True, count=3))
