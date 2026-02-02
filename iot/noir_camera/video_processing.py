# Module: raw NoIR video frames to metrics
# Return: (session_id: int, blink: bool, cx: float, cy: float)

import cv2
import time
import numpy as np
from picamera2 import Picamera2

class PupilTracker:
    """Tracks pupil metrics using Multi-Level Thresholding for better IR robustness."""

    def __init__(self, resolution=(640, 480), fps=40):
        """
        Initialize tracker parameters.
        
        Args:
            resolution (tuple): Capture width and height. Optimized at 640x480.
            fps (int): Target frames per second.
        """
        self.resolution = resolution
        self.fps = fps
        self.picam2 = None  
        self.session_id = None
        self.frame_count = 0

    def init_camera(self):
        """
        Start Pi 5 camera with YUV420 configuration.
        
        Returns:
            bool: True if camera started successfully.
        """
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(
            main={'format': 'YUV420', 'size': self.resolution}
        )
        self.picam2.configure(config)
        self.picam2.start()
        return True

    def init_session(self):
        """Generate a unique session ID."""
        self.session_id = time.time_ns()

    def find_best_pupil(self, grey_frame):
        """
        Multi-thresholding logic to find the most circular dark object.
        
        Args:
            grey_frame (numpy.ndarray): Grayscale input.
            
        Returns:
            tuple: (blink: bool, cx: float, cy: float, area: float)
        """
        # Noise reduction is vital for high-res NoIR
        blurred = cv2.GaussianBlur(grey_frame, (5, 5), 0)
        
        best_contour = None
        max_circularity = 0
        
        # Multi-thresholding: scan dark-to-mid tones (Pupils are usually < 80)
        for threshold_value in range(20, 100, 20):
            _, binary = cv2.threshold(blurred, threshold_value, 255, cv2.THRESH_BINARY_INV)
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if 200 < area < 15000:  # Size filter for 640x480
                    perimeter = cv2.arcLength(cnt, True)
                    if perimeter == 0: continue
                    
                    # Circularity formula: 4 * pi * Area / Perimeter^2
                    circularity = (4 * np.pi * area) / (perimeter ** 2)
                    
                    if circularity > max_circularity and len(cnt) >= 5:
                        max_circularity = circularity
                        best_contour = cnt

        # Determine if a valid pupil was found (circularity > 0.6 is typical)
        if best_contour is not None and max_circularity > 0.5:
            (cx, cy), (w, h), angle = cv2.fitEllipse(best_contour)
            # Aspect ratio check: pupils should not be extremely thin rectangles
            if 0.5 < (w / h) < 1.5:
                return False, round(cx, 2), round(cy, 2), round(cv2.contourArea(best_contour), 2)

        return True, 0, 0, 0

    def process_frame(self):
        """Capture YUV buffer and run multi-threshold tracking."""
        if self.picam2 is None:
            raise Exception("Camera not initialized.")
        
        frame_data = self.picam2.capture_array()
        self.frame_count += 1

        if frame_data is None:
            return None
            
        # Extract Y-plane (Grayscale)
        if len(frame_data.shape) == 2:
            grey_frame = frame_data
        else:
            grey_frame = frame_data[:, :, 0]
        
        blink, cx, cy, area = self.find_best_pupil(grey_frame)
        
        return (self.frame_count, float(blink), float(cx), float(cy), float(area))

    def end_session(self):
        """Stop camera and release hardware resources."""
        if self.picam2 is not None:
            self.picam2.stop()
            self.picam2 = None
    
    def __enter__(self):
        self.init_camera()
        self.init_session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_session()