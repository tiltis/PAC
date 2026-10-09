"""Environment and serial inventory only; never opens ports or enables torque."""
import importlib.util
import json
import platform
import sys

result = dict(python=sys.version,executable=sys.executable,platform=platform.platform(),
              modules={m:bool(importlib.util.find_spec(m)) for m in
                       ['cv2','mediapipe','flask','numpy','lerobot','placo','serial']})
try:
    from serial.tools import list_ports
    result['ports'] = [dict(device=p.device,description=p.description,vid=p.vid,pid=p.pid,
                           serial_number=p.serial_number) for p in list_ports.comports()]
except ImportError:
    result['ports'] = 'pyserial not installed; run python -m pip install pyserial'
print(json.dumps(result,ensure_ascii=False,indent=2))
