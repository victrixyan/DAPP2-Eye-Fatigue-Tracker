# Temporary terminal-prompted test for NoIR 
import time

from video_processing import PupilTracker

def test_camera():
    tracker = PupilTracker()
    user_id = input("user id :")

    try:
        if tracker.init_camera():
            print("Camera initialized...")
        else: 
            raise ConnectionError("Camera initiation failure")
        session_id = tracker.init_session
        print("New session. id: {session_id}")
        print("Test started. Press Ctrl + c to end test")

        while True:
            metric_tuple = tracker.process_frame()
            print(metric_tuple)
    except KeyboardInterrupt:
        print("^C test ended")
    finally:
        tracker.end_session()
