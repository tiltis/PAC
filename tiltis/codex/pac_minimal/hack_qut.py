"""Reuses the original OpenCV / MediaPipe / Flask wrist pipeline."""
import argparse
import threading
import time
from pathlib import Path
from flask import Flask, jsonify, send_file
from control import Controller
from workspace import Workspace

app = Flask(__name__)
controller = Controller()


@app.get('/')
def index():
    return send_file(Path(__file__).with_name('index.html'))


@app.get('/api/state')
def state():
    return jsonify(controller.state())


@app.post('/api/enable')
def enable():
    return jsonify(ok=controller.enable(), state=controller.state())


@app.post('/api/stop')
def stop():
    controller.stop()
    return jsonify(controller.state())


def run_camera(camera_index=0, preview=True):
    import cv2
    import mediapipe as mp
    cap = cv2.VideoCapture(camera_index)
    try:
        with mp.solutions.hands.Hands(model_complexity=0, max_num_hands=2,
                                     min_detection_confidence=.7,
                                     min_tracking_confidence=.7) as hands:
            while cap.isOpened():
                captured = time.monotonic()
                ok, frame = cap.read()
                if not ok:
                    break
                frame = cv2.flip(frame, 1)
                result = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                found = result.multi_hand_landmarks or []
                wrist = found[0].landmark[0] if len(found) == 1 else None
                controller.update((wrist.x, wrist.y) if wrist else None, len(found), captured)
                h, w = frame.shape[:2]
                cv2.rectangle(frame, (int(w*.1), int(h*.1)), (int(w*.9), int(h*.9)), (0,255,255), 2)
                if wrist:
                    cv2.circle(frame, (int(wrist.x*w), int(wrist.y*h)), 8, (0,255,0), -1)
                if preview:
                    cv2.imshow('PAC wrist input - Q to stop', frame)
                    if cv2.waitKey(1) & 255 == ord('q'):
                        break
    finally:
        controller.stop('camera_stopped')
        cap.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', default=str(Path(__file__).with_name('workspace.virtual.json')))
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--no-preview', action='store_true')
    args = parser.parse_args()
    controller = Controller(workspace=Workspace.load(args.workspace))
    threading.Thread(target=run_camera, args=(args.camera, not args.no_preview), daemon=True).start()
    app.run(host='127.0.0.1', port=5001, threaded=True, use_reloader=False)
