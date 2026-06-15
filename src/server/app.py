"""FastAPI entrypoint — serves the UI and manages the session lifecycle."""

from __future__ import annotations

import csv
import multiprocessing
import queue
import re
import shutil
import sys
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# src/ must be importable when this file is executed directly.
SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.gc0308 import CALIBRATION_COLUMNS, camera_worker_main  # noqa: E402
from core.pipeline import ml_worker_main, train_session_model  # noqa: E402
from server.web_socket import handle_session_ws, session_hub  # noqa: E402

# spawn avoids fork + OpenCV issues on the Pi
MP_CTX = multiprocessing.get_context("spawn")

UI_DIR = Path(__file__).resolve().parent / "ui"
CORE_DIR = SRC_ROOT / "core"
DATA_DIR = CORE_DIR / "data"
MODEL_DIR = CORE_DIR / "model"
HISTORY_DIR = CORE_DIR / "history"

HISTORY_COLUMNS = [
    "uid",
    "session_number",
    "date",
    "start_time",
    "duration",
    "latest_fatigue_score",
    "latest_blinking_rate",
]
UID_PATTERN = re.compile(r"^[a-z0-9_]+$")
FATIGUE_MAX_SECOND_DELTA = 2.0


class SessionPhase(str, Enum):
    IDLE = "idle"
    ADJUSTING = "adjusting"
    CALIBRATING = "calibrating"
    TRAINING = "training"
    LIVE = "live"


@dataclass
class CameraWorkerHandle:
    """References to a running camera child process and its control flags."""

    process: multiprocessing.Process
    stop_event: Any
    pause_event: Any
    data_queue: Any | None = None
    relay_stop: threading.Event | None = None
    relay_thread: threading.Thread | None = None


@dataclass
class LiveWorkers:
    """Camera + ML child processes and the relay thread for a live session."""

    stop_event: Any
    pause_event: Any
    data_queue: Any
    result_queue: Any
    camera_process: multiprocessing.Process
    ml_process: multiprocessing.Process
    relay_stop: threading.Event
    relay_thread: threading.Thread


@dataclass
class RuntimeSession:
    """In-memory state for the one active session the Pi can run at a time."""

    phase: SessionPhase = SessionPhase.IDLE
    uid: str | None = None
    calibration_csv: Path | None = None
    model_path: Path | None = None
    session_started_at: datetime | None = None
    paused: bool = False
    camera_worker: CameraWorkerHandle | None = None
    live_workers: LiveWorkers | None = None
    latest_fatigue: float = 0.0
    last_valid_fatigue: float | None = None
    training_error: str | None = None
    blink_state: str = "OPEN"
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


runtime = RuntimeSession()


# --- request / response models ---


class UidRequest(BaseModel):
    uid: str = Field(min_length=1, max_length=64)


class SessionStatusResponse(BaseModel):
    phase: SessionPhase
    uid: str | None
    paused: bool
    model_ready: bool
    calibration_csv: str | None
    calibration_rows: int | None = None


class ModelStatusResponse(BaseModel):
    ready: bool
    model_path: str | None
    training_error: str | None = None


class HistoryResponse(BaseModel):
    uid: str
    total_sessions: int
    last_session: dict[str, Any] | None
    sessions: list[dict[str, Any]]


class BlinkStateResponse(BaseModel):
    state: str


class LiveTelemetryResponse(BaseModel):
    phase: SessionPhase
    fatigue: float
    elapsed: str
    paused: bool


# --- filesystem helpers ---


def ensure_storage_dirs() -> None:
    """Create transient and persistent storage folders if they are missing."""
    for directory in (DATA_DIR, MODEL_DIR, HISTORY_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def normalize_uid(uid: str) -> str:
    """Lowercase and validate usernames used in filenames and history logs."""
    cleaned = uid.strip().lower()
    if not UID_PATTERN.match(cleaned):
        raise HTTPException(status_code=400, detail="Invalid uid format.")
    return cleaned


def history_path(uid: str) -> Path:
    return HISTORY_DIR / f"{uid}.csv"


def calibration_filename(uid: str, stamp: datetime) -> str:
    return f"{uid}_{stamp.strftime('%Y%m%d')}_{stamp.strftime('%H%M%S')}.csv"


def read_history_rows(uid: str) -> list[dict[str, Any]]:
    """Load all completed sessions for a user from their persistent CSV."""
    path = history_path(uid)
    if not path.exists():
        return []

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, Any]] = []
        for row in reader:
            rows.append(
                {
                    "uid": row["uid"],
                    "session_number": int(row["session_number"]),
                    "date": row["date"],
                    "start_time": row["start_time"],
                    "duration": row["duration"],
                    "latest_fatigue_score": float(row["latest_fatigue_score"]),
                    "latest_blinking_rate": float(row["latest_blinking_rate"]),
                }
            )
        return rows


def next_session_number(uid: str) -> int:
    rows = read_history_rows(uid)
    if not rows:
        return 0
    return max(row["session_number"] for row in rows) + 1


def append_history_row(
    uid: str,
    *,
    date: str,
    start_time: str,
    duration: str,
    latest_fatigue_score: float,
    latest_blinking_rate: float,
) -> dict[str, Any]:
    """Append one session summary row and return the written record."""
    ensure_storage_dirs()
    path = history_path(uid)
    session_number = next_session_number(uid)
    row = {
        "uid": uid,
        "session_number": session_number,
        "date": date,
        "start_time": start_time,
        "duration": duration,
        "latest_fatigue_score": round(latest_fatigue_score, 2),
        "latest_blinking_rate": round(latest_blinking_rate, 2),
    }

    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    return row


def wipe_transient_storage() -> None:
    """Remove all calibration CSVs and session models after a session ends."""
    for directory in (DATA_DIR, MODEL_DIR):
        if not directory.exists():
            continue
        for item in directory.iterdir():
            if item.name == ".gitkeep":
                continue
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)


def find_session_model(uid: str) -> Path | None:
    """Return the newest joblib artifact for the current uid, if one exists."""
    if not MODEL_DIR.exists():
        return None
    matches = sorted(
        MODEL_DIR.glob(f"{uid}_*.joblib"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def create_calibration_csv(uid: str) -> Path:
    """Open a fresh calibration file with the required column headers."""
    ensure_storage_dirs()
    stamp = datetime.now()
    path = DATA_DIR / calibration_filename(uid, stamp)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CALIBRATION_COLUMNS)
        writer.writeheader()
    return path


def require_phase(*allowed: SessionPhase) -> None:
    with runtime._lock:
        if runtime.phase not in allowed:
            raise HTTPException(
                status_code=409,
                detail=f"Session is in '{runtime.phase.value}', expected one of "
                f"{[phase.value for phase in allowed]}.",
            )


def stop_camera_worker() -> None:
    """Signal the camera child to exit and wait for a clean shutdown."""
    with runtime._lock:
        handle = runtime.camera_worker
        runtime.camera_worker = None

    if handle is None:
        return

    if handle.relay_stop is not None:
        handle.relay_stop.set()
    if handle.relay_thread is not None:
        handle.relay_thread.join(timeout=3)

    handle.stop_event.set()
    handle.process.join(timeout=8)
    if handle.process.is_alive():
        handle.process.terminate()
        handle.process.join(timeout=3)


def _blink_relay(blink_queue: Any, relay_stop: threading.Event) -> None:
    """Read per-frame blink labels from the camera worker."""
    while not relay_stop.is_set():
        try:
            message = blink_queue.get(timeout=0.2)
        except queue.Empty:
            continue

        with runtime._lock:
            if runtime.phase == SessionPhase.ADJUSTING:
                runtime.blink_state = message["state"]


def start_camera_worker(*, mode: str, uid: str, calibration_csv: Path | None) -> None:
    """Spawn the camera worker in adjust, calibration, or live mode."""
    stop_camera_worker()

    stop_event = MP_CTX.Event()
    pause_event = MP_CTX.Event()
    data_queue: Any | None = None
    relay_stop: threading.Event | None = None
    relay_thread: threading.Thread | None = None

    if mode in ("live", "adjust"):
        data_queue = MP_CTX.Queue(maxsize=1 if mode == "adjust" else 64)

    if mode == "adjust":
        relay_stop = threading.Event()
        relay_thread = threading.Thread(
            target=_blink_relay,
            args=(data_queue, relay_stop),
            daemon=True,
            name="blink-relay",
        )
        relay_thread.start()

    process = MP_CTX.Process(
        target=camera_worker_main,
        kwargs={
            "stop_event": stop_event,
            "pause_event": pause_event,
            "mode": mode,
            "uid": uid,
            "calibration_csv": str(calibration_csv) if calibration_csv else None,
            "data_queue": data_queue,
        },
        name=f"camera-{mode}",
        daemon=True,
    )
    process.start()

    with runtime._lock:
        runtime.camera_worker = CameraWorkerHandle(
            process=process,
            stop_event=stop_event,
            pause_event=pause_event,
            data_queue=data_queue,
            relay_stop=relay_stop,
            relay_thread=relay_thread,
        )


def set_workers_paused(paused: bool) -> None:
    """Pause or resume camera capture and ML scoring."""
    with runtime._lock:
        live = runtime.live_workers
        camera = runtime.camera_worker

    if live is not None:
        if paused:
            live.pause_event.set()
        else:
            live.pause_event.clear()
    elif camera is not None:
        if paused:
            camera.pause_event.set()
        else:
            camera.pause_event.clear()


def _format_elapsed(started_at: datetime) -> str:
    elapsed = int((datetime.now() - started_at).total_seconds())
    hours, remainder = divmod(elapsed, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _fatigue_jump_accepted(candidate: float, previous: float | None) -> bool:
    """Reject per-second fatigue spikes larger than FATIGUE_MAX_SECOND_DELTA."""
    if previous is None:
        return True
    return abs(candidate - previous) <= FATIGUE_MAX_SECOND_DELTA


def build_live_telemetry_payload() -> dict[str, Any] | None:
    """Build the latest live-session telemetry snapshot for HTTP/WS clients."""
    with runtime._lock:
        if runtime.phase != SessionPhase.LIVE:
            return None
        started_at = runtime.session_started_at
        return {
            "type": "telemetry",
            "fatigue": float(runtime.latest_fatigue),
            "elapsed": _format_elapsed(started_at) if started_at else "00:00:00",
        }


def _telemetry_relay(result_queue: Any, relay_stop: threading.Event) -> None:
    """Read ML results and push them to WebSocket clients."""
    while not relay_stop.is_set():
        try:
            message = result_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        publish = False
        outbound: dict[str, Any] = {}

        with runtime._lock:
            if runtime.phase != SessionPhase.LIVE:
                continue

            candidate = float(message["fatigue"])
            started_at = runtime.session_started_at

            if _fatigue_jump_accepted(candidate, runtime.last_valid_fatigue):
                runtime.last_valid_fatigue = candidate
                runtime.latest_fatigue = candidate
                outbound = {
                    "type": "telemetry",
                    "second": int(message.get("second", 0)),
                    "fatigue": candidate,
                }
                publish = True

        if not publish:
            continue

        if started_at is not None:
            outbound["elapsed"] = _format_elapsed(started_at)

        session_hub.publish(outbound)


def stop_live_workers() -> None:
    """Stop the camera + ML processes and the telemetry relay thread."""
    with runtime._lock:
        live = runtime.live_workers
        runtime.live_workers = None

    if live is None:
        return

    live.relay_stop.set()
    live.stop_event.set()

    live.camera_process.join(timeout=8)
    live.ml_process.join(timeout=8)

    if live.camera_process.is_alive():
        live.camera_process.terminate()
        live.camera_process.join(timeout=3)
    if live.ml_process.is_alive():
        live.ml_process.terminate()
        live.ml_process.join(timeout=3)

    live.relay_thread.join(timeout=3)


def start_live_workers(uid: str, model_path: Path) -> None:
    """Spawn camera and ML workers for real-time session monitoring."""
    stop_live_workers()
    stop_camera_worker()

    stop_event = MP_CTX.Event()
    pause_event = MP_CTX.Event()
    data_queue = MP_CTX.Queue(maxsize=64)
    result_queue = MP_CTX.Queue(maxsize=64)

    camera_process = MP_CTX.Process(
        target=camera_worker_main,
        kwargs={
            "stop_event": stop_event,
            "pause_event": pause_event,
            "mode": "live",
            "uid": uid,
            "calibration_csv": None,
            "data_queue": data_queue,
        },
        name="camera-live",
        daemon=True,
    )
    ml_process = MP_CTX.Process(
        target=ml_worker_main,
        kwargs={
            "stop_event": stop_event,
            "pause_event": pause_event,
            "model_path": str(model_path),
            "data_queue": data_queue,
            "result_queue": result_queue,
        },
        name="ml-live",
        daemon=True,
    )

    relay_stop = threading.Event()
    relay_thread = threading.Thread(
        target=_telemetry_relay,
        args=(result_queue, relay_stop),
        daemon=True,
        name="telemetry-relay",
    )

    camera_process.start()
    ml_process.start()
    relay_thread.start()

    with runtime._lock:
        runtime.live_workers = LiveWorkers(
            stop_event=stop_event,
            pause_event=pause_event,
            data_queue=data_queue,
            result_queue=result_queue,
            camera_process=camera_process,
            ml_process=ml_process,
            relay_stop=relay_stop,
            relay_thread=relay_thread,
        )


def start_model_training(csv_path: Path, uid: str) -> None:
    """Train the session model in a background thread while loading.html polls."""

    def _run_training() -> None:
        try:
            path = train_session_model(csv_path, uid, MODEL_DIR)
            with runtime._lock:
                runtime.model_path = path
                runtime.training_error = None
        except Exception as exc:
            with runtime._lock:
                runtime.training_error = str(exc)
            print(f"[training] failed: {exc}", file=sys.stderr)

    threading.Thread(
        target=_run_training,
        daemon=True,
        name="model-training",
    ).start()


def calibration_row_count() -> int:
    """Return how many data rows exist in the active calibration CSV."""
    with runtime._lock:
        path = runtime.calibration_csv
    if path is None or not path.exists():
        return 0

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return sum(1 for _ in reader)


# --- FastAPI app ---


@asynccontextmanager
async def lifespan(_: FastAPI):
    import asyncio

    session_hub.bind_loop(asyncio.get_running_loop())
    ensure_storage_dirs()
    yield
    stop_live_workers()
    stop_camera_worker()


app = FastAPI(title="Eye Fatigue Tracker", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/session/status", response_model=SessionStatusResponse)
def session_status() -> SessionStatusResponse:
    with runtime._lock:
        phase = runtime.phase
        uid = runtime.uid
        paused = runtime.paused
        calibration_csv = runtime.calibration_csv
        model_path = runtime.model_path
        if uid and (model_path is None or not model_path.exists()):
            model_path = find_session_model(uid)
        model_ready = model_path is not None and model_path.exists()

    cal_rows = calibration_row_count() if phase == SessionPhase.CALIBRATING else None

    return SessionStatusResponse(
        phase=phase,
        uid=uid,
        paused=paused,
        model_ready=model_ready,
        calibration_csv=str(calibration_csv) if calibration_csv else None,
        calibration_rows=cal_rows,
    )


@app.post("/api/session/start-adjust")
def start_adjust(body: UidRequest) -> dict[str, str]:
    """Open the camera for live blink-state preview before calibration."""
    uid = normalize_uid(body.uid)

    with runtime._lock:
        if runtime.phase != SessionPhase.IDLE:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot start adjust while phase is '{runtime.phase.value}'.",
            )
        runtime.uid = uid
        runtime.blink_state = "OPEN"
        runtime.phase = SessionPhase.ADJUSTING

    start_camera_worker(mode="adjust", uid=uid, calibration_csv=None)
    return {"phase": SessionPhase.ADJUSTING.value}


@app.post("/api/session/stop-adjust")
def stop_adjust() -> dict[str, str]:
    """Stop the camera preview and return to idle."""
    require_phase(SessionPhase.ADJUSTING)

    stop_camera_worker()

    with runtime._lock:
        runtime.phase = SessionPhase.IDLE
        runtime.uid = None
        runtime.blink_state = "OPEN"

    return {"phase": SessionPhase.IDLE.value}


@app.get("/api/session/blink-state", response_model=BlinkStateResponse)
def blink_state() -> BlinkStateResponse:
    with runtime._lock:
        return BlinkStateResponse(state=runtime.blink_state)


@app.post("/api/session/start-calibration")
def start_calibration(body: UidRequest) -> dict[str, Any]:
    uid = normalize_uid(body.uid)

    with runtime._lock:
        if runtime.phase != SessionPhase.IDLE:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot start calibration while phase is '{runtime.phase.value}'.",
            )

        runtime.uid = uid
        runtime.calibration_csv = create_calibration_csv(uid)
        runtime.model_path = None
        runtime.session_started_at = None
        runtime.paused = False
        runtime.latest_fatigue = 0.0
        runtime.phase = SessionPhase.CALIBRATING
        calibration_csv = runtime.calibration_csv

    start_camera_worker(mode="calibration", uid=uid, calibration_csv=calibration_csv)

    return {
        "phase": SessionPhase.CALIBRATING.value,
        "uid": uid,
        "calibration_csv": str(calibration_csv),
        "duration_seconds": 300,
    }


@app.post("/api/session/end-calibration")
def end_calibration() -> dict[str, Any]:
    """Finish calibration and move on to model training."""
    require_phase(SessionPhase.CALIBRATING)

    stop_camera_worker()
    rows_collected = calibration_row_count()

    with runtime._lock:
        csv_path = runtime.calibration_csv
        uid = runtime.uid
        runtime.phase = SessionPhase.TRAINING
        runtime.model_path = None
        runtime.training_error = None

    if csv_path is None or uid is None:
        raise HTTPException(status_code=500, detail="Calibration metadata missing.")

    start_model_training(csv_path, uid)

    return {
        "phase": SessionPhase.TRAINING.value,
        "rows_collected": rows_collected,
    }


@app.post("/api/session/cancel-calibration")
def cancel_calibration() -> dict[str, str]:
    """Abort an in-progress calibration and return to idle (early exit to dashboard)."""
    require_phase(SessionPhase.CALIBRATING)

    stop_camera_worker()

    with runtime._lock:
        partial_csv = runtime.calibration_csv
        runtime.phase = SessionPhase.IDLE
        runtime.uid = None
        runtime.calibration_csv = None

    if partial_csv is not None and partial_csv.exists():
        partial_csv.unlink()

    return {"phase": SessionPhase.IDLE.value}


@app.get("/api/session/model-status", response_model=ModelStatusResponse)
def model_status() -> ModelStatusResponse:
    with runtime._lock:
        if runtime.uid is None:
            return ModelStatusResponse(ready=False, model_path=None)

        training_error = runtime.training_error
        model_path = runtime.model_path or find_session_model(runtime.uid)
        if model_path is not None and model_path.exists():
            runtime.model_path = model_path
            return ModelStatusResponse(
                ready=True,
                model_path=str(model_path),
                training_error=None,
            )

        return ModelStatusResponse(
            ready=False,
            model_path=None,
            training_error=training_error,
        )


@app.post("/api/session/start-live")
def start_live() -> dict[str, str]:
    require_phase(SessionPhase.TRAINING)

    with runtime._lock:
        uid = runtime.uid
        model_path = runtime.model_path or (
            find_session_model(uid) if uid else None
        )
        if uid is None:
            raise HTTPException(status_code=500, detail="Session uid missing.")
        if model_path is None or not model_path.exists():
            raise HTTPException(status_code=409, detail="Session model is not ready.")

        runtime.model_path = model_path
        runtime.session_started_at = datetime.now()
        runtime.paused = False
        runtime.latest_fatigue = 0.0
        runtime.last_valid_fatigue = None
        runtime.phase = SessionPhase.LIVE

    start_live_workers(uid, model_path)
    return {"phase": SessionPhase.LIVE.value}


@app.get("/api/session/live-telemetry", response_model=LiveTelemetryResponse)
def live_telemetry() -> LiveTelemetryResponse:
    """Return the latest live metrics for session UI polling and reconnects."""
    with runtime._lock:
        if runtime.phase != SessionPhase.LIVE:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot read telemetry while phase is '{runtime.phase.value}'.",
            )
        started_at = runtime.session_started_at
        return LiveTelemetryResponse(
            phase=runtime.phase,
            fatigue=float(runtime.latest_fatigue),
            elapsed=_format_elapsed(started_at) if started_at else "00:00:00",
            paused=runtime.paused,
        )


@app.post("/api/session/pause")
def pause_session() -> dict[str, bool]:
    require_phase(SessionPhase.LIVE)

    with runtime._lock:
        runtime.paused = True

    set_workers_paused(True)
    return {"paused": True}


@app.post("/api/session/resume")
def resume_session() -> dict[str, bool]:
    require_phase(SessionPhase.LIVE)

    with runtime._lock:
        runtime.paused = False

    set_workers_paused(False)
    return {"paused": False}


@app.post("/api/session/end")
def end_session() -> dict[str, Any]:
    require_phase(SessionPhase.LIVE)

    with runtime._lock:
        uid = runtime.uid
        if uid is None or runtime.session_started_at is None:
            raise HTTPException(status_code=500, detail="Live session metadata missing.")

        ended_at = datetime.now()
        elapsed = ended_at - runtime.session_started_at
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        duration = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        row = append_history_row(
            uid,
            date=ended_at.strftime("%d/%m/%Y"),
            start_time=runtime.session_started_at.strftime("%H:%M:%S"),
            duration=duration,
            latest_fatigue_score=runtime.latest_fatigue,
            latest_blinking_rate=0.0,
        )

    stop_live_workers()

    with runtime._lock:
        runtime.phase = SessionPhase.IDLE
        runtime.uid = None
        runtime.calibration_csv = None
        runtime.model_path = None
        runtime.session_started_at = None
        runtime.paused = False

    wipe_transient_storage()
    return {"phase": SessionPhase.IDLE.value, "history_row": row}


@app.get("/api/history/{uid}", response_model=HistoryResponse)
def get_history(uid: str) -> HistoryResponse:
    normalized = normalize_uid(uid)
    sessions = read_history_rows(normalized)
    last_session = sessions[-1] if sessions else None
    return HistoryResponse(
        uid=normalized,
        total_sessions=len(sessions),
        last_session=last_session,
        sessions=sessions,
    )


@app.websocket("/ws/session")
async def session_websocket(websocket):
    await handle_session_ws(websocket)


# Static UI — register API routes above this mount.
app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
