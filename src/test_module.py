"""CLI test for USBPupilTracker per-second feature stream."""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.gc0308 import USBPupilTracker


def run() -> None:
    print("USBPupilTracker per-second test")
    print("Format: Second X | IBI=<sec> | Pupil=<px2>")
    print("Press Ctrl+C to stop\n")

    try:
        with USBPupilTracker() as tracker:
            while True:
                result = tracker.process_frame()
                if result is not None:
                    sec, ibi_sec, pupil_area = result
                    print(f"Second {sec}: IBI={ibi_sec:.2f}s, Pupil={pupil_area:.2f}px²")
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as e:
        print(f"\nError: {e}")


if __name__ == "__main__":
    run()
