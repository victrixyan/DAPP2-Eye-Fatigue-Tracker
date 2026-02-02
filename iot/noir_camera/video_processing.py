# Module: raw NoIR video frames to metrics
# Return: (session_id: int, blink: bool, cx: float, cy: float)

import cv2
import time
import math
from picamera2 import Picamera2

class PupilTracker:
    """
    Pupil Tracker optimized for tiny-aperture NoIR lenses (<=1mm).
    Features contrast stretching to handle shallow depth-of-field issues.
    """

    def __init__(self, resolution=(640, 480), fps=60):
        self.resolution = resolution
        self.fps = fps
        self.picam2 = None  
        self.session_id = None
        self.frame_count = 0
        self._pi = math.pi 

    def init_camera(self):
        """Initializes camera using dictionary-style configuration."""
        self.picam2 = Picamera2()
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
        # --- NEW: CONTRAST STRETCHING ---
        # Tiny lenses often produce 'muddy' gray images. 
        # This stretches the darkest pixels to black to help the threshold find the pupil.
        min_val, max_val, _, _ = cv2.minMaxLoc(grey_frame)
        grey_frame = cv2.convertScaleAbs(grey_frame, alpha=255.0/(max_val - min_val + 1), beta=-min_val)

        # Heavier blur to handle the high noise of a tiny 1mm lens
        blurred = cv2.medianBlur(grey_frame, 9)
        
        best_candidate = None
        highest_score = 0
        
        # Scan dark levels - focused on the very low end (darkest spots)
        for thresh in [25, 45, 65, 85]:
            _, binary = cv2.threshold(blurred, thresh, 255, cv2.THRESH_BINARY_INV)
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for cnt in contours:
                area = cv2.contourArea(cnt)
                # Filter for realistic pupil sizes
                if 400 < area < 25000:
                    peri = cv2.arcLength(cnt, True)
                    if peri == 0: continue
                    
                    circ = (4 * self._pi * area) / (peri ** 2)
                    
                    # Keep circularity low (0.20) for tiny lens distortion
                    if circ > 0.20: 
                        score = circ * area
                        if score > highest_score and len(cnt) >= 5:
                            highest_score = score
                            best_candidate = cnt

        if best_candidate is not None:
            (cx, cy), (w, h), angle = cv2.fitEllipse(best_candidate)
            area = cv2.contourArea(best_candidate)
            
            # Blink Detection: Aspect Ratio + Area Floor
            if h < (w * 0.30) or area < 500:
                return True, 0.0, 0.0, 0.0
                
            return False, round(cx, 2), round(cy, 2), round(area, 2)

        return True, 0.0, 0.0, 0.0

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