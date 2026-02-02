# Module: raw NoIR video frames to metrics
# Return: session_id: int, blink: bool, cx: float, cy: float 
# Units: pixels for time, s or ns for time
# All constant parameters can be tuned according to test results

import cv2
import time
import math
from picamera2 import Picamera2  # Raspberry pi camera module interface 

class PupilTracker:
    """
    Pupil Tracker optimized for Camera Module 2 NoIR lenses (<=1mm).
    Features contrast stretching to handle shallow depth-of-field issues.
    """

    def __init__(self, resolution=(640, 480), fps=50):
        self.resolution = resolution
        self.fps = fps
        self.picam2 = None  
        self.session_id = None
        self.frame_count = 0

    def init_camera(self):
        """Initialize camera"""
        self.picam2 = Picamera2()
        # YUV420: picamera2 native; Y-plane(luminance) is pure greyscale
        config = self.picam2.create_preview_configuration(
            main={'format': 'YUV420', 'size': self.resolution}
        )
        config['main']['fps'] = self.fps
        self.picam2.configure(config)
        self.picam2.start()
        return True

    def init_session(self):
        self.session_id = time.time_ns()

    def find_best_pupil(self, grey_frame):
        """
        1. Normalizes image contrast to handle 'muddy' NoIR sensor data.
        2. Applies a heavy median blur to reduce sensor noise from the small aperture.
        3. Iterates through multiple dark-level thresholds to find dark blobs.
        4. Filters blobs based on area and circularity.
        5. Performs blink detection based on the aspect ratio of the fitted ellipse.
        Args:
            grey_frame (numpy.ndarray)
        Returns:
            tuple: (is_blink, cx, cy, area)
                - is_blink (bool): True if no pupil is found or if the eye is closed.
                - cx (float): The X-coordinate of the pupil center.
                - cy (float): The Y-coordinate of the pupil center.
                - area (float): The calculated area of the pupil contour.
        """
        # Contrast stretch/ Normalization
        # normalize narrow distributions
        min_val, max_val, _, _ = cv2.minMaxLoc(grey_frame)
        # output = (input + beta) * alpha
        grey_frame = cv2.convertScaleAbs(grey_frame, alpha=255.0/(max_val - min_val + 1), beta=-min_val)

        # Blur to remove noise points using a sliding window
        # center of kernel = median (not weighted average in convolution) to preserve sharp edges
        blurred = cv2.medianBlur(grey_frame, 9) # kernel size n x n
        
        best_candidate = None
        highest_score = 0
        
        # Multilevel Thresholding
        # for low constrast, poor lighting; brightness can fluctuate
        # singular thresholding may produce no contours
        for thresh in [25, 45, 65, 85]:
            _, binary = cv2.threshold(blurred, thresh, 255, cv2.THRESH_BINARY_INV)
            # Approximate pupils with contours
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for contour in contours:
                area = cv2.contourArea(contour)
                # Filter for realistic pupil sizes
                if 40 < area < 27000:
                    perimeter = cv2.arcLength(contour, True)
                    if perimeter == 0: continue
                    
                    # Circularity formula (roundness)
                    # if circle, circularity = 1 
                    circularity = (4 * math.pi * area) / (perimeter ** 2)
                    
                    if circularity > 0.20: 
                        score = circularity * area
                        if score > highest_score and len(contour) >= 5:
                            highest_score = score
                            best_candidate = contour
                            candidate_area = area

        if best_candidate is not None:
            # width and height of the smallest rectangle that can contain the ellipse
            (cx, cy), (w, h), _ = cv2.fitEllipse(best_candidate)
            
            # Blink Detection: Aspect Ratio (flatness) + Area Floor
            if h < (w * 0.20) or candidate_area < 400:
                return 1, 0.0, 0.0, 0.0
                
            return 0, round(cx, 2), round(cy, 2), round(candidate_area, 2)

        return 1, 0.0, 0.0, 0.0

    def process_frame(self):
        if self.picam2 is None:
            return None
        
        frame_data = self.picam2.capture_array()
        self.frame_count += 1
        
        if frame_data is None:
            return None
            
        # Extract Y-plane (Grayscale)
        grey_frame = frame_data if len(frame_data.shape) == 2 else frame_data[:, :, 0]
        
        blink, cx, cy, area = self.find_best_pupil(grey_frame)
        return (self.frame_count, float(blink), float(cx), float(cy), float(area))

    def end_session(self):
        if self.picam2 is not None:
            self.picam2.stop()
            self.picam2 = None
    
    def __enter__(self):
        self.init_camera()
        self.init_session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_session()