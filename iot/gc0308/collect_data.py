import csv
import os
import sys
import threading
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from gc0308 import USBPupilTracker

DATA_DIR = os.path.join(SCRIPT_DIR, "data")


def prompt_text(prompt):
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Please enter a non-empty value.")


def prompt_duration(prompt):
    while True:
        value = input(prompt).strip()
        try:
            minutes = float(value)
            if minutes > 0:
                return minutes
        except ValueError:
            pass
        print("Please enter a valid duration in minutes (numeric and greater than 0).")


def prompt_yes_no(prompt):
    while True:
        value = input(prompt).strip().lower()
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Enter 'y' or 'n'.")


class CameraWorker(threading.Thread):
    def __init__(self, camera_index=0, resolution=(640, 480), fps=30):
        super().__init__(daemon=True)
        self.camera_index = camera_index
        self.resolution = resolution
        self.fps = fps
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.error = None
        self.status_lock = threading.Lock()

        self.blink = 1
        self.ibi = 0.0
        self.pupil_size = 0.0
        self.status_label = "INIT"

    def run(self):
        try:
            with USBPupilTracker(camera_index=self.camera_index, resolution=self.resolution, fps=self.fps) as tracker:
                self.ready_event.set()
                while not self.stop_event.is_set():
                    data = tracker.process_frame()
                    if data is None:
                        self.error = "Failed to read from camera."
                        break

                    _, blink, _, _, _, ibi, ema, _ = data
                    with self.status_lock:
                        self.blink = blink
                        self.ibi = ibi
                        self.pupil_size = ema
                        self.status_label = "BLINK" if blink == 1 else "OPEN "

                    # Keep capture responsive but avoid tight busy loops
                    time.sleep(max(0.0, 1.0 / self.fps))
        except Exception as exc:
            self.error = str(exc)
            self.ready_event.set()

    def stop(self):
        self.stop_event.set()
        self.join(timeout=5.0)

    def get_status(self):
        with self.status_lock:
            return {
                "blink": self.blink,
                "ibi": self.ibi,
                "pupil_size": self.pupil_size,
                "label": self.status_label,
            }


def ensure_data_directory():
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR


def format_line(label, remaining, ibi, pupil_size):
    return (
        f"{label} | Remaining: {remaining:>3}s | IBI: {ibi:>5.2f}s | "
        f"Pupil: {pupil_size:>6.2f}"
    )


def warmup_camera(worker, duration_seconds=60):
    print(f"\nStarting 1-minute camera warmup. Watch open/blink status below.")
    start_time = time.time()
    end_time = start_time + duration_seconds
    while time.time() < end_time:
        if worker.error:
            raise RuntimeError(worker.error)

        status = worker.get_status()
        remaining = int(max(0, end_time - time.time()))
        sys.stdout.write("\r" + format_line(status["label"], remaining, status["ibi"], status["pupil_size"]))
        sys.stdout.flush()
        time.sleep(0.15)
    print("\r" + " " * 80 + "\r", end="")
    print("Warmup complete. Camera is ready.")


def collect_measurements(worker, uid, duration_minutes):
    total_seconds = int(round(duration_minutes * 60))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_uid = uid.replace(" ", "_")
    filename = f"{safe_uid}_{timestamp}.csv"
    filepath = os.path.join(ensure_data_directory(), filename)

    with open(filepath, mode="w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["uid", "seconds", "ibi", "pupil_size"])

        start_time = time.time()
        next_tick = start_time + 1.0
        second_index = 0

        print(f"\nCollecting data for {duration_minutes:.2f} minute(s).")
        while time.time() < start_time + total_seconds:
            if worker.error:
                raise RuntimeError(worker.error)

            now = time.time()
            if now >= next_tick:
                second_index += 1
                status = worker.get_status()
                writer.writerow([uid, second_index, status["ibi"], status["pupil_size"]])
                csv_file.flush()
                next_tick += 1.0

            remaining = int(max(0, start_time + total_seconds - now))
            status = worker.get_status()
            sys.stdout.write(
                "\r" +
                format_line(status["label"], remaining, status["ibi"], status["pupil_size"]) +
                f" | Elapsed: {int(now - start_time):>3}s"
            )
            sys.stdout.flush()
            time.sleep(0.1)

        print("\r" + " " * 120 + "\r", end="")
        print(f"Collection finished. Saved to: {filepath}")

    return filepath


def main():
    print("Eye Tracker Data Collection")
    uid = prompt_text("UID: ")
    duration_minutes = prompt_duration("Collection duration (min): ")

    worker = CameraWorker()
    worker.start()

    if not worker.ready_event.wait(timeout=15.0):
        worker.stop()
        raise RuntimeError("Camera did not initialize.")

    if worker.error:
        worker.stop()
        raise RuntimeError(worker.error)

    try:
        warmup_camera(worker, duration_seconds=60)
        if not prompt_yes_no("Start collection now? (y/n): "):
            print("Collection cancelled.")
            return

        filepath = collect_measurements(worker, uid, duration_minutes)
        print(f"Data collection complete. File path: {filepath}")
    finally:
        worker.stop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting.")
    except Exception as exc:
        print(f"\nError: {exc}")
        sys.exit(1)
