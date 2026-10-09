"""Bounded camera/MediaPipe smoke check, without robot commands or image storage."""
import argparse
import json
import statistics
import time
from pathlib import Path


def main():
    import cv2
    import mediapipe as mp
    parser = argparse.ArgumentParser()
    parser.add_argument('--camera',type=int,default=0)
    parser.add_argument('--frames',type=int,default=30)
    parser.add_argument('--report',default='logs/camera_check.json')
    args = parser.parse_args()
    if not 1 <= args.frames <= 300:
        parser.error('--frames must be between 1 and 300')
    cap = cv2.VideoCapture(args.camera)
    report = dict(opencv=cv2.__version__,mediapipe=mp.__version__,
                  camera_index=args.camera,camera_open=cap.isOpened(),frames=0,
                  detected_hand_frames=0,max_processing_age_s=0.)
    ages = []
    try:
        with mp.solutions.hands.Hands(model_complexity=0,max_num_hands=2,
                                     min_detection_confidence=.7,
                                     min_tracking_confidence=.7) as hands:
            for _ in range(args.frames):
                start = time.monotonic()
                ok,frame = cap.read()
                if not ok:
                    break
                frame = cv2.flip(frame,1)
                results = hands.process(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
                report['frames'] += 1
                report['frame_shape'] = list(frame.shape)
                report['detected_hand_frames'] += bool(results.multi_hand_landmarks)
                age = time.monotonic()-start
                ages.append(age)
                report['max_processing_age_s'] = max(report['max_processing_age_s'],age)
    finally:
        cap.release()
    report['requested_frames'] = args.frames
    report['capture_and_processing_passed'] = report['frames'] == args.frames
    report['frames_over_200ms'] = sum(age > .2 for age in ages)
    report['first_frame_age_s'] = ages[0] if ages else None
    report['median_frame_age_s'] = statistics.median(ages) if ages else None
    path = Path(args.report)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    if not report['capture_and_processing_passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
