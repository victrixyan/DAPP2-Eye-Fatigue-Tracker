import cv2
import time
import math
import numpy as np


class PupilDetector:
    """Detect the pupil from a grayscale IR image and return pupil metrics."""

    # Tunable camera and pupil detection parameters                    #
    ROI_SIZE        = 220          # Half-side of the search square (px)
    ROI_MARGIN      = 20           # Pixel border ignored when locating darkest point
    DARK_STEP       = 10           # Stride for darkest-point scan (speed vs precision)
    DARK_PATCH      = 20           # Patch size summed when scoring darkness
    THRESH_OFFSETS  = [5, 15, 25, 40]  # Added to darkest pixel value
    DILATE_KERNEL   = 5            # Morphological dilation kernel size
    DILATE_ITERS    = 2
    AREA_MIN        = 400          # Minimum contour area (px²)
    AREA_MAX        = 27_000       # Maximum contour area (px²)
    ASPECT_MIN      = 0.20         # Minimum minor/major axis ratio (flatness gate)
    OVERLAP_MIN     = 0.45         # Minimum ellipse border coverage ratio

    @staticmethod
    def _find_darkest_point(grey_frame: np.ndarray) -> tuple[int, int]:
        """Find the darkest patch in the image and return its center point."""
        margin = PupilDetector.ROI_MARGIN
        step   = PupilDetector.DARK_STEP
        patch  = PupilDetector.DARK_PATCH
        h, w   = grey_frame.shape

        min_sum  = float('inf')
        best_pt  = (w // 2, h // 2)        # sensible default

        for y in range(margin, h - margin - patch, step):
            for x in range(margin, w - margin - patch, step):
                s = int(grey_frame[y:y + patch, x:x + patch].sum())
                if s < min_sum:
                    min_sum = s
                    best_pt = (x + patch // 2, y + patch // 2)

        return best_pt

    @staticmethod
    def _mask_roi(image: np.ndarray, center: tuple[int, int], half: int) -> np.ndarray:
        """Zero out pixels outside a square region of interest around `center`."""
        cx, cy = center
        h, w   = image.shape[:2]
        x1, y1 = max(0, cx - half), max(0, cy - half)
        x2, y2 = min(w, cx + half), min(h, cy + half)
        mask   = np.zeros_like(image)
        mask[y1:y2, x1:x2] = image[y1:y2, x1:x2]
        return mask

    @staticmethod
    def _ellipse_overlap_score(contour: np.ndarray, shape: tuple) -> float:
        """Return how well a fitted ellipse matches the contour border."""
        if len(contour) < 5:
            return 0.0

        try:
            ellipse = cv2.fitEllipse(contour)
        except cv2.error:
            return 0.0

        contour_mask  = np.zeros(shape, dtype=np.uint8)
        cv2.drawContours(contour_mask, [contour], -1, 255, 1)

        ellipse_mask  = np.zeros(shape, dtype=np.uint8)
        cv2.ellipse(ellipse_mask, ellipse, 255, 4)          # thin stroke for ratio

        overlap       = cv2.bitwise_and(contour_mask, ellipse_mask)
        total_border  = int(np.sum(contour_mask > 0))

        return float(np.sum(overlap > 0)) / total_border if total_border > 0 else 0.0

    @classmethod
    def process(cls, grey_frame: np.ndarray) -> tuple[int, float, float, float]:
        """Detect the pupil in a grayscale frame and return blink / pupil metrics."""
        h, w = grey_frame.shape

        # 1. Contrast stretch
        min_val, max_val, _, _ = cv2.minMaxLoc(grey_frame)
        if max_val == min_val:
            return 1, 0.0, 0.0, 0.0

        stretched = cv2.convertScaleAbs(
            grey_frame,
            alpha=255.0 / (max_val - min_val),
            beta=-float(min_val)
        )

        # 2. Median blur
        blurred = cv2.medianBlur(stretched, 9)

        # 3. Find the darkest region and use it as the search center.
        dark_pt     = cls._find_darkest_point(blurred)
        dark_value  = int(blurred[dark_pt[1], dark_pt[0]])

        # 4. Try several thresholds around the darkest pixel value.
        kernel       = np.ones((cls.DILATE_KERNEL, cls.DILATE_KERNEL), np.uint8)
        best_contour = None
        best_score   = 0.0
        best_area    = 0.0

        for offset in cls.THRESH_OFFSETS:
            thresh_val = min(dark_value + offset, 254)

            _, binary = cv2.threshold(
                blurred, thresh_val, 255, cv2.THRESH_BINARY_INV
            )

            # Mask to ROI around the darkest region
            binary = cls._mask_roi(binary, dark_pt, cls.ROI_SIZE // 2)

            # Morphological dilation bridges eyelash-induced gaps
            dilated   = cv2.dilate(binary, kernel, iterations=cls.DILATE_ITERS)

            contours, _ = cv2.findContours(
                dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            for contour in contours:
                area = cv2.contourArea(contour)
                if not (cls.AREA_MIN <= area <= cls.AREA_MAX):
                    continue
                if len(contour) < 5:
                    continue

                coverage = cls._ellipse_overlap_score(contour, (h, w))
                if coverage < cls.OVERLAP_MIN:
                    continue

                # Score rewards both a clean ellipse fit and a reasonably sized pupil
                score = coverage * area
                if score > best_score:
                    best_score   = score
                    best_contour = contour
                    best_area    = area

        if best_contour is None:
            return 1, 0.0, 0.0, 0.0

        # 5. Fit final ellipse
        try:
            (cx, cy), (minor, major), _ = cv2.fitEllipse(best_contour)
        except cv2.error:
            return 1, 0.0, 0.0, 0.0

        # 6. Axis-ratio sanity check (rejects eye corners and near-line shapes)
        if major == 0 or (minor / major) < cls.ASPECT_MIN:
            return 1, 0.0, 0.0, 0.0

        return 0, round(cx, 2), round(cy, 2), round(best_area, 2)


class MetricStateTracker:
    """Track blink timing, smoothed pupil size, and light level state."""

    BLINK_MIN_DURATION = 0.05   # seconds — ignore very short blinks

    def __init__(self, ema_alpha: float = 0.15):
        self.ema_alpha       = ema_alpha
        self.ema_pupil_size  = 0.0

        # IBI state
        self.last_blink_time        = time.time()
        self.effective_ibi          = 0.0
        self.is_currently_blinking  = False
        self._blink_onset: float    = 0.0   # timestamp of the blink's leading edge

        # Light intensity state
        self.sec_start_time   = time.time()
        self.intensity_accum  = 0.0
        self.frames_this_sec  = 0
        self.light_intensity  = 0.0

    def update_light(self, grey_frame: np.ndarray, current_time: float) -> float:
        """Update the 1-second average brightness and return it."""
        self.intensity_accum += float(cv2.mean(grey_frame)[0])
        self.frames_this_sec += 1

        if current_time - self.sec_start_time >= 1.0:
            self.light_intensity  = self.intensity_accum / self.frames_this_sec
            self.intensity_accum  = 0.0
            self.frames_this_sec  = 0
            self.sec_start_time   = current_time

        return round(self.light_intensity, 2)

    def update_ibi(self, blink: int, current_time: float) -> float:
        """Update blink timing and return the current inter-blink interval."""
        if blink == 1:
            if not self.is_currently_blinking:
                # Rising edge — record onset but don't commit yet
                self._blink_onset          = current_time
                self.is_currently_blinking = True
        else:
            if self.is_currently_blinking:
                # Falling edge — only commit if the blink lasted long enough
                duration = current_time - self._blink_onset
                if duration >= self.BLINK_MIN_DURATION:
                    self.effective_ibi   = self._blink_onset - self.last_blink_time
                    self.last_blink_time = self._blink_onset
            self.is_currently_blinking = False

        live_tslb        = current_time - self.last_blink_time
        effective_output = max(self.effective_ibi, live_tslb)
        return round(effective_output, 2)

    def update_ema(self, blink: int, area: float) -> float:
        """Update a smoothed pupil area value when a pupil is detected."""
        if blink == 0:
            if self.ema_pupil_size == 0.0:
                self.ema_pupil_size = area      # cold start
            else:
                self.ema_pupil_size = (
                    self.ema_alpha * area
                    + (1 - self.ema_alpha) * self.ema_pupil_size
                )
        return round(self.ema_pupil_size, 2)


class USBPupilTracker:
    """Control USB camera capture and process pupil frames."""

    def __init__(
        self,
        camera_index: int = 0,
        resolution: tuple[int, int] = (640, 480),
        fps: int = 30,
    ):
        self.camera_index = camera_index
        self.resolution   = resolution
        self.fps          = fps
        self.cap          = None
        self.frame_count  = 0

        self.detector = PupilDetector()
        self.tracker  = MetricStateTracker()

    def init_camera(self) -> bool:
        """Open and configure the USB camera for capture."""
        self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.resolution[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        self.cap.set(cv2.CAP_PROP_FPS,          self.fps)
        self.cap.set(cv2.CAP_PROP_AUTOFOCUS,    0)

        if not self.cap.isOpened():
            raise RuntimeError(
                f"Failed to open USB camera at index {self.camera_index}"
            )
        return True

    def process_frame(self) -> tuple | None:
        """Capture one frame, detect the pupil, and return metrics."""
        if self.cap is None or not self.cap.isOpened():
            return None

        ret, frame = self.cap.read()
        if not ret:
            return None

        self.frame_count += 1
        current_time = time.time()
        grey_frame   = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 1. Vision — detect pupil
        blink, cx, cy, area = PupilDetector.process(grey_frame)

        # 2. State — update temporal metrics
        light = self.tracker.update_light(grey_frame, current_time)
        ibi   = self.tracker.update_ibi(blink, current_time)
        ema   = self.tracker.update_ema(blink, area)

        return (self.frame_count, blink, cx, cy, area, ibi, ema, light)

    def end_session(self) -> None:
        """Release the camera resource."""
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def __enter__(self):
        self.init_camera()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_session()
