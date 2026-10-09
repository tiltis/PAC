"""센서 서버가 켜진 상태에서 실시간 3화면(RGB·열화상·깊이)을 이 PC 창으로 띄운다.

    .venv-sensor\\Scripts\\python tools\\live_view.py            # http://127.0.0.1:8001/live.jpg
    .venv-sensor\\Scripts\\python tools\\live_view.py --url http://<센서IP>:8001/live.jpg
창에서 q 또는 Esc로 닫는다. 서버가 카메라를 쥐고 있으므로 capture_app과 달리 서버와 같이 쓸 수 있다.
"""
import argparse
import time
import urllib.request

import cv2
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8001/live.jpg")
ap.add_argument("--fps", type=float, default=5.0)
a = ap.parse_args()

WIN = "PAC2026 Live RGB-LWIR-Depth (q: close)"
cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
cv2.resizeWindow(WIN, 1500, 360)
last_err = None
while True:
    t0 = time.time()
    try:
        with urllib.request.urlopen(a.url, timeout=3) as r:
            buf = np.frombuffer(r.read(), np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("decode failed")
        last_err = None
    except Exception as e:  # 서버가 아직 안 켜졌거나 꺼짐: 안내만 띄우고 계속 시도
        last_err = str(e)
        img = np.zeros((360, 1500, 3), np.uint8)
        cv2.putText(img, f"sensor server not reachable: {a.url}", (20, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.putText(img, "run_sensor.bat -Depth  /  run_all.bat -Depth", (20, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)
    cv2.imshow(WIN, img)
    key = cv2.waitKey(max(1, int(1000 / a.fps - (time.time() - t0) * 1000))) & 0xFF
    if key in (ord("q"), 27) or cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
        break
cv2.destroyAllWindows()
