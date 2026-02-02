# Module: raw NoIR video frames to metrics
# Return: (session_id: int, blink: bool, cx: float, cy: float)

import cv2
import time
import numpy as np
from picamera2 import Picamera2

class PupilTracker:
    """Tracks pupil metrics using Pi 5 NoIR camera via optimized YUV420 capture."""

    def __init__(self, resolution=(320, 240), fps=40):
        """
        Initialize tracker parameters.
        
        Args:
            resolution (tuple): Capture width and height.
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

    def raw2binary(self, grey_frame): 
        """
        Convert grayscale image to binary.
        
        Args:
            grey_frame (numpy.ndarray): Input grayscale array.
            
        Returns:
            numpy.ndarray: Thresholded binary image.
        """
        _, binary_frame = cv2.threshold(
            grey_frame, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )
        return binary_frame
    
    def fit_ellipse(self, binary_frame, min_area=100):
        """
        Fit ellipse to largest contour.
        
        Args:
            binary_frame (numpy.ndarray): Binary image input.
            min_area (int): Minimum pixel area for valid pupil.
            
        Returns:
            tuple: (blink: bool, cx: float, cy: float, area: float)
        """
        contours, _ = cv2.findContours(
            binary_frame, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        
        if not contours:
            return True, 0, 0, 0  
        
        max_contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(max_contour) 

        if area > min_area and len(max_contour) > 5:
            (cx, cy), _, _ = cv2.fitEllipse(max_contour)
            return False, round(cx, 2), round(cy, 2), round(area, 2)
            
        return True, 0, 0, 0 

    def process_frame(self):
        """
        Extract grayscale from YUV buffer and run tracking logic.
        
        Returns:
            tuple: (frame_count, blink, cx, cy, area) or None.
        """
        if self.picam2 is None:
            raise Exception("Camera not initialized.")
        
        frame_data = self.picam2.capture_array()
        self.frame_count += 1

        if frame_data is None:
            return None
            
        # Optimization: Slice Y-plane (index 0) to get grayscale natively
        grey_frame = frame_data[:, :, 0]
        
        binary_frame = self.raw2binary(grey_frame)
        blink, cx, cy, area = self.fit_ellipse(binary_frame)
        
        return (self.frame_count, float(blink), float(cx), float(cy), float(area))

    def end_session(self):
        """Stop camera and release hardware resources."""
        if self.picam2 is not None:
            self.picam2.stop()
            self.picam2 = None
    
    def __enter__(self):
        """Context manager entry."""
        self.init_camera()
        self.init_session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.end_session()