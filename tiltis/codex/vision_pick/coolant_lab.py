"""Offline coolant calibration using peer rules; never changes station config.

Consumes saved Y16 stacks, not false-color JPEGs. The laboratory config remains
unvalidated even after fitting; independent evaluation precedes any deployment.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np


def read_stack(capture):
    path = Path(capture)
    meta = json.loads((path / "meta.json").read_text(encoding="utf-8-sig"))
    if meta.get("sensor_data", {}).get("simulated") is not False:
        raise ValueError("Capture must explicitly identify real sensor data")
    with np.load(path / "lwir_y16.npz", allow_pickle=False) as archive:
        stack = archive["stack"]
    if stack.dtype != np.uint16 or stack.ndim != 3 or min(stack.shape) < 1:
        raise ValueError("Expected nonempty uint16 Y16 stack[n,h,w]")
    return stack, meta


def validate_rois(rois, shape):
    height, width = shape
    if len(rois) != 2:
        raise ValueError("Select box surface and independent reference patch")
    for r in rois:
        if len(r) != 4 or not all(type(v) is int for v in r):
            raise ValueError("ROI coordinates must be four integers")
        x0, y0, x1, y1 = r
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError("ROI outside original thermal image")
    a, b = rois
    if max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3]):
        raise ValueError("Surface and reference must not overlap")


def load_peer(system_dir, workspace):
    system, workspace = Path(system_dir).resolve(), Path(workspace).resolve()
    if workspace == system or system in workspace.parents:
        raise ValueError("Use a lab workspace outside the running system")
    sys.path.insert(0, str(system / "sensor"))
    rules = importlib.import_module("rules")
    calib = importlib.import_module("rules_calib")
    workspace.mkdir(parents=True, exist_ok=True)
    rules.CALIB_DIR = workspace
    rules.PATH = workspace / "coolant_draft.json"
    if not rules.PATH.exists():
        rules.PATH.write_text(json.dumps({"version": "coolant-lab-1", "validated": False,
            "tapes": [], "coolant": None, "faces_without_checks_ok": []}, indent=2), encoding="utf-8")
    return rules, calib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-dir", required=True)
    parser.add_argument("--workspace", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    roi = commands.add_parser("roi")
    roi.add_argument("--capture", required=True)
    roi.add_argument("--rois", required=True, help='Original Y16 pixels: "x0,y0,x1,y1;x0,y0,x1,y1"')
    measure = commands.add_parser("measure")
    measure.add_argument("--captures", nargs="+", required=True)
    measure.add_argument("--label", choices=["present", "absent", "unknown"], default="unknown")
    fit = commands.add_parser("fit")
    fit.add_argument("--on", nargs="+", required=True)
    fit.add_argument("--off", nargs="+", required=True)
    fit.add_argument("--source-id", required=True)
    args = parser.parse_args()
    rules, calib = load_peer(args.system_dir, args.workspace)
    cfg = rules.load()
    if args.command == "init":
        print(rules.PATH)
        return
    if args.command == "roi":
        stack, meta = read_stack(args.capture)
        rois = [[int(v) for v in part.split(",")] for part in args.rois.split(";")]
        validate_rois(rois, stack.shape[1:])
        if meta.get("face") not in ("A", "B", "C"):
            raise ValueError("Capture face missing")
        cfg["coolant"] = dict(face=meta["face"], roi_lwir=rois[0], ref_roi_lwir=rois[1],
                              delta_max_counts=None, margin_counts=None)
        cfg.update(validated=False, roi_source=str(Path(args.capture).resolve()))
        calib.cfg_save(cfg)
        return
    coolant = cfg.get("coolant")
    if not coolant:
        raise ValueError("First select thermal surface/reference ROIs with roi command")
    paths = args.captures if args.command == "measure" else args.on + args.off
    resolved = [str(Path(p).resolve()) for p in paths]
    if len(set(resolved)) != len(resolved):
        raise ValueError("Duplicate capture or same capture in both classes")
    rows = []
    for path in paths:
        stack, meta = read_stack(path)
        quality_ok = meta.get("sensor_data", {}).get("assessment", {}).get("capture_quality_ok")
        if args.command == "fit" and quality_ok is not True:
            raise ValueError("Fit requires a capture with verified capture_quality_ok=true")
        if meta.get("face") != coolant["face"]:
            raise ValueError("Capture face differs from ROI face")
        validate_rois([coolant["roi_lwir"], coolant["ref_roi_lwir"]], stack.shape[1:])
        mean = stack.astype(np.float32).mean(axis=0)
        delta = lambda im: rules.coolant_delta(im.astype(np.float32), coolant["roi_lwir"], coolant["ref_roi_lwir"])
        per_frame = [delta(frame) for frame in stack]
        rows.append(dict(capture=str(Path(path).resolve()), face=meta["face"], frames=len(stack),
                         capture_quality_ok=quality_ok, delta_counts=delta(mean),
                         frame_delta_range=[min(per_frame), max(per_frame)]))
    if args.command == "measure":
        print(json.dumps(dict(label=args.label, unit="raw_counts_not_celsius", deployment_ready=False,
                              samples=rows), ensure_ascii=False, indent=2))
        return
    if len(args.on) < 3 or len(args.off) < 3:
        raise ValueError("Need at least three distinct captures in each class")
    calib.cmd_fit(SimpleNamespace(tape_on=[], tape_off=[], coolant_on=args.on,
                                 coolant_off=args.off, source_id=args.source_id))
    fitted = rules.load()
    fitted.update(validated=False, deployment_ready=False, independent_evaluation_required=True,
                  calibration_samples={"present": args.on, "absent": args.off})
    calib.cfg_save(fitted)
    print("Draft only. Evaluate independent captures before integrating with station rules.")


if __name__ == "__main__":
    main()
