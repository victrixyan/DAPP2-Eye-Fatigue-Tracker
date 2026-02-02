# Module: raw NoIR video frames to metrics
# Return: (session_id: int, blink: bool, cx: float, cy: float)

import cv2
import time
import numpy as np
from picamera2 import Picamera2

class PupilTracker:
    """Optimized pupil tracker for Pi 5 NoIR using Adaptive Multi-Thresholding."""

    def __init__(self, resolution=(640, 480), fps=40):
        """
        Args:
            resolution (tuple): 640x480 is the sweet spot for Pi 5 precision.
            fps (int): Target frame rate.
        """
        self.resolution = resolution
        self.fps = fps
        self.picam2 = None  
        self.session_id = None
        self.frame_count = 0

    def init_camera(self):
        """Initialize camera handle and start YUV420 stream."""
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(
            main={'format': 'YUV420', 'size': self.resolution}
        )
        self.picam2.configure(config)
        self.picam2.start()
        return True

    def init_session(self):
        """Generate session timestamp."""
        self.session_id = time.time_ns()

    def find_best_pupil(self, grey_frame):
        """
        Scan multiple thresholds to find the most circular dark object.
        
        Args:
            grey_frame (numpy.ndarray): Native grayscale Y-plane.
        Returns:
            tuple: (blink: bool, cx: float, cy: float, area: float)
        """
        # Stronger blur to handle NoIR sensor grain at 640x480
        blurred = cv2.medianBlur(grey_frame, 5)
        
        best_contour = None
        max_circularity = 0
        
        # We scan a wider range of thresholds to catch the pupil
        # If your pupil is 'Bright' (White), change THRESH_BINARY_INV to THRESH_BINARY
        for threshold_value in [30, 50, 70, 90, 110]:
            _, binary = cv2.threshold(blurred, threshold_value, 255, cv2.THRESH_BINARY_INV)
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for cnt in contours:
                area = cv2.contourArea(cnt)
                # Size constraints for 640x480
                if 500 < area < 15000: 
                    perimeter = cv2.arcLength(cnt, True)
                    if perimeter == 0: continue
                    
                    # Circularity: 1.0 is a perfect circle
                    circularity = (4 * np.pi * area) / (perimeter ** 2)
                    
                    # Relaxed circularity to 0.4 to catch pupils partially covered by lids
                    if circularity > max_circularity and len(cnt) >= 5:
                        max_circularity = circularity
                        best_contour = cnt

        if best_contour is not None and max_circularity > 0.4:
            (cx, cy), (w, h), angle = cv2.fitEllipse(best_contour)
            # Ensure the object isn't too thin (like an eyelash)
            if 0.4 < (w / h) < 1.6:
                return False, round(cx, 2), round(cy, 2), round(cv2.contourArea(best_contour), 2)

        return True, 0, 0, 0

    def process_frame(self):
        """Capture hardware buffer and process."""
        if self.picam2 is None:
            raise Exception("Camera handle not created.")
        
        frame_data = self.picam2.capture_array()
        self.frame_count += 1
        
        if frame_data is None:
            return None
            
        # Get Grayscale (Y-plane)
        grey_frame = frame_data if len(frame_data.shape) == 2 else frame_data[:, :, 0]
        
        blink, cx, cy, area = self.find_best_pupil(grey_frame)
        return (self.frame_count, float(blink), float(cx), float(cy), float(area))

    def end_session(self):
        """Stop hardware."""
        if self.picam2 is not None:
            self.picam2.stop()
            self.picam2 = None
    
    def __enter__(self):
        self.init_camera()
        self.init_session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_session()