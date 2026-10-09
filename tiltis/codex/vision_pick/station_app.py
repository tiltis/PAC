"""Optional station entry point: shared web app + guarded vision picker.

Default ROBOT=mock and PICK_MODE=taught still apply. Import does not connect
hardware. Starting the shared app with ROBOT=so101 does connect hardware.
"""
from bootstrap import station_path

station = station_path()
import handeye  # noqa: E402
import os  # noqa: E402
from app import app  # noqa: E402
from guard import GuardedVisionPicker  # noqa: E402

seq = app.state.sequencer
base = seq.picker
preview_picker = GuardedVisionPicker(
    seq.sensor,
    base.he if base is not None else handeye.load(os.environ.get("HANDEYE") or station / "calib" / "handeye.json"),
    dry_run=base.dry_run if base is not None else True,
    cfg=dict(base.cfg, require_flat_placement=True) if base is not None else None,
    joint_map=base.joint_map if base is not None else None,
)
if base is not None:
    preview_picker.dry_stage = getattr(base, "dry_stage", "approach")
    preview_picker.dry_hold_s = getattr(base, "dry_hold_s", 8.0)
    path_service = getattr(app.state, "pick_path", None)
    if path_service is not None:
        path_service.bind_picker(preview_picker)
    else:
        seq.picker = preview_picker


@app.get("/api/pick/readiness")
def pick_readiness():
    return {"motion_enabled": False, "pick_mode": "vision" if seq.picker is not None else "taught",
            "grasp_mode": preview_picker.cfg.get("grasp_mode", "top"),
            "recomputes_pick_each_cycle": seq.picker is not None, "readiness": preview_picker.preflight_ready()}


@app.get("/api/pick/preview")
def pick_preview():
    from fastapi import HTTPException
    if seq.busy:
        raise HTTPException(409, "Cannot preview during a sorting run")
    loc = preview_picker.locate()
    plan = preview_picker.plan(loc)
    return {"motion_enabled": False, "locate": loc, "plan": plan}
