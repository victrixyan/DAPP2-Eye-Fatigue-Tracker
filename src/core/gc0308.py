# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "numpy>=1.26",
#     "opencv-python-headless>=4.8",
# ]
# ///
"""USB camera capture and per-second pupil / blink metrics for the ML pipeline."""

from __future__ import annotations

import csv
import sys
import time
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

CALIBRATION_COLUMNS = ["uid", "second", "ibi", "pupil_area"]


class PupilDetector:
    """Detect the pupil from a grayscale IR image and return pupil metrics."""

    # Tunable camera and pupil detection parameters                    #
    ROI_SIZE         = 220          # Half-side of the search square (px)
    ROI_MARGIN       = 20           # Pixel border ignored when locating darkest point
    DARK_STEP        = 10           # Stride for darkest-point scan (speed vs precision)
    DARK_PATCH       = 20           # Patch size summed when scoring darkness
    TRACK_WINDOW     = 80           # Local search radius when reusing last pupil center
    CLAHE_CLIP       = 2.0          # CLAHE contrast clip limit
    CLAHE_TILE       = (8, 8)       # CLAHE local tile grid
    ADAPTIVE_BLOCK   = 31           # Adaptive threshold block size (must be odd)
    ADAPTIVE_C       = [2, 5, 8, 11]  # Constant subtracted from local mean
    DILATE_KERNEL    = 5            # Morphological kernel size
    DILATE_ITERS     = 2
    AREA_MIN         = 400          # Minimum contour area (px²)
    AREA_MAX         = 27_000       # Maximum contour area (px²)
    ASPECT_MIN       = 0.4          # Minimum minor/major axis ratio (flatness gate)
    OVERLAP_MIN      = 0.5          # Minimum ellipse border coverage ratio
    CIRCULARITY_MIN  = 0.25         # Rejects jagged eyelash blobs
    SOLIDITY_MIN     = 0.75         # Rejects concave / fragmented shapes
    CENTER_MAX_DIST  = 70           # Max px between seed point and contour centroid

    def __init__(self):
        self._last_center: tuple[float, float] | None = None

    @staticmethod
    def _circularity(contour: np.ndarray) -> float:
        area = cv2.contourArea(contour)
        perimeter = cv2.arcLength(contour, True)
        if perimeter == 0:
            return 0.0
        return (4 * math.pi * area) / (perimeter ** 2)

    @staticmethod
    def _solidity(contour: np.ndarray) -> float:
        area = cv2.contourArea(contour)
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        return float(area / hull_area) if hull_area > 0 else 0.0

    @staticmethod
    def _ellipse_area(minor: float, major: float) -> float:
        """Area of the fitted ellipse from its axis lengths."""
        return math.pi * (minor / 2) * (major / 2)

    @classmethod
    def _apply_clahe(cls, grey_frame: np.ndarray) -> np.ndarray:
        """Apply CLAHE to handle uneven IR illumination locally."""
        clahe = cv2.createCLAHE(clipLimit=cls.CLAHE_CLIP, tileGridSize=cls.CLAHE_TILE)
        return clahe.apply(grey_frame.astype(np.uint8))

    @classmethod
    def _find_darkest_point(
        cls,
        grey_frame: np.ndarray,
        hint: tuple[float, float] | None = None,
    ) -> tuple[int, int]:
        """Find the darkest patch, preferring a local window around `hint`."""
        margin = cls.ROI_MARGIN
        step   = cls.DARK_STEP
        patch  = cls.DARK_PATCH
        h, w   = grey_frame.shape

        min_sum = float('inf')
        best_pt = (int(hint[0]), int(hint[1])) if hint else (w // 2, h // 2)

        if hint is not None:
            hx, hy = int(hint[0]), int(hint[1])
            x1 = max(margin, hx - cls.TRACK_WINDOW)
            y1 = max(margin, hy - cls.TRACK_WINDOW)
            x2 = min(w - margin - patch, hx + cls.TRACK_WINDOW)
            y2 = min(h - margin - patch, hy + cls.TRACK_WINDOW)
        else:
            x1, y1, x2, y2 = margin, margin, w - margin - patch, h - margin - patch

        for y in range(y1, y2, step):
            for x in range(x1, x2, step):
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

    def process(self, grey_frame: np.ndarray) -> tuple[int, float]:
        """Detect the pupil in a grayscale frame and return blink state and area."""
        h, w = grey_frame.shape

        # 1. CLAHE — local contrast enhancement for uneven IR illumination
        min_val, max_val, _, _ = cv2.minMaxLoc(grey_frame)
        if max_val == min_val:
            return 1, 0.0

        enhanced = self._apply_clahe(grey_frame)

        # 2. Median blur
        blurred = cv2.medianBlur(enhanced, 9)

        # 3. Seed search from last pupil center when available.
        dark_pt = self._find_darkest_point(blurred, self._last_center)

        # 4. Try several adaptive-threshold constants for local brightness drift.
        kernel       = np.ones((self.DILATE_KERNEL, self.DILATE_KERNEL), np.uint8)
        best_contour = None
        best_score   = 0.0
        best_area    = 0.0

        for c_val in self.ADAPTIVE_C:
            binary = cv2.adaptiveThreshold(
                blurred,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV,
                self.ADAPTIVE_BLOCK,
                c_val,
            )

            # Mask to ROI around the darkest region
            binary = self._mask_roi(binary, dark_pt, self.ROI_SIZE // 2)

            # Close small eyelash gaps, then dilate to connect the pupil border
            closed  = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
            dilated = cv2.dilate(closed, kernel, iterations=self.DILATE_ITERS)

            contours, _ = cv2.findContours(
                dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            for contour in contours:
                if len(contour) < 5:
                    continue

                try:
                    (_, _), (minor, major), _ = cv2.fitEllipse(contour)
                except cv2.error:
                    continue

                if major == 0 or (minor / major) < self.ASPECT_MIN:
                    continue

                ellipse_area = self._ellipse_area(minor, major)
                if not (self.AREA_MIN <= ellipse_area <= self.AREA_MAX):
                    continue

                circularity = self._circularity(contour)
                if circularity < self.CIRCULARITY_MIN:
                    continue

                solidity = self._solidity(contour)
                if solidity < self.SOLIDITY_MIN:
                    continue

                moments = cv2.moments(contour)
                if moments["m00"] == 0:
                    continue
                cx = moments["m10"] / moments["m00"]
                cy = moments["m01"] / moments["m00"]
                center_dist = math.hypot(cx - dark_pt[0], cy - dark_pt[1])
                if center_dist > self.CENTER_MAX_DIST:
                    continue

                coverage = self._ellipse_overlap_score(contour, (h, w))
                if coverage < self.OVERLAP_MIN:
                    continue

                proximity = 1.0 - min(center_dist / self.CENTER_MAX_DIST, 1.0)
                score = (
                    coverage * circularity * solidity
                    * math.sqrt(ellipse_area) * (0.5 + 0.5 * proximity)
                )
                if score > best_score:
                    best_score   = score
                    best_contour = contour
                    best_area    = ellipse_area

        if best_contour is None:
            self._last_center = None
            return 1, 0.0

        # 5. Fit final ellipse
        try:
            (cx, cy), (minor, major), _ = cv2.fitEllipse(best_contour)
        except cv2.error:
            self._last_center = None
            return 1, 0.0

        # 6. Axis-ratio sanity check (rejects eye corners and near-line shapes)
        if major == 0 or (minor / major) < self.ASPECT_MIN:
            self._last_center = None
            return 1, 0.0

        self._last_center = (cx, cy)
        pupil_area = self._ellipse_area(minor, major)
        return 0, round(pupil_area, 2)


class MetricStateTracker:
    """Aggregate frame-rate pupil metrics into per-second feature rows."""

    BLINK_MIN_DURATION = 0.05   # seconds — ignore very short blinks

    def __init__(self):
        self._session_start = time.time()
        self._current_second = 0

        self._pupil_samples: list[float] = []

        self._last_blink_time = self._session_start
        self._committed_ibi = 0.0
        self._is_blinking = False
        self._blink_onset = 0.0
        self._ibi_at_second_end = 0.0

    def _effective_ibi(self, now: float) -> float:
        live = now - self._last_blink_time
        return max(self._committed_ibi, live)

    def _update_blink_state(self, blink: int, now: float) -> None:
        if blink == 1:
            if not self._is_blinking:
                self._blink_onset = now
                self._is_blinking = True
        else:
            if self._is_blinking:
                if now - self._blink_onset >= self.BLINK_MIN_DURATION:
                    self._committed_ibi = self._blink_onset - self._last_blink_time
                    self._last_blink_time = self._blink_onset
            self._is_blinking = False

        self._ibi_at_second_end = self._effective_ibi(now)

    def _pupil_size_for_second(self) -> float:
        if not self._pupil_samples:
            return 0.0
        return float(np.median(self._pupil_samples))

    def _finalize_second(self, second_index: int) -> tuple[int, float, float]:
        """Emit one per-second row: (second, ibi_seconds, pupil_area_px2)."""
        return (
            second_index + 1,
            round(self._ibi_at_second_end, 2),
            round(self._pupil_size_for_second(), 2),
        )

    def update_frame(
        self, blink: int, area: float, now: float | None = None
    ) -> tuple[int, float, float] | None:
        """Ingest one frame; return a feature row when a full second has elapsed."""
        now = now if now is not None else time.time()
        elapsed_sec = int(now - self._session_start)

        self._update_blink_state(blink, now)

        if blink == 0 and area > 0.0:
            self._pupil_samples.append(area)

        if elapsed_sec <= self._current_second:
            return None

        result = None
        while self._current_second < elapsed_sec:
            result = self._finalize_second(self._current_second)
            self._current_second += 1
            self._pupil_samples = []

        if blink == 0 and area > 0.0:
            self._pupil_samples.append(area)

        return result


class USBPupilTracker:
    """Capture frames and emit per-second feature rows for downstream ML."""

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

        self.detector = PupilDetector()
        self.tracker  = MetricStateTracker()

    def init_camera(self) -> bool:
        """Open and configure the USB camera for capture."""
        if sys.platform == "linux":
            self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_V4L2)
        else:
            self.cap = cv2.VideoCapture(self.camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.resolution[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        self.cap.set(cv2.CAP_PROP_FPS,          self.fps)
        self.cap.set(cv2.CAP_PROP_AUTOFOCUS,    0)

        if not self.cap.isOpened():
            raise RuntimeError(
                f"Failed to open USB camera at index {self.camera_index}"
            )
        return True

    def process_frame(self) -> tuple[int, float, float] | None:
        """Capture one frame; return (second, ibi_sec, pupil_area_px2) once per second."""
        if self.cap is None or not self.cap.isOpened():
            return None

        ret, frame = self.cap.read()
        if not ret:
            return None

        grey_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blink, area = self.detector.process(grey_frame)
        return self.tracker.update_frame(blink, area, time.time())

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


def append_calibration_row(
    csv_path: Path | str,
    uid: str,
    second: int,
    ibi: float,
    pupil_area: float,
) -> None:
    """Append one per-second calibration row to the session CSV."""
    with Path(csv_path).open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CALIBRATION_COLUMNS)
        writer.writerow(
            {
                "uid": uid,
                "second": second,
                "ibi": ibi,
                "pupil_area": pupil_area,
            }
        )


def camera_worker_main(
    stop_event: Any,
    pause_event: Any,
    mode: str,
    uid: str,
    calibration_csv: str | None,
    data_queue: Any | None,
    camera_index: int = 0,
) -> None:
    """
    Child process entrypoint — capture frames and emit one row per second.

    calibration mode: append rows to calibration_csv
    live mode: push dict rows onto data_queue for the ML worker (Phase 4)
    """
    tracker = USBPupilTracker(camera_index=camera_index)

    try:
        tracker.init_camera()
    except RuntimeError as exc:
        print(f"[camera_worker] failed to open camera: {exc}", file=sys.stderr)
        return

    try:
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            row = tracker.process_frame()
            if row is None:
                continue

            second, ibi, pupil_area = row

            if mode == "calibration":
                if calibration_csv is None:
                    continue
                append_calibration_row(calibration_csv, uid, second, ibi, pupil_area)
            elif mode == "live" and data_queue is not None:
                data_queue.put(
                    {
                        "uid": uid,
                        "second": second,
                        "ibi": ibi,
                        "pupil_area": pupil_area,
                    }
                )
    finally:
        tracker.end_session()