#density plot for the data points
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


    blink_rate_bpm = np.random.normal(loc=16.0, scale=3.0, size=num_samples)
    blink_rate_bpm = np.clip(blink_rate_bpm, 8, 28)

    pupil_size_mm = np.round(pupil_size_mm, 2)
    blink_rate_bpm = np.round(blink_rate_bpm, 1)
    return np.column_stack((pupil_size_mm, blink_rate_bpm))


eye_data_df = generate_eye_data(num_samples=200, seed=42)
x= eye_data_df[:, 0]
y= eye_data_df[:, 1]
n_estimators = 100 # Number of trees

sample_size = 64  # Number of samples used to train each tree
# Train Isolation Forest
iso_forest = IsolationForest(n_estimators=n_estimators,
                            contamination="auto",
                            max_samples=sample_size,
                            random_state=42)
iso_forest.fit(eye_data_df)
kde = gaussian_kde(np.vstack([x, y]))
pointdensity = kde(np.vstack([x, y]))
idx = pointdensity.argsort()
x, y, pointdensity = x[idx], y[idx], pointdensity[idx]

t = 1
fig, ax = plt.subplots(num="Anomaly Detection")
scatter=ax.scatter(x, y,c=pointdensity, cmap="viridis",s=15)
fig.colorbar(scatter, label='Density')

new_point = ax.scatter([], [], c=[], cmap="Reds", vmin=0, vmax=2,
                       marker="o", s=100, label="New Data Point")

points_x, points_y, scores = [], [], []

for i in range(200):
    pupil_size_mm = np.clip(np.random.normal(4.5, 1.0), 2.0, 8.0)
    blink_rate_bpm = np.clip(np.random.normal(16.0, 3.0), 8, 28) * t

    score = (iso_forest.decision_function([[pupil_size_mm, blink_rate_bpm]])[0] * -1) + 1

    points_x.append(pupil_size_mm)
    points_y.append(blink_rate_bpm)
    scores.append(score)

    new_point.set_offsets(np.column_stack((points_x, points_y)))
    new_point.set_array(np.array(scores))

    fig.canvas.flush_events()
    plt.pause(5)
    t -= 0.05
