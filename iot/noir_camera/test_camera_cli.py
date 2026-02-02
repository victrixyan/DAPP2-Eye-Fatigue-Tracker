# Temporary terminal-prompted test for NoIR 
import time
from video_processing import PupilTracker

def test_camera():
    user_id = input("Enter User ID: ")
    print(f"Starting session for {user_id}. Press Ctrl+C to stop...")
    
    try: 
        # The context manager automatically calls init_camera() and init_session()
        with PupilTracker() as tracker:
            while True:
                data = tracker.process_frame()
                
                if data:
                    # Unpacking the tuple for clearer terminal feedback
                    f_count, blink, cx, cy, area = data
                    status = "BLINK" if blink else f"Pos: ({cx}, {cy}) Area: {area}"
                    print(f"Frame {f_count} | {status}", end='\r')
                else:
                    print("\nWarning: Failed to capture frame.")
                    break
                    
    except KeyboardInterrupt:
        print("\n\n^C Detected: Closing camera and exiting test session.")
    except Exception as e:
        print(f"\nError during tracking: {e}")

def main():
    start = time.perf_counter()
    test_camera()
    end = time.perf_counter()
    print(f"\nSession duration: {(end - start):.2f} seconds")

if __name__ == "__main__":
    main()