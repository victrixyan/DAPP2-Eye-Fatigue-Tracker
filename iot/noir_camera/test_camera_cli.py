# Temporary terminal-prompted test for NoIR 
import time

from video_processing import PupilTracker

def test_camera():
    user_id = input("user id :")
    try: 
        with PupilTracker() as tracker:
            while True:
                print(tracker.process_frame())          
    except KeyboardInterrupt:
        print("^c exit test session")
    except Exception as e:
        print(f"Error: {e}")

def main():
    start = time.perf_counter()
    test_camera()
    end = time.perf_counter()
    print(f"Session duration: {end - start}")

if __name__ == "__main__":
    main()
