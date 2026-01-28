# Module: raw NoIR video frames to metrics
# Return: (session_id: int, blink: bool, cx: float, cy: float)

import cv2  # opencv-python-headless version, optimize for pi (zero)
import time

class PupilTracker:
    # resolution to be tuned according to device
    # human blink duration average ~0.1-0.4s
    # frames per second > 10 + margin to compare adjacent states
    def __init__(self, resolution=(320, 240), fps=30):
        """
        Args: (Optional) resolution: tuple=(320, 240), fps: int=30
        """
        self.resolution = resolution
        self.fps = fps
        self.cap = None  # camera capture obj, a handle to the camera
        self.session_id = None
        self.frame_count = 0

    def init_camera(self, port=0):
        """
        Check camera connection. Initialze camera settings (resolution, fps)
        Return: True if successful camera setup
        """
        self.cap = cv2.VideoCapture(port)  # assume CSI using port 0
        if not self.cap.isOpened():
            raise ConnectionError("Camera cannot be connected...")
        
        # set lower resolution + sufficient fps
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        return True

    def init_session(self):
        """Generate a unique session identifier (current time stamp in ns)"""
        self.session_id = time.time_ns()

    def raw2binary(self, frame): 
        """
        process raw frames to grey-scale than to binary using Otsu's thresholding
        """
        grey_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # convert pupil to white fir finding contour
        _, binary_frame = cv2.threshold(grey_frame, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        return binary_frame
    
    def fit_ellipse(self, binary_frame, min_area=100):
        """
        Find the largest contour and fit ellipse.
        Return: blink, cx, cy, area
        """
        # Only retreive outermost contours, compress edge data
        contours, _ = cv2.findContours(binary_frame, cv2.RETR_EXTERNAL, cv2. CHAIN_APPROX_SIMPLE)
        
        # Blink detection
        if not contours:
            return True, 0, 0, 0  
        
        # Approximate pupil with the largest contour detected
        max_contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(max_contour) 

        # Noise filter: if contour is too small, not considered as pupil
        # >= 5 needed to fitEllispse
        if area > min_area and len(max_contour) > 5:
            (cx, cy), _, _ = cv2.fitEllipse(max_contour)
            return False, round(cx, 2), round(cy, 2), round(area, 2)
        return True, 0, 0, 0 

    def process_frame(self):
        if self.cap == None:
            raise Exception("Camera handle not created. Please initialize or check connections...")
        captured, frame = self.cap.read()
        self.frame_count += 1

        if not captured:
            return None
        binary_frame = self.raw2binary(frame)
        blink, cx, cy, area = self.fit_ellipse(binary_frame)
        return (self.frame_count, float(blink), float(cx), float(cy), float(area))

    def end_session(self):
        """Manually end a session""" 
        if self.cap != None:
            self.cap.release()
            self.cap = None
    
    # Cotext manager: auto release camera after use
    def __enter__(self):
        self.init_camera()
        self.init_session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_session()