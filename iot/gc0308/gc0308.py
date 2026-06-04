import cv2
import time
import math

class PupilDetector:
    """
    Image processing logic to isolate the pupil from raw frames.
    Uses adaptive thresholding and geometric filtering to handle varying lighting.
    """
    
    @staticmethod
    def process(grey_frame):
        """
        Processes a grayscale frame to extract pupil center and area.
        
        Logic:
        1. Contrast Stretching: Normalizes pixel intensities based on min/max.
        2. Blur: Reduces high-frequency noise.
        3. Multilevel Thresholding: Scans range to find the most circular candidate.
        
        Returns:
            (is_blink, cx, cy, area)
            - is_blink: 1 if blink/no-pupil detected, 0 otherwise.
            - cx, cy: Float coordinates of pupil center.
            - area: Float pixel area of the detected pupil.
        """
        min_val, max_val, _, _ = cv2.minMaxLoc(grey_frame)
        if max_val == min_val: 
            return 1, 0.0, 0.0, 0.0

        # Enhance contrast to make the dark pupil stand out against the iris
        grey_frame = cv2.convertScaleAbs(grey_frame, alpha=255.0/(max_val - min_val), beta=-min_val)
        blurred = cv2.medianBlur(grey_frame, 9) 
        
        best_candidate = None
        highest_score = 0
        candidate_area = 0.0
        
        # Test multiple thresholds to find a shape matching pupil characteristics
        for thresh in [25, 45, 65, 85]:
            _, binary = cv2.threshold(blurred, thresh, 255, cv2.THRESH_BINARY_INV)
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for contour in contours:
                area = cv2.contourArea(contour)
                # Geometric constraints (based on anticipated sensor FOV/distance)
                if 40 < area < 27000:
                    perimeter = cv2.arcLength(contour, True)
                    if perimeter == 0: continue
                    
                    # Circularity = 4 * PI * Area / Perimeter^2 (1.0 = perfect circle)
                    circularity = (4 * math.pi * area) / (perimeter ** 2)
                    
                    if circularity > 0.20: 
                        score = circularity * area
                        if score > highest_score and len(contour) >= 5:
                            highest_score = score
                            best_candidate = contour
                            candidate_area = area

        if best_candidate is not None:
            (cx, cy), (w, h), _ = cv2.fitEllipse(best_candidate)
            
            # Reject if the ellipse is too flat (likely eye corner) or too small
            if h < (w * 0.20) or candidate_area < 400:
                return 1, 0.0, 0.0, 0.0
                
            return 0, round(cx, 2), round(cy, 2), round(candidate_area, 2)

        return 1, 0.0, 0.0, 0.0


class MetricStateTracker:
    """
    Manages temporal data streams. Maintains state for IBI, pupil size,
    and light intensity without storing large historical datasets.
    """
    
    def __init__(self, ema_alpha=0.15):
        self.ema_alpha = ema_alpha  # Smoothing factor (alpha) for EMA
        self.ema_pupil_size = 0.0
        
        self.last_blink_time = time.time()
        self.effective_ibi = 0.0
        self.is_currently_blinking = False
        
        self.sec_start_time = time.time()
        self.intensity_accum = 0.0
        self.frames_this_sec = 0
        self.light_intensity = 0.0

    def update_light(self, grey_frame, current_time):
        """Calculates running mean intensity per 1-second window."""
        current_intensity = cv2.mean(grey_frame)[0]
        self.intensity_accum += current_intensity
        self.frames_this_sec += 1
        
        if current_time - self.sec_start_time >= 1.0:
            self.light_intensity = self.intensity_accum / self.frames_this_sec
            self.intensity_accum = 0.0
            self.frames_this_sec = 0
            self.sec_start_time = current_time
            
        return round(self.light_intensity, 2)

    def update_ibi(self, blink, current_time):
        """
        Calculates blink interval.
        Uses max() to bridge the gap between stable IBI (history) 
        and TSLB (Time Since Last Blink) for real-time microsleep detection.
        """
        if blink == 1:
            if not self.is_currently_blinking:
                self.effective_ibi = current_time - self.last_blink_time
                self.last_blink_time = current_time
                self.is_currently_blinking = True
        else:
            self.is_currently_blinking = False
            
        # If the user is asleep, 'live_tslb' grows and exceeds the last recorded IBI,
        # forcing the monitor to display the real-time time-since-blink.
        live_tslb = current_time - self.last_blink_time
        effective_output = max(self.effective_ibi, live_tslb)
        
        return round(effective_output, 2)

    def update_ema(self, blink, area):
        """
        Updates pupil size using Exponential Moving Average:
        S_t = (alpha * current) + ((1 - alpha) * S_{t-1})
        """
        if blink == 0:
            if self.ema_pupil_size == 0.0:
                self.ema_pupil_size = area 
            else:
                self.ema_pupil_size = (self.ema_alpha * area) + ((1 - self.ema_alpha) * self.ema_pupil_size)
        return round(self.ema_pupil_size, 2)


class USBPupilTracker:
    """Orchestrates the lifecycle of the USB video pipeline."""
    
    def __init__(self, camera_index=0, resolution=(640, 480), fps=30):
        self.camera_index = camera_index
        self.resolution = resolution
        self.fps = fps
        self.cap = None
        self.frame_count = 0
        
        self.detector = PupilDetector()
        self.tracker = MetricStateTracker()

    def init_camera(self):
        """Configures V4L2 backend for optimal headless performance."""
        self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0) 
        
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open USB camera at index {self.camera_index}")
        return True

    def process_frame(self):
        """Captures a frame and flows it through the detector and state tracker."""
        if self.cap is None or not self.cap.isOpened():
            return None
        
        ret, frame = self.cap.read()
        if not ret:
            return None
            
        self.frame_count += 1
        current_time = time.time()
        grey_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 1. Vision Processing: Isolates eyes
        blink, cx, cy, area = self.detector.process(grey_frame)
        
        # 2. State Management: Updates metrics based on findings
        light = self.tracker.update_light(grey_frame, current_time)
        ibi = self.tracker.update_ibi(blink, current_time)
        ema = self.tracker.update_ema(blink, area)

        return (self.frame_count, blink, cx, cy, area, ibi, ema, light)

    def end_session(self):
        """Releases hardware resources."""
        if self.cap is not None:
            self.cap.release()
            self.cap = None
    
    def __enter__(self):
        self.init_camera()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_session()