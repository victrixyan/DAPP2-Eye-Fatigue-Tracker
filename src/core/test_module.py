"""Live CLI test for PupilDetector blink-state accuracy."""

import sys
import time
import platform
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gc0308 import PupilDetector


def _open_camera(camera_index: int = 0) -> cv2.VideoCapture:
    if platform.system() == "Linux":
        cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
    else:
        cap = cv2.VideoCapture(camera_index)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)

    if not cap.isOpened():
        raise RuntimeError(f"Failed to open camera at index {camera_index}")
    return cap


def run(camera_index: int = 0) -> None:

    detector = PupilDetector()
    cap = _open_camera(camera_index)
    start = time.time()
    frame_count = 0
    last_state = None
    open_frames = 0
    blink_frames = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("\nFailed to read frame.")
                break

            frame_count += 1
            grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            blink, area = detector.process(grey)

            state = "BLINK" if blink == 1 else "OPEN"
            if state == "OPEN":
                open_frames += 1
            else:
                blink_frames += 1

            elapsed = int(time.time() - start)
            area_str = f"{area:8.2f}" if state == "OPEN" else "    ---"

            sys.stdout.write(
                f"\rTime: {elapsed:>4d}s | Frame: {frame_count:>5d} | "
                f"State: {state} | Area: {area_str}"
            )
            sys.stdout.flush()

            if state != last_state:
                if last_state is not None:
                    sys.stdout.write(f"\r[{elapsed:>4d}s] {last_state} -> {state}\r")
                    sys.stdout.flush()
                last_state = state

    except KeyboardInterrupt:
        elapsed = int(time.time() - start)
        total = open_frames + blink_frames
        open_pct = (100.0 * open_frames / total) if total else 0.0
        blink_pct = (100.0 * blink_frames / total) if total else 0.0

        print(f"\n\nStopped after {elapsed}s ({frame_count} frames)")
        print(f"OPEN:  {open_frames:>5d} frames ({open_pct:5.1f}%)")
        print(f"BLINK: {blink_frames:>5d} frames ({blink_pct:5.1f}%)")
    finally:
        cap.release()


if __name__ == "__main__":
    run()
