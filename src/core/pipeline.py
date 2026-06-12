# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "numpy>=1.26",
#     "scikit-learn>=1.4",
#     "joblib>=1.3",
# ]
# ///
"""Feature engineering, IsolationForest training, and per-second fatigue scoring."""

from __future__ import annotations

import csv
import queue
import sys
import time
from collections import deque
from typing import Any
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

ROLLING_WINDOW = 30
MIN_CALIBRATION_ROWS = 60


def _column_value(row: dict[str, str | float], *names: str) -> float:
    """Read a numeric field, accepting legacy column names from older CSV exports."""
    for name in names:
        if name in row and row[name] not in (None, ""):
            return float(row[name])
    raise KeyError(f"Row is missing any of: {names}")


def load_metric_rows(csv_path: Path | str) -> list[dict[str, float]]:
    """Load per-second metric rows from a calibration CSV."""
    rows: list[dict[str, float]] = []
    with Path(csv_path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            rows.append(
                {
                    "ibi": _column_value(raw, "ibi"),
                    "pupil_area": _column_value(
                        raw, "pupil_area", "pupil_size"
                    ),
                }
            )
    return rows


def _min_max(values: list[float]) -> tuple[float, float]:
    low = float(min(values))
    high = float(max(values))
    if high <= low:
        high = low + 1.0
    return low, high


def _normalize(value: float, low: float, high: float) -> float:
    return float(np.clip((value - low) / (high - low), 0.0, 1.0))


@dataclass
class FeatureEngineer:
    """
    Causal per-second feature builder.

    Each transform_step call only uses the current row and seconds already seen.
    Normalization bounds are frozen from calibration and reused during live inference.
    """

    ibi_low: float = 0.0
    ibi_high: float = 1.0
    pupil_low: float = 0.0
    pupil_high: float = 1.0
    _ibi_hist: deque[float] | None = None
    _pupil_hist: deque[float] | None = None
    _prev_ibi: float | None = None
    _prev_pupil: float | None = None

    def __post_init__(self) -> None:
        self.reset_stream()

    def reset_stream(self) -> None:
        """Clear rolling state before a new live session stream."""
        self._ibi_hist = deque(maxlen=ROLLING_WINDOW)
        self._pupil_hist = deque(maxlen=ROLLING_WINDOW)
        self._prev_ibi = None
        self._prev_pupil = None

    def fit_bounds(self, rows: list[dict[str, float]]) -> None:
        """Set normalization ranges from the calibration file (training only)."""
        ibis = [row["ibi"] for row in rows]
        pupils = [row["pupil_area"] for row in rows]
        self.ibi_low, self.ibi_high = _min_max(ibis)
        self.pupil_low, self.pupil_high = _min_max(pupils)
        self.reset_stream()

    def transform_step(self, ibi: float, pupil_area: float) -> np.ndarray:
        """Build one feature vector from the latest second of metrics."""
        norm_ibi = _normalize(ibi, self.ibi_low, self.ibi_high)
        norm_pupil = _normalize(pupil_area, self.pupil_low, self.pupil_high)

        ibi_delta = 0.0 if self._prev_ibi is None else ibi - self._prev_ibi
        pupil_delta = (
            0.0 if self._prev_pupil is None else pupil_area - self._prev_pupil
        )

        self._ibi_hist.append(ibi)
        self._pupil_hist.append(pupil_area)

        ibi_roll_mean = float(np.mean(self._ibi_hist))
        pupil_roll_mean = float(np.mean(self._pupil_hist))
        ibi_roll_std = (
            float(np.std(self._ibi_hist)) if len(self._ibi_hist) > 1 else 0.0
        )

        self._prev_ibi = ibi
        self._prev_pupil = pupil_area

        return np.array(
            [
                norm_ibi,
                norm_pupil,
                ibi_delta,
                pupil_delta,
                ibi_roll_mean,
                pupil_roll_mean,
                ibi_roll_std,
            ],
            dtype=np.float64,
        )

    def build_matrix(self, rows: list[dict[str, float]]) -> np.ndarray:
        """Sequentially transform an entire calibration file into a feature matrix."""
        self.reset_stream()
        return np.vstack(
            [self.transform_step(row["ibi"], row["pupil_area"]) for row in rows]
        )


@dataclass
class BlinkRateTracker:
    """Estimate blinks per minute from trailing inter-blink intervals."""

    window_seconds: int = 60

    def __post_init__(self) -> None:
        self._blink_flags: deque[int] = deque(maxlen=self.window_seconds)
        self._prev_ibi: float | None = None

    def reset(self) -> None:
        self._blink_flags.clear()
        self._prev_ibi = None

    def update(self, ibi: float) -> float:
        """
        Count blink events when IBI drops sharply, then scale to per-minute rate.

        A drop usually means a blink was just committed in the camera pipeline.
        """
        blinked = (
            self._prev_ibi is not None
            and ibi < self._prev_ibi * 0.55
            and ibi < 2.5
        )
        self._blink_flags.append(1 if blinked else 0)
        self._prev_ibi = ibi

        if not self._blink_flags:
            return 0.0

        blinks = sum(self._blink_flags)
        return round((blinks / len(self._blink_flags)) * 60.0, 1)


@dataclass
class SessionModel:
    """Trained session bundle used for live per-second scoring."""

    uid: str
    forest: IsolationForest
    engineer: FeatureEngineer
    score_lo: float
    score_hi: float
    blink_tracker: BlinkRateTracker

    def predict(self, ibi: float, pupil_area: float) -> tuple[float, float]:
        """Return fatigue score (0-10) and blink rate (per minute)."""
        features = self.engineer.transform_step(ibi, pupil_area).reshape(1, -1)
        raw = float(self.forest.score_samples(features)[0])
        fatigue = score_to_fatigue(raw, self.score_lo, self.score_hi)
        blink_rate = self.blink_tracker.update(ibi)
        return fatigue, blink_rate


def score_to_fatigue(raw_score: float, score_lo: float, score_hi: float) -> float:
    """
    Map an IsolationForest score onto 0-10.

    Lower raw scores mean more anomalous in sklearn, so larger deviation yields
    a higher fatigue number.
    """
    span = score_hi - score_lo
    if span <= 1e-9:
        return 0.0
    normalized = (score_hi - raw_score) / span
    return round(float(np.clip(normalized * 10.0, 0.0, 10.0)), 2)


def train_session_model(
    csv_path: Path | str,
    uid: str,
    model_dir: Path | str,
) -> Path:
    """
    Train an IsolationForest on calibration data and save a session model artifact.

    Returns the path to the written .joblib file.
    """
    rows = load_metric_rows(csv_path)
    if len(rows) < MIN_CALIBRATION_ROWS:
        raise ValueError(
            f"Need at least {MIN_CALIBRATION_ROWS} calibration rows, got {len(rows)}."
        )

    engineer = FeatureEngineer()
    engineer.fit_bounds(rows)
    features = engineer.build_matrix(rows)

    # Tuned for a short calibration window and a handful of features.
    sample_count = len(features)
    forest = IsolationForest(
        n_estimators=min(100, max(50, sample_count // 10)),
        max_samples=min(256, sample_count),
        contamination="auto",
        random_state=42,
        n_jobs=1,
    )
    forest.fit(features)

    calibration_scores = forest.score_samples(features)
    score_lo = float(np.percentile(calibration_scores, 5))
    score_hi = float(np.percentile(calibration_scores, 95))

    engineer.reset_stream()
    artifact = SessionModel(
        uid=uid,
        forest=forest,
        engineer=engineer,
        score_lo=score_lo,
        score_hi=score_hi,
        blink_tracker=BlinkRateTracker(),
    )

    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = model_dir / f"{uid}_{stamp}.joblib"
    joblib.dump(artifact, out_path)
    return out_path


def load_session_model(model_path: Path | str) -> SessionModel:
    """Load a session model artifact from disk."""
    artifact = joblib.load(model_path)
    if not isinstance(artifact, SessionModel):
        raise TypeError("Model file does not contain a SessionModel artifact.")
    artifact.engineer.reset_stream()
    artifact.blink_tracker.reset()
    return artifact


def ml_worker_main(
    stop_event: Any,
    pause_event: Any,
    model_path: str,
    data_queue: Any,
    result_queue: Any,
) -> None:
    """
    Child process entrypoint — score each camera row and push telemetry upstream.

    Reads per-second metric dicts from data_queue and writes fatigue results to
    result_queue for the web server to stream over WebSocket.
    """
    try:
        model = load_session_model(model_path)
    except Exception as exc:
        print(f"[ml_worker] failed to load model: {exc}", file=sys.stderr)
        return

    while not stop_event.is_set():
        if pause_event.is_set():
            time.sleep(0.05)
            continue

        try:
            row = data_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        fatigue, blink_rate = model.predict(row["ibi"], row["pupil_area"])
        result_queue.put(
            {
                "type": "telemetry",
                "second": int(row["second"]),
                "fatigue": fatigue,
                "blink_rate": blink_rate,
            }
        )
