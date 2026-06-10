# Temporary terminal-prompted test for NoIR 
import time
import sys
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
                    # Unpacking the 5 metrics
                    f_count, blink, cx, cy, area = data
                    
                    # UPDATED: Mapping integer 1/0 to BLINK/NOT BLINK
                    status = "BLINK    " if blink == 1 else "NOT BLINK"
                    
                    # Using \r to update the same line in the terminal
                    print(f"F: {f_count:05d} | {status} | X: {cx:>6.2f} | Y: {cy:>6.2f} | A: {area:>8.2f}", end='\r')
                    sys.stdout.flush() 
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