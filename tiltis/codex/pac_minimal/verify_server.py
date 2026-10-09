"""Start the real webcam/Flask entrypoint briefly and inspect its local API.

Uses no robot backend, never enables motion, and terminates only its own child.
"""
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    logs = root/'logs'
    logs.mkdir(exist_ok=True)
    try:
        with socket.create_connection(('127.0.0.1',5001),timeout=.1):
            raise RuntimeError('Port 5001 already occupied; existing service will not be stopped')
    except (ConnectionRefusedError, socket.timeout):
        pass
    with (logs/'server_check_stdout.txt').open('w',encoding='utf-8') as output:
        process = subprocess.Popen([sys.executable,str(root/'hack_qut.py'),'--no-preview'],
            cwd=root,stdout=output,stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            deadline = time.monotonic()+45
            last = None
            while time.monotonic()<deadline:
                if process.poll() is not None:
                    raise RuntimeError('Tracker exited during startup; inspect logs/server_check_stdout.txt')
                try:
                    with urllib.request.urlopen('http://127.0.0.1:5001/api/state',timeout=.5) as response:
                        last = json.load(response)
                    if last['frame_id'] > 1 and last['frame_age_s'] is not None and 0 <= last['frame_age_s'] <= .2:
                        break
                except (OSError,ValueError):
                    pass
                time.sleep(.1)
            if last is None or last['frame_id'] <= 1 or last['frame_age_s'] is None or not 0 <= last['frame_age_s'] <= .2:
                raise RuntimeError('No processed camera frames; inspect logs/server_check_stdout.txt')
            page_started = time.monotonic()
            # Static-page startup is independent of the bridge's short API timeout.
            with urllib.request.urlopen('http://127.0.0.1:5001/',timeout=5) as response:
                html_ok = response.status == 200 and b'canvas' in response.read()
            if last['motion_enabled'] is not False:
                raise RuntimeError('Tracker unexpectedly enabled motion')
            report = dict(camera_and_api_passed=html_ok,state=last,robot_backend_used=False,
                          monitor_page_load_s=time.monotonic()-page_started)
            (logs/'server_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == '__main__':
    main()
