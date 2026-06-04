#accelerated point update
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from sklearn.ensemble import IsolationForest
import time
from scipy.stats import gaussian_kde
plt.ion()
# Parameters
def generate_eye_data(num_samples, seed=42):
    """Generates a DataFrame with realistic synthetic data for pupil size

    and average blink rate.
    """
    # Set seed for reproducibility
    np.random.seed(seed)

    pupil_size_mm = np.random.normal(loc=4.5, scale=1.0, size=num_samples)
    pupil_size_mm = np.clip(pupil_size_mm, 2.0, 8.0)


    blink_interval_s = np.random.normal(loc=4.5, scale=1.5, size=num_samples)
    blink_intervals_s = np.clip(blink_interval_s, 1, 8)

    pupil_size_mm = np.round(pupil_size_mm, 2)
    blink_intervals_s = np.round(blink_intervals_s, 1)
    return np.column_stack((pupil_size_mm, blink_intervals_s))


eye_data_df = generate_eye_data(num_samples=200, seed=42)
n_estimators = 100 # Number of trees

sample_size = 64  # Number of samples used to train each tree
iso_forest = IsolationForest(n_estimators=n_estimators,
                            contamination="auto",
                            max_samples=sample_size,
                            random_state=42)
iso_forest.fit(eye_data_df)
t=1
t1=1
fig, ax = plt.subplots(num="Anomaly Detection")
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
training_points = ax.scatter(eye_data_df[:, 0], eye_data_df[:, 1], c="gainsboro", label="Training Data", alpha=0.6,marker="o")
new_point = ax.scatter([], [], c=[], cmap="Reds", vmin=0, vmax=2,
                       marker="o", s=50, label="New Data Point")

points_x, points_y, scores = [], [], []
np.random.seed(32)
for i in range(200):
    pupil_size_mm = np.clip(np.random.normal(4.5, 1.0), 2.0, 8.0)*t1
    blink_intervals_s = np.clip(np.random.normal(4.5, 1.5), 1, 8) * t

    score = (iso_forest.decision_function([[pupil_size_mm, blink_intervals_s]])[0] * -1) + 1

    points_x.append(pupil_size_mm)
    points_y.append(blink_intervals_s)
    scores.append(score)

    new_point.set_offsets(np.column_stack((points_x, points_y)))
    new_point.set_array(np.array(scores))

    fig.canvas.flush_events()
    plt.pause(0.1)
    t += 0.0025
    t1-=0.0025
