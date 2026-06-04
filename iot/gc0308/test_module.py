import time
import sys
# Update import to match the new modular class name
from gc0308 import USBPupilTracker

def test_camera():
    user_id = input("Enter User ID: ")
    print(f"Starting USB tracking session for {user_id}. Press Ctrl+C to stop...")
    
    try: 
        # Initialize the orchestrator class (defaults to camera_index=0)
        with USBPupilTracker() as tracker:
            while True:
                data = tracker.process_frame()
                
                if data:
                    # Unpack the 8 metrics returned by the modularized process_frame()
                    f_count, blink, cx, cy, area, ibi, ema, light = data
                    
                    # Map integer 1/0 to clean terminal output
                    status = "BLINK" if blink == 1 else "OPEN "
                    
                    # Compact formatting to fit safely on one terminal line
                    out_str = (f"F:{f_count:05d} | {status} | X:{cx:>6.2f} Y:{cy:>6.2f} "
                               f"| A:{area:>7.2f} | EMA:{ema:>7.2f} "
                               f"| IBI:{ibi:>5.2f}s | LGT:{light:>6.2f}")
                    
                    sys.stdout.write('\r' + out_str)
                    sys.stdout.flush() 
                else:
                    print("\nWarning: Failed to capture frame. Check USB connection.")
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