# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "matplotlib>=3.8",
#     "numpy>=1.26",
#     "scikit-learn>=1.4",
#     "joblib>=1.3",
# ]
# ///
"""Build a 3D fatigue-score scatter plot from calibration and test CSVs."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import colors as mcolors
from matplotlib.colors import LinearSegmentedColormap
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.pipeline import load_metric_rows, load_session_model, train_session_model


DATA_DIR = Path(__file__).resolve().parent
CALIBRATION_CSV = DATA_DIR / "edb_calibration_20260605_201339.csv"
TEST_CSV = DATA_DIR / "edb_test_20260605_202359.csv"
OUTPUT_PDF = DATA_DIR / "fatigue_score_3d.pdf"

# Reserve fatigue 10 for only the most anomalous tail of the plotted session.
FATIGUE_TAIL_PERCENTILE = 1.0


def score_rows(
    model,
    rows: list[dict[str, float]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return pupil area, IBI, and raw IsolationForest scores for a metric stream."""
    model.engineer.reset_stream()

    pupils: list[float] = []
    ibis: list[float] = []
    raw_scores: list[float] = []

    for row in rows:
        pupils.append(row["pupil_area"])
        ibis.append(row["ibi"])
        features = model.engineer.transform_step(
            row["ibi"], row["pupil_area"]
        ).reshape(1, -1)
        raw_scores.append(float(model.forest.score_samples(features)[0]))

    return (
        np.asarray(pupils, dtype=float),
        np.asarray(ibis, dtype=float),
        np.asarray(raw_scores, dtype=float),
    )


def remap_fatigue_for_plot(
    raw_scores: np.ndarray,
    rested_raw: float,
    tail_percentile: float = FATIGUE_TAIL_PERCENTILE,
) -> np.ndarray:
    """
    Spread fatigue across 0-10 without saturating the plot at the maximum.

    Calibration defines the rested baseline. Only the most anomalous tail of
    the plotted session is allowed to reach 10.
    """
    extreme_raw = float(np.percentile(raw_scores, tail_percentile))
    span = rested_raw - extreme_raw
    if span <= 1e-9:
        return np.zeros_like(raw_scores)

    normalized = (rested_raw - raw_scores) / span
    return np.round(np.clip(normalized * 10.0, 0.0, 10.0), 2)


def fatigue_colormap() -> LinearSegmentedColormap:
    """Light peach at low fatigue, dark red at high fatigue."""
    return LinearSegmentedColormap.from_list(
        "fatigue_reds",
        ["#fdbb84", "#fc8d59", "#ef6548", "#d7301f", "#7f0000"],
        N=256,
    )


def plot_fatigue_surface(
    pupil: np.ndarray,
    ibi: np.ndarray,
    fatigue: np.ndarray,
    output_path: Path,
) -> None:
    cmap = fatigue_colormap()
    norm = mcolors.Normalize(vmin=0.0, vmax=10.0)
    colors = cmap(norm(fatigue))

    fig = plt.figure(figsize=(9, 7), dpi=150)
    ax = fig.add_subplot(111, projection="3d")

    ax.scatter(
        pupil,
        ibi,
        np.zeros_like(fatigue),
        c="#e0e0e0",
        s=10,
        alpha=0.18,
        depthshade=False,
        edgecolors="none",
    )

    ax.scatter(
        pupil,
        ibi,
        fatigue,
        c=colors,
        s=36,
        alpha=0.9,
        depthshade=False,
        edgecolors="#4a4a4a",
        linewidths=0.25,
    )

    ax.set_xlabel("Pupil Area (px²)", labelpad=10)
    ax.set_ylabel("Inter-blink Interval (s)", labelpad=10)
    ax.set_zlabel("Fatigue Score", labelpad=10)

    pupil_pad = max(250.0, (pupil.max() - pupil.min()) * 0.05)
    ibi_pad = max(0.5, (ibi.max() - ibi.min()) * 0.05)
    ax.set_xlim(0.0, pupil.max() + pupil_pad)
    ax.set_ylim(0.0, ibi.max() + ibi_pad)
    ax.set_zlim(0.0, 10.0)

    ax.set_box_aspect((1.0, 1.0, 0.75))
    ax.view_init(elev=24, azim=-58)
    ax.grid(True, color="#e6e6e6", linewidth=0.6)
    ax.xaxis.pane.fill = False
    ax.yaxis.pane.fill = False
    ax.zaxis.pane.fill = False

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, shrink=0.62, pad=0.08)
    cbar.set_label("Fatigue Score")

    fig.tight_layout()
    fig.savefig(output_path, format="pdf", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    if not CALIBRATION_CSV.exists():
        raise FileNotFoundError(f"Missing calibration CSV: {CALIBRATION_CSV}")
    if not TEST_CSV.exists():
        raise FileNotFoundError(f"Missing test CSV: {TEST_CSV}")

    with tempfile.TemporaryDirectory() as tmp:
        model_path = train_session_model(
            CALIBRATION_CSV,
            uid="edb",
            model_dir=Path(tmp),
        )
        model = load_session_model(model_path)

    cal_rows = load_metric_rows(CALIBRATION_CSV)
    test_rows = load_metric_rows(TEST_CSV)

    cal_pupil, cal_ibi, cal_raw = score_rows(model, cal_rows)
    test_pupil, test_ibi, test_raw = score_rows(model, test_rows)

    rested_raw = model.score_hi
    cal_fatigue = remap_fatigue_for_plot(cal_raw, rested_raw)
    test_fatigue = remap_fatigue_for_plot(test_raw, rested_raw)

    pupil = np.concatenate([cal_pupil, test_pupil])
    ibi = np.concatenate([cal_ibi, test_ibi])
    fatigue = np.concatenate([cal_fatigue, test_fatigue])

    plot_fatigue_surface(pupil, ibi, fatigue, OUTPUT_PDF)
    print(f"Saved {OUTPUT_PDF}")
    print(f"Points: {len(pupil)} (calibration={len(cal_pupil)}, test={len(test_pupil)})")
    print(
        "Ranges — pupil area: "
        f"{pupil.min():.1f}–{pupil.max():.1f} px², "
        f"IBI: {ibi.min():.2f}–{ibi.max():.2f} s, "
        f"fatigue: {fatigue.min():.2f}–{fatigue.max():.2f}"
    )
    for label, scores in (("all", fatigue), ("test", test_fatigue)):
        at_max = int(np.sum(scores >= 9.95))
        high = int(np.sum(scores >= 8.0))
        print(
            f"Fatigue distribution ({label}): "
            f"mean={scores.mean():.2f}, "
            f">=8: {high} ({100 * high / len(scores):.1f}%), "
            f"~10: {at_max} ({100 * at_max / len(scores):.1f}%)"
        )


if __name__ == "__main__":
    main()
